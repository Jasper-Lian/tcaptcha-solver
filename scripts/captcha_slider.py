# -*- coding: utf-8 -*-
"""腾讯 TCaptcha 滑块拼图求解（CodeBuddy / OneID 登录页实测可用）。

要点（踩过的坑，勿改）：
1. 拼图块是 `div.tc-fg-item`（非 tc-slider），其 background-image 是**整张 UI 精灵图**
   （含滑轨+把手+拼图块），必须按 computed background-position/size 裁剪出块本身。
2. 裁剪结果**不能**去掉透明边，否则与元素盒子失配，距离会整体偏移。
3. 成功判定看框内文字「验证成功」，此时弹窗仍在播动画，不能以弹窗存在与否判断。
4. 拖动距离按显示像素 1:1：dist = gap_x(显示) - piece_x(显示)。

用法：
    import captcha_slider
    if captcha_slider.visible(page):
        captcha_slider.solve(page)
"""
import base64
import io
import random
import re
import time

import cv2
import numpy as np
from PIL import Image, ImageDraw


def _frame(page):
    for f in page.frames:
        if f == page.main_frame:
            continue
        try:
            if f.query_selector("#slideBg"):
                return f
        except Exception:
            pass
    return None


def visible(page):
    """滑块是否真的在屏幕上。

    不能用「元素存在」判断：点关闭后 DOM 里 wrapper/iframe 仍然残留，
    会误判成"还在弹"，导致反复重置、白等好几轮。
    """
    try:
        return bool(page.evaluate("""() => {
            const shown = el => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                if (r.width < 20 || r.height < 20) return false;
                const cs = getComputedStyle(el);
                if (cs.display === 'none' || cs.visibility === 'hidden') return false;
                return parseFloat(cs.opacity || '1') > 0.05;
            };
            if (shown(document.querySelector('#t_mask'))) return true;
            if (shown(document.querySelector('#tcaptcha_wrapper_transform_dy'))) return true;
            return false;
        }"""))
    except Exception:
        return False


def _style_bytes(fr, el):
    style = fr.evaluate("e => getComputedStyle(e).backgroundImage", el)
    m = re.search(r'url\("?(.*?)"?\)', style)
    if not m:
        raise RuntimeError("无 background-image: " + style[:80])
    url = m.group(1)
    if url.startswith("data:"):
        return base64.b64decode(url.split(",", 1)[1])
    resp = fr.page.request.get(url, timeout=15000)
    if not resp.ok:
        raise RuntimeError(f"图下载失败 HTTP {resp.status}")
    return resp.body()


def _px(v, base):
    v = (v or "").strip()
    if v.endswith("px"):
        return float(v[:-2])
    if v.endswith("%"):
        return float(v[:-1]) / 100.0 * base
    return 0.0


def _crop_atlas(atlas, cs, el_w, el_h):
    """按 background-position/size 从精灵图裁出元素可见区域。"""
    AW, AH = atlas.size
    parts = (cs.get("size") or "auto").replace("/", " ").split()
    if len(parts) >= 2 and parts[0] != "auto":
        sw, sh = _px(parts[0], AW), _px(parts[1], AH)
    else:
        sw, sh = AW, AH
    scale = AW / sw if sw else 1.0

    pos = (cs.get("pos") or "0px 0px").split()
    px_ = _px(pos[0], sw) if pos else 0.0
    py_ = _px(pos[1], sh) if len(pos) > 1 else 0.0

    cx = max(0, min(int(round(-px_ * scale)), AW - 1))
    cy = max(0, min(int(round(-py_ * scale)), AH - 1))
    cw = max(1, min(int(round(el_w * scale)), AW - cx))
    ch = max(1, min(int(round(el_h * scale)), AH - cy))
    return atlas.crop((cx, cy, cx + cw, cy + ch))


def locate_gap(fr, debug_prefix=None):
    """返回 (dist 显示像素, conf)。dist<=3 视为不可信。"""
    bg = fr.query_selector("#slideBg")
    bgbox = bg.bounding_box()
    bgi = Image.open(io.BytesIO(_style_bytes(fr, bg))).convert("RGB")

    piece_el = None
    for el in fr.query_selector_all(".tc-fg-item"):
        cls = (el.evaluate("e => e.className") or "")
        if "tc-slider" in cls:
            continue
        r = el.bounding_box()
        if r and 40 <= r["width"] <= 90 and 40 <= r["height"] <= 90:
            piece_el = el
            break
    if piece_el is None:
        raise RuntimeError("找不到拼图块 .tc-fg-item(约61x61)")
    pbox = piece_el.bounding_box()
    atlas = Image.open(io.BytesIO(_style_bytes(fr, piece_el))).convert("RGBA")
    cs = fr.evaluate("""e => { const s = getComputedStyle(e);
        return {pos: s.backgroundPosition, size: s.backgroundSize}; }""", piece_el)
    pi = _crop_atlas(atlas, cs, pbox["width"], pbox["height"])

    f_nat = bgi.width / bgbox["width"]
    bg_gray = cv2.cvtColor(np.asarray(bgi), cv2.COLOR_RGB2GRAY)
    tw = max(1, round(pbox["width"] * f_nat))
    th = max(1, round(pbox["height"] * f_nat))
    p_nat = pi.resize((tw, th), Image.LANCZOS)

    # 方法1：Canny 边缘匹配
    bg_edge = cv2.Canny(bg_gray, 100, 200)
    p_gray = cv2.cvtColor(np.asarray(p_nat.convert("RGB")), cv2.COLOR_RGB2GRAY)
    p_edge = cv2.Canny(p_gray, 100, 200)
    res = cv2.matchTemplate(bg_edge, p_edge, cv2.TM_CCOEFF_NORMED)
    _, _, _, maxloc = cv2.minMaxLoc(res)
    mx, my = maxloc
    conf = float(res[my, mx])
    best_mx, best_conf, method = mx, conf, "canny"

    # 方法2：α 蒙版 NCC（纵向 ±6 搜索）
    bgr = np.asarray(bgi, dtype=np.float32)
    pn = np.asarray(p_nat.convert("RGBA"), dtype=np.float32)
    y0 = max(0, round((pbox["y"] - bgbox["y"]) * f_nat))
    mask = (pn[..., 3] > 20)
    prgb = pn[..., :3]
    pm = prgb[mask]
    pm0 = pm - pm.mean(axis=0)
    pm_norm = float(np.sqrt((pm0 ** 2).sum()) + 1e-6)
    H, W = bgr.shape[:2]
    ncc_best, ncc_x, ncc_y = -2.0, -1, y0
    for yy in range(max(0, y0 - 6), min(H - pn.shape[0], y0 + 6) + 1):
        for x in range(0, W - pn.shape[1] + 1, 2):
            win = bgr[yy:yy + pn.shape[0], x:x + pn.shape[1]]
            wm = win[mask]
            d = wm - wm.mean(axis=0)
            denom = float(np.sqrt((d ** 2).sum()) + 1e-6) * pm_norm
            if denom <= 0:
                continue
            c = float((d * pm0).sum()) / denom
            if c > ncc_best:
                ncc_best, ncc_x, ncc_y = c, x, yy
    if ncc_best > conf:
        best_mx, best_conf, method = ncc_x, ncc_best, "ncc"
    mx, my = best_mx, (my if method == "canny" else ncc_y)
    conf = best_conf
    if my + th > bgi.height or mx + tw > bgi.width:
        conf = min(conf, 0.05)

    if debug_prefix:
        try:
            dbg = bgi.copy()
            ImageDraw.Draw(dbg).rectangle([mx, my, mx + tw, my + th], outline=(255, 0, 0), width=4)
            dbg.save(debug_prefix + "_mark.png")
            pi.save(debug_prefix + "_piece.png")
        except Exception:
            pass

    dist = mx / f_nat - (pbox["x"] - bgbox["x"])
    print(f"[cap] conf={conf:.3f} method={method} gap_x={mx / f_nat:.1f} "
          f"piece_x={pbox['x'] - bgbox['x']:.1f} dist={dist:.1f}")
    return dist, conf


def human_drag(page, handle, dist):
    """加速→减速→过冲→回正，带纵向抖动。"""
    hb = handle.bounding_box()
    sx = hb["x"] + hb["width"] / 2
    sy = hb["y"] + hb["height"] / 2
    page.mouse.move(sx, sy, steps=5)
    time.sleep(random.uniform(0.12, 0.25))
    page.mouse.down()
    time.sleep(random.uniform(0.08, 0.15))

    total = dist + random.uniform(-1.5, 1.5)
    overshoot = total + random.uniform(2.5, 5.5)
    pos = 0.0
    for i in range(22):
        t = (i + 1) / 22
        target = overshoot * 0.92 * (t * t * (3 - 2 * t))
        page.mouse.move(sx + target, sy + random.uniform(-1.6, 1.6))
        time.sleep(random.uniform(0.014, 0.034))
        pos = target
    time.sleep(random.uniform(0.05, 0.12))
    for i in range(8):
        target = pos + (overshoot - pos) * (i + 1) / 8
        page.mouse.move(sx + target, sy + random.uniform(-1.2, 1.2))
        time.sleep(random.uniform(0.02, 0.045))
        pos = target
    time.sleep(random.uniform(0.08, 0.16))
    for i in range(7):
        target = pos + (total - pos) * (i + 1) / 7
        page.mouse.move(sx + target, sy + random.uniform(-0.8, 0.8))
        time.sleep(random.uniform(0.022, 0.05))
        pos = target
    time.sleep(random.uniform(0.06, 0.14))
    page.mouse.up()


def _cap_text(fr):
    try:
        return (fr.evaluate("() => document.body ? document.body.innerText : ''") or "").strip()[:120]
    except Exception:
        return ""


def reset(page, code_btn_selector=".oneid-react-verify-code__code-btn"):
    """关闭并重新唤起验证码，换一张新图。"""
    fr = _frame(page)
    if fr:
        try:
            fr.click(".tc-close-icon", timeout=3000)
        except Exception:
            pass
    page.wait_for_timeout(1200)
    try:
        page.query_selector(code_btn_selector).click()
    except Exception:
        pass
    page.wait_for_timeout(3200)


def solve(page, tries=8, debug_prefix=None):
    """求解滑块。True=通过（或本就没弹），False=轮次用尽。"""
    piece_moved = 0
    for attempt in range(1, tries + 1):
        if not visible(page):
            # 弹窗已不在（含关闭后 DOM 残留的情况）
            return True
        fr = _frame(page)
        if not fr:
            return True
        try:
            if piece_moved > 40:
                print("[cap] 拼图未复位，重置")
                reset(page)
                piece_moved = 0
                fr = _frame(page)
                if not fr:
                    return True

            handle = fr.query_selector(".tc-fg-item.tc-slider-normal")
            if not handle or not handle.bounding_box():
                handle = None
                for el in fr.query_selector_all("[class*=tc-slider],[class*=tc-fg-item]"):
                    b2 = el.bounding_box()
                    if b2 and b2["width"] > 20:
                        handle = el
                        break
            if not handle:
                reset(page)
                continue
            hb0 = handle.bounding_box()
            dist, conf = locate_gap(fr, f"{debug_prefix}{attempt}" if debug_prefix else None)
            piece_moved = dist + 25
            if dist <= 3 or conf < 0.25:
                print(f"[cap] dist={dist:.1f} conf={conf:.3f} 不可信，换图")
                reset(page)
                piece_moved = 0
                continue

            human_drag(page, handle, dist)
            page.wait_for_timeout(900)
            hb1 = handle.bounding_box()
            if hb1 and hb0:
                print(f"[cap] 位移 {hb1['x'] - hb0['x']:.1f}px / 目标 {dist:.1f}px")
        except Exception as e:
            print(f"[cap] 第{attempt}次异常: {e}")
            page.wait_for_timeout(1500)
            continue

        passed = False
        for _ in range(16):
            frx = _frame(page)
            if not frx:
                passed = True
                break
            t = _cap_text(frx)
            if "验证成功" in t:
                print(f"[cap] 框内: {t!r}")
                passed = True
                break
            if "验证失败" in t or "点击刷新" in t:
                print(f"[cap] 框内: {t!r}")
                break
            page.wait_for_timeout(500)
        if passed:
            print(f"[cap] ✅ 第{attempt}次通过")
            for _ in range(20):
                if not visible(page):
                    break
                page.wait_for_timeout(400)
            return True
        print(f"[cap] 第{attempt}次未通过")
        piece_moved = 999
        page.wait_for_timeout(800)
    return False

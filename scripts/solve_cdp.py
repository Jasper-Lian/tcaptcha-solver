#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对已运行的 Chrome（CDP）里的腾讯滑块验证码求解。

用法：
    python solve_cdp.py                          # 默认连 127.0.0.1:9222
    python solve_cdp.py --cdp http://1.2.3.4:9222 --wait 30
    python solve_cdp.py --url https://example.com/login   # 先开页再等滑块

退出码：0 通过；3 未找到验证码（含超时）；4 求解失败；2 连接失败。
"""
import argparse
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, __file__.rsplit("\\", 1)[0] if "\\" in __file__ else ".")
import captcha_slider  # noqa: E402

from playwright.sync_api import sync_playwright  # noqa: E402


def find_captcha_page(ctx):
    for pg in ctx.pages:
        try:
            if captcha_slider.visible(pg):
                return pg
        except Exception:
            pass
    return None


def main():
    ap = argparse.ArgumentParser(description="TCaptcha 滑块求解 CLI")
    ap.add_argument("--cdp", default="http://127.0.0.1:9222", help="CDP 端点")
    ap.add_argument("--wait", type=int, default=0, help="等待滑块出现的秒数")
    ap.add_argument("--url", help="可选：先在新标签打开该 URL 再等滑块")
    ap.add_argument("--tries", type=int, default=8, help="求解轮次上限")
    ap.add_argument("--debug", action="store_true", help="保存匹配调试图 _capN_*.png")
    args = ap.parse_args()

    try:
        with sync_playwright() as p:
            try:
                b = p.chromium.connect_over_cdp(args.cdp, timeout=10000)
            except Exception as e:
                print(f"[FAIL] 连不上 CDP {args.cdp}: {e}")
                return 2
            ctx = b.contexts[0] if b.contexts else b.new_context()

            if args.url:
                pg = ctx.new_page()
                pg.goto(args.url, wait_until="domcontentloaded", timeout=45000)
                print(f"[page] {pg.url}")

            deadline = time.time() + args.wait
            pg = find_captcha_page(ctx)
            while pg is None and time.time() < deadline:
                time.sleep(1)
                pg = find_captcha_page(ctx)
            if pg is None:
                print("[FAIL] 页面上没有滑块验证码")
                return 3
            print(f"[page] {pg.url}")

            ok = captcha_slider.solve(pg, tries=args.tries,
                                      debug_prefix="_cap" if args.debug else None)
            if ok:
                print("=== 滑块验证通过 ===")
                return 0
            print("=== 滑块验证未通过 ===")
            return 4
    finally:
        pass


if __name__ == "__main__":
    sys.exit(main())

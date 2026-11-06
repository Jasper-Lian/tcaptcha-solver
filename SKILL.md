---
name: tcaptcha-solver
description: 自动求解腾讯 TCaptcha 滑块拼图验证码。经 CDP 连接已运行的 Chrome，精灵图裁剪定位缺口+拟人拖动，CodeBuddy/OneID 登录页实测一次通过。
---

# TCaptcha 滑块求解器

## 概述

对页面里弹出的腾讯滑块拼图（`t.captcha.qq.com` / TCaptcha）做全自动求解：
定位缺口 → 拟人轨迹拖动 → 确认「验证成功」。核心逻辑在
`scripts/captcha_slider.py`，既可被其他脚本 import，也可用 CLI 直接对
已运行的 Chrome 操作。

## 何时使用

- 任何流程卡在「安全验证 / 拖动滑块完成拼图」弹窗上
- 页面出现 `#tcaptcha_wrapper_transform_dy` / iframe `#slideBg`
- 需要把「点按钮 → 弹滑块 → 解掉 → 继续原流程」接进自动化

## 快速开始

```bash
# 1) 对已运行的 Chrome（9222）里现存的滑块求解，最多等 30s 出现
python scripts/solve_cdp.py --cdp http://127.0.0.1:9222 --wait 30

# 2) 作为库调用（在 Playwright 流程内）
python - <<'EOF'
import sys; sys.path.insert(0, "scripts")
import captcha_slider
if captcha_slider.visible(page):
    captcha_slider.solve(page)          # True=通过
EOF
```

## 执行前检查

1. **Chrome 带 CDP**：`--remote-debugging-port=9222` 启动；连接参数用 `--cdp` 覆盖。
2. **依赖**：`playwright`、`opencv-python-headless`、`numpy`（`pip install opencv-python-headless numpy`）。
3. Chrome 若被宿主作业对象回收，用常驻宿主进程持有（见 references/internals.md 第 8 条）。

## 工作流程

1. 连接 CDP，枚举所有页面/iframe 找 `#slideBg`
2. `#slideBg` 背景即原图；拼图块是 `div.tc-fg-item`（非 tc-slider、约 61×61），
   其 `background-image` 是**整张 UI 精灵图**，按 computed
   `background-position/size` 裁剪出块本身
3. 双路匹配取高置信：Canny 边缘 `TM_CCOEFF_NORMED` + α 蒙版 NCC（纵向 ±6 搜索）；
   `conf < 0.25` 或 `dist <= 3` 直接换图重试
4. 拟人拖动：加速→减速→过冲 2.5-5.5px→回正，纵向抖动，全程 ~1s
5. 成功判定看框内文字「验证成功」（此时弹窗还在播动画，**不能**用"弹窗消失"判断）
6. 失败后拼图不回原位：先关 `.tc-close-icon`，重新触发业务按钮换新图

## 必须遵守的判定规则

- 拖动距离按**显示像素 1:1**：`dist = gap_x(显示) - piece_x(显示)`
- 裁剪结果**不能**去透明边，否则与元素盒子失配、距离整体偏移
- 装饰条（340×16）与真块同 class，必须按尺寸过滤
- 更多坑见 `references/internals.md`

## 结果校验

- CLI 退出码：`0` 通过 / `3` 未找到验证码 / `4` 轮次用尽未通过
- 过程日志带 `[cap]` 前缀：`conf`（匹配置信度）、`位移 Xpx / 目标 Ypx`
  （偏差应 <1px）

## 资源

- `scripts/captcha_slider.py` — 核心求解模块（visible / locate_gap / human_drag / solve / reset）
- `scripts/solve_cdp.py` — 独立 CLI
- `references/internals.md` — 实现细节与全部踩坑记录

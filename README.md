# tcaptcha-solver

腾讯 **TCaptcha 滑块拼图验证码**自动求解器（AgentSkill 格式）。

对页面里弹出的「安全验证 / 拖动滑块完成拼图」做全自动求解：精灵图裁剪定位缺口 → 双路图像匹配（Canny 边缘 + α 蒙版 NCC）→ 拟人轨迹拖动 → 确认「验证成功」。

已在腾讯云 CodeBuddy（`www.codebuddy.cn` OneID 登录组件）实测，**一次通过**。

## 它能解决什么

点按钮后弹出滑块、业务请求根本没发出去的场景——典型症状是「验证码收不到 / 按钮没倒计时 / 接码平台 records 恒为空」，看起来像被风控，其实是滑块没解掉。

## 安装

```bash
pip install playwright opencv-python-headless numpy pillow
playwright install chromium   # 仅当需要脚本自己拉浏览器
```

## 用法

### 1. 独立 CLI（对已在运行的 Chrome）

```bash
# Chrome 需带 CDP 启动：
#   chrome.exe --remote-debugging-port=9222 --user-data-dir=<某目录>

python scripts/solve_cdp.py --cdp http://127.0.0.1:9222 --wait 30
```

| 参数 | 说明 |
|---|---|
| `--cdp` | CDP 端点，默认 `http://127.0.0.1:9222` |
| `--wait N` | 等待滑块出现 N 秒（轮询） |
| `--url URL` | 可选，先在新标签打开该 URL |
| `--tries N` | 求解轮次上限，默认 8 |
| `--debug` | 保存匹配调试图 |

退出码：`0` 通过 / `2` 连不上 CDP / `3` 没找到滑块 / `4` 轮次用尽。

### 2. 作为库嵌入 Playwright 流程

```python
import sys
sys.path.insert(0, "scripts")
import captcha_slider

# ... 你的业务流程点完按钮之后：
if captcha_slider.visible(page):
    if not captcha_slider.solve(page):
        raise RuntimeError("滑块未通过")
# 继续原流程（此时业务请求才真正发出）
```

### 3. 作为 AgentSkill 使用

本仓库根目录就是标准 AgentSkill 结构（`SKILL.md` + scripts + references）。
WorkBuddy / OpenClaw / Claude Code 等兼容 AgentSkills 规范的运行时，把仓库
clone 到技能目录即可：

```bash
# WorkBuddy（用户级技能）
git clone https://github.com/<you>/tcaptcha-solver.git ~/.workbuddy/skills/tcaptcha-solver

# OpenClaw
git clone https://github.com/<you>/tcaptcha-solver.git ~/.openclaw/skills/tcaptcha-solver
```

## 工作原理（要点）

1. 拼图块是 `div.tc-fg-item`（非 `tc-slider`，约 61×61），它的 `background-image`
   是**整张 UI 精灵图**——必须按 computed `background-position/size` 裁剪出块本身
2. 双路匹配取高置信：Canny 边缘 `matchTemplate` + α 蒙版 NCC（纵向 ±6 全搜）
3. 拟人拖动：smoothstep 加速 → 过冲 2.5-5.5px → 回正，纵向抖动，全程 ~1s
4. 成功判定看框内文字「验证成功」——此时弹窗还在播动画，用"弹窗消失"判断会把成功当失败
5. 失败后拼图不回原位，必须关弹窗重新触发业务按钮换新图

完整踩坑记录见 [references/internals.md](references/internals.md)。

## 免责声明

- 本项目仅用于**自动化测试自己拥有或获授权的系统**，请遵守目标站点服务条款与当地法律法规
- 验证码机制属于目标站点的反滥用措施，请勿用于批量注册、薅羊毛等滥用场景
- 腾讯可能随时更新验证码结构导致本工具失效，本项目不承诺持续维护

## License

MIT

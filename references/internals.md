# 实现细节与踩坑记录

以下每条都在 CodeBuddy（`www.codebuddy.cn/login`，OneID 组件）上实测踩过，
改代码前务必读完。

## 1. 滑块拦截 = 业务请求根本没发出去

点「获取验证码」后若弹滑块，短信不会发送、按钮不进倒计时、接码平台
`records` 恒为空。**不要**误判成"号码被风控"——先看页面有没有滑块。

识别特征：
- 主文档：`#tcaptcha_wrapper_transform_dy`（360×360 弹窗）、`#t_mask`
- iframe：`#slideBg`（340×243 背景图）、`.tc-fg-item.tc-slider-normal`（把手）

## 2. 拼图块元素识别

`.tc-fg-item` 有**多个**同 class 元素：

| 元素 | 尺寸 | 说明 |
|---|---|---|
| 真拼图块 | ~61×61 | `background-image` 指向精灵图 |
| 装饰条 | 340×16 | 底部轨道装饰，**必须排除** |
| 滑块把手 | 66×35 | 额外带 `tc-slider-normal` class |

过滤规则：class 不含 `tc-slider` 且 bounding box 宽高都在 40-90 之间。

另有一个无 class 的 64×64 `<img>`（绿色对勾/失败图标），**不是**拼图块，
不要用"找 64×64 图片"这种规则。

## 3. 精灵图裁剪（最大的坑）

拼图块 div 的 `background-image` 是**整张 UI 精灵图**（682×620，含滑轨、
蓝色把手、拼图块），通过 `background-position: -70.83px -247.92px` 和
`background-size: 345.06px 313.69px` 只显示块的区域。

正确做法：
```python
scale = 精灵图自然宽 / background-size 宽
cx = -pos_x * scale;  cy = -pos_y * scale
cw = el_w * scale;    ch = el_h * scale   # ≈ 120×120，即 2x DPI
crop = atlas.crop((cx, cy, cx+cw, cy+ch))
```

两个禁忌：
- **不能**对 crop 去透明边（`getbbox` 裁剪）——crop 必须与元素盒子严格对齐，
  否则 `dist = gap_x - piece_x` 整体偏移，怎么拖都不对
- **不能**把整张精灵图当模板——匹配会落到把手/滑轨上，conf≈0.06

## 4. 缺口定位：双路匹配

- 路 1：Canny(bg) + Canny(piece) → `cv2.matchTemplate(TM_CCOEFF_NORMED)`
- 路 2：α 蒙版 NCC（piece alpha>20 的像素 vs 背景窗口），纵向在
  `y0±6` 内全搜索（y0 = piece 相对 bg 的 y × DPI 倍率），x 步长 2

取置信度高的一路。`conf < 0.25` 或 `dist <= 3` 时不要硬拖——点刷新换图。

背景图与精灵图都是 2x 资产（显示 340 → 自然 672），模板要 resize 到
`显示尺寸 × 1.976` 再匹配，精度才能到亚像素级。

## 5. 拖动

- 距离按**显示像素 1:1**：`dist = gap_x(显示) - piece_x(显示)`
- 轨迹：smoothstep 加速到 92% → 慢速过冲 2.5-5.5px → 回正，全程 ~1s，
  纵向 ±1.6px 抖动
- 拖完读把手 bounding box 验证：实测位移与目标偏差应 <1px；
  若把手 box 变 None 说明 DOM 已重渲染

## 6. 成功判定（第二大坑）

验证通过时框内先显示**「验证成功！」**，弹窗播完动画才消失。
用"弹窗是否还在"判断会把成功当失败 → 反复拖同一张图 → 轮次耗尽。

正确判定：轮询 iframe `body.innerText`，出现「验证成功」即通过；
出现「验证失败 / 点击刷新」为失败。

## 7. 失败后的重置

拖过的拼图块**不会回原位**，同一张图重拖无意义。必须：
1. 点 `.tc-close-icon` 关弹窗
2. 重新点业务按钮（如「获取验证码」）唤起新验证码
3. 若业务按钮在倒计时中点不动，等倒计时结束再点

## 8. 环境备忘

- 依赖：`opencv-python-headless`、`numpy`、`playwright`
- Chrome 被 shell 作业对象回收时（Popen 后命令一结束进程消失，
  `CREATE_BREAKAWAY_FROM_JOB` 报 WinError 5），用常驻宿主进程持有 Chrome
- 本机访问 `127.0.0.1` 别走系统代理（curl 加 `--noproxy '*'`）

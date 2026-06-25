# Why

两处键鼠/开发者工具的交互修正：

1. **键盘输入入口抬高页面**：当前开启键盘镜像会把侧栏里「键盘输入」切换按钮**就地替换**为「捕获输入框 + 退出叉」，使该行变高、侧栏布局高度跳变。改为入口按钮恒定（文字在「键盘输入：已关闭 / 已打开」间切换），键盘捕获输入框放到一个可拖拽的浮动子窗口里，开关开启/关闭都不改变侧栏高度。

2. **tunnel 刷新不联动门控**：开发者工具页有 DDI 与 XPC tunnel 两个「刷新状态」按钮，二者都影响 RSD/DVT 前置。DDI 刷新会重跑就绪检查（含 RSD 探测）并刷新功能位门控，但 tunnel 的刷新按钮只重读 tunnel 运行状态、用缓存的 RSD 就绪态重绘，tunnel 起来后点它不会解锁功能位。改为 tunnel 刷新也重跑就绪检查（iOS 17+ 在 tunnel 运行且 DDI 已挂载时重新探测 RSD），与 DDI 刷新一致。

# What Changes

1. **键鼠操作键盘输入入口**（slide6-keyboard-input）：
   - 入口改为恒定的文字按钮，点击在「键盘输入：已关闭」/「键盘输入：已打开」间切换；按钮位置与高度不变。
   - 开启时弹出一个浮动「键盘输入」子窗口（键鼠 Tab 内的子窗口）：含键盘捕获输入框 + 退出（叉）按钮，默认按 baseline 覆盖在入口按钮位置。
   - 浮动窗口可在键鼠 Tab 区域内任意拖拽，但不可拖出 Tab 边界（越界位置被钳制回 Tab 内）。
   - 点退出叉 / 再次点击入口按钮 / 断开连接，均关闭浮动窗口、停止捕获、按钮恢复「已关闭」。

2. **tunnel 刷新按钮联动门控**（slide6-developer-tools）：
   - tunnel 面板「刷新状态」按钮点击时，除重读 tunnel 运行状态外，MUST 重跑设备就绪检查：iOS 17+ 在 tunnel 运行且 DDI 已挂载时重新探测 RSD/DVT，据结果刷新功能位门控；tunnel 未运行时清除过期就绪态使功能位保持禁用。

# Impact

- Affected specs: `slide6-keyboard-input`、`slide6-developer-tools`
- Affected code:
  - `slide6_ui/keymouse/keymouse_tab.py`（入口按钮文案切换、浮动键盘输入窗口的创建/显示/关闭/拖拽钳制、与现有 KeyboardCapture/KeyboardSender 接线）
  - `slide6_ui/developer_tools/developer_tools_tab.py`（`_on_refresh_tunnel` 重跑就绪检查/RSD 探测——已实现）
  - `slide6_ui/languages/zh-CN.json`、`en-US.json`（入口按钮「已关闭 / 已打开」文案）
- WDA：无需改动。

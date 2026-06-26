# Why

键鼠操作 Tab 的浮动「键盘输入」窗口有三处交互体验问题：

1. **浮窗位置每次都回默认**：浮窗每次开启都覆盖在入口按钮位置，用户拖到顺手的位置后，关掉再开又跳回默认，无法保留。
2. **浮窗常驻遮挡**：失焦后浮窗仍完全不透明，挡住下方镜像/控件，用户在别处操作时浮窗碍事。
3. **操作后焦点被强夺回捕获框**：屏幕手势与各类操作（发送、剪贴板、UI XML、截图等）完成后都会把键盘焦点强制拉回捕获框，导致用户主动停驻在「发送文本」框等别处的焦点被无故抢走。

# What Changes

均落在 `slide6-keyboard-input`：

1. **浮窗位置记忆（设置项，默认关闭）**：Key/Mouse 设置新增「记住当前设备的键盘输入浮窗位置」开关。开启后，关闭再开启键盘捕获时浮窗 SHALL 出现在上一次的位置；该位置仅保存在内存，切换设备或重启 App 后丢失，回到默认（覆盖入口按钮）位置。

2. **失焦半透明（设置项，默认关闭）**：Key/Mouse 设置新增「鼠标不聚焦时输入浮窗半透明」开关。开启后，键盘焦点离开浮窗（落到其它控件）时浮窗 SHALL 变为半透明，焦点回到浮窗时恢复不透明。

3. **焦点保持（不强夺）**：屏幕手势与各类操作完成后 MUST NOT 强制把键盘焦点拉回捕获框；焦点停在用户放置处。要在操作后继续向设备打字，用户重新点击捕获框即可。

# Impact

- Affected specs: `slide6-keyboard-input`
- Affected code:
  - `slide6_ui/common/keymouse_settings.py`（两个新设置键 + getter/setter）
  - `slide6_ui/common/keymouse_settings_widget.py`（Key/Mouse 设置新增「键盘输入」分组与两个开关）
  - `slide6_ui/keymouse/keymouse_tab.py`（浮窗位置记忆/per-device 清除、失焦半透明 graphics effect、移除 `_refocus_keyboard` 及其 12 处调用与 `gesture_finished` 连接）
  - `slide6_ui/languages/zh-CN.json`、`en-US.json`（分组与开关文案）
- WDA：无需改动。

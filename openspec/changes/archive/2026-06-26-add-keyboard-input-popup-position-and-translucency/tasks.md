# Tasks

## 1. 浮窗位置记忆（slide6-keyboard-input）

- [x] 1.1 `keymouse_settings.py` 新增 `REMEMBER_KBD_POPUP_POS_KEY` + `get/set_remember_kbd_popup_pos`，默认关闭
- [x] 1.2 Key/Mouse 设置新增「键盘输入」分组与「记住当前设备的键盘输入浮窗位置」开关，toggle 即时落盘
- [x] 1.3 `keymouse_tab` 内存保存浮窗位置 `_kbd_popup_pos`：关闭浮窗时记下 `pos()`，开启时按设置恢复；`show_over` 支持可选位置参数
- [x] 1.4 `select_device` 每次切换设备清空 `_kbd_popup_pos`（per-device、重启即失）

## 2. 失焦半透明（slide6-keyboard-input）

- [x] 2.1 `keymouse_settings.py` 新增 `KBD_POPUP_TRANSLUCENT_KEY` + `get/set_kbd_popup_translucent_unfocused`，默认关闭
- [x] 2.2 设置「键盘输入」分组新增「鼠标不聚焦时输入浮窗半透明」开关，toggle 即时落盘
- [x] 2.3 浮窗用 `QGraphicsOpacityEffect` 在失焦时半透明、聚焦时关闭 effect（避免叠在 IME 激活的输入框上）；监听 `QApplication.focusChanged` 实时更新
- [x] 2.4 打开浮窗时由 `_set_keyboard` 按设置 `set_translucent_when_unfocused`

## 3. 焦点保持（slide6-keyboard-input）

- [x] 3.1 移除 `gesture_finished → _refocus_keyboard` 连接（mirror 为 NoFocus，点屏幕不夺焦点）
- [x] 3.2 移除 `_refocus_keyboard` 方法及其余 11 处操作后调用（发送/剪贴板/UI XML/截图/底部手势等）

## 4. 文案与验证

- [x] 4.1 `zh-CN.json` / `en-US.json` 新增 `settings.keymouse.keyboard_input.{group,remember_popup_pos,translucent_unfocused}`
- [x] 4.2 `py_compile` 通过、JSON 合法、全仓库无残留 `_refocus_keyboard` 引用
- [x] 4.3 真机：开启位置记忆后拖拽→关开复现位置；切设备/重启回默认；开启半透明后失焦变淡、回焦恢复；操作后焦点不被夺回
- [x] 4.4 `openspec validate add-keyboard-input-popup-position-and-translucency --strict`

## Why

当前 `Key/Mouse` 设置只支持单一的 `App Switcher` 按钮配置，无法表达更通用的底部边缘手势能力，也无法同时控制：

1. `swipe up hold`
2. `swipe up`
3. 每种手势在主界面里的按钮名称
4. 默认规则与按 `device id` 的覆盖规则

本变更把该能力升级为 `Bottom Gestures / 底部手势`，统一用表格配置默认行与设备行，并在主界面动态生成对应按钮。

## What Changes

- 保留 Settings → `Key/Mouse` tab。
- 保留 WDA 配置项：
  - `WDA bundle id`
  - `WDA server port`
  - `WDA MJPEG port`
- 用 `Bottom Gestures / 底部手势` 替换 `App Switcher` 设置区域。
- 新增统一表格配置：
  - `Device`
  - `Swipe Up Hold`
  - `Bottom Swipe Up`
- 表格第一行固定为 `Default / 默认`。
- `Swipe Up Hold` 允许值：
  - `disabled`
  - `app_switcher`
- `Swipe Up` 允许值：
  - `disabled`
  - `bottom_swipe_up`
  - `control_center`
- 默认值：
  - `swipeUpHold = app_switcher`
  - `swipeUp = bottom_swipe_up`
- 主界面根据当前设备命中的行动态显示底部手势按钮。
- 底层动作规则：
  - `app_switcher` -> `swipe_up_hold`
  - `bottom_swipe_up` / `control_center` -> `swipe_up`

## Impact

- 受影响 spec：
  - `slide6-settings-window`
  - `slide6-desktop-shell`
- 受影响代码：
  - `slide6_ui/main_window.py`
  - `slide6_ui/keymouse/keymouse_tab.py`
  - `slide6_ui/common/keymouse_settings.py`
  - `ios_toolkit/device.py`
  - `ios_toolkit/toolkit_api.py`
  - `slide6_ui/languages/*.json`

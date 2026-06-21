## MODIFIED Requirements

### Requirement: 设备动作（HOME / Bottom Gestures / 截图）

应用 SHALL 提供 HOME、底部手势按钮、截图保存按钮。HOME 与截图行为不变；底部手势按钮 SHALL 根据当前设备命中的底部手势配置动态生成。

解析规则：

1. 读取当前设备 `device id`
2. 在 `settings/keymouse_bottom_edge_gestures` 中精确匹配设备行
3. 命中则使用设备行
4. 未命中则回退默认行 `deviceId=default`
5. `disabled` 的动作不显示按钮

按钮位置：

1. 位于 `HOME` 下方
2. 位于 `Keyboard input` 上方

#### Scenario: 设备命中覆盖行

- **WHEN** 当前设备 `device id` 在表格中命中
- **THEN** 主界面根据该设备行生成底部手势按钮

#### Scenario: 设备未命中覆盖行

- **WHEN** 当前设备未命中设备行
- **THEN** 主界面根据默认行生成底部手势按钮

### Requirement: app_switcher 映射为 swipe_up_hold

当 `swipeUpHold = app_switcher` 时，点击对应按钮 SHALL 调用 `app_switcher(target)`，并使用 `swipe_up_hold` 底层动作。

#### Scenario: 点击应用切换按钮

- **WHEN** 当前设备启用了 `swipeUpHold = app_switcher`
- **AND** 用户点击 `应用切换 / App Switcher`
- **THEN** 调用 `app_switcher(target)`

### Requirement: bottom_swipe_up 和 control_center 映射为 swipe_up

当 `swipeUp = bottom_swipe_up` 或 `swipeUp = control_center` 时，点击对应按钮 SHALL 调用 `bottom_edge_swipe(target)`，并使用普通 `swipe_up` 底层动作。

#### Scenario: 点击底部上滑按钮

- **WHEN** 当前设备启用了 `swipeUp = bottom_swipe_up`
- **THEN** 点击按钮时调用 `bottom_edge_swipe(target)`

#### Scenario: 点击控制中心按钮

- **WHEN** 当前设备启用了 `swipeUp = control_center`
- **THEN** 点击按钮时调用 `bottom_edge_swipe(target)`

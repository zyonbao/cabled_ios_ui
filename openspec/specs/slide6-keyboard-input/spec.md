## Purpose

桌面应用键盘输入——键盘镜像开关、文本/IME 输入、按键分流与命令串行化，并拦截 Tab 等快捷键键序。

## Requirements

### Requirement: 键盘镜像开关

应用 SHALL 提供键盘镜像开关；仅在已连接且开关开启时捕获宿主键盘并转发到设备当前聚焦控件。键盘镜像开启时，原「键盘输入」切换按钮所在位置 SHALL 就地替换为「键盘捕获输入框 + 退出（叉）按钮」；输入框承载键盘捕获焦点，点击退出叉关闭键盘镜像并把该位置恢复为原切换按钮。

#### Scenario: 开启键盘镜像

- **WHEN** 已连接状态下用户开启键盘镜像
- **THEN** 原切换按钮位置就地替换为「键盘捕获输入框 + 退出叉」
- **AND** 输入焦点进入键盘捕获输入框，后续击键被转发到设备

#### Scenario: 点击退出叉关闭键盘镜像

- **WHEN** 键盘镜像开启且用户点击退出（叉）按钮
- **THEN** 停止捕获，宿主键盘不再转发到设备
- **AND** 该位置恢复为原「键盘输入」切换按钮

#### Scenario: 关闭键盘镜像

- **WHEN** 用户关闭键盘镜像（含断开连接等导致的关闭）
- **THEN** 停止捕获，宿主键盘不再转发到设备
- **AND** 该位置恢复为原「键盘输入」切换按钮

### Requirement: 文本与 IME 输入

应用 SHALL 把普通字符、粘贴文本与中文 IME 组合输入，在输入法组合完成后通过 `toolkit_api.send_keys(target, text)` 发送。

#### Scenario: 输入英文文本

- **WHEN** 键盘镜像开启且用户输入可见字符
- **THEN** 文本通过 `send_keys` 发送到设备聚焦控件

#### Scenario: 中文 IME 输入

- **WHEN** 用户通过输入法完成一段中文组合输入
- **THEN** 仅在组合完成（commit）后将最终文本通过 `send_keys` 发送，组合过程中不发送中间态

### Requirement: 按键种类分流

应用 SHALL 按 iOS 通道差异对按键分流：编辑键（Enter/Backspace/Tab/Esc）走 `toolkit_api.key_event`；导航键（方向/Home/End/PageUp/PageDown）与一切带 ⌘/⌃/⌥/⇧ 修饰的组合键走 `toolkit_api.key_chord`。

#### Scenario: 编辑键

- **WHEN** 用户按下回车/退格/Tab/Esc 且无修饰键
- **THEN** 调用 `key_event` 发送对应按键

#### Scenario: 导航键

- **WHEN** 用户按下方向键/Home/End/PageUp/PageDown
- **THEN** 调用 `key_chord` 发送对应导航键

#### Scenario: 修饰组合键

- **WHEN** 用户按下带 ⌘/⌃/⌥/⇧ 修饰的组合键（如 ⌘C、⇧→）
- **THEN** 调用 `key_chord` 发送基础键与修饰键集合

### Requirement: 键盘命令串行化发送

应用 SHALL 把所有键盘命令（文本/按键/组合键）放入单一 FIFO 队列由一个 worker 串行发送，连续文本合并为一次请求，以保证设备端字符顺序正确。

#### Scenario: 快速连续输入不乱序

- **WHEN** 用户快速连续输入多个字符
- **THEN** 命令按入队顺序串行发送，且连续文本被合并为一次 `send_keys`
- **AND** 设备端字符顺序与输入顺序一致

### Requirement: 捕获框拦截 Tab 与快捷键键序

键盘捕获输入框 SHALL 在 Qt 的 `event()` 层拦截 Tab/Backtab，使其作为 `TAB` 转发到设备，而不是触发宿主控件的焦点遍历；并 SHALL 接受 `ShortcutOverride` 事件，强制所有组合键以普通按键投递到 `keyPressEvent` 后转发到设备，避免被应用/窗口级快捷键吞掉。被 macOS 窗口管理器在 Qt 之前消费的系统级快捷键（如 ⌘Q/⌘W/⌘Tab 等）不在可捕获范围。

#### Scenario: 按 Tab 转发到设备而非切换焦点

- **WHEN** 键盘镜像开启且用户按下 Tab（或 Shift+Tab）
- **THEN** 捕获框拦截该键并作为 `TAB` 转发到设备
- **AND** 宿主界面焦点不发生切换

#### Scenario: 组合键不被快捷键吞掉

- **WHEN** 用户按下带 ⌘/⌃/⌥ 修饰的组合键
- **THEN** 该键序经 `ShortcutOverride` 被接受并以普通按键投递，进而转发到设备

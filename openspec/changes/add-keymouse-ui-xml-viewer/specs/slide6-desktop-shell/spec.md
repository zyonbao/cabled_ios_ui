## MODIFIED Requirements

### Requirement: 设备动作（HOME / Bottom Gestures / 截图）

应用 SHALL 提供 HOME、底部手势按钮、截图保存按钮，并在右侧操作区额外提供 `Input`、`Clipboard`、`UI XML` 三个区块。

按钮位置：

1. `HOME / Bottom Gestures` 保持当前布局
2. `Input` 组位于底部手势下方，包含 `Keyboard input` 与 `Send text`
3. `Screenshot` 位于 `Input` 组下方
4. `Clipboard` 组位于截图下方，包含 `Set Clipboard / Read Clipboard`
5. `UI XML` 组位于 `Clipboard` 组下方

#### Scenario: 已连接状态显示 UI XML 按钮

- **WHEN** 当前设备进入已连接状态
- **THEN** `UI XML` 按钮可用
- **AND** 其位置位于 `Clipboard` 组下方

### Requirement: 视频流中断后清空最后一帧

当视频流中断时，桌面端 SHALL 清空镜像区域中最后一帧，使画面恢复为黑底，再显示错误提示文字。

#### Scenario: 视频流中断后黑底显示提示

- **WHEN** 镜像线程报告视频流中断
- **THEN** 当前镜像帧被清空
- **AND** 镜像区域恢复为黑底
- **AND** 错误提示文字显示在黑底上

### Requirement: UI XML 弹窗查看与复制

当用户点击 `UI XML` 按钮时，桌面端 SHALL 调用 `dump_ui(target)` 获取 WDA 当前页面的原始 XML，并用 `QPlainTextEdit` 弹窗展示，同时提供复制按钮。

#### Scenario: 成功查看 UI XML

- **WHEN** 已连接状态下用户点击 `UI XML`
- **THEN** 调用 `dump_ui(target)`
- **AND** 打开一个弹窗
- **AND** 弹窗中的 `QPlainTextEdit` 展示返回的 `data.raw`

#### Scenario: 复制 UI XML

- **WHEN** `UI XML` 弹窗已打开，且用户点击复制按钮
- **THEN** 当前 XML 内容被写入本机系统剪贴板

#### Scenario: 获取 UI XML 失败

- **WHEN** `dump_ui(target)` 返回错误或抛出异常
- **THEN** 桌面端显示失败状态与错误信息

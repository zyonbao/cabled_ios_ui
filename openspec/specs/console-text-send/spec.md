## Purpose

定义 Web 控制台的独立文本发送能力：通过专用输入框将文本直接发送到设备，并与键盘镜像输入链路彻底解耦，保证两种输入方式可独立启停与互不干扰。
## Requirements
### Requirement: 独立文本发送输入框

slide6 桌面端与 web 端 SHALL 各提供一个独立于键盘镜像捕获框的文本输入框，其右侧紧邻一个「发送」按钮。该输入框仅在设备已连接时可用。

#### Scenario: 未连接时不可用

- **WHEN** 尚未连接设备（无画面流）
- **THEN** 文本输入框与发送按钮处于禁用状态

#### Scenario: 已连接时可用

- **WHEN** 设备已连接且画面流就绪
- **THEN** 文本输入框与发送按钮启用

### Requirement: 点击发送把文本送至设备

系统 SHALL 在用户点击「发送」按钮时，把输入框当前内容通过 `toolkit_api.send_keys(target, text)`（web 端经 `/api/type` 或等价端点）一次性发送到设备当前聚焦控件。

#### Scenario: 发送一段文本

- **WHEN** 输入框内容为 `"hello world"` 且用户点击发送
- **THEN** 该文本通过 `send_keys` 发送到设备聚焦控件

#### Scenario: 空内容不发送

- **WHEN** 输入框为空且用户点击发送
- **THEN** 不发起发送请求

#### Scenario: 发送成功后清空输入框

- **WHEN** 文本成功发送到设备
- **THEN** UI SHALL 清空文本输入框内容

#### Scenario: 发送失败提示并保留内容

- **WHEN** 发送过程中底层返回错误
- **THEN** UI SHALL 给出失败提示（状态栏或等价反馈），不崩溃
- **AND** SHALL 保留文本输入框内容以便用户重试

### Requirement: 文本发送独立于键盘镜像

文本发送输入框 SHALL 独立工作，不要求开启键盘镜像，也不抢占键盘镜像捕获框的焦点逻辑。

#### Scenario: 未开键盘镜像也能发送

- **WHEN** 键盘镜像处于关闭状态，用户在文本输入框输入并点击发送
- **THEN** 文本正常发送到设备，键盘镜像状态不变

### Requirement: 多行文本输入与自适应高度（桌面端）

slide6 桌面端文本发送输入框 SHALL 支持多行文本的输入与展示，并随内容自适应高度：单行内容时保持单行高度，内容增多时自动增高，最多显示 5 行；超过 5 行时 SHALL 保持 5 行高度并提供竖向滚动条上下查看。输入框 SHALL 自动换行（按宽度折行），MUST NOT 出现横向滚动条。

#### Scenario: 粘贴多行内容按多行展示

- **WHEN** 用户向文本发送输入框粘贴含换行符的多行内容
- **THEN** 内容按多行展示，输入框高度随之增高，而非压成一行

#### Scenario: 超过 5 行封顶并滚动

- **WHEN** 输入框内容超过 5 行可显示高度
- **THEN** 输入框高度保持在 5 行，并出现竖向滚动条供上下查看

#### Scenario: 单行内容保持单行高度

- **WHEN** 输入框为空或仅一行内容
- **THEN** 输入框维持单行高度

### Requirement: Enter 发送与 Shift+Enter 换行（桌面端）

slide6 桌面端文本发送输入框 SHALL 支持按 Enter 直接发送当前内容（等价于点击「发送」按钮，走 `toolkit_api.send_keys`），并支持 Shift+Enter 在输入框内插入换行。当宿主输入法处于组合（preedit）状态时，按 Enter SHALL 用于确认候选而 MUST NOT 触发发送。「发送」按钮 SHALL 继续保留且可用。

#### Scenario: 按 Enter 发送

- **WHEN** 输入框有内容且未处于输入法组合态，用户按下 Enter（不含 Shift）
- **THEN** 当前内容通过 `send_keys` 发送到设备，等价于点击发送按钮

#### Scenario: Shift+Enter 换行不发送

- **WHEN** 用户按下 Shift+Enter
- **THEN** 在输入框内插入换行，不发起发送

#### Scenario: 输入法组合态 Enter 不发送

- **WHEN** 宿主输入法正在组合（如拼音选字）时用户按下 Enter
- **THEN** Enter 用于确认候选词，不触发发送

#### Scenario: 发送按钮仍可用

- **WHEN** 用户点击「发送」按钮
- **THEN** 与按 Enter 一致，把当前内容发送到设备


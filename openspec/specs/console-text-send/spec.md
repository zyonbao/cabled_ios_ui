## Purpose

Web 控制台独立文本发送能力——通过独立输入框把文本直接送至设备，独立于键盘镜像。

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

## ADDED Requirements

### Requirement: 临时 usbmux 端口转发上下文管理器
系统 SHALL 提供 `_ephemeral_forward(udid, device_port)` 异步上下文管理器，在 `async with` 块内持续运行端口转发 server，退出时自动关闭。每次操作使用独立的临时转发，不维护跨调用的持久转发。

#### Scenario: 成功建立端口转发
- **WHEN** 以有效 UDID 进入 `_ephemeral_forward` 上下文
- **THEN** `yield` 一个可用的本地端口 `local_port`，对该端口的 TCP 连接可正常透传到设备的 `device_port`（默认 8100）

#### Scenario: UDID 不存在时抛出 ValueError
- **WHEN** 以不存在的 UDID 进入 `_ephemeral_forward` 上下文
- **THEN** 抛出 `ValueError`，调用方捕获后返回 `BAD_TARGET` 错误

#### Scenario: 退出上下文后 server 自动关闭
- **WHEN** `async with _ephemeral_forward(...)` 块正常或异常退出
- **THEN** 端口转发 server 关闭，本地端口不再接受新连接

### Requirement: 动态探测可用本地端口
系统 SHALL 从端口 8200 起，通过 `socket.bind` 探测找到第一个可用的本地端口作为 `local_port`，避免端口冲突。

#### Scenario: 8200 端口可用时使用 8200
- **WHEN** 系统本地 8200 端口未被占用
- **THEN** `_ephemeral_forward` 使用 8200 作为 `local_port`

#### Scenario: 8200 端口被占用时顺延
- **WHEN** 系统本地 8200 端口已被占用
- **THEN** `_ephemeral_forward` 探测 8201、8202…直到找到可用端口

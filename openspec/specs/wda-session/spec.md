## Purpose

WDA 会话能力——每次操作新建 WDA Session（Phase 1 不缓存），并封装 WDA HTTP 工具与错误（WdaError）。

## Requirements

### Requirement: 每次操作新建 WDA Session（Phase 1 不缓存）
系统 SHALL 提供 `_create_session(local_port)` 函数，通过 `POST /session` 新建 WDA session 并返回 `sessionId`。Phase 1 中每次需要 session 的操作均调用此函数，不读写任何全局 session 状态。

#### Scenario: 成功创建 session
- **WHEN** WDA 正在运行且对 `local_port` 可访问，调用 `_create_session(local_port)`
- **THEN** 返回从响应体中提取的 `sessionId` 字符串

#### Scenario: WDA 不可访问时抛出 WdaError
- **WHEN** WDA 未运行或端口不通，调用 `_create_session(local_port)`
- **THEN** 抛出 `WdaError`，调用方捕获后返回 `SUBPROCESS` 错误

### Requirement: WDA HTTP 工具函数封装错误为 WdaError
系统 SHALL 提供 `_wda_get(local_port, path, timeout)` 和 `_wda_post(local_port, path, body, timeout)` 同步函数，连接失败或 HTTP 错误时统一抛出携带 `message` 的 `WdaError`。

#### Scenario: 请求成功返回解析后的 JSON
- **WHEN** WDA 返回 2xx 响应且 body 为合法 JSON
- **THEN** 函数返回解析后的 dict

#### Scenario: 连接失败时抛出 WdaError
- **WHEN** TCP 连接超时或被拒绝
- **THEN** 抛出 `WdaError`，message 包含失败描述

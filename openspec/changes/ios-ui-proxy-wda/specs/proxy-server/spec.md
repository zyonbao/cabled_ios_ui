## ADDED Requirements

### Requirement: Proxy 服务启动参数

Proxy 服务 SHALL 支持通过命令行参数配置 WDA 连接地址和对外监听端口。

#### Scenario: 使用默认参数启动

- **WHEN** 执行 `python -m ios_ui_ta_proxy`（无参数）
- **THEN** 服务以 `--wda-host 127.0.0.1`、`--wda-port 8100`、`--proxy-port 9000` 启动，并在控制台输出 `iOS UI Proxy running on http://0.0.0.0:9000`

#### Scenario: 使用自定义参数启动

- **WHEN** 执行 `python -m ios_ui_ta_proxy --wda-port 8101 --proxy-port 9001`
- **THEN** 服务连接 WDA `127.0.0.1:8101`，对外监听 `9001`

#### Scenario: 端口已被占用

- **WHEN** 指定的 `--proxy-port` 已被其他进程占用
- **THEN** 服务启动失败，输出 `Error: port <n> is already in use`，退出码为 1

---

### Requirement: 健康检查接口

Proxy 服务 SHALL 提供 `GET /health` 接口，返回 proxy 自身状态及 WDA 连通性状态。

#### Scenario: 服务正常且 WDA 可达

- **WHEN** 调用方发送 `GET /health`，proxy 可连通 WDA
- **THEN** 返回 HTTP 200，body 为 `{"status": "ok", "wda": {"reachable": true, "session": "<session_id_or_null>"}}`

#### Scenario: WDA 不可达

- **WHEN** 调用方发送 `GET /health`，WDA 无响应
- **THEN** 返回 HTTP 200（proxy 自身正常），body 为 `{"status": "ok", "wda": {"reachable": false, "session": null}}`

---

### Requirement: 统一错误响应格式

Proxy 服务 SHALL 对所有接口的错误响应使用统一 JSON 格式：`{"error": "<error_code>", "detail": "<human_readable_message>"}`。

#### Scenario: WDA 通信错误

- **WHEN** 任意操作接口因 WDA 通信失败返回错误
- **THEN** 响应 body 符合 `{"error": "wda_<error_type>", "detail": "..."}` 格式，HTTP 状态码为 502 或 503

#### Scenario: 参数校验错误

- **WHEN** 调用方请求体缺少必填字段或字段类型错误
- **THEN** 返回 HTTP 422，body 包含 `{"error": "validation_error", "detail": [{"field": "<name>", "msg": "<reason>"}]}`

---

### Requirement: 请求超时保护

Proxy 服务 SHALL 对所有转发给 WDA 的请求设置默认超时：screenshot/click/swipe 为 5s，ui_dump 为 15s。

#### Scenario: 请求超过超时阈值

- **WHEN** WDA 在超时时间内无响应
- **THEN** proxy 中断等待，返回 HTTP 504，body 包含 `{"error": "wda_timeout", "detail": "Request timed out after <n>s"}`

#### Scenario: 调用方自定义超时

- **WHEN** 调用方在请求体中传入 `"timeout": 20`（秒）
- **THEN** proxy 使用调用方指定超时（上限 60s），覆盖默认值

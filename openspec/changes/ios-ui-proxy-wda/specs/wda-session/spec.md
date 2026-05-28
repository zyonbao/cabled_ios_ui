## ADDED Requirements

### Requirement: Proxy 建立 WDA session

Proxy 服务 SHALL 在第一次操作请求到来时，通过 `POST /session` 向 WDA 建立 session，并缓存 session ID 供后续请求复用。

#### Scenario: 首次操作触发 session 建立

- **WHEN** proxy 收到任意操作请求（screenshot / ui_dump / swipe / click）且当前无活跃 session
- **THEN** proxy 先向 WDA `POST /session` 建立 session，成功后执行原请求，并在响应头中包含 `X-WDA-Session-Id`

#### Scenario: WDA 未就绪时建立 session 失败

- **WHEN** proxy 尝试建立 session 但 WDA 无响应（连接超时 3s）
- **THEN** proxy 返回 HTTP 503，body 包含 `{"error": "wda_unavailable", "detail": "WDA not responding on <host>:<port>"}`

---

### Requirement: Proxy 保活 WDA session

Proxy 服务 SHALL 每 30 秒对活跃 session 发送一次 `GET /session/:id` 心跳请求，以防止 WDA 超时关闭 session。

#### Scenario: 心跳成功

- **WHEN** 后台心跳线程发送 `GET /session/:id`，WDA 返回 200
- **THEN** session 保持活跃，`last_heartbeat_at` 更新为当前时间

#### Scenario: 连续 3 次心跳失败后重建 session

- **WHEN** 连续 3 次心跳请求均失败（超时或非 2xx）
- **THEN** proxy 清除当前 session ID，下次操作请求到来时重新建立 session

---

### Requirement: Proxy 支持手动重置 session

Proxy 服务 SHALL 提供 `POST /session/reset` 接口，允许调用方强制关闭当前 session 并触发重建。

#### Scenario: 手动重置 session

- **WHEN** 调用方发送 `POST /session/reset`
- **THEN** proxy 向 WDA 发送 `DELETE /session/:id`（如 session 存在），清除本地 session 缓存，返回 HTTP 200 `{"status": "reset"}`

#### Scenario: 重置后操作自动重建 session

- **WHEN** 调用方在 `POST /session/reset` 后立即发送 screenshot 请求
- **THEN** proxy 自动建立新 session 后执行截图，返回正常结果

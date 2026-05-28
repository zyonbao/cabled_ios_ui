## ADDED Requirements

### Requirement: 截取 iOS 设备当前屏幕

Proxy 服务 SHALL 提供 `GET /screenshot` 接口，调用 WDA 的 `GET /screenshot` 端点，返回当前屏幕的 PNG 图像数据。

#### Scenario: 截图成功返回 PNG

- **WHEN** 调用方发送 `GET /screenshot`，query 参数 `format=png`（默认）
- **THEN** proxy 返回 HTTP 200，`Content-Type: image/png`，body 为原始 PNG 二进制数据

#### Scenario: 截图成功返回 base64

- **WHEN** 调用方发送 `GET /screenshot?format=base64`
- **THEN** proxy 返回 HTTP 200，`Content-Type: application/json`，body 为 `{"data": "<base64-string>", "format": "base64"}`

#### Scenario: WDA 截图失败

- **WHEN** WDA 返回非 2xx 状态或截图数据为空
- **THEN** proxy 返回 HTTP 502，body 包含 `{"error": "screenshot_failed", "detail": "<wda_error_message>"}`

---

### Requirement: 截图操作不依赖 App session

Proxy 的截图接口 SHALL 使用 WDA 的无 session 截图端点（`GET /screenshot` withoutSession），确保无论 App session 状态如何均可截图。

#### Scenario: 无活跃 App session 时截图

- **WHEN** WDA session 未建立或已过期，调用方发送截图请求
- **THEN** proxy 仍能成功返回截图，不触发 session 建立流程

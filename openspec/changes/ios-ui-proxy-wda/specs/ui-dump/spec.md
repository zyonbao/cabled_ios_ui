## ADDED Requirements

### Requirement: 导出 iOS 设备当前 UI 层级树

Proxy 服务 SHALL 提供 `GET /ui_dump` 接口，调用 WDA 的 `GET /source` 端点，返回当前屏幕的 UI 元素树。

#### Scenario: 默认返回 XML 格式

- **WHEN** 调用方发送 `GET /ui_dump`（无 format 参数）
- **THEN** proxy 调用 WDA `GET /source`，返回 HTTP 200，`Content-Type: application/xml`，body 为 WDA 返回的 XML 字符串

#### Scenario: 请求 JSON 格式

- **WHEN** 调用方发送 `GET /ui_dump?format=json`
- **THEN** proxy 调用 WDA `GET /source?format=json`，返回 HTTP 200，`Content-Type: application/json`，body 为解析后的 JSON 对象

#### Scenario: UI dump 超时

- **WHEN** WDA `GET /source` 响应超时（> 10s，复杂页面层级深时可能发生）
- **THEN** proxy 返回 HTTP 504，body 包含 `{"error": "ui_dump_timeout", "detail": "WDA source request timed out after 10s"}`

---

### Requirement: 支持可访问性 UI 树导出

Proxy 服务 SHALL 提供 `GET /ui_dump?mode=accessible` 接口，调用 WDA 的 `GET /wda/accessibleSource` 端点，返回仅包含可访问性元素的 UI 树。

#### Scenario: 可访问性模式导出

- **WHEN** 调用方发送 `GET /ui_dump?mode=accessible`
- **THEN** proxy 调用 WDA `GET /wda/accessibleSource`，返回 HTTP 200 及对应数据

#### Scenario: 普通模式与可访问性模式结果差异

- **WHEN** 同一屏幕分别调用默认模式和 accessible 模式
- **THEN** accessible 模式返回的元素数量 SHALL 少于或等于默认模式（过滤非可访问元素）

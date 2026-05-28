## ADDED Requirements

### Requirement: 坐标点击

Proxy 服务 SHALL 提供 `POST /click` 接口，接收屏幕坐标，通过 WDA W3C Actions 协议执行 tap 操作。

#### Scenario: 坐标点击成功

- **WHEN** 调用方发送 `POST /click`，body 为 `{"x": 200, "y": 400}`（逻辑点坐标）
- **THEN** proxy 向 WDA `POST /session/:id/actions` 发送 W3C pointer action（pointerDown + pointerUp，duration: 100ms），WDA 返回 200 后，proxy 返回 HTTP 200 `{"status": "ok"}`

#### Scenario: 坐标超出屏幕范围

- **WHEN** 调用方发送的坐标（x 或 y）超出设备屏幕逻辑分辨率（从 `GET /wda/screen` 获取）
- **THEN** proxy 返回 HTTP 400，body 包含 `{"error": "invalid_coordinate", "detail": "x/y out of screen bounds (<width>x<height>)"}`

#### Scenario: 点击操作 WDA 返回错误

- **WHEN** WDA `POST /actions` 返回非 2xx
- **THEN** proxy 返回 HTTP 502，body 包含 WDA 错误信息

---

### Requirement: 滑动手势

Proxy 服务 SHALL 提供 `POST /swipe` 接口，接收起止坐标和持续时间，通过 WDA W3C Actions 协议执行 swipe 手势。

#### Scenario: 基础 swipe 操作

- **WHEN** 调用方发送 `POST /swipe`，body 为 `{"from_x": 200, "from_y": 700, "to_x": 200, "to_y": 200, "duration": 500}`（duration 单位：毫秒）
- **THEN** proxy 向 WDA 发送 W3C Actions：`pointerDown` at (from_x, from_y) → `pause` duration ms → `pointerMove` to (to_x, to_y) → `pointerUp`，WDA 返回 200 后 proxy 返回 HTTP 200 `{"status": "ok"}`

#### Scenario: 使用默认 duration

- **WHEN** 调用方发送 `POST /swipe`，body 中不包含 `duration` 字段
- **THEN** proxy 使用默认 duration 300ms 执行滑动

#### Scenario: duration 为 0 或负数

- **WHEN** 调用方发送的 `duration` ≤ 0
- **THEN** proxy 返回 HTTP 400，body 包含 `{"error": "invalid_duration", "detail": "duration must be positive"}`

---

### Requirement: 长按手势

Proxy 服务 SHALL 提供 `POST /long_press` 接口，接收坐标和持续时间，通过 WDA W3C Actions 执行 long press。

#### Scenario: 长按操作

- **WHEN** 调用方发送 `POST /long_press`，body 为 `{"x": 200, "y": 400, "duration": 1500}`
- **THEN** proxy 向 WDA 发送 W3C Actions：`pointerDown` at (x, y) → `pause` duration ms → `pointerUp`，返回 HTTP 200 `{"status": "ok"}`

#### Scenario: 长按 duration 不足

- **WHEN** 调用方发送的 `duration` < 500ms（低于系统识别长按的最小时间）
- **THEN** proxy 仍执行操作（不做限制），但在响应中附加 warning：`{"status": "ok", "warning": "duration < 500ms may not trigger long press recognition"}`

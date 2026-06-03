## ADDED Requirements

### Requirement: 截图操作返回 PNG base64
系统 SHALL 通过 WDA `GET /screenshot` 获取设备截图，将响应中 `value` 字段的 base64 字符串封装为统一格式返回。此端点无需 WDA session。

#### Scenario: 截图成功
- **WHEN** 以有效 UDID 调用 `screenshot(target)`，WDA 正在运行
- **THEN** 返回 `{"ok": true, "data": {"mimeType": "image/png", "base64": "<base64字符串>"}}`, base64 解码后为合法 PNG 图像数据

#### Scenario: UDID 不存在时返回 BAD_TARGET
- **WHEN** 以不存在的 UDID 调用 `screenshot(target)`
- **THEN** 返回 `{"ok": false, "error": {"kind": "BAD_TARGET", ...}}`

#### Scenario: WDA 请求失败时返回 SUBPROCESS
- **WHEN** 以有效 UDID 调用 `screenshot(target)` 但 WDA 不可访问或返回错误
- **THEN** 返回 `{"ok": false, "error": {"kind": "SUBPROCESS", ...}}`

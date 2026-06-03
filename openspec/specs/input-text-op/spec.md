## ADDED Requirements

### Requirement: 输入文本前校验输入内容
系统 SHALL 在执行文本输入前，对 `text` 参数进行校验：拒绝包含换行符（`\n`、`\r`）、单引号（`'`）、反引号（`` ` ``）的文本，以及超过 1024 字节的文本。校验失败返回 `BAD_TARGET`。

#### Scenario: 包含换行符时返回 BAD_TARGET
- **WHEN** 调用 `input_text(target, "hello\nworld")`
- **THEN** 返回 `{"ok": false, "error": {"kind": "BAD_TARGET", ...}}`，不发起 WDA 请求

#### Scenario: 超过 1024 字节时返回 BAD_TARGET
- **WHEN** 调用 `input_text(target, text)` 且 `text` 编码后超过 1024 字节
- **THEN** 返回 `{"ok": false, "error": {"kind": "BAD_TARGET", ...}}`

#### Scenario: 合法文本通过校验
- **WHEN** 调用 `input_text(target, "hello world")` 且 WDA 正在运行
- **THEN** 继续执行 WDA 输入操作

### Requirement: 通过活跃元素 value API 输入文本
系统 SHALL 优先通过 `GET /session/<id>/element/active` 获取当前聚焦元素 ID，再使用 `POST /session/<id>/element/<id>/value` 写入文本。返回格式包含 `extra.length`（输入的字符数）。

#### Scenario: 活跃元素可用时通过 value API 输入
- **WHEN** 文本框已聚焦，调用 `input_text(target, "hello")`
- **THEN** 返回 `{"ok": true, "data": {"exitCode": 0, "stdout": "", "stderr": "", "extra": {"length": 5}}}` 且文本框内容为 `"hello"`

### Requirement: 活跃元素不可用时 fallback 到 W3C key actions
系统 SHALL 在 `/element/active` 返回 404 或无元素时，fallback 到通过 `POST /session/<id>/actions`（ActionType = key）逐字符发送文本。

#### Scenario: 无聚焦元素时 fallback 成功
- **WHEN** 调用 `input_text(target, "hi")` 但 `/element/active` 返回 404
- **THEN** 通过 W3C key actions 发送字符，返回 `{"ok": true, "data": {..., "extra": {"length": 2}}}`

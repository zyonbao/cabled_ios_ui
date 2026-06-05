## ADDED Requirements

### Requirement: 设置设备剪贴板

系统 SHALL 提供 `toolkit_api.set_pasteboard(target, text)`，把给定纯文本写入目标设备剪贴板，底层调用 WDA `POST /session/<id>/wda/setPasteboard`，`content` 字段为 UTF-8 文本经 Base64 编码后的字符串、`contentType` 为 `plaintext`。返回统一 envelope。

#### Scenario: 成功设置纯文本剪贴板

- **WHEN** WDA 在前台运行，调用 `set_pasteboard(target, "hello")`
- **THEN** 返回 `{"ok": true, "data": {...}}`，且设备剪贴板内容变为 `"hello"`

#### Scenario: 设备不存在时返回 BAD_TARGET

- **WHEN** 调用 `set_pasteboard(target, text)` 且 `target` 不存在
- **THEN** 返回 `{"ok": false, "error": {"kind": "BAD_TARGET", ...}}`，不发起 WDA 请求

### Requirement: 读取设备剪贴板

系统 SHALL 提供 `toolkit_api.get_pasteboard(target)`，读取目标设备剪贴板纯文本内容，底层调用 WDA `POST /session/<id>/wda/getPasteboard`（`contentType` 为 `plaintext`），把返回的 Base64 解码为 UTF-8 文本。返回 envelope 的 `data` SHALL 包含 `text`（解码后的字符串）与 `isText`（布尔，标识是否为可解码的文本内容）。

#### Scenario: 读取文本剪贴板

- **WHEN** WDA 在前台运行且剪贴板为文本 `"copied"`，调用 `get_pasteboard(target)`
- **THEN** 返回 `{"ok": true, "data": {"text": "copied", "isText": true}}`

#### Scenario: 剪贴板为非文本内容

- **WHEN** 设备剪贴板为图片等非文本内容，`plaintext` 读取返回空或无法解码为有效文本
- **THEN** 返回 `{"ok": true, "data": {"text": "", "isText": false}}`，由上层据 `isText` 提示「非文本内容」

### Requirement: 读写前自动前台化 WDA 并还原

由于 iOS 限制 `UIPasteboard` 仅在 App 前台可访问，`set_pasteboard` 与 `get_pasteboard` SHALL 在执行 WDA 读写前，记录当前前台 app 的 bundle id、把 WDA 切到前台（`/wda/apps/launch` 并轮询 `/wda/activeAppInfo` 确认），读写完成后再把记录的原 app 切回前台。还原失败 SHALL 不影响读写结果的返回。

#### Scenario: 读取后还原原前台 app

- **WHEN** 设备前台为某 app 且用户复制了文本，调用 `get_pasteboard(target)`
- **THEN** 先把 WDA 切到前台读取剪贴板，再把原 app 切回前台
- **AND** 返回读到的文本（系统剪贴板跨 app 持久）

#### Scenario: 设置后还原原前台 app

- **WHEN** 调用 `set_pasteboard(target, text)`
- **THEN** 先把 WDA 切到前台写入剪贴板，再把原 app 切回前台

### Requirement: 单次读取，「允许粘贴」弹窗由用户手动处理

iOS 16+ 在 WDA 首次读取其它 app 的剪贴板时会弹出「允许粘贴」系统弹窗，弹窗未处理前读取返回空。`get_pasteboard` SHALL 只做单次读取、不重试、不自动接受弹窗；若读到空则返回 `isText=false`，由用户手动点按弹窗后再次读取。

#### Scenario: 弹窗未处理时返回空

- **WHEN** 读取触发「允许粘贴」弹窗且用户尚未点按
- **THEN** 单次读取返回 `{"text": "", "isText": false}`，不重试、不自动接受

#### Scenario: 用户允许后再次读取成功

- **WHEN** 用户手动点按「允许粘贴」后再次调用 `get_pasteboard`
- **THEN** 读到剪贴板文本并返回 `isText=true`

### Requirement: web 控制台剪贴板端点

web 控制台 SHALL 暴露 `POST /api/set_pasteboard`（body 含 `target`、`text`）与 `POST /api/get_pasteboard`（body 含 `target`），分别代理到 `toolkit_api.set_pasteboard` 与 `toolkit_api.get_pasteboard`，并沿用现有错误码到 HTTP 状态码的映射（`BAD_TARGET` → 404，其余 → 503）。

#### Scenario: 通过端点设置剪贴板

- **WHEN** 客户端 `POST /api/set_pasteboard` 且 body 为 `{"target": "<udid>", "text": "hi"}`
- **THEN** 服务端调用 `set_pasteboard` 并返回成功的 `data`

#### Scenario: 通过端点读取剪贴板

- **WHEN** 客户端 `POST /api/get_pasteboard` 且 body 为 `{"target": "<udid>"}`
- **THEN** 服务端调用 `get_pasteboard` 并返回包含 `text` 与 `isText` 的 `data`

# pasteboard-op (delta)

## MODIFIED Requirements

### Requirement: 设置设备剪贴板

系统 SHALL 提供 `toolkit_api.set_pasteboard(target, content, content_type="plaintext")`，支持 `plaintext` / `url` / `image` 三种 `content_type`，把内容写入目标设备剪贴板，底层调用 WDA `POST /session/<id>/wda/setPasteboard`，`contentType` 透传，`content` 按类型编码后 Base64。`plaintext` 与 `url` 的 `content` 为字符串、按 UTF-8 编码；`image` 的 `content` 为图片原始字节（PNG/JPEG），直接 Base64。大小校验按类型区分：`plaintext` / `url` 维持现有上限（64 KiB），`image` 采用独立、更大的字节上限（默认 16 MiB）。超限 SHALL 返回 `BAD_TARGET` 且不发起 WDA 请求。返回统一 envelope。

#### Scenario: 成功设置纯文本剪贴板

- **WHEN** WDA 在前台运行，调用 `set_pasteboard(target, "hello")`（默认 `content_type="plaintext"`）
- **THEN** 返回 `{"ok": true, "data": {...}}`，且设备剪贴板内容变为 `"hello"`

#### Scenario: 成功设置 URL 剪贴板

- **WHEN** 调用 `set_pasteboard(target, "https://example.com", content_type="url")`
- **THEN** 以 `contentType=url` 写入，设备剪贴板 URL 项变为该链接，返回 `{"ok": true, ...}`

#### Scenario: 成功设置图片剪贴板

- **WHEN** 调用 `set_pasteboard(target, <png_bytes>, content_type="image")` 且字节数在 image 上限内
- **THEN** 以 `contentType=image`、`content` 为图片字节的 Base64 写入，设备剪贴板图片项被设置，返回 `{"ok": true, ...}`

#### Scenario: 图片超过上限被拒绝

- **WHEN** 调用 `set_pasteboard(target, <bytes>, content_type="image")` 且字节数超过 image 上限
- **THEN** 返回 `{"ok": false, "error": {"kind": "BAD_TARGET", ...}}`，不发起 WDA 请求

#### Scenario: 设备不存在时返回 BAD_TARGET

- **WHEN** 调用 `set_pasteboard(target, content, content_type)` 且 `target` 不存在
- **THEN** 返回 `{"ok": false, "error": {"kind": "BAD_TARGET", ...}}`，不发起 WDA 请求

### Requirement: 读取设备剪贴板

系统 SHALL 提供 `toolkit_api.get_pasteboard(target, content_type="plaintext")`，读取目标设备剪贴板指定类型内容，底层调用 WDA `POST /session/<id>/wda/getPasteboard`（`contentType` 透传），把返回的 Base64 解码。返回 envelope 的 `data` SHALL 包含 `contentType`（实际内容类型：`plaintext` / `image` / `empty`）。`plaintext` 态 SHALL 包含 `text`（解码后的字符串）与 `isText=true`；非文本或空 SHALL 返回 `text=""`、`isText=false`；`image` 态 SHALL 额外包含 `image`（PNG 的 Base64 字符串）。默认 `content_type="plaintext"` 时行为与既有纯文本读取一致，SHALL NOT 为探测类型而额外发起第二次读取。

#### Scenario: 读取文本剪贴板

- **WHEN** WDA 在前台运行且剪贴板为文本 `"copied"`，调用 `get_pasteboard(target)`
- **THEN** 返回 `{"ok": true, "data": {"contentType": "plaintext", "text": "copied", "isText": true}}`

#### Scenario: 文本读取得到空或非文本

- **WHEN** 以默认 `plaintext` 读取且剪贴板为空或为图片等非文本内容
- **THEN** 返回 `{"ok": true, "data": {"contentType": "empty", "text": "", "isText": false}}`，由上层据 `isText` 提示「非文本内容」

#### Scenario: 显式读取图片剪贴板

- **WHEN** 调用 `get_pasteboard(target, content_type="image")` 且剪贴板为图片
- **THEN** 返回 `{"ok": true, "data": {"contentType": "image", "image": "<png base64>", "isText": false}}`

### Requirement: web 控制台剪贴板端点

web 控制台 SHALL 暴露 `POST /api/set_pasteboard` 与 `POST /api/get_pasteboard`，代理到 `toolkit_api.set_pasteboard` / `get_pasteboard`，并沿用现有错误码到 HTTP 状态码的映射（`BAD_TARGET` → 404，其余 → 503）。`POST /api/set_pasteboard` body SHALL 接受 `target` 与可选 `contentType`（默认 `plaintext`）：`plaintext` / `url` 用 `text` 字段（字符串）；`image` 用 `image` 字段（图片字节的 Base64）。为向后兼容，仅含 `{target, text}` 的请求 SHALL 等价于 `contentType=plaintext`。`POST /api/get_pasteboard` body SHALL 接受 `target` 与可选 `contentType`，并原样返回包含 `contentType` 的 `data`。

#### Scenario: 通过端点设置纯文本（向后兼容）

- **WHEN** 客户端 `POST /api/set_pasteboard` 且 body 为 `{"target": "<udid>", "text": "hi"}`
- **THEN** 服务端以 `plaintext` 调用 `set_pasteboard` 并返回成功的 `data`

#### Scenario: 通过端点设置图片

- **WHEN** 客户端 `POST /api/set_pasteboard` 且 body 为 `{"target": "<udid>", "contentType": "image", "image": "<base64>"}`
- **THEN** 服务端以 `image` 调用 `set_pasteboard`；超过 image 上限时返回 404（`BAD_TARGET`）

#### Scenario: 通过端点读取剪贴板

- **WHEN** 客户端 `POST /api/get_pasteboard` 且 body 为 `{"target": "<udid>"}`
- **THEN** 服务端以 `plaintext` 调用 `get_pasteboard` 并返回包含 `contentType`、`text`、`isText` 的 `data`

# Design

## Context

剪贴板三层结构：WDA（设备端，`FBPasteboard`）→ 代理层（`device.py` / `toolkit_api.py`）→ UI（web `app.js` / slide6 `keymouse_tab.py`）。WDA 已支持 `plaintext` / `image` / `url`，但代理层写死 `plaintext` 且对内容设 64 KiB 上限，UI 只有纯文本输入。本设计在不改 WDA 的前提下打通图片/URL，并补齐两个「读取后复制到本机」设置。

## Decisions

### 1. 代理层多类型接口

`set_pasteboard(target, content, content_type="plaintext")`：
- `plaintext` / `url`：`content` 为字符串，UTF-8 → Base64，`contentType` 透传给 WDA。`url` 仍由 WDA 校验是否为合法 URL，失败返回错误。
- `image`：`content` 为图片原始字节（PNG/JPEG），直接 Base64，`contentType=image`。
- 大小上限按类型区分：文本/URL 维持现有 64 KiB（`_PASTEBOARD_MAX_BYTES`）；image 采用独立常量 `_PASTEBOARD_IMAGE_MAX_BYTES`（默认 16 MiB）。超限返回 `BAD_TARGET`（沿用现有「超限」错误风格），不发起 WDA 请求。

`get_pasteboard(target, content_type="plaintext")`：
- 新增可选 `content_type` 参数。默认 `plaintext`，保持现有「单次读取、不重试、不自动接受『允许粘贴』弹窗」语义（见 `pasteboard-op` 既有要求），**不做** plaintext→image 的二次自动读取，以免触发两次系统弹窗。
- 返回 `data` 增加 `contentType` 字段；`image` 态返回 `image`（PNG Base64），`text` 为空、`isText=false`。

> WHY 不自动双读：iOS 16+ 每次跨 app 读取会弹「允许粘贴」，自动双读会弹两次并违背既有「单次读取」要求。读取图片由调用方显式指定 `content_type=image`。

### 2. 10 MiB 二次确认（UI 层）

10 MiB 阈值是**用户体验确认**，放在 UI 层（发送前判断图片字节数），与代理层 16 MiB 硬上限是两件事：
- 0–10 MiB：直接发送。
- 10–16 MiB：弹「过大、耗时较长」确认框，确认后发送、取消则不发。
- >16 MiB：代理层硬上限拒绝（UI 也可前置提示）。

### 3. 设置弹窗的文字/图片互斥（2.1）

输入窗维护「当前内容种类」单一状态：
- 仅文字 或 仅图片，二者互斥。
- 输入框已有文字时点击「添加图片」：弹二次确认「将清空已输入文字」，确认后清空文字并载入图片预览；取消则保持文字。
- 已有图片时再选图片：直接替换（无文字丢失风险，不强制确认）。
- 「确认」发送时：有图片 → `image`；否则文本若识别为 URL → `url`，否则 → `plaintext`。

### 4. URL 识别（2.2）

仅对**纯文本且整体为单个 URL**的输入按 `url` 发送，避免把含 URL 的长文本误判。判定：trim 后无内部空白/换行，且匹配 `scheme://`（`http`/`https`/`ftp` 等常见 scheme）或可被 `urllib`/`URL()` 解析出 scheme+host。不满足则按 `plaintext`。WDA 侧对非法 URL 会再次校验兜底。

### 5. 拖拽图片到画面区域（3，桌面端）

键鼠操作画面控件接受 `image/*` 文件拖入（复用现有拖拽模式，参考 App 列表 `.ipa`、Profile `.mobileconfig` 的 drop 实现）：
- drop 后读取文件字节，走与设置弹窗相同的 10 MiB 确认与 `set_pasteboard(..., content_type="image")` 路径。
- 仅在设备已连接时接受 drop；非图片文件给出「仅支持图片」提示。
- drop 不应与现有手势（点按/滑动/长按）冲突——拖拽进入用 Qt 的 `dragEnterEvent`/`dropEvent`，与鼠标按下/抬起手势链路分离。

### 6. 两个设置开关（1.1 / 1.2）

持久化到 `keymouse_settings`（QSettings），新增两个布尔键，默认 **关闭**（保持现有「弹窗展示」为默认行为，避免静默改变剪贴板）：
- `keymouse/pasteboard_auto_copy_host`（1.1）：开启时「读取剪贴板」成功且为文本态后不弹展示窗，直接写入本机剪贴板并提示「已复制到本机」；非文本/失败仍按原提示。
- `keymouse/ui_xml_auto_copy_host`（1.2）：开启时「UI XML」加载成功后不弹查看窗，直接把 XML 文本写入本机剪贴板并提示。

开关由 `keymouse_settings_widget` 渲染、即时写回（与现有 keymouse 设置一致）。

## Risks / Trade-offs

- 图片经 Base64 膨胀约 33% 且全量驻留内存；16 MiB 原图 → ~21 MiB 请求体。CocoaHTTPServer 无 body 上限，受设备内存约束，16 MiB 上限留出安全余量。
- 读取图片需调用方显式指定类型，UI 默认仍读文本；如后续需要「读取并自动识别图片」，再单独设计（须解决双弹窗问题）。

## Migration

- 现有 `set_pasteboard(target, text)` 调用通过 `content_type` 默认值 `plaintext` 保持兼容。
- web `/api/set_pasteboard` 保留 `{target, text}` 形态（等价 `contentType=plaintext`），新增 `contentType` 与图片字段为可选扩展。

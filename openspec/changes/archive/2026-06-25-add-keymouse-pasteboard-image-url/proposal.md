# Why

键鼠操作的剪贴板读写目前只支持纯文本（`contentType=plaintext`），但 WDA `FBPasteboard` 已原生支持 `plaintext` / `image` / `url` 三种类型。用户在键鼠操作中常需把图片或链接写入设备剪贴板，并希望读取设备剪贴板或 UI XML 后能快速取回本机。本次改动打通图片 / URL 类型，并补齐两项「读取后直接复制到本机」的设置项，减少弹窗操作。

WDA 端无需改动（`setData:forType:` / `dataForType:` 已支持三种类型）；改动集中在代理层、web 端点与前端 UI。当前唯一的硬上限是代理层自设的 64 KiB 文本上限（`_PASTEBOARD_MAX_BYTES`），对图片过小，需按类型放宽。

# What Changes

1. **设置（Key/Mouse Tab 设置）新增两个开关**（文案待定）：
   - 1.1 读取设备剪贴板后不弹窗，直接把内容复制到本机系统剪贴板。
   - 1.2 获取 UI XML 后不弹窗，直接把 XML 复制到本机系统剪贴板。
2. **剪贴板设置弹窗支持 文字 / 图片 / URL 三类**：
   - 2.1 输入窗允许输入文字，也允许添加图片，但一次只能存在一种；已有文字时添加图片会清空文字，且需二次确认。
   - 2.2 发送文字时若识别为 URL，则以 `url` 类型写入设备剪贴板。
3. **拖拽图片到画面区域写入设备剪贴板**：在键鼠操作画面显示区域拖入图片文件，将该图片以 `image` 类型写入设备剪贴板。
4. **大图片二次确认**：2 与 3 中，待发送图片超过 10 MiB 时提示「图片过大、耗时较长」，需用户确认或取消。
5. **后端能力扩展**：`toolkit_api.set_pasteboard` / `get_pasteboard` 与 web `/api/set_pasteboard` / `/api/get_pasteboard` 支持 `contentType`（`plaintext` / `url` / `image`），并对 image 放宽字节上限。

# Impact

- Affected specs: `pasteboard-op`、`console-pasteboard-ui`
- Affected code:
  - `ios_toolkit/device.py`、`ios_toolkit/toolkit_api.py`（多类型 set/get、放宽 image 上限）
  - `web_page/web_server.py`、`web_page/web/app.js`（端点与前端弹窗、URL 识别、复制到本机）
  - `slide6_ui/keymouse/keymouse_tab.py`（设置弹窗、拖拽、读取后复制、UI XML 复制）
  - `slide6_ui/common/keymouse_settings.py`、`slide6_ui/common/keymouse_settings_widget.py`（两个新开关持久化与渲染）
  - `slide6_ui/languages/zh-CN.json`、`en-US.json`（新增文案）
- WDA：无需改动。

# Open questions / 待确认

- 两个设置开关与「拖拽到画面」当前按桌面端（slide6）落地；web 端是否同步实现拖拽到镜像画布待定（本提案标记为可选）。
- 1.2「UI XML 复制到本机」的开关在 spec 中归入 `console-pasteboard-ui`（与「复制到本机」交互同源），如团队认为应归 UI XML 查看器自有 spec，审阅时可平移。

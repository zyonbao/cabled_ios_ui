## Context

`executor_ios` 已有一套基于 house-arrest 的 App 沙盒 AFC 访问（`afc_list/pull/push/rm/mkdir/rename`，`root` 取 `documents`/`container`，详见 add-app-list-and-file-manager），并在 `slide6_console/afc_browser.py` 实现了通用文件浏览器对话框。本变更在此基础上扩展到**设备媒体分区**（`com.apple.afc`，经 lockdown 直连，不含 app 沙盒），并新增「文件系统」与「相册（DCIM）」两个 UI Tab。所有访问复用现有后台 `_bg_loop` 与 `AsyncRunner`，无需 WDA / tunnel。

## Goals / Non-Goals

**Goals:**

- 以最小新增面，把 AFC 能力扩展到媒体分区根：复用现有 `afc_*` 契约，新增 `root="media"`。
- 「文件系统」Tab 复用现有 `AfcBrowserDialog` 的浏览/传输/删除/新建/重命名交互。
- 「相册」Tab 提供缩略图网格、双击查看大图、带元数据导入/导出、多选删除（二次确认）。
- 导入/导出保字节、保时间戳，EXIF 等元数据随文件原样保留。

**Non-Goals:**

- 不修改"照片"App 的相册数据库（Photos DB）；不保证经 AFC 写入 `DCIM` 的照片立即出现在相册。
- 不做图片转码 / 压缩 / 编辑；缩略图仅在本地按比例缩放展示。
- 不做目录递归大图预览；大图查看仅针对单个被双击的图片/视频首帧（视频暂仅展示占位）。
- 不触碰 app 沙盒访问（已由既有能力覆盖）。

## Decisions

### 决策 1：`root="media"` 复用现有 AFC 契约

在 `_validate_root` 接受 `media`；`_AFC_BASE["media"]="/"`（媒体分区根即逻辑根，无需偏移）。`iOSDevice._with_afc` 按 `root` 分流：

- `media` → `AfcService(lockdown)`（`com.apple.afc`），忽略 `bundle_id`。
- `documents`/`container` → 现有 `HouseArrestService`（需 `bundle_id`）。

`toolkit_api.afc_*` 在 `root="media"` 时允许 `bundle_id` 为空。这样「文件系统」「相册」两 Tab 直接复用 `afc_list/pull/push/rm/mkdir/rename`，零新增传输函数。

**备选**：为媒体分区另起一套 `media_*` 函数。**否决**：与沙盒 AFC 高度重复，维护成本高。

### 决策 2：新增 `afc_read(target, root, remote_path, max_bytes=None)` 供缩略图

相册网格需要为每个条目读取图片字节生成缩略图。逐个 `afc_pull` 落地临时文件再读盘开销大。新增 `afc_read` 直接经 AFC `get_file_contents`（或分块 `fopen/fread`）返回 bytes（受 `max_bytes` 上限保护，超大文件截断或跳过）。UI 侧用 `QImage.fromData` 缩放成缩略图。

**备选**：复用 `afc_pull` 到临时目录。**否决**：批量缩略图会产生大量临时文件与磁盘往返。

### 决策 3：相册数据获取——基于 `/DCIM` 的 AFC 列举

DCIM 位于媒体根 `/DCIM`，其下为 `100APPLE`、`101APPLE`… 子目录，含 `IMG_*.HEIC/JPG/MOV` 等。「相册」Tab 即对 `root="media"`、路径 `/DCIM/...` 的浏览，但渲染为**缩略图网格**而非列表。条目元数据（名称/大小/mtime/是否目录）来自 `afc_list`；缩略图按需异步加载（仅可见项），按 remote 路径在内存缓存，避免滚动重复拉取。

### 决策 4：带元数据导入/导出语义

- 导出（pull）：`AfcService.pull` 写入文件字节并 `os.utime` 同步设备侧 `st_mtime`；EXIF/创建时间等嵌入图片文件内的元数据原样保留。文件夹递归导出同既有语义。
- 导入（push）：`AfcService.push` 写入字节，文件夹递归。导入照片到 `DCIM` 在文件层面保留元数据；是否登记进 Photos DB 取决于系统索引（见风险）。

### 决策 5：缩略图查看与多选删除交互

- 缩略图网格用 `QListView`（IconMode）或带图标的 `QListWidget`；双击图片项弹出大图查看对话框（`QImage` 适配窗口缩放）。
- 多选删除：网格开启 `ExtendedSelection`，"删除"对选中项弹**一次**汇总二次确认（列出数量/示例名称），确认后逐个 `afc_rm` 并刷新。

### 决策 6：UI 复用与新增

- 「文件系统」Tab 复用 `AfcBrowserDialog`：将其作为嵌入式面板或以 `root="media"`、起始路径 `/` 打开；为复用，浏览器的 `bundle_id` 在 media 模式可传空串。
- 「相册」Tab 为新组件（`slide6_console/dcim_album.py`），网格 + 大图查看 + 导入/导出/删除，传输仍走 `afc_*(root="media")` 与 `afc_read`。

## Risks / Trade-offs

- [经 AFC 写入 DCIM 不一定登记进 Photos DB] → UI 提示"已写入文件，相册可见性取决于系统索引"，不声称写入相册库。
- [媒体分区部分目录受限/只读（如 `PhotoData`）] → 列举/写入失败时返回明确 `error`，UI 友好提示，不崩溃。

> 真机预验证（iOS 17.6.1，无 tunnel）：`com.apple.afc` 经 usbmux 连接成功；`list '/'` 得到 `Downloads/Books/Photos/DCIM/iTunes_Control/MediaAnalysis/PhotoData/PublicStaging`；`list '/DCIM'` 得到 `.MISC/100APPLE`；在 `/DCIM` 下 **push + get_file_contents + rm 均成功**——即媒体分区与 DCIM 的列举/导入/删除权限可用。`stat` 返回 `st_size/st_mtime/st_birthtime/st_ifmt`（`st_mtime` 为 `datetime`，入包络前需转 epoch/字符串，复用既有 `afc_list` 映射）。
>
> 实现要点：`AfcService` 的 `listdir/stat/push/rm/get_file_contents` 实际为**协程**（被装饰，`inspect.iscoroutinefunction` 会误报为同步），调用处必须 `await`。`usbmux.list_devices()` 亦为异步。
- [批量缩略图内存/往返开销] → 仅对可见项按需加载、按路径缓存、`afc_read` 设字节上限；非图片/超大文件用占位图标。
- [HEIC 等格式解码] → 开发环境 PySide6 的 `QImageReader.supportedImageFormats()` **已含 `heic`/`heif`**（iPhone 照片可原生解码），无需 `pillow_heif`。但 Nuitka 打包后必须连带 **heif 图像格式插件（qheif）与 libheif**；打包验证时需确认。解码失败统一回退占位图标，仍可正常导出/删除。
- [缩略图无设备端预览，需拉全图字节] → DCIM 无服务端缩略图，`afc_read` 需取整张图（HEIC/JPG 常为数 MB）再本地缩放；相册条目多时 I/O 与内存压力大。缓解：仅可见项按需加载、按路径缓存、限制并发、对超过阈值（如 >N MB）的文件跳过解码直接占位；后续可改为解析 EXIF 内嵌缩略图以大幅降本。
- [媒体分区路径越界/注入] → 复用既有 `_safe_remote_path` 规范化与越界校验。
- [删除为破坏性且媒体分区影响真实相册] → 多选删除强制二次确认并展示影响范围。

### 决策 7：「文件系统」Tab 采用内联面板（已确认）

将 `AfcBrowserDialog` 的浏览能力抽成可嵌入的面板组件，直接内联到「文件系统」Tab，而非弹窗，以贴合 Tab 形态。抽象后弹窗与内联面板复用同一浏览器组件（差异仅在容器）。

**备选**：直接以弹窗形式复用 `AfcBrowserDialog`。**否决**：Tab 内再弹窗交互割裂。

### 决策 8：相册视频首版仅占位、不做首帧预览（已确认）

视频（.MOV/.MP4 等）在缩略图网格与双击查看时**仅显示占位图标**（标注类型/文件名），不提取首帧预览；视频仍可正常**导出/删除/导入**。首帧预览留作后续增强。

**备选**：用 ffmpeg/AVFoundation 提取首帧。**否决**：引入额外依赖与解码成本，首版不必要。

## Open Questions

（暂无；上述开放项已确认并固化为决策 7 / 决策 8。）

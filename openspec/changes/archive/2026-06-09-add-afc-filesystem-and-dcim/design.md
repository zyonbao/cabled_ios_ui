## Context

`executor_ios` 已有一套基于 house-arrest 的 App 沙盒 AFC 访问（`afc_list/pull/push/rm/mkdir/rename`，`root` 取 `documents`/`container`，详见 add-app-list-and-file-manager），并在 `slide6_console/afc_browser.py` 实现了通用文件浏览器对话框。本变更在此基础上扩展到**设备媒体分区**（`com.apple.afc`，经 lockdown 直连，不含 app 沙盒），并新增「文件系统」与「相册（DCIM）」两个 UI Tab。所有访问复用现有后台 `_bg_loop` 与 `AsyncRunner`，无需 WDA / tunnel。

## Goals / Non-Goals

**Goals:**

- 以最小新增面，把 AFC 能力扩展到媒体分区根：复用现有 `afc_*` 契约，新增 `root="media"`。
- 「文件系统」Tab 复用现有 `AfcBrowserDialog` 的浏览/传输/删除/新建/重命名交互。
- 「相册」Tab 提供缩略图网格、双击查看大图、带元数据导出（不提供导入到相册与删除）。
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

### 决策 2：本地持久缩略图缓存 + 不自行解码 HEIC（真机确认）

真机（iOS 17.6.1）确认 iOS 自身为每个 DCIM 资源维护了**小 JPG 缩略图**，且**路径按原文件名直接映射**，无需解析 `Photos.sqlite`：

```
原图：  /DCIM/<相册>/<文件名>                 例：/DCIM/100APPLE/IMG_0003.PNG
缩略图：/PhotoData/Thumbnails/V2/DCIM/<相册>/<文件名>/<id>.JPG   例：.../IMG_0003.PNG/5005.JPG（≈4KB，JPG）
```

**本地持久缓存（按设备）**：app 维护一个磁盘缓存目录（如 `~/Library/Caches/CablediOS/thumbs/<udid>/`），以 remote 路径为 key、以原图 `(st_size, st_mtime)` 为失效依据，缓存内容为**小 JPEG**。缓存跨会话持久；进入「相册」Tab/选中设备后对可见项优先建缓存，其余可后台渐进补齐。

**建缓存流水线**（每项异步、写盘持久）：

1. **iOS 缩略图命中**：经 `afc_read(root="media")` 读取 `PhotoData/Thumbnails/V2/DCIM/<相册>/<文件名>/` 下 JPG（取其一/最大者，几 KB），**直接落地为本地缓存**（已是 JPEG，无需解码）。
2. **缺失（新照片未索引/其他 iOS 布局不同）**：`afc_read` 读原图字节，生成本地 JPEG 缩略图后落地缓存。
3. **占位**：原图超过阈值或无法生成 → 占位图标（视频等非图片项始终占位）。

**HEIC 解码：用 `pillow-heif`，不依赖 Qt 的 HEIF 解析（跨平台、打包确定）**：
- **HEIC/HEIF**（按扩展名 `.heic/.heif` 判定）用 `pillow-heif`（Pillow）解码：`register_heif_opener()` 后 `Image.open(BytesIO(bytes))`，缩放后保存为 JPEG（缩略图），或转 `QImage/QPixmap` 用于预览。
- **非 HEIC**（PNG/JPEG 等）走 `QImage`（Qt 核心格式，无需任何图像插件）解码缩放。
- 刻意**不使用 Qt 的 heif 插件**：即使环境带了 `qheif` 也绕开，HEIC 一律交 `pillow-heif`，使打包依赖单一确定（只看 `pillow-heif` 自带的 libheif，不关心 Qt 是否打进 heif 插件）。
- 这样**网格只显示 JPEG，预览只显示 JPEG/PNG**，无平台特定子进程。

缩略图统一用 **JPEG**（体积小、足够预览）；仅当源本身是 PNG（如截图）时直接沿用 PNG，不必要地转码。

`pillow-heif` 为**必备依赖**；其 wheel 为 mac/win/linux 自带 libheif，打包随产物携带即可。`pillow-heif` 解码失败（极少）回退占位图标。

新增 `afc_read(target, bundle_id, root, remote_path, max_bytes=None)` 直接经 AFC `get_file_contents`（或分块）返回 bytes（`max_bytes` 保护步骤 2 不一次性载入超大原图）。

**备选**：用 Qt `QImage` 解码 HEIC（依赖 qheif 插件）。**否决**：打包后插件随产物与否不确定，可移植性差。
**备选**：用系统 `sips` 转码。**否决**：仅 macOS。
**备选**：解析 `.ithmb` 旧式缩略图容器。**否决**：格式私有、跨版本脆弱；`V2/DCIM` 的按名映射 JPG 更稳更简单。

### 决策 3：相册数据获取——基于 `/DCIM` 的 AFC 列举

DCIM 位于媒体根 `/DCIM`，其下为 `100APPLE`、`101APPLE`… 子目录，含 `IMG_*.HEIC/JPG/MOV` 等。「相册」Tab 即对 `root="media"`、路径 `/DCIM/...` 的浏览，但渲染为**缩略图网格**而非列表。条目元数据（名称/大小/mtime/是否目录）来自 `afc_list`；缩略图按需异步加载（仅可见项），按 remote 路径在内存缓存，避免滚动重复拉取。

### 决策 4：相册导出（带元数据）与查看；不提供"导入到相册"与"删除"

- **导出（pull，带元数据）**：`AfcService.pull` 写入文件字节并 `os.utime` 同步设备侧 `st_mtime`；EXIF/创建时间等嵌入文件内的元数据原样保留。HEIC 原样导出 HEIC（不转码），用户本机能否预览由用户自备软件决定。
- **查看（双击）**：HEIC/HEIF 用 `pillow-heif` 解码为像素再转 `QPixmap` 显示；非 HEIC 用 `QImage` 直接显示。不落地转码原文件。导出仍是原始字节（HEIC 原样）。
- **不在「相册」Tab 提供"导入到相册"与"删除"**：Apple 相册由系统照片库索引（PhotoData）维护，并非纯文件管理；经 AFC 写入或删除 `/DCIM` 下文件**不能可靠地**反映到"照片"App（是否入库/移除取决于系统索引）。可靠的相册增删需由运行在设备上的 iOS App 调用系统照片库接口（PhotoKit）完成，超出本桌面工具经 AFC 的能力边界。故相册 Tab 仅做浏览/查看/导出。若用户确需对设备做文件级写入/删除，可走「文件系统」Tab 的 AFC 导入/删除（用户自担可见性后果）。

**备选**：相册 Tab 直接提供导入/删除。**否决**：经 AFC 的文件级增删不能可靠反映到"照片"App，易误导用户以为已加入/移出相册。

### 决策 5：缩略图查看交互（仅浏览/查看，无删除）

- 缩略图网格用 `QListView`（IconMode）或带图标的 `QListWidget`；双击图片项弹出大图查看对话框（`QImage` 适配窗口缩放）。视频仅占位（见决策 8）。
- 相册 Tab **不提供删除**（理由见决策 4）；文件级删除改由「文件系统」Tab 经 `afc_rm` 完成（带二次确认）。

### 决策 6：UI 复用与新增

- 「文件系统」Tab：把 `AfcBrowserDialog` 的浏览能力抽成**可嵌入面板**内联到 Tab（见决策 7），以 `root="media"`、起始路径 `/` 打开；media 模式 `bundle_id` 传空串。
- 「相册」Tab 为新组件（`slide6_console/dcim_album.py`），网格 + 大图查看 + 导出（不含导入/删除），传输走 `afc_*(root="media")` 与 `afc_read`（缩略图优先读 `PhotoData/Thumbnails`）。

## Risks / Trade-offs

- [经 AFC 写入 DCIM 不一定登记进 Photos DB] → UI 提示"已写入文件，相册可见性取决于系统索引"，不声称写入相册库。
- [媒体分区部分目录受限/只读（如 `PhotoData`）] → 列举/写入失败时返回明确 `error`，UI 友好提示，不崩溃。

> 真机预验证（iOS 17.6.1，无 tunnel）：`com.apple.afc` 经 usbmux 连接成功；`list '/'` 得到 `Downloads/Books/Photos/DCIM/iTunes_Control/MediaAnalysis/PhotoData/PublicStaging`；`list '/DCIM'` 得到 `.MISC/100APPLE`；在 `/DCIM` 下 **push + get_file_contents + rm 均成功**——即媒体分区与 DCIM 的列举/导入/删除权限可用。`stat` 返回 `st_size/st_mtime/st_birthtime/st_ifmt`（`st_mtime` 为 `datetime`，入包络前需转 epoch/字符串，复用既有 `afc_list` 映射）。
>
> 实现要点：`AfcService` 的 `listdir/stat/push/rm/get_file_contents` 实际为**协程**（被装饰，`inspect.iscoroutinefunction` 会误报为同步），调用处必须 `await`。`usbmux.list_devices()` 亦为异步。
- [批量缩略图内存/往返开销] → 仅对可见项按需加载、按路径缓存、`afc_read` 设字节上限；非图片/超大文件用占位图标。
- [HEIC 等格式解码] → 用必备依赖 `pillow-heif`（不依赖 Qt heif 插件），非 HEIC 用 QImage；解码失败回退占位。打包只需确认 `pillow-heif` 及其 libheif 随产物存在（其 wheel 自带）。
- [缩略图 I/O 与内存] → 首选复用 iOS 端小 JPEG（几 KB），仅缺失时才拉原图生成；本地磁盘缓存按 `(size,mtime)` 失效、跨会话持久；仅可见项优先、其余后台渐进、限制并发；超阈值原图跳过转码直接占位。后续可改为解析 EXIF 内嵌缩略图进一步降本。
- [媒体分区路径越界/注入] → 复用既有 `_safe_remote_path` 规范化与越界校验。
- [删除为破坏性操作] → 删除仅在「文件系统」Tab 提供并强制二次确认；相册 Tab 不提供删除（经 AFC 文件级删除不能可靠反映到"照片"App，需 iOS App 调系统照片库接口）。

### 决策 7：「文件系统」Tab 采用内联面板（已确认）

将 `AfcBrowserDialog` 的浏览能力抽成可嵌入的面板组件，直接内联到「文件系统」Tab，而非弹窗，以贴合 Tab 形态。抽象后弹窗与内联面板复用同一浏览器组件（差异仅在容器）。

**备选**：直接以弹窗形式复用 `AfcBrowserDialog`。**否决**：Tab 内再弹窗交互割裂。

### 决策 8：相册视频首版仅占位、不做首帧预览（已确认）

视频（.MOV/.MP4 等）在缩略图网格与双击查看时**仅显示占位图标**（标注类型/文件名），不提取首帧预览；视频仍可正常**导出**（相册 Tab 不提供删除/导入）。首帧预览留作后续增强。

**备选**：用 ffmpeg/AVFoundation 提取首帧。**否决**：引入额外依赖与解码成本，首版不必要。

## Open Questions

（暂无；上述开放项已确认并固化为决策 7 / 决策 8。）

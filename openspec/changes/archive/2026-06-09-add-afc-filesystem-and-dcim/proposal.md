## Why

当前 CablediOS.app 的文件能力仅限于 **App 沙盒**（经 house-arrest 访问 Documents / 容器）。但 iOS 测试中还高频需要访问**设备媒体分区**（`com.apple.afc` 根，含 `DCIM`、`Downloads`、`Books` 等，不含 app 沙盒），尤其是**相册（DCIM）**的批量浏览与导出。底层 `pymobiledevice3` 的 `AfcService` 原生支持媒体分区访问，无需新增依赖即可补齐这块空白；且 iOS 为每张 DCIM 照片维护了按文件名映射的小 JPG 缩略图（`PhotoData/Thumbnails/V2/DCIM/...`），可直接复用以高效出图。

## What Changes

- `executor_ios` 扩展 AFC 访问到**设备媒体分区根**（`com.apple.afc`，经 lockdown 直连，**不含** app 沙盒）：新增 `root="media"`，复用现有 `afc_list/afc_pull/afc_push/afc_rm/afc_mkdir/afc_rename` 语义（`media` 模式忽略 `bundle_id`）；新增按需读取文件字节的 `afc_read`（供缩略图加载，避免逐个落地临时文件）。
- 主界面新增两个左侧 Tab：
  - **「文件系统」Tab**：浏览设备媒体分区目录树，支持导入 / 导出（文件与文件夹）/ 删除（二次确认）/ 新建文件夹 / 重命名，交互与 App 文件浏览器一致。
  - **「相册」Tab**：DCIM 相册管理——以**缩略图网格**浏览，并建立**按设备的本地磁盘缩略图缓存**（优先复用 iOS 端 `PhotoData/Thumbnails` 小 JPG，缺失时拉原图生成 JPEG）；双击查看大图（HEIC 用 `pillow-heif` 解码，跨平台、不依赖 Qt heif 插件；非 HEIC 用 `QImage`）；支持**带元数据**导出（pull 保字节 + 时间戳，EXIF/HEIC 原样保留）。**不提供"导入到相册"与"删除"**：Apple 相册由系统照片库索引维护，经 AFC 写入/删除 `/DCIM` 不能可靠反映到"照片"App，需由设备上 iOS App 调用系统照片库接口（PhotoKit）才能可靠完成；如需文件级写入/删除可走「文件系统」Tab。
- 媒体分区与相册访问均**无需 WDA 或 XPC tunnel**，选中设备即可使用。

## Capabilities

### New Capabilities

- `afc-filesystem-op`: executor 层能力——经 `com.apple.afc`（lockdown 直连）访问设备媒体分区根（不含 app 沙盒）的目录浏览、文件/文件夹导入(push)/导出(pull)、删除、新建目录、重命名，以及按需读取文件字节（缩略图/回退解码）。
- `slide6-file-system`: 桌面应用「文件系统」Tab——浏览设备媒体分区目录树并进行导入/导出/删除/新建/重命名的交互界面。
- `slide6-dcim-album`: 桌面应用「相册」Tab——DCIM 缩略图网格浏览（优先复用 iOS 端缩略图）、双击查看大图、带元数据导出的交互界面；不提供导入到相册与删除（相册增删需经设备上 iOS App 调用系统照片库接口）。

### Modified Capabilities

- `nuitka-macos-packaging`: 打包脚本新增 `pillow-heif`（含 `_pillow_heif` 原生扩展与 `libheif` 动态库）与 `PIL` 的显式包含，并在预检阶段校验 `pillow-heif` 已安装，使「相册」Tab 的 HEIC/HEIF 解码在冻结产物中可用。

（新增的「文件系统」「相册」Tab 由上述两个新 UI 能力各自声明其在左侧 Tab 栏的归属；主窗口布局与生命周期不变，不改动 `slide6-desktop-shell` 既有要求。）

## Impact

- 受影响代码：
  - `executor_ios/device.py`、`executor_ios/toolkit_api.py`：AFC 访问层支持 `root="media"`（`_with_afc` 在 media 模式下使用 `AfcService(lockdown)` 而非 house-arrest，`_AFC_BASE["media"]="/"`），新增 `afc_read`。
  - `slide6_console/`：把 `afc_browser` 的浏览器抽成可嵌入面板供「文件系统」Tab 内联使用；新增「相册」Tab（缩略图网格 + 大图查看）。
  - `slide6_console/main_window.py`：注册两个新 Tab。
- 依赖：复用已打包的 `pymobiledevice3`（`AfcService`）。新增**必备**依赖 `pillow-heif` 用于 HEIC/HEIF 解码（不依赖 Qt 的 heif 插件，跨平台）；非 HEIC 用 `QImage`。打包已确认 `pillow-heif`（`_pillow_heif` 原生扩展 + `libheif` 动态库）与 `PIL` 随 `.app` 产物存在。
- iOS 系统级约束（需在 UI 上提示）：
  - 媒体分区为越狱前的"用户可见"区域，受系统权限限制；部分子目录（如 `PhotoData/CPL/...`）可能不可枚举，失败需友好降级。
  - 经 AFC 向 `DCIM` 写入的照片**不保证**自动登记进"照片"App 相册；故首版相册 Tab 不提供导入到相册，删除的 Photos 同步表现亦取决于系统索引。
- 安全基线：媒体分区路径同样做规范化与越界校验；缩略图优先读小 JPG，回退解码原图时限制单次读取上限避免内存峰值；删除为破坏性操作，多选删除强制二次确认。

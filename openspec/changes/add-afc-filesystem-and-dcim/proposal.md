## Why

当前 CablediOS.app 的文件能力仅限于 **App 沙盒**（经 house-arrest 访问 Documents / 容器）。但 iOS 测试中还高频需要访问**设备媒体分区**（`com.apple.afc` 根，含 `DCIM`、`Downloads`、`Books` 等，不含 app 沙盒），尤其是**相册（DCIM）**的批量浏览与导入导出。底层 `pymobiledevice3` 的 `AfcService` 原生支持媒体分区访问，无需新增依赖即可补齐这块空白。

## What Changes

- `executor_ios` 扩展 AFC 访问到**设备媒体分区根**（`com.apple.afc`，经 lockdown 直连，**不含** app 沙盒）：新增 `root="media"`，复用现有 `afc_list/afc_pull/afc_push/afc_rm/afc_mkdir/afc_rename` 语义（`media` 模式忽略 `bundle_id`）；新增按需读取文件字节的 `afc_read`（供缩略图加载，避免逐个落地临时文件）。
- 主界面新增两个左侧 Tab：
  - **「文件系统」Tab**：浏览设备媒体分区目录树，支持导入 / 导出（文件与文件夹）/ 删除（二次确认）/ 新建文件夹 / 重命名，交互与 App 文件浏览器一致。
  - **「相册」Tab**：DCIM 相册管理——以**缩略图网格**浏览，双击查看大图；支持**带元数据**导出（pull 保字节 + 时间戳，EXIF 原样保留）与导入（push 保字节），支持**多选删除并二次确认**。
- 媒体分区与相册访问均**无需 WDA 或 XPC tunnel**，选中设备即可使用。

## Capabilities

### New Capabilities

- `afc-filesystem-op`: executor 层能力——经 `com.apple.afc`（lockdown 直连）访问设备媒体分区根（不含 app 沙盒）的目录浏览、文件/文件夹导入(push)/导出(pull)、删除、新建目录、重命名，以及按需读取文件字节（缩略图）。
- `slide6-file-system`: 桌面应用「文件系统」Tab——浏览设备媒体分区目录树并进行导入/导出/删除/新建/重命名的交互界面。
- `slide6-dcim-album`: 桌面应用「相册」Tab——DCIM 缩略图网格浏览、双击查看大图、带元数据导入/导出、多选删除（二次确认）的交互界面。

### Modified Capabilities

（无。新增的「文件系统」「相册」Tab 由上述两个新 UI 能力各自声明其在左侧 Tab 栏的归属；主窗口布局与生命周期不变，不改动 `slide6-desktop-shell` 既有要求。）

## Impact

- 受影响代码：
  - `executor_ios/device.py`、`executor_ios/toolkit_api.py`：AFC 访问层支持 `root="media"`（`_with_afc` 在 media 模式下使用 `AfcService(lockdown)` 而非 house-arrest，`_AFC_BASE["media"]="/"`），新增 `afc_read`。
  - `slide6_console/`：新增「文件系统」Tab（可复用 `afc_browser` 的浏览器对话框/组件）与「相册」Tab（缩略图网格 + 大图查看）。
  - `slide6_console/main_window.py`：注册两个新 Tab。
- 依赖：无新增第三方依赖；复用已打包的 `pymobiledevice3`（`AfcService`）。打包脚本无需改动。
- iOS 系统级约束（需在 UI 上提示）：
  - 媒体分区为越狱前的"用户可见"区域，受系统权限限制；部分目录（如 `PhotoData`）可能只读或不可枚举。
  - 经 AFC 向 `DCIM` 写入的照片**不保证**自动登记进"照片"App 的相册数据库（Photos DB），可能需重启或由系统索引；本能力聚焦文件级带元数据传输，不修改 Photos DB。
- 安全基线：媒体分区路径同样做规范化与越界校验；缩略图按需读取限制单次读取上限，避免大文件内存峰值；删除为破坏性操作，多选删除强制二次确认。

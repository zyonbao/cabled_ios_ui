## Why

相册/文件系统两个新 Tab 上线后暴露了多处体验与稳定性问题：相册缩略图为拉伸/留边观感、不齐整且网格间距过宽、缺少文件名；相册「删除选中」会经 AFC 删 DCIM 文件，但 Apple「照片」相册不仅靠文件管理（需经 iOS App 调用系统相册接口增删），文件层面删除并不可靠地反映到相册，易误导；文件系统 Tab 缺少多选批量下载/删除，逐项操作低效；在终端运行时按 Ctrl+C 会让进程崩溃而非干净退出；侧边 Tab 顺序与「每次选设备都跳回设备信息」也需调整。这些都属于打磨性修复，适合一并处理。

## What Changes

- **相册缩略图改为居中裁剪（Crop）填充**：统一把缩略图（无论来自 iOS 端缓存 JPG 还是回退生成）渲染为正方形居中裁剪，消除拉伸变形与留边；网格间距收紧（约 16px）、每项底部显示单行文件名。
- **相册不提供导入/删除**：相册 Tab 不提供「导入到相册」与「删除选中」。原因：Apple「照片」相册由系统数据库索引，**不仅靠文件管理**——要可靠地向相册增删媒体需经 iOS App 调用系统相册接口（PhotoKit 等），仅经 AFC 在 `/DCIM` 增删文件无法保证反映到相册。需要对设备文件做增删时，走「文件系统」Tab 的 AFC 操作。
- **相册根隐藏点目录**：相册以 `/DCIM` 为根并隐藏以 `.` 开头的系统目录（如 `.MISC`），完整展示 `NNNAPPLE`（100APPLE/101APPLE/…）相册子目录，跨 iOS 版本/多相册均正确。
- **「文件系统」Tab 支持多选 + 右键批量操作**：列表支持多选（ExtendedSelection），右键提供「批量下载」（选目标目录后逐项 `afc_pull`）与「批量删除」（一次汇总二次确认后逐项 `afc_rm`）。
- **侧边 Tab 顺序与选中行为**：Tab 顺序为 设备信息 / 相册 / 文件系统 / App 列表 / 键鼠操作；设备信息仅为启动默认，切换设备时**保留**用户当前所在 Tab（不再每次跳回设备信息）。
- **修复 Ctrl+C 崩溃**：为 Qt 应用安装 SIGINT 处理，使 Ctrl+C 触发应用干净退出（停止镜像/后台任务后退出事件循环），而非在 C++ 栈中崩溃。

## Capabilities

### New Capabilities
- `slide6-app-lifecycle`: 桌面应用的进程生命周期与信号处理（含 Ctrl+C/SIGINT 干净退出）。

### Modified Capabilities
- `slide6-dcim-album`: 缩略图正方形居中裁剪 + 网格间距/文件名展示；明确不提供导入/删除（及原因）；根隐藏点目录。
- `slide6-file-system`: 文件系统 Tab 新增多选与右键批量下载/删除。
- `slide6-desktop-shell`: 侧边 Tab 顺序调整，且切换设备时保留当前所在 Tab。

## Impact

- 代码：`slide6_console/dcim_album.py`（缩略图裁剪/间距/文件名、移除删除、隐藏点目录）、`slide6_console/afc_browser.py`（`AfcBrowserPanel` 多选与右键批量操作）、`slide6_console/file_system_tab.py`（多选开关）、`slide6_console/app.py`（SIGINT 处理）、`slide6_console/main_window.py`（Tab 顺序与选中行为）。
- 行为：相册缩略图外观变化、相册移除删除入口；文件系统 Tab 由单选变为多选；Tab 顺序变化、切设备不再跳回设备信息；Ctrl+C 改为干净退出。
- 依赖：无新增第三方依赖（仅使用 Python `signal` 与 Qt 既有能力）。

## Why

当前 CablediOS.app 仅提供"键鼠操作"相关能力（屏幕镜像、手势、键盘、剪贴板、截图），所有控件平铺在单一界面中。随着功能增多，单一界面已不利于扩展，且缺少 iOS 测试场景中高频的 **App 管理** 与 **App 沙盒文件管理** 能力（装包、卸载、导入导出测试数据等）。底层 `executor_ios` 已依赖 `pymobiledevice3`，其 `InstallationProxyService` / `HouseArrestService` / `AfcService` 原生支持这些操作，无需新增依赖即可补齐这一空白。

## What Changes

- 顶部设备下拉选择与"刷新设备列表"保持不变；顶部 **不再展示**系统版本 / UDID / 名称 / 型号等设备明细（改由「设备信息」Tab 承载）。
- 主界面改为 **左侧纵向多 Tab 布局**：
  - **「键鼠操作」Tab**：整合现有全部功能（屏幕镜像、点按/长按/滑动、键盘镜像、文本发送、剪贴板、HOME/App Switcher/截图）；**帧率切换控件从顶部移入该 Tab 右侧操作区**。
  - **「App 列表」Tab**：新增，提供 App 管理与文件管理。
  - **「设备信息」Tab**：新增，以键/值表格尽可能详细地展示当前设备的 lockdown 全量属性。
- 「App 列表」Tab 新增能力：
  - 展示设备已安装 App 列表（图标占位/名称/bundleId）。
  - 支持卸载 App；支持点击选择或拖拽 `.ipa` 安装 App。
  - 支持按关键字搜索 App；支持按"是否开启文件共享(fileSharing)"与"沙盒是否可访问"筛选。
  - 对开启文件共享的 App，支持浏览其 `Documents` 及子目录，并进行文件导入/导出。
  - 对沙盒可访问（带 `get-task-allow` 的开发签名 App）的 App，支持浏览整个沙盒容器，并进行文件导入/导出。
- `executor_ios.toolkit_api` 新增 App 清单与文件传输能力函数，供桌面应用通过 `AsyncRunner` 调用，沿用现有进程内分层（不引入 HTTP）。

## Capabilities

### New Capabilities

- `app-inventory-op`: executor 层能力——列出设备已安装 App 及其元数据（含 fileSharing 标志与沙盒可访问标志）、从本地 `.ipa` 安装 App、按 bundleId 卸载 App。
- `app-file-transfer-op`: executor 层能力——基于 house-arrest + AFC 浏览指定 App 的 `Documents` 或整个沙盒容器目录树，并进行文件/文件夹导入(push)、导出(pull)、删除、新建目录与重命名。
- `device-info-op`: executor 层能力——通过 lockdown 读取设备全量属性（DeviceName/ProductType/ProductVersion/SerialNumber 等），无需 WDA 或 tunnel。
- `slide6-app-manager`: 桌面应用「App 列表」Tab——展示/搜索/筛选 App，触发安装、卸载，以及文件浏览器（导入/导出/重命名/删除）的交互界面。

### Modified Capabilities

- `slide6-desktop-shell`: 桌面应用主界面从单一布局改为左侧纵向多 Tab 布局（「键鼠操作」「App 列表」「设备信息」）；顶部不再展示系统版本/UDID/名称/型号；帧率控件从顶部迁入「键鼠操作」Tab 的右侧操作区；新增「设备信息」Tab 展示 lockdown 全量属性。原"键鼠操作"相关功能行为不变。

## Impact

- 受影响代码：
  - `slide6_console/main_window.py`（主界面重构、Tab 化、新增 App 列表 Tab 与文件浏览器）。
  - `executor_ios/toolkit_api.py`、`executor_ios/device.py`（新增 App 清单/安装/卸载与 AFC 文件传输能力，运行于现有后台 asyncio loop）。
  - 可能新增 `slide6_console/` 下的 Tab/对话框组件文件。
- 依赖：无新增第三方依赖；复用已打包的 `pymobiledevice3`（`InstallationProxyService` / `HouseArrestService` / `AfcService`）。打包脚本 `packaging/build_macos_app.sh` 无需改动（已 `--include-package=pymobiledevice3`）。
- iOS 系统级约束（非工具缺陷，需在 UI 上明确提示）：
  - 安装 `.ipa` 需为本设备可信任证书签名，否则设备端拒绝安装。
  - 整个沙盒容器（VendContainer）仅对带 `get-task-allow` 的开发签名 App 开放；App Store 正式包不可访问，仅在开启 fileSharing 时可访问 `Documents`。
- 安全基线：文件导入/导出需对设备侧路径做规范化与越界校验，大文件采用分块/流式读写避免内存峰值，错误信息不泄露敏感路径。

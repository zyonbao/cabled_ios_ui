## Context

CablediOS.app 由两层组成：`executor_ios`（进程内 iOS 能力层，封装 `pymobiledevice3` 与 WDA）与 `slide6_console`（PySide6 桌面 UI，通过 `AsyncRunner` 在工作线程调用 `toolkit_api`）。`executor_ios/device.py` 维护一个模块级常驻 asyncio 事件循环 `_bg_loop`（守护线程），所有 `pymobiledevice3` 协程都通过 `asyncio.run_coroutine_threadsafe(...)` 提交到该循环执行。

当前 `slide6_console/main_window.py` 为单一中央布局，承载屏幕镜像与全部键鼠操作控件；设备信息区展示 名称/型号/系统/UDID/分辨率/方向。本变更在不改动设备生命周期（tunnel/WDA/mirror）逻辑的前提下，重构 UI 为多 Tab，并新增 App 管理与沙盒文件管理能力。

底层服务已确认可用（`pymobiledevice3==9.16.0`）：
- `InstallationProxyService.get_apps()`（协程）、`install_from_local()`（同步）、`uninstall()`（协程）。
- `HouseArrestService(lockdown, documents_only=bool)` + `send_command()`（协程），`documents_only=True` → `VendDocuments`，`False` → `VendContainer`。
- `AfcService`：`listdir`/`walk`/`stat`/`get_file_contents`/`set_file_contents`/`makedirs`/`rm`/`push` 同步，`pull` 协程。

## Goals / Non-Goals

**Goals:**

- 主界面 Tab 化：「键鼠操作」承载现有全部功能，「App 列表」承载新能力；顶部设备下拉与刷新不变。
- 顶部信息项调整为 系统/UDID；帧率控件迁入「键鼠操作」右侧操作区；移除 名称/型号。
- 提供 App 列表展示、搜索、按 fileSharing 与 沙盒可访问 两种维度筛选。
- 提供 IPA 安装（点击/拖拽）与卸载。
- 对 fileSharing App 浏览 `Documents`、对沙盒可访问 App 浏览整个容器，二者均支持文件导入/导出。
- 复用现有分层与 `_bg_loop`，不引入 HTTP、不新增第三方依赖。

**Non-Goals:**

- 不做 IPA 重签名；安装失败（签名/证书不匹配）仅提示，不尝试绕过。
- 不实现文件内编辑/预览（仅导入、导出、删除、新建目录）。
- 不改动 WDA、tunnel、镜像流相关逻辑与打包脚本。

## Decisions

### 决策 1：能力分层——executor 新增 `app-inventory-op` 与 `app-file-transfer-op`，UI 单独 `slide6-app-manager`

延续仓库既有约定（executor 侧的 `*-op` capability 与 slide6 侧的 UI capability 分离，如 `launch-kill-app-op` vs `slide6-*`）。`toolkit_api` 暴露纯数据契约函数，UI 只做交互与展示。

**备选**：把 App/文件逻辑直接写进 `main_window.py`。**否决**：违反现有分层，难以测试与复用（CLI/web_console 也可能复用 executor 能力）。

### 决策 2：所有 pymobiledevice3 调用统一在 `_bg_loop` 上以协程执行

即便 AFC 的部分方法是同步的，也将"建立 house-arrest 连接 + 一组文件操作"封装为一个 async 函数提交到 `_bg_loop`，保证与现有 lockdown/usbmux 访问串行、线程安全，避免跨线程复用同一 lockdown 连接。每次文件操作请求按需建立并关闭 house-arrest/AFC 连接（短连接），避免长连接状态管理复杂度。

**备选**：在 `AsyncRunner` 工作线程内直接同步调用。**否决**：`pymobiledevice3` 的连接对象绑定在 `_bg_loop`，跨线程使用不安全。

### 决策 3：App 元数据字段映射

调用 `get_apps(application_type="Any")` 后，对每个 App 计算：
- `name` ← `CFBundleDisplayName` 或 `CFBundleName`。
- `bundleId` ← key。
- `fileSharing` ← `UIFileSharingEnabled == True`。
- `sandboxAccessible` ← `Entitlements["com.apple.security.get-task-allow"] == True` **或** 存在 `SignerIdentity`。
- `appType` ← `ApplicationType`（User/System），列表默认展示 User，可选显示 System。

筛选在 UI 侧对该结构做内存过滤，搜索匹配 `name`/`bundleId`（不区分大小写）。

> 实测修正：installation_proxy 返回的 `Entitlements` 经系统裁剪，通常**不含** `get-task-allow`，导致仅凭该字段判定会把可访问沙盒的开发签名 App 误判为不可访问。开发 / 临时 / 企业签名 App 在 App 信息中带 `SignerIdentity`（App Store 与系统 App 没有），且其容器确实可经 `VendContainer` 访问，故以 `SignerIdentity` 作为兜底信号。

### 决策 3b：house-arrest 逻辑路径与设备路径映射

> 实测修正：`VendDocuments` 模式下 AFC 根仍位于**容器根**，App 的 Documents 位于 `/Documents`，直接列容器根 `/` 会被拒绝（AFC status 10）。因此 UI 暴露统一的逻辑路径（根为 `/`），executor 内部按 `root` 映射到真实设备路径：`documents → /Documents + 逻辑路径`、`container → / + 逻辑路径`。用户与 UI 始终只见逻辑路径，映射只在 AFC 调用处发生。

### 决策 4：文件浏览器交互模型

`afc_list(target, bundle_id, root, sub_path)` 返回当前目录条目（名称/是否目录/大小/修改时间）；UI 以**可编辑的相对路径输入框**展示当前路径（回车跳转），非根目录列表顶部以 `..` 行支持双击返回上一级。每个条目右侧提供文字按钮（导入 ↑ / 导出 ↓ / 重命名 ✎ / 删除 ✕），并支持等价的右键菜单。
- `root` 取值：`documents`（VendDocuments，路径基于 `/Documents`）或 `container`（VendContainer，路径基于容器根 `/`）。
- 导出：`afc_pull(target, bundle_id, root, remote_path, local_path)` → 文件"另存为" / 文件夹"选择目录"对话框，或将条目拖出到 Finder（先同步落地临时副本再发起拖拽）。
- 导入：`afc_push(target, bundle_id, root, local_path, remote_dir)` → 文件选择对话框或从 Finder 拖入，支持文件与文件夹（pull/push 均递归）。
- 删除（二次确认）/ 新建目录 / 重命名作为辅助操作提供（`afc_rm` / `afc_mkdir` / `afc_rename`）。

UI 模块拆分：`app_manager.py`（`AppManagerTab`，App 清单/搜索/筛选/装卸）、`afc_browser.py`（`AfcBrowserDialog` + 拖拽 `_FileTable`，文件浏览器）、`device_info.py`（`DeviceInfoTab`，lockdown 属性键值表）。文件浏览器中重复的"提交 afc_* 调用并将 ok/error 包络折叠为状态提示"的逻辑统一收敛到 `AfcBrowserDialog._submit`。

### 决策 5：IPA 安装入口

「App 列表」Tab 同时支持：点击"安装 IPA"按钮选择 `.ipa`，以及在列表区拖拽 `.ipa` 文件（`QWidget` 接受 `dragEnterEvent`/`dropEvent`，校验扩展名为 `.ipa`）。安装通过 `install_from_local(path)`（同步）包进 `_bg_loop` 协程，完成后自动刷新列表。

## Risks / Trade-offs

- [IPA 签名不匹配导致安装失败] → 捕获 installation_proxy 错误，UI 给出"需本设备可信任证书签名"的明确提示，而非堆栈错误。
- [对 App Store 正式包请求 VendContainer 会失败] → 列表预先按 `get-task-allow` 标记 `sandboxAccessible`，不可访问的 App 禁用"浏览沙盒"入口；对仅 fileSharing 的 App 仅开放"浏览 Documents"。
- [大文件导入/导出造成内存峰值或 UI 卡顿] → 文件传输在 `_bg_loop` 执行（不阻塞 UI 线程），优先使用 AFC 的 `pull`/`push`（内部分块）而非一次性 `get_file_contents`/`set_file_contents`；超大文件给出进度或忙碌状态提示。
- [设备侧路径越界/注入] → 对 `sub_path`/`remote_path` 做规范化，拒绝 `..` 跨越根目录，所有路径相对所选 root 解析（遵循安全基线"Never Feed Raw Data to Sensitive Sinks"）。
- [house-arrest 短连接频繁建连开销] → 文件浏览为低频交互，短连接开销可接受；若后续出现性能问题再引入按 (target,bundleId,root) 缓存的连接池。
- [Tab 重构影响既有键鼠功能] → 仅迁移控件归属与帧率位置，不改动信号/槽与生命周期逻辑；通过对照现有 `slide6-desktop-shell` 场景回归验证。

## Resolved Decisions

- **文件浏览器支持文件与文件夹导入/导出**：底层 `pull`/`push` 已支持递归，因此目录连同其内容可整体导出/导入。导出文件夹时 `local_path` 传父目录、导入文件夹时 `remote_dir` 传目标目录，由 pymobiledevice3 递归处理。
- **拖拽导出需先落地本地临时副本**：Qt 跨平台拖拽到 Finder 需在 `startDrag` 前提供本地 file:// URL，因此选中条目会先同步 `afc_pull` 到临时目录（期间显示等待光标）再发起拖拽；大文件/大目录会有可感知耗时。
- **App 列表首版使用占位图标**：真实图标需通过 `SpringBoardServicesService.get_icon_pngdata(bundle_id)` 逐 App 拉取，每个 App 一次独立 lockdown 往返；设备 App 较多时串行拉取会显著拖慢列表加载（数秒级）。本次用占位图标使列表即时呈现。
  - 后续若需真实图标：列表先以占位即时呈现 → 仅对当前可见行按需异步拉取图标 → 按 bundleId 本地缓存（避免滚动重复拉取），以摊薄往返开销。

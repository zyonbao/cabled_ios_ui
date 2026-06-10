## Context

`pymobiledevice3` 9.x 把 DDI 挂载与 DVT instruments 拆为两条链路：

- **DDI 挂载**（`services.mobile_image_mounter`）：`MobileImageMounterService.is_image_mounted(image_type)` 查状态；`auto_mount` 按版本分流（<17 `auto_mount_developer`、17+ `auto_mount_personalized`，均会从 Xcode/官方仓库获取镜像）；手动挂载用 `DeveloperDiskImageMounter.mount(image, signature)`（<17，type=`Developer`）或 `PersonalizedImageMounter.mount(image, build_manifest, trustcache)`（17+，type=`Personalized`）；卸载用对应 mounter 的 `umount()`。**这条链路走 usbmux lockdown，iOS 17+ 也不需 tunnel**，但需设备已开启开发者模式。
- **DVT instruments**（`services.dvt.instruments.*`）：经 `DvtProvider(lockdown_or_rsd)`（异步上下文管理器，自动按 RSD/lockdown 选服务名）建 DTX 连接后使用：`DeviceInfo(dvt).proclist()`、`ProcessControl(dvt).launch(bundle_id)/kill(pid)`、`LocationSimulation(dvt).set(lat,lon)/clear()`。**DVT 要求 DDI 已挂载**；iOS<17 走 usbmux lockdown，iOS 17+ 走 tunneld 的 RSD（复用 `_get_rsd_from_tunneld`）。

现有 `device.py` 已有成熟范式可复用：共享 `_bg_loop` 守护事件循环 + `asyncio.run_coroutine_threadsafe`，每次请求开一次性连接并返回 `{ok,data}`（见 `list_profiles` / `_with_crash`）；长生命周期任务（WDA runner）以 `Future` 持有（见 `_wda_task`）。UI 层经 `AsyncRunner`（QThreadPool）把阻塞调用挪出 GUI 线程。

## Goals / Non-Goals

**Goals:**

- 提供 DDI 挂载状态机（状态查询 / 多方式挂载 / 卸载）。
- 提供两个 DVT 工具：进程管理（列表 / 筛选 / 按 bundle id 启动 / kill / 明细）与虚拟定位（设定 / 清除）。
- 「DDI 状态栏 + 功能位 grid」布局，DDI 挂载门控，便于 Phase 2 扩展。

**Non-Goals:**

- 不实现 Phase 2 的性能监控 / 网络监控 / trace 等其它 DVT 工具。
- 不实现进程的修改（只支持创建 / kill / 查看，符合用户要求的「不支持更改」）。
- 不实现 GPX 轨迹回放（仅单点定位）；不做自定义 DDI 下载源 / 缓存管理（沿用 pmd3 默认缓存）。

## Decisions

### 决策 1：DDI 挂载/卸载/状态走 usbmux lockdown（与 tunnel 解耦）

`ddi_status()` 按版本选 image type（<17 `Developer`、17+ `Personalized`）调 `is_image_mounted`，并返回 `developerMode`（`query_developer_mode_status`）与 `iosMajor`。挂载与卸载同样经 usbmux lockdown，**iOS 17+ 不需 tunnel**，从而保证「先挂 DDI、再按需起 tunnel 用 DVT」的顺序成立。

`ddi_mount(method, **paths)` 支持四种方式：

- `auto`：`auto_mount(lockdown)`（按版本自动分流，需联网 / Xcode）。
- `personalized`：`auto_mount_personalized(lockdown)`（强制 17+ 个性化镜像，联网下载）。
- `developer`：`auto_mount_developer(lockdown, xcode, version)`（<17，从 Xcode/下载）。
- `manual`：手动本地文件——17+ 传 `image/build_manifest/trustcache` → `PersonalizedImageMounter.mount`；<17 传 `image/signature` → `DeveloperDiskImageMounter.mount`。

`AlreadyMountedError` 视为成功（幂等）。`DeveloperModeIsNotEnabledError` 返回可读错误，提示在设备「设置 → 隐私与安全性 → 开发者模式」开启。

### 决策 2：DVT 连接复用 WDA 的 lockdown/RSD 二分

新增内部 `_with_dvt(op)`：iOS<17 用 `create_using_usbmux` 取 lockdown；iOS 17+ 用 `_get_rsd_from_tunneld` 取 RSD（为 None 时抛可读 `RuntimeError`，提示先启动 XPC tunnel）。在所选 service provider 上 `async with DvtProvider(...) as dvt` 建连后执行 `op(dvt)`。进程列表 / 启动 / kill 各开一次性连接（工具型低频操作，开销可接受）。

- `list_processes()` → `DeviceInfo(dvt).proclist()`，规整为 `[{pid,name,realAppName,isApplication,startDate}]`。
- `launch_app_dvt(bundle_id)` → `ProcessControl(dvt).launch(bundle_id)` 返回 pid。
- `kill_process(pid)` → `ProcessControl(dvt).kill(pid)`。
- 进程明细：直接展示 `proclist` 对应条目（只读），不另开接口；`proclist` 不含 bundle id，筛选基于进程名（前端筛选）。

### 决策 3：虚拟定位按 iOS 版本分流，17+ 维持常驻会话

iOS 模拟定位有两种实现且语义不同：

- **iOS<17**：`DtSimulateLocation`（lockdown 服务）`set(lat,lon)` 设完即返回并**持续生效**，`clear()` 恢复真实 GPS。一次性连接即可。
- **iOS 17+**：DVT `LocationSimulation.set` 的模拟**仅在 DTX 连接存活期间有效**（pmd3 CLI 设完调用 `wait_return()` 阻塞保持连接为证）。因此 17+ 必须维持一个**常驻定位会话**：在 `_bg_loop` 上提交一个协程，建 RSD+`DvtProvider` 连接 → `set` → 置位「就绪」事件 → 永久等待（直到取消）；`set_location` 同步包装等待「就绪」后返回 `{ok}`。重复 `set` 先取消旧会话再起新会话。`clear_location` 取消常驻会话（关闭连接即停止模拟）并尽力调用一次 `clear()`。会话 `Future` 持于 device 实例，主窗口 `closeEvent` 经 `shutdown` 取消，避免悬挂连接。

### 决策 4：Tab 布局「DDI 状态栏 + 功能位 grid」，DDI 门控

顶部状态栏：DDI 状态标签 + 「挂载 / 卸载」按钮（按状态切换）；挂载按钮弹 `QInputDialog`/自定义弹窗选挂载方式，手动方式再走 `QFileDialog` 选文件。下方 `QGridLayout` 放功能位卡片（进程管理、虚拟定位），点击打开各自对话框 / 面板。`_set_features_enabled(bool)` 在状态刷新后统一启停所有功能位；DDI 未挂载时禁用并提示「请先挂载 DDI」。iOS 17+ 在状态栏附带 tunnel 提示与「启动 XPC tunnel」入口（复用 `tunnel.launch_tunneld`），DVT 调用失败时也回显可读原因。所有阻塞调用经 `AsyncRunner`；`set_target` 由主窗口在设备切换时分发，未选设备显示「未选择设备」。

## Risks / Trade-offs

- **[iOS 17+ 定位需常驻连接]** → 用持于 device 的 `Future` 管理会话生命周期，`set` 等待就绪事件确认生效，`clear`/`shutdown`/换设备时取消；真机验证设/清及 app 内退出无悬挂。
- **[DVT 在 17+ 依赖 tunnel]** → DDI 已挂载但 tunnel 未起时，进程/定位会失败；平台层返回明确「需 XPC tunnel」错误，Tab 提供 tunnel 状态提示与启动入口（不强制在打开 Tab 时拉起，避免打扰）。
- **[DDI 自动挂载需联网/ Xcode]** → 提供「手动选本地镜像」兜底；`AlreadyMountedError` 幂等成功，`DeveloperModeIsNotEnabledError` 给可读提示。
- **[`proclist` 无 bundle id]** → 进程筛选基于进程名；按 bundle id 仅用于「创建（启动）」，与列表筛选解耦，UI 文案说明。
- **[kill / 启动为高权限动作]** → kill 前二次确认；仅作用于用户显式选中的 pid；遵循安全基线，不在日志泄露敏感信息。

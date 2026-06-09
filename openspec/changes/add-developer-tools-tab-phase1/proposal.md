## Why

项目已具备 DVT/tunnel 底座（WDA 经 `XCUITestService`，iOS 17+ 经 tunneld 的 RSD），但**未暴露任何面向用户的 DVT 工具**，且 **DDI（DeveloperDiskImage）从不由本应用挂载**——依赖外部预挂载，失败时只有 generic error。

新增独立「开发者工具」Tab，分两期落地。**Phase 1** 补齐最小闭环：把 DDI 挂载状态机打通，并落地两个高价值 DVT 工具（进程管理、虚拟定位）。布局采用「DDI 状态栏 + 功能位 grid」，DDI 挂载后逐步解锁能力，为 Phase 2（性能监控 / 网络监控等）预留可扩展的 grid。

## What Changes

- 新增独立「开发者工具」sidebar Tab（`DeveloperToolsTab`）。
- **DDI 状态与控制**：Tab 顶部展示 DDI 挂载状态（已挂载 / 未挂载）与开发者模式状态；未挂载提供「挂载」按钮（弹窗可选多种 `pymobiledevice3` 挂载方式：自动按版本 / 个性化镜像(17+) / 开发者镜像(<17) / 手动选本地镜像文件），已挂载提供「卸载」按钮。挂载 / 卸载 / 状态查询走 usbmux lockdown，iOS 17+ 也不需 tunnel。
- **功能位 grid**：进程管理、虚拟定位以「功能位」卡片在 grid 中展示，便于 Phase 2 叠加。DDI 未挂载时所有功能位 Disabled，挂载成功后自动 enable。
- **进程管理**：查看当前进程列表（`DeviceInfo.proclist`），按名称筛选；按 bundle id 启动进程（`ProcessControl.launch`，返回 pid）；选中进程 kill（`ProcessControl.kill`）；查看进程明细（只读，不支持修改）。
- **虚拟定位**：设定 / 清除虚拟 GPS 坐标。iOS<17 走 `DtSimulateLocation`（设完即生效）；iOS 17+ 走 DVT `LocationSimulation`，因模拟仅在 DTX 连接存活期间有效，需后台常驻定位会话，清除时取消会话。
- **轨迹回放**：除单点设定外，支持沿轨迹移动。两种来源：(1) **GPX 文件回放**——解析 `.gpx` 轨迹点，带时间戳则按真实速度回放，可选忽略时间戳立即跑完 / 加时间抖动；(2) **手动多点轨迹**——用户输入若干途经点 + 速度，平台层按 haversine 距离与固定 tick 自研插值，平滑逐点 `set`。两者复用同一条「常驻路线回放会话」（可被「清除」中止），按 iOS 版本分流连接方式。
- **平台能力层**新增 DDI 与 DVT 相关方法及 `toolkit_api` 包装。
- **tunnel 依赖**：iOS 17+ 的进程 / 定位能力依赖 XPC tunnel（RSD），复用 `tunnel.py` + `_get_rsd_from_tunneld`；tunnel 未起时返回可读错误并在 Tab 内给出提示 / 启动入口。

## Capabilities

### New Capabilities

- `ddi-mount-op`：DDI 挂载状态查询 / 多方式挂载 / 卸载（平台能力）。
- `dvt-process-op`：DVT 进程列表 / 按 bundle id 启动 / kill / 明细（平台能力）。
- `dvt-location-op`：虚拟定位设定 / 清除（平台能力，按 iOS 版本分流）。
- `slide6-developer-tools`：「开发者工具」Tab（DDI 状态栏 + 功能位 grid + 进程 / 定位 UI）。

### Modified Capabilities

- 无。

## Impact

- `ios_toolkit/device.py`：新增 DDI 方法（`ddi_status` / `ddi_mount` / `ddi_unmount`）、DVT 进程方法（`list_processes` / `launch_app_dvt` / `kill_process`）、虚拟定位方法（`set_location` / `clear_location`，含 iOS 17+ 常驻会话）；新增轨迹回放（`play_route_gpx` / `play_route_manual` + 统一的 `_run_route_async` 路线会话、`_parse_gpx_steps` / `_interpolate_route` 辅助）。
- `ios_toolkit/toolkit_api.py`：新增对应 `{ok,data}` 包装。
- `slide6_ui/developer_tools/`（新增包）：`DeveloperToolsTab` 及进程 / 定位 / 挂载对话框。
- `slide6_ui/main_window.py`：注册「开发者工具」Tab，`on_select_device` 分发 `set_target`，`closeEvent` 调用 `shutdown` 释放定位会话。
- `slide6_ui/common/tunnel.py`：复用现有 `is_tunnel_running` / `needs_tunnel` / `launch_tunneld`（不改动）。

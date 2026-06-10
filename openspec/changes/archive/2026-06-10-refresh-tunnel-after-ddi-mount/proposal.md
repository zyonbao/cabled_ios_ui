## Why

iOS 17+ 设备上，开发者服务（`com.apple.dt.testmanagerd.remote`、`com.apple.coredevice.feature.processcontrol` 等）只有在 DDI 挂载完成后才会被设备 remoted 暴露，而这些服务**在 XPC tunnel 建立那一刻被枚举进该 tunnel 会话的 RSD 服务表**。若 tunnel 在挂载 DDI 之前就已建立（常见：开机后早早拉起了 tunnel），事后挂载/重挂 DDI 都不会刷新这条旧 tunnel 的服务表，导致 `testmanagerd.remote` 始终缺失——WDA（键鼠操作）报 `No such service: com.apple.dt.testmanagerd.remote` 而无法启动。实测确认：同一条 RSD 上 `dtservicehub` 在、`testmanagerd.remote` 缺失，且 tunnel 进程的建立时间远早于挂载 DDI 的时间。

## What Changes

- iOS 17+ 设备**挂载 DDI 成功后**，若检测到 XPC tunnel 已在运行（即可能是挂载前建立的陈旧会话），应用 SHALL 重启该 tunnel，使 RSD 重新与设备握手、重新枚举此刻已可用的开发者服务（`testmanagerd.remote` 等）。
- 重启 tunneld 必然需要 root（经 macOS 原生授权拉起/停止），因此**不存在"免授权自动重启"**：应用 SHALL 先弹窗告知用户"挂载成功，需要重启 XPC tunnel 以启用开发者服务（键鼠 / WDA 等）"，用户确认后再触发系统授权框完成 stop + relaunch。
- 若挂载成功时 tunnel **未在运行**，则不做任何重启（后续首次按需拉起的 tunnel 天然包含已挂载 DDI 的开发者服务）。
- 仅适用于 iOS 17+（`needs_tunnel`）；iOS<17 不涉及 tunnel，跳过。
- 在 `slide6_ui/common/tunnel.py` 新增 `restart_tunneld()`（= `stop_tunneld()` + `launch_tunneld()`）。

## Capabilities

### New Capabilities

（无新增能力）

### Modified Capabilities

- `slide6-tunnel-bootstrap`: 新增"DDI 挂载成功后按需重启 tunnel 以刷新 RSD 开发者服务列表"的需求与对应的弹窗授权流程。

## Impact

- `slide6_ui/common/tunnel.py`：新增 `restart_tunneld()`。
- `slide6_ui/developer_tools/developer_tools_tab.py`：`_on_mounted`（挂载成功回调）在 iOS 17+ 且 tunnel 已运行时弹窗并触发重启，再进行 DVT 就绪探测。
- 行为面向用户：iOS 17+ 挂载后会多一次"是否重启 XPC tunnel"的确认与系统授权框。
- 不影响 iOS<17 流程；不影响 `manual` 挂载之外的既有 tunnel 启停逻辑。

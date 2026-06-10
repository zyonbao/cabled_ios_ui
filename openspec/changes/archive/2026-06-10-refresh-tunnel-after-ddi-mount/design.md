## Context

iOS 17+ 的开发者服务经 RSD 暴露，服务列表在 **XPC tunnel 建立时**由设备 remoted 枚举进该会话。`slide6_ui/common/tunnel.py` 已提供：

- `is_tunnel_running()`：探测 `127.0.0.1:49151` 是否有监听；
- `launch_tunneld()`：经 osascript 管理员授权拉起 tunneld（前台运行、轮询端口就绪）；
- `stop_tunneld()`：经 osascript 管理员授权按端口 kill tunneld（root 进程）。

tunneld 以 root 运行，stop/launch 均需系统授权。实测：tunnel 在挂载 DDI 之前建立时，其 RSD 服务表缺 `com.apple.dt.testmanagerd.remote`，导致 `ios_toolkit.device.do_prepare`（iOS 17+ 经 `_run_wda_rsd_async` → `XCUITestService`）报 `No such service`，键鼠 / WDA 起不来；而 `dtservicehub`（进程 / 定位用）仍在，故进程/定位功能不受影响。

挂载成功回调在 `slide6_ui/developer_tools/developer_tools_tab.py:_on_mounted`，挂载后已有"乐观置已挂载 + 后台 DVT 就绪探测（`ddi_wait_ready`）"流程。

## Goals / Non-Goals

**Goals:**

- iOS 17+ 挂载 DDI 成功后，自动把"陈旧 tunnel"刷新为含最新开发者服务的新 tunnel，使键鼠 / WDA 可用。
- 因重启必然需要 root，明确以"弹窗告知 + 系统授权"完成，绝不静默提权。
- 不破坏 iOS<17 流程与既有 tunnel 启停 / 退出询问逻辑。

**Non-Goals:**

- 不改变 DDI 挂载本身的镜像解析 / 选择逻辑（已确认本地 PDI 镜像内容无误，问题在 tunnel 服务表陈旧）。
- 不实现免授权的后台重启（macOS 上 root 进程的 stop/launch 必须授权）。
- 不改 iOS<17 的 usbmux 路径，不改 WDA 在 `do_prepare` 中已加入的 testmanagerd 有界重试（二者互补）。

## Decisions

**决策 1：触发点与条件。** 在 `_on_mounted` 挂载成功分支，仅当 `tunnel.needs_tunnel(os_version)` 为真（iOS 17+）且 `tunnel.is_tunnel_running()` 为真时，触发"重启 tunnel"流程。tunnel 未运行则跳过——后续按需首次拉起的 tunnel 天然最新。

**决策 2：先弹窗告知再授权。** 用 `QMessageBox` 告知用户"DDI 挂载成功；需要重启 XPC tunnel 以启用开发者服务（键鼠 / WDA），将请求管理员授权"，确认后才执行重启。取消则保持"已挂载（准备中…）"，并在状态栏提示 tunnel 刷新前键鼠 / WDA 可能不可用。

**决策 3：`restart_tunneld()` 收敛在 tunnel.py。** 新增 `restart_tunneld(timeout=30.0) -> bool` = `stop_tunneld()` 后 `launch_tunneld(timeout)`；stop 失败不阻断（端口可能已空），以最终 `is_tunnel_running()` / `launch_tunneld` 返回为准。重启在后台线程（`AsyncRunner.submit`）执行，避免阻塞 UI；期间状态栏提示"正在重启 XPC tunnel（需管理员授权）…"。

**决策 4：与就绪探测衔接。** 重启成功后再启动既有 `ddi_wait_ready` 探测（解锁进程/定位功能位）；键鼠 / WDA 的可用性由其各自路径（`do_prepare`，已含 testmanagerd 重试）在重启后自然恢复。重启失败 / 取消时按"准备超时/未就绪"提示处理，不崩溃。

**决策 5：授权次数。** stop + launch 为两次 osascript 授权调用；macOS 可能在短时间内复用授权缓存而只提示一次。文案说明"将请求管理员授权"，不承诺次数。

## Risks / Trade-offs

- **多一次授权弹窗**：iOS 17+ 每次挂载后若 tunnel 在跑都会询问重启。取舍：仅在 tunnel 已运行时触发，且用户可取消；避免每次都强制。
- **stop/launch 时序**：stop 后端口释放可能有延迟，`launch_tunneld` 已带轮询超时；stop 失败（无授权/无进程）时直接尝试 launch，以端口就绪为最终判据。
- **授权缓存差异**：不同 macOS 行为下可能提示一次或两次，文案不绑定具体次数。
- **WDA 重试窗口**：`do_prepare` 已把 testmanagerd 重试窗收敛为 60s，与本变更互补——重启 tunnel 是根因修复，重试是兜底。

# Tasks

## 1. tunnel 层：重启能力

- [x] 1.1 `slide6_ui/common/tunnel.py`：新增 `restart_tunneld(timeout=30.0) -> bool`——先 `stop_tunneld()`（失败不阻断），再 `launch_tunneld(timeout)`，以最终端口就绪为准；补日志

## 2. UI：挂载成功后按需重启 tunnel

- [x] 2.1 `developer_tools_tab.py` `_on_mounted`：iOS 17+（`tunnel.needs_tunnel`）且 `tunnel.is_tunnel_running()` 时，弹 `QMessageBox` 告知"挂载成功，需重启 XPC tunnel 以启用开发者服务（键鼠/WDA），将请求管理员授权"
- [x] 2.2 用户确认 → 后台 `AsyncRunner.submit(tunnel.restart_tunneld)`，状态栏"正在重启 XPC tunnel（需管理员授权）…"；成功后再启动既有 `ddi_wait_ready` 就绪探测
- [x] 2.3 用户取消 / 重启失败：不崩溃，状态栏提示 tunnel 刷新前键鼠/WDA 可能不可用，可稍后用「启动 XPC tunnel」手动重试；保持"已挂载（准备中…）"
- [x] 2.4 tunnel 未运行或 iOS<17：跳过重启，沿用现有挂载后流程

## 3. 验证

- [x] 3.1 lint 无误 + 导入冒烟
- [x] 3.2 真机手验（iOS 17+，tunnel 早于挂载建立）：挂载成功 → 弹窗确认 → 授权重启 → RSD 出现 `com.apple.dt.testmanagerd.remote`（`list_rsd_services` 复验）→ 键鼠/WDA 可用
- [x] 3.3 回归：tunnel 未运行时挂载不弹重启窗；iOS<17 挂载不涉及 tunnel；用户取消重启不崩溃且提示可读

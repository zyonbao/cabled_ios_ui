# xpc-tunnel（已删除，Not In Scope）

> `xpc_tunnel.py` 查询辅助脚本已删除。iOS 17+ 设备的 RSD 信息由 `device.py` 中的 `_get_rsd_from_tunneld()` 在 `do_prepare()` 时自动查询，无需独立脚本或手动设置环境变量。

## 替代方案：`tunneld_main.py`

iOS 17+ 的 XPC tunnel 功能由独立的 `ios_tunneld` 二进制（`tunneld_main.py` 打包而来）以 root 权限作为 LaunchDaemon 提供：

- 监听 `http://127.0.0.1:49151`，提供 JSON HTTP API
- `device.py` 的 `_get_rsd_from_tunneld(udid)` 直接 GET 该地址，解析 `tunnel-address` 和 `tunnel-port` 字段

## 错误场景

- tunneld 未运行 → `do_prepare()` 抛出明确错误：`"iOS 17+ device <udid>: cannot get RSD info from tunneld. Make sure ios_tunneld is running (it must run as root)."`

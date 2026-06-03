# wda-lifecycle

WDA 进程生命周期管理：安装检测、进程探活、按需启动。

## 方法

### `is_wda_installed() -> bool`

供 `list_targets` 使用，判断设备是否已安装 WDA：

- 通过 `AppServiceClient.list_installed_apps()` 检查 `_wda_bundle_id` 是否存在
- 返回 True → 已安装；False → 未安装

### `is_prepared() -> bool`

供操作前置检查使用，判断 WDA HTTP 进程是否活跃：

- 向 `http://127.0.0.1:<local_port>/status` 发 GET 请求
- 2 秒内收到 200 响应 → True
- 超时或连接拒绝 → False
- **不检查安装状态**

### `do_prepare() -> None`

触发条件：`is_prepared()` 返回 False 时由操作函数调用。

步骤：
1. 调用 `is_wda_installed()`，若返回 False → 抛出 `RuntimeError("WDA not installed on device <udid>. Please install manually.")`
2. 根据 `os_version` 判断 iOS 版本：
   - **iOS ≤ 16**：通过 lockdown/usbmux 路径启动 WDA xctrunner
   - **iOS 17+**：
     - 调用 `_get_rsd_from_tunneld(udid)` 查询本地 tunneld（`http://127.0.0.1:49151`）
     - 若返回 None（tunneld 未运行或设备未建立 tunnel）→ 抛出 `RuntimeError("iOS 17+ device <udid>: cannot get RSD info from tunneld. Make sure ios_tunneld is running (it must run as root).")`
     - 否则使用查询得到的 `rsd_address` / `rsd_port`，通过 `RemoteServiceDiscoveryService` 连接 CoreDevice 启动 WDA xctrunner
3. 等待 WDA HTTP 端点就绪：轮询 `GET /status`，间隔 1 秒，最多等待 60 秒；超时则抛出 `RuntimeError("WDA failed to start within 60s")`
4. 重置 `_session_id = None`

## 与 `list_targets` 的交互

`list_targets()` 对每台设备调用 `is_wda_installed()`：
- True → `state: "online"`
- False → `state: "offline"`

`list_targets()` **不调用** `do_prepare()`。

## 与操作函数的交互

`screenshot`、`tap`、`dump_ui` 等所有操作函数在执行前：

```python
if not device.is_prepared():
    device.do_prepare()
```

`do_prepare()` 抛出异常时，由 `toolkit_api.py` 捕获并转换为 `_err("SUBPROCESS", ...)` 返回。

# Phase 3 设计文档

## 模块结构

```
executor_ios/
  device.py          # 新增：iOSDevice + iOSDevicesManager
  tunneld_main.py    # 新增：tunneld 守护进程入口（打包为独立二进制）
  toolkit_api.py     # 更新：迁移到 iOSDevicesManager
  toolkit_cli.py     # 不变
  port_forward.py    # 不变（relay 逻辑被 device.py 复用）
  secrets.py         # 不变
```

## 后台事件循环（模块级单例）

`device.py` 在模块加载时创建一个后台事件循环线程，供所有 `iOSDevice` 的持久端口转发使用：

```python
_bg_loop = asyncio.new_event_loop()
_bg_thread = threading.Thread(target=_bg_loop.run_forever, daemon=True)
_bg_thread.start()
```

## `iOSDevice` 类

```python
class iOSDevice:
    udid: str
    local_port: int          # 持久分配，进程生命周期内不变
    name: str
    model: str
    os_version: str
    _forward_task: Future    # 后台转发协程句柄
    _session_id: str | None  # WDA session 缓存
    _session_lock: Lock      # 保护 _session_id 读写
    _wda_bundle_id: str      # 从 ~/.executor_ios.json 读取或使用默认值
```

> iOS 17+ 的 `rsd_address` / `rsd_port` **不作为固定属性存储**，而在 `do_prepare()` 中通过查询本地 tunneld HTTP API（`http://127.0.0.1:49151`）动态获取。

### 持久端口转发

设备注册时通过 `asyncio.run_coroutine_threadsafe` 在后台循环提交转发协程：

```python
future = asyncio.run_coroutine_threadsafe(
    _start_forward(udid, local_port), _bg_loop
)
device._forward_task = future
```

`_start_forward` 内部使用 `asyncio.start_server` + 双向 relay（复用 `port_forward.py` 中的 `_relay_via_usbmux` 逻辑），协程永不主动退出。

### WDA 生命周期

| 方法 | 职责 |
|---|---|
| `is_wda_installed() -> bool` | 检查 WDA bundle 是否已安装（供 `list_targets` 使用） |
| `is_prepared() -> bool` | 检查 WDA HTTP 进程是否活跃（GET /status 在 2s 内返回 200） |
| `do_prepare() -> None` | 若 WDA 未安装则报错；否则启动 WDA xctrunner，等待就绪（最多 60s） |

`do_prepare()` 中 iOS 版本路由：
- iOS ≤ 16：通过 lockdown/usbmux 路径启动 WDA
- iOS 17+：自动查询本地 tunneld（`http://127.0.0.1:49151`）获取 `rsd_address` / `rsd_port`，tunneld 未运行时抛出明确错误；查询成功后通过 `RemoteServiceDiscoveryService` 连接 CoreDevice 启动 WDA

### Session 复用

```
_ensure_session():
  with _session_lock:
    if _session_id is not None → return  # 复用缓存
    _session_id = POST /session → 返回新 session_id

WDA 操作返回 "invalid session id" 时:
  清除 _session_id → 重新 _ensure_session() → 重试一次
```

## `iOSDevicesManager` 类（单例）

```python
class iOSDevicesManager:
    _devices: dict[str, iOSDevice]  # UDID → iOSDevice

    def list_devices() -> list[iOSDevice]   # 触发设备发现，更新内部表
    def get_device(udid) -> iOSDevice | None
```

设备发现流程：
1. `pymobiledevice3.usbmux.list_devices()` 枚举 USB 物理设备
2. 过滤 `connection_type != "USB"` 的条目
3. 新 UDID → 分配本地端口 → 启动持久转发 → 创建 `iOSDevice`（RSD 信息不在发现阶段读取，在 `do_prepare()` 时按需查询 tunneld）
4. 已知 UDID → 跳过

## `toolkit_api.py` 迁移对照

| Phase 1 | Phase 3 |
|---|---|
| `asyncio.run()` + `_ephemeral_forward` | 直接使用 `device.local_port`（持久转发保证） |
| `_create_session()` 每次新建 | `device._ensure_session()` 复用缓存 |
| 无全局设备表 | `iOSDevicesManager` 单例 |
| `list_targets` 通过 usbmux 直接枚举 | 通过 `manager.list_devices()`，`state` 由 `is_wda_installed()` 决定 |

每个操作函数的统一模式：
```python
device = _manager.get_device(target)
if device is None:
    return _err("BAD_TARGET", ...)
if not device.is_prepared():
    device.do_prepare()
return device.<op>(...)
```

## `tunneld_main.py` — tunneld 守护进程入口

`tunneld_main.py` 封装 `pymobiledevice3.tunneld.server.TunneldRunner.create()` 调用，打包为独立可执行二进制（`ios_tunneld`），以 root 权限作为 LaunchDaemon 运行。

- 监听地址：`127.0.0.1:49151`（HTTP JSON API）
- 监控 USB 设备插拔（`usb_monitor=True`、`usbmux_monitor=True`），不监控 Wi-Fi（`wifi_monitor=False`）
- Python ≥ 3.13 使用 `TunnelProtocol.TCP`，否则使用 `TunnelProtocol.DEFAULT`，避免 QUIC 依赖
- `device.py` 中的 `_get_rsd_from_tunneld(udid)` 直接 GET `http://127.0.0.1:49151` 解析 JSON，获取对应设备的 `tunnel-address` 和 `tunnel-port`

## 配置文件 `~/.executor_ios.json`

```json
{
  "wda_bundle_id": "com.facebook.WebDriverAgentRunner.xctrunner"
}
```

字段缺失时使用默认值，文件不存在时全部使用默认值。

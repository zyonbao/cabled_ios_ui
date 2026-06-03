# Phase 3 实现任务

## device.py — 基础设施

- [x] 创建 `executor_ios/device.py`，初始化模块级后台事件循环线程（`_bg_loop` + `_bg_thread`）
- [x] 实现 `_load_config() -> dict` 函数：读取 `~/.executor_ios.json`，文件不存在或字段缺失时返回默认值
- [x] 实现 `_find_free_port(start: int = 8200) -> int`：从 `start` 起探测找到第一个可用本地端口

## device.py — 持久端口转发

- [x] 实现 `_start_forward(udid: str, local_port: int)` 异步协程：`asyncio.start_server` + 双向 relay（复用 `port_forward.py` 的 relay 逻辑）
- [x] 实现 `_launch_forward(udid: str, local_port: int) -> Future`：通过 `run_coroutine_threadsafe` 在 `_bg_loop` 中提交 `_start_forward`

## device.py — `iOSDevice` 类

- [x] 定义 `iOSDevice` 数据类，含全部属性（`udid`、`local_port`、`name`、`model`、`os_version`、`_forward_task`、`_session_id`、`_session_lock`、`_wda_bundle_id`）；iOS 17+ RSD 信息不作为属性存储，在 `do_prepare()` 中按需查询 tunneld
- [x] 实现 `iOSDevice.is_wda_installed() -> bool`：通过 `AppServiceClient.list_installed_apps()` 检查 `_wda_bundle_id`
- [x] 实现 `iOSDevice.is_prepared() -> bool`：GET `/status`，2 秒超时，200 返回 True
- [x] 实现 `iOSDevice.do_prepare() -> None`：前置检查安装状态 → iOS 版本路由启动 WDA → 等待就绪（最多 60s）→ 重置 `_session_id`
- [x] 实现 `iOSDevice._ensure_session() -> str`：加锁复用缓存，缓存为 None 时调用 `_create_session`
- [x] 实现 `iOSDevice` 的 WDA 操作方法（同步，直接用 `requests` + `self.local_port`）：`screenshot`、`dump_ui`、`tap`、`swipe`、`input_text`、`key_event`、`launch_app`、`kill_app`；需要 session 的方法内部调用 `_ensure_session()`，并在收到 `invalid session id` 时自动重建 session 并重试一次

## device.py — `iOSDevicesManager` 类

- [x] 定义 `iOSDevicesManager` 类，内部维护 `dict[str, iOSDevice]`
- [x] 实现 `iOSDevicesManager._discover() -> None`：枚举 USB 设备，对新 UDID 分配端口、启动转发、创建 `iOSDevice`（RSD 信息不在发现阶段读取）
- [x] 实现 `iOSDevicesManager.list_devices() -> list[iOSDevice]`：调用 `_discover()` 后返回设备列表
- [x] 实现 `iOSDevicesManager.get_device(udid: str) -> iOSDevice | None`
- [x] 创建模块级单例 `_manager = iOSDevicesManager()`

## xpc_tunnel.py（已删除，Not In Scope）

- [x] ~~创建 `executor_ios/xpc_tunnel.py`~~：`device.py` 直接查询 tunneld HTTP API，无需独立辅助脚本，已删除

## toolkit_api.py 迁移

- [x] 在 `toolkit_api.py` 顶部导入 `_manager`，替换原有的模块级状态
- [x] 更新 `list_targets()`：调用 `_manager.list_devices()`，`state` 字段由 `device.is_wda_installed()` 决定
- [x] 更新 `screenshot(target)`、`dump_ui(target)`、`tap(target, x, y)`、`swipe(target, ...)`、`input_text(target, text)`、`key_event(target, key)`、`launch_app(target, package, activity)`、`kill_app(target, package)`：统一模式 — `get_device` → `BAD_TARGET` 检查 → `is_prepared` + `do_prepare` → 委托给 `device.<op>()`
- [x] 移除 `toolkit_api.py` 中所有 `asyncio.run()` 调用和 `_ephemeral_forward` 使用

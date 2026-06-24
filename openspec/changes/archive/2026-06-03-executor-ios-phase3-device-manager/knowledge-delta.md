# Phase 3 知识增量 — 多设备支持与设备管理器

## 变更摘要

Phase 3 将 iOS 执行器从单次操作临时转发迁移为 `iOSDevicesManager` 管理的多设备、持久端口转发和 WDA session 复用架构。

## 目标模块

executor-ios

## 知识写入目标

executor-ios

## 架构变更

- 新增 `executor_ios/device.py`，引入模块级后台 `asyncio` event loop 和 daemon thread，所有持久 usbmux 转发协程都提交到该后台循环运行。
- 新增 `iOSDevice` 表示单台 USB 物理设备，持有 UDID、本地转发端口、设备元数据、后台转发任务、WDA session 缓存和 WDA bundle ID。
- 新增 `iOSDevicesManager` 模块级单例 `_manager`，负责发现 USB 设备、维护 UDID 到 `iOSDevice` 的注册表、处理设备拔出时的转发任务取消。
- `toolkit_api.py` 不再维护临时转发状态，也不再调用 `asyncio.run()`；公开操作先通过 `_manager` 获取设备，再执行 `is_prepared()` / `do_prepare()`，最后委托给 `iOSDevice` 方法。
- iOS 17+ 的 RSD 信息不作为设备属性长期保存，而是在 `do_prepare()` 中通过本机 `ios_tunneld` HTTP API 按需查询。

## 接口变更

- 新增 `iOSDevicesManager.list_devices() -> list[iOSDevice]`，调用时触发设备发现并返回当前注册设备。
- 新增 `iOSDevicesManager.get_device(udid: str) -> iOSDevice | None`，未命中时会再触发一次发现，便于刚插入设备被操作命中。
- 新增 `iOSDevice.is_wda_installed() -> bool`，通过 installation proxy 检查配置的 WDA bundle 是否安装。
- 新增 `iOSDevice.is_prepared() -> bool`，通过 `GET /status` 判断 WDA HTTP 服务是否已就绪。
- 新增 `iOSDevice.do_prepare() -> None`，按 iOS 版本启动 WDA，并等待 `/status` 就绪后清空 session 缓存。
- 新增 `iOSDevice` 操作方法：`screenshot`、`dump_ui`、`tap`、`swipe`、`input_text`、`key_event`、`launch_app`、`kill_app`，返回值保持 `toolkit_api.py` 的统一 `_ok` / `_err` 格式。
- 新增独立入口 `executor_ios/tunneld_main.py`，用于打包 `ios_tunneld`，监听 `127.0.0.1:49151` 并只监控 USB 设备。

## 代码路径变更

- `executor_ios/device.py`：新增多设备管理器、持久端口转发、WDA 生命周期、session 复用和具体 WDA 操作实现。
- `executor_ios/toolkit_api.py`：迁移为通过 `_get_manager()` 延迟导入 `_manager`，所有平台操作统一委托给 `iOSDevice`。
- `executor_ios/tunneld_main.py`：新增 tunneld 守护进程入口，供 iOS 17+ CoreDevice / RSD 路径使用。
- `openspec/changes/executor-ios-phase3-device-manager/specs/*/spec.md`：记录 device manager、persistent forward、WDA lifecycle、session reuse 和 XPC tunnel 行为。

## 平台差异更新

- iOS 16 及以下通过 lockdown/usbmux 路径启动 WDA xctrunner。
- iOS 17 及以上通过 `ios_tunneld` 提供的 RSD 地址和端口连接 CoreDevice，再启动 WDA xctrunner。
- Wi-Fi 配对设备、iOS 模拟器和 WDA 安装均不在 Phase 3 范围内；设备发现仅保留 USB 物理设备。

## 设计决策

- 选择持久端口转发而不是每次操作临时转发，是为了避免重复创建 event loop 和 usbmux 连接，降低多次操作延迟，并支持多台 USB 设备各自占用独立本地端口。
- `toolkit_api.py` 通过函数内延迟导入 `_manager`，是为了避免 `device.py` 在操作方法中复用 `_ok`、`_err`、`_xml_to_selectors` 等 helper 时形成模块加载期循环依赖。
- RSD 信息在 `do_prepare()` 中按需查询，而不是在发现阶段缓存，是因为 iOS 17+ tunnel 状态可能随 `ios_tunneld` 和设备插拔变化，按需读取可以减少过期地址导致的启动失败。
- WDA session 使用 `_session_lock` 保护缓存，是为了在并发操作同一设备时避免重复 `POST /session`，并在 WDA 返回 invalid session id 后只重建一次。
- `ios_tunneld` 固定监听 `127.0.0.1:49151` 且 `wifi_monitor=False`，是为了把 Phase 3 范围限定在本机 USB 设备，减少网络面暴露和不受支持设备类型带来的不确定性。

## 已知限制更新

- `is_wda_installed()` 当前通过 installation proxy 查询 User apps，如果 WDA 安装类型或 pymobiledevice3 行为变化，可能需要调整应用枚举方式。
- `_find_free_port()` 当前在 8200-8399 范围内顺序探测；极端多设备或端口占用场景下可能耗尽端口。
- 持久转发任务在设备拔出时会 cancel，但当前没有显式等待任务清理完成。
- `input_text` 仍保留 `toolkit_api.py` 侧的输入约束，禁止换行、单引号、反引号，并限制 1024 bytes，避免把不受控文本传入敏感输入路径。

# executor-ios 项目知识库

## 概述

`executor-ios` 是 iOS 平台能力执行层，负责发现 USB 物理设备、管理 WebDriverAgent 生命周期，并向上提供截图、UI dump、点击、滑动、输入、按键、启动应用和结束应用等同步操作接口。

## 架构

### Phase 3 多设备设备管理器

Phase 3 引入 `executor_ios/device.py`，用 `iOSDevicesManager` 单例维护 UDID 到 `iOSDevice` 的注册表。`device.py` 在模块加载时创建后台 `asyncio` event loop 和 daemon thread，每个 `iOSDevice` 注册时启动一个持久 usbmux 端口转发任务，设备操作直接访问对应 `local_port` 上的 WDA HTTP 服务。来源：`openspec/archive/executor-ios-phase3-device-manager/`

`toolkit_api.py` 通过 `_get_manager()` 延迟导入 `_manager`，公开操作统一执行：解析设备、必要时 `do_prepare()` 启动 WDA、委托 `iOSDevice` 方法。这样保留同步 API 形态，同时移除 Phase 1 的 `asyncio.run()` 和每次操作临时转发模式。来源：`openspec/archive/executor-ios-phase3-device-manager/`

## 接口说明

### 设备管理接口

| 接口 | 说明 |
|---|---|
| `iOSDevicesManager.list_devices() -> list[iOSDevice]` | 触发 USB 设备发现并返回当前注册设备。 |
| `iOSDevicesManager.get_device(udid: str) -> iOSDevice | None` | 根据 UDID 获取设备；未命中时重新发现一次。 |
| `iOSDevice.is_wda_installed() -> bool` | 通过 installation proxy 检查配置的 WDA bundle 是否安装。 |
| `iOSDevice.is_prepared() -> bool` | 通过 `GET /status` 判断 WDA HTTP 服务是否已就绪。 |
| `iOSDevice.do_prepare() -> None` | 按 iOS 版本启动 WDA，等待就绪后重置 session 缓存。 |

### 平台操作接口

`iOSDevice` 提供 `screenshot`、`dump_ui`、`tap`、`swipe`、`input_text`、`key_event`、`launch_app`、`kill_app` 方法，返回值沿用 `toolkit_api.py` 的 `_ok` / `_err` 结构。需要 WDA session 的操作会通过 `_ensure_session()` 复用缓存，并在 `invalid session id` 后清空缓存、重建 session、重试一次。来源：`openspec/archive/executor-ios-phase3-device-manager/`

## 代码路径

| 路径 | 说明 |
|---|---|
| `executor_ios/device.py` | 多设备管理器、持久端口转发、WDA 生命周期、session 复用和 WDA 操作实现。 |
| `executor_ios/toolkit_api.py` | iOS 平台同步 API，对外保持统一返回格式，对内委托 `iOSDevice`。 |
| `executor_ios/tunneld_main.py` | `ios_tunneld` 独立入口，监听 `127.0.0.1:49151`，为 iOS 17+ 提供 RSD 信息。 |

## 平台支持

| 平台 | 行为 | 原因 |
|---|---|---|
| iOS 16 及以下 USB 物理设备 | 通过 lockdown/usbmux 路径启动 WDA xctrunner。 | 该路径不依赖 CoreDevice RSD tunnel。 |
| iOS 17 及以上 USB 物理设备 | 通过 `ios_tunneld` 查询 RSD 地址和端口，再连接 CoreDevice 启动 WDA。 | iOS 17+ 的服务访问需要 RSD tunnel 信息。 |
| Wi-Fi 配对设备 | 不支持发现和操作。 | Phase 3 明确限定 USB 物理设备，减少连接状态不确定性。 |
| iOS 模拟器 | 不支持。 | 当前执行器面向真实设备和 WDA。 |

## 关键设计决策

| 决策 | WHY |
|---|---|
| 使用持久端口转发替代每次操作临时转发。 | 降低重复创建 event loop 和 usbmux 连接的成本，并让多设备各自拥有稳定本地端口。 |
| 使用 `iOSDevicesManager` 单例集中维护设备注册表。 | 让 `list_targets` 与具体操作共享同一批 `iOSDevice` 对象和转发任务。 |
| RSD 信息在 `do_prepare()` 中按需查询，不在发现阶段缓存。 | tunnel 信息可能随 `ios_tunneld` 状态和设备插拔变化，按需读取可避免使用过期地址。 |
| `toolkit_api.py` 延迟导入 `_manager`。 | 避免 `device.py` 复用 `_ok`、`_err`、`_xml_to_selectors` 时形成模块加载期循环依赖。 |
| `ios_tunneld` 仅监听本机地址且禁用 Wi-Fi monitor。 | 将能力范围限定为本机 USB 设备，降低不必要的网络暴露面。 |

## 已知限制与技术债

| 限制 | 影响 | 后续方向 |
|---|---|---|
| `_find_free_port()` 只在 8200-8399 范围内顺序探测。 | 极端端口占用或大量设备场景可能找不到可用端口。 | 可配置端口范围或记录端口分配状态。 |
| 设备拔出时只 cancel 转发任务。 | 没有显式等待任务清理完成。 | 增加转发任务生命周期观测和清理确认。 |
| WDA 安装检测依赖 installation proxy 应用枚举。 | WDA 安装类型变化时可能误判为未安装。 | 根据实际安装方式补充枚举范围或 fallback。 |
| `input_text` 限制换行、单引号、反引号和 1024 bytes。 | 部分复杂输入无法直接注入。 | 如确需支持，先设计更严格的输入编码和敏感 sink 约束。 |

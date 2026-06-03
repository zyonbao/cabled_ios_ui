## Why

`executor_ios` 目前只有两个空文件（`toolkit_api.py`、`toolkit_cli.py`），缺少任何可运行的 iOS 平台能力层。Broker 无法通过 JSON CLI 协议调用任何 iOS 设备操作，阻塞了整个 iOS UI 自动化链路。Phase 1 的目标是在单设备场景下，交付完整可用的平台能力层，使所有 WDA 操作均可被 broker 调用。

## What Changes

- **新增** `executor_ios/__init__.py`：将目录标记为 Python 包
- **实现** `executor_ios/toolkit_api.py`：提供所有平台操作的公共 API 函数
  - 内部基础设施：`_ephemeral_forward`（临时 usbmux 端口转发）、`_wda_get`/`_wda_post`（WDA HTTP 工具）、`_create_session`（WDA session 新建）、统一返回值工具函数 `_ok`/`_err`/`_not_implemented`
  - 平台操作：`list_targets`、`screenshot`、`dump_ui`、`tap`、`swipe`、`input_text`、`key_event`、`launch_app`、`kill_app`
  - 空桩：`switch_app_env`、`type_credential`（返回 `NOT_IMPLEMENTED`）
- **全局约束**：仅支持 USB 连接物理设备，不支持 Wi-Fi 配对设备和 iOS 模拟器

## Capabilities

### New Capabilities

- `device-discovery`：通过 pymobiledevice3 枚举 USB 连接的物理 iOS 设备，读取设备元数据（name、model、os_version），过滤 Wi-Fi 配对设备
- `ephemeral-port-forward`：每次操作独立建立临时 usbmux 端口转发（localhost → device:8100），操作完成后自动释放，无需维护全局端口表
- `wda-session`：每次需要 session 的操作均新建 WDA session（Phase 1 不缓存），通过 `POST /session` 获取 `sessionId`
- `screenshot-op`：通过 WDA `GET /screenshot` 获取 PNG base64 截图
- `dump-ui-op`：通过 WDA `GET /source?format=xml` 获取 UI 层级树，解析为统一 selector 格式（含去重和数量上限）
- `tap-op`：通过 WDA W3C Actions（pointer 事件）实现点击
- `swipe-op`：通过 WDA W3C Actions（pointerDown → pause → pointerMove → pointerUp）实现滑动
- `input-text-op`：通过 WDA 活跃元素 value API 或 W3C key actions 输入文本（含输入校验）
- `key-event-op`：按键路由表，部分键通过 WDA pressButton，部分通过 W3C key events，iOS 不支持的键返回 `NOT_IMPLEMENTED`
- `launch-kill-app-op`：通过 WDA apps/launch 和 apps/terminate 启动/终止 App，WDA 失败时 fallback 到 pymobiledevice3 AppServiceClient

### Modified Capabilities

（无现有规格，本 Change 全为新增）

## Impact

- **新增文件**：`executor_ios/__init__.py`、`executor_ios/toolkit_api.py`
- **依赖**：`pymobiledevice3`（设备发现、usbmux 转发）、`requests`（WDA HTTP 通信）
- **不影响**：Phase 2 的 `toolkit_cli.py`（CLI 入口）和 Phase 3 的 `device.py`（设备管理器）在本 Change 范围之外

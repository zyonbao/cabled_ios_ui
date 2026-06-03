## Why

Studio 平台需要一套统一的多端 executor 体系。iOS 平台目前缺少符合 PYTHON-PLATFORM-EXECUTOR-CONTRACT 规范的实现，导致 Studio broker 无法通过标准 stdin/stdout JSON 协议调用 iOS 设备控制能力。本 change 实现 `executor_ios` 包，以 WebDriverAgent（WDA）REST API 为底层驱动，交付符合 Contract 的 iOS 平台执行器。

## What Changes

- 新增 `executor_ios/` Python 包，遵守 PYTHON-PLATFORM-EXECUTOR-CONTRACT 第 1–2 层规范
- 新增 `toolkit_api.py`：11 项平台操作的唯一真实实现层（list_targets / screenshot / dump_ui / tap / swipe / input_text / key_event / launch_app / kill_app / switch_app_env / type_credential）
- 新增 `toolkit_cli.py`：stdin → stdout 一次性 JSON CLI 入口，供 Studio broker 以子进程方式调用
- 新增 `__init__.py`：Python 包声明
- 新增 `secrets.py`：凭据读取模块，仅供 type_credential 内部使用
- 新增 `README.md`：环境依赖、安装步骤、自测记录

复用现有模块（不在本 change 范围内修改）：
- `wda_client.py`：已有的 WDA HTTP 低层封装
- `session.py`：已有的 WDA session 管理（lazy 创建 + heartbeat）

## Capabilities

### New Capabilities

- `device-discovery`：通过 pymobiledevice3 发现已连接的 iOS 物理设备，结合 WDA liveness 探测返回 target 列表
- `screenshot`：调用 WDA `GET /screenshot`，返回 base64 PNG，坐标体系与手势操作保持一致
- `ui-dump`：调用 WDA `GET /source?format=xml`，解析 Accessibility 树并映射为 8 字段统一 selectors 格式
- `gestures`：tap 和 swipe，基于 WDA W3C Actions（pointer）实现，坐标为逻辑点（pt）
- `text-input`：input_text（WDA element value / W3C key fallback）和 key_event（HOME/POWER 等硬件键 + ENTER/DEL 等软键盘键）
- `app-control`：launch_app 和 kill_app，基于 WDA `wda/apps/launch` 和 `wda/apps/terminate`
- `credential-input`：type_credential，从 secrets.py 读取凭据后调用 input_text 写入，明文不出现在任何日志或响应中
- `json-cli`：toolkit_cli.py 实现的 stdin/stdout 一次性 JSON 协议，定义请求格式、响应格式和退出码约定

### Modified Capabilities

<!-- 全新包，无已有 spec -->

## Impact

- **新增依赖**：`requests`（已有）、`pymobiledevice3`（pip install）
- **调用方式**：`python3 -B -m executor_ios.toolkit_cli`，stdin 传入 JSON 请求，stdout 返回 JSON 响应
- **环境前置条件**：
  - WDA 已通过 Xcode（⌘U）部署到目标 iOS 物理设备并运行
  - usbmux port forward 已建立（`localhost:8100` → 设备 WDA）
  - iOS 17+ 物理设备需提前运行 `sudo pymobiledevice3 remote tunneld`
- **平台限制**：macOS only，仅支持物理设备（模拟器 Not In Scope）

## Non-goals

- **模拟器支持**：Not In Scope，当前阶段仅支持物理设备
- **NDJSON executor（main.py）**：WillNotDo，Contract 第 3 层，当前不实现
- **switch_app_env**：WDA 无法通用实现，统一返回 NOT_IMPLEMENTED
- **key_event BACK / MENU / RECENTS**：iOS 无对应硬件键，统一返回 NOT_IMPLEMENTED
- **HTTP proxy server**：本 change 不暴露 HTTP 接口，仅实现 stdin/stdout CLI 协议

## Why

iOS UI 自动化测试需要在 Mac 端以编程方式控制 iOS 设备/模拟器执行截图、UI 树导出、手势操作等基础动作，现有方案依赖完整 Appium Server 栈，启动重、维护成本高。本项目通过直接对接 WebDriverAgent（WDA）的 REST API 构建轻量 proxy 服务，为 TA 框架提供稳定、低依赖的 iOS UI 操作能力。

## What Changes

- 新增 Python HTTP 服务（`ios_ui_ta_proxy`），封装 WDA REST API 的四项核心操作
- 提供 `snapshot`：截取当前屏幕并返回 PNG 图像
- 提供 `ui_dump`：导出当前 UI 层级树（XML/JSON）
- 提供 `swipe`：基于 W3C Actions 协议执行滑动手势
- 提供 `click`：基于坐标或元素 xpath 执行点击
- 内置 WDA 连接管理：心跳检测、自动重连、session 保持
- 支持多设备并发：通过端口映射区分不同设备实例

## Capabilities

### New Capabilities

- `wda-session`: WDA 连接管理——建立 session、心跳检测、自动重连
- `screenshot`: 截图操作——调用 `GET /screenshot`，返回 base64 PNG
- `ui-dump`: UI 层级导出——调用 `GET /source`，返回 XML/JSON UI 树
- `touch-actions`: 手势操作——封装 swipe（`POST /actions` W3C）和 click（坐标点击）
- `proxy-server`: HTTP 代理服务——对外暴露统一 REST 接口，管理 WDA 路由转发

### Modified Capabilities

<!-- 无已有 spec，全新项目 -->

## Impact

- **依赖**：Python 3.9+、`requests`、`fastapi`/`uvicorn`，无需 Appium Server
- **WDA 前置条件**：WDA 须已通过 `xcodebuild` 或 `idb` 部署到目标设备，端口默认 8100
- **真机 vs 模拟器**：模拟器直连 localhost:8100；真机需通过 `iproxy` 做 USB 端口转发
- **平台限制**：Mac only（依赖 Xcode/idb 工具链）

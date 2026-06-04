## Why

当前 `executor_ios` 只支持 `tap` 与 `swipe` 两种触控手势，缺少长按（long press / touch-and-hold）。很多 iOS 交互（弹出上下文菜单、进入图标抖动编辑态、消息长按菜单等）依赖长按，没有它就无法在镜像控制台里完整复现真机操作。两个控制台（`slide6_console`、`web_console`）目前也只能发起点按与滑动，缺一个对应的长按入口。

## What Changes

- `executor_ios` 新增 `long_press(target, x, y, duration_ms)` 能力：通过 WDA W3C pointer actions 在同一坐标按下、保持 `duration_ms`、再抬起，单位为逻辑点（pt），`duration_ms` 默认 800。
- `executor_ios/toolkit_cli.py` 新增 `long_press` op 路由，纳入一次性 JSON CLI 协议。
- `web_console` 后端新增 `POST /api/long_press` 端点，转发到 `toolkit_api.long_press`。
- `web_console` 前端在原地按住超过阈值（位移不超过点按阈值且按住时长达到长按时长）时识别为长按并调用 `/api/long_press`，与点按/滑动互斥。
- `slide6_console` 在画面控件上识别原地长按手势，新增 `long_press` 信号并调用 `toolkit_api.long_press`，与点按/滑动互斥，且不打断键盘捕获。

## Capabilities

### New Capabilities

- `long-press-op`: `executor_ios` 的长按平台能力（`toolkit_api.long_press` 与 `toolkit_cli` 的 `long_press` op）的行为契约。
- `web-console-long-press`: `web_console` 的长按支持，包括 `POST /api/long_press` 后端端点与前端原地长按手势识别。

### Modified Capabilities

- `slide6-gesture-input`: 新增"原地长按"作为第三类手势，与点按/滑动按位移与按住时长共同区分。

## Impact

- 代码：`executor_ios/device.py`、`executor_ios/toolkit_api.py`、`executor_ios/toolkit_cli.py`；`web_console/web_server.py`、`web_console/web/app.js`；`slide6_console/mirror.py`、`slide6_console/gestures.py`、`slide6_console/main_window.py`。
- 文档：`docs/PYTHON-PLATFORM-EXECUTOR-CONTRACT.zh-CN.md` 增补 `long_press` op 说明。
- 协议：JSON CLI op 表新增一个 op，向后兼容（仅新增，不改动既有 op）。
- 依赖：无新增第三方依赖，复用现有 WDA `/session/{sid}/actions` 通道。

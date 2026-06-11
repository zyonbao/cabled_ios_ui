## Why

CablediOS 目前没有「诊断」能力：用户无法在桌面端重启 / 关机 / 休眠设备，也看不到电池 / Wi‑Fi / 诊断 / IORegistry 等设备运行信息。`pymobiledevice3` 的 `DiagnosticsService` 已原生提供这些能力（usbmux/lockdown 或 iOS 17+ 经 RSD/XPC tunnel），接入成本低、价值明确。

## What Changes

- 新增「诊断」Tab（`DiagnosticsTab`），采用与「开发者工具」一致的卡片 + 流式网格视觉，分为两个 section：
  - **Section 1「电源控制 / Power」**：`restart` / `shutdown` / `sleep` 三个卡片。三者均为不可逆/打断性操作，点击 MUST 弹窗二次确认后才执行。
  - **Section 2「诊断信息 / Diagnostics」**：`battery status` / `wifi status` / `diagnostic info` / `ioregistry info` 卡片；并在 **iOS < 17.4** 额外提供 `MobileGestalt` 卡片（Apple 自 iOS 17.4 起弃用 MobileGestalt，故 ≥ 17.4 MUST 隐藏该卡片）。
- 诊断信息类操作的结果以只读弹窗（可滚动 + 可复制）呈现。
- 新增 `ios_toolkit` 诊断 API（逻辑层，零 i18n）：版本感知地打开 `DiagnosticsService`（iOS<17 走 usbmux lockdown，iOS17+ 走 RSD/tunnel），封装电源动作与信息查询，统一错误信封（含稳定 `code`，复用既有 `localize_error` 本地化）。
- 新增诊断相关 i18n 文案（`diagnostics.*` + 必要的 `errors.*` 错误码）。

## Capabilities

### New Capabilities

- `diagnostics-op`：`ios_toolkit` 诊断能力——重启 / 关机 / 休眠、电池 / Wi‑Fi / 诊断 info / IORegistry 查询、MobileGestalt 查询（含 iOS 17.4+ 弃用处理），版本感知连接与统一错误信封。
- `slide6-diagnostics`：CablediOS「诊断」Tab 的 UI 规格——双 section 卡片网格、电源操作二次确认、信息只读弹窗、版本门控与就绪门控。

### Modified Capabilities

（无。诊断为 GUI 进程内 `toolkit_api` 调用，与 device_info / crash 一致，不新增 CLI op，`json-cli` 不变。）

## Impact

- 新增代码：`slide6_ui/diagnostics/`（Tab + 信息弹窗），`ios_toolkit/device.py`（`DiagnosticsService` 接入与方法），`ios_toolkit/toolkit_api.py`（诊断 API 包装）。
- 复用：`FlowLayout`、卡片样式（`_FeatureTile`，将提升为可复用组件）、`AsyncRunner`、`localize_error`、`readiness`/`tunnel`（iOS 17+ 门控）。
- i18n：`slide6_ui/languages/{zh-CN,en-US}.json` 新增 `diagnostics.*` 与诊断错误码。
- 主窗口：`main_window.py` 注册新 Tab 并在设备切换时 `set_target`。
- 无新增第三方依赖（`pymobiledevice3` 已在用）。

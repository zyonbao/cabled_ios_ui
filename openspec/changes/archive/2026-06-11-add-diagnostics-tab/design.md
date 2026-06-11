## Context

`pymobiledevice3` 9.16.0 的 `pymobiledevice3.services.diagnostics.DiagnosticsService`（`LockdownService` 子类）已提供本特性所需的全部底层能力：

- 电源：`restart()` / `shutdown()` / `sleep()`（均经通用 `action(name)`，请求 `{"Request": "Restart|Shutdown|Sleep"}`，要求 `Status == "Success"`）。
- 信息：`get_battery()`（`ioregistry(ioclass="IOPMPowerSource")`）、`get_wifi()`、`info(diag_type="All")`、`ioregistry(plane/name/ioclass)`、`mobilegestalt(keys=None)`。
- 连接：构造 `DiagnosticsService(lockdown)` 时按通道选服务名——`LockdownClient`（usbmux）用 `com.apple.mobile.diagnostics_relay`；RSD provider 用 `com.apple.mobile.diagnostics_relay.shim.remote`。即 **iOS < 17 走 usbmux lockdown；iOS 17+ 走 RSD（需 XPC tunnel）**，与本仓 `device._with_dvt` 的版本分支同构（已有 `_get_rsd_from_tunneld`）。
- `mobilegestalt()` 在 **iOS ≥ 17.4** 已被 Apple 弃用，库会抛 `DeprecationError`。

现状：CablediOS 无诊断/电源能力；其它 GUI Tab（device_info / crash 等）均以进程内 `toolkit_api` 直接调用（非 CLI 子进程）。

## Goals / Non-Goals

**Goals:**

- 新增「诊断」Tab，双 section 卡片网格：Section 1 电源控制（restart/shutdown/sleep，二次确认）、Section 2 诊断信息（battery/wifi/info/ioregistry，外加 iOS<17.4 的 MobileGestalt）。
- 逻辑层（`ios_toolkit`）零 i18n，统一错误信封（含稳定 `code`），UI 经既有 `localize_error` 本地化。
- 复用既有视觉（卡片 + `FlowLayout`）与异步（`AsyncRunner`）。

**Non-Goals:**

- 不新增 CLI op（与 device_info/crash 一致，仅进程内 API）；不改 `json-cli`。
- 不解析/美化 IORegistry / MobileGestalt 的全部字段语义——只做只读结构化展示（JSON/键值）。
- 不做电源操作的设备侧回执轮询（操作下发成功即视为成功；设备随后自行重启/关机）。

## Decisions

### 决策 1：逻辑层接入 `DiagnosticsService`（版本感知）

在 `device.py` 新增 `_run_diagnostics(op)` 辅助：iOS<17 经 `create_using_usbmux` 打开 `DiagnosticsService(lockdown)`；iOS17+ 经 `_get_rsd_from_tunneld` + `RemoteServiceDiscoveryService` 打开 `DiagnosticsService(rsd)`；tunnel 缺失时复用既有 `_TunnelRequiredError`（→ `code=TUNNEL_REQUIRED`，已本地化）。在其上实现：`device_restart` / `device_shutdown` / `device_sleep` / `diagnostics_battery` / `diagnostics_wifi` / `diagnostics_info` / `diagnostics_ioregistry` / `diagnostics_mobilegestalt`。`toolkit_api` 加同名薄包装 + `_prepare_device_basic` + 统一 `_err`。

> 注意：`DiagnosticsService` 的方法（`restart/shutdown/sleep/info/ioregistry/get_battery/get_wifi/mobilegestalt`）均为 `async def`。复用 `device.py` 既有的异步驱动模式（模块级 `_bg_loop` 守护线程 + `asyncio.run_coroutine_threadsafe`，或带超时的 `asyncio.run` 包装）同步化执行，避免阻塞 GUI 线程（实际阻塞经 `AsyncRunner` 已在工作线程）。

- 备选：仅 usbmux（忽略 17+ RSD）。否决——17+ 必须 RSD，否则功能在新系统不可用。

### 决策 2：电源操作二次确认（UI 层）

`restart` / `shutdown` / `sleep` 点击后 MUST 先 `QMessageBox.question`（本地化标题/正文、默认按钮为「取消/否」）确认，确认后才经 `AsyncRunner` 下发。信息类操作无需确认。

### 决策 3：MobileGestalt 的版本门控

按当前设备 `os_version` 解析 major.minor（复用 `ddi_provider.parse_major_minor`）：仅当 `major < 17` 或 `(major == 17 and minor < 4)` 时在 Section 2 显示 MobileGestalt 卡片，否则不创建该卡片。逻辑层额外把库的 `DeprecationError` 兜底映射为 `code=MOBILEGESTALT_DEPRECATED`，双重保险。

### 决策 4：iOS 17+ 门控策略——tunnel 状态条 + 禁用式门控，不耦合 DDI 就绪

诊断只依赖 XPC tunnel（**不需要 DDI 挂载**），故不复用面向 DVT 的 `readiness`（DDI+RSD）。在诊断 Tab 顶部提供 XPC tunnel 状态条（复用 `common.tunnel` 与 `dev_tools.tunnel.*` 文案）：仅 iOS 17+ 设备显示，反映运行状态并提供启动（未起）或停止 + 重启（已起）入口。采取**禁用式门控**：当 17+ 且 tunnel 未运行时，全部卡片置为 Disabled 并以 tooltip 说明（`diagnostics.tunnel_required_hint`）；tunnel 启动后自动 enable。逻辑层仍保留 `TUNNEL_REQUIRED` 错误兜底（双保险）。注意 `restart` / `shutdown` 成功后设备重启会使 tunnel 掉线，回调中重算面板与卡片态。

- 备选：纯错误驱动（点击后才提示）。否决——17+ 全功能都吃 tunnel，状态条 + 禁用门控体验更明确，与开发者工具一致。
- 备选：复用 `readiness`（要求 DDI）。否决——诊断不需要 DDI，过度门控会误禁用。

### 决策 5：卡片/网格复用——提升 `_FeatureTile` 为公共组件

将 `developer_tools_tab._FeatureTile` 提升到 `slide6_ui/common/feature_tile.py`（保持现有标题/描述分层样式与点击穿透），开发者工具与诊断 Tab 共用；`FlowLayout` 已在 `slide6_ui/common/flow_layout.py`。诊断 Tab 用两个 `FlowLayout`（每个 section 一个），section 之间以标题 `QLabel` 分隔。

- 备选：诊断 Tab 复制一份卡片实现。否决——重复代码、样式易漂移。

### 决策 6：信息结果展示

battery/wifi/info/ioregistry/mobilegestalt 的返回是 dict/嵌套结构，以只读弹窗呈现（`QPlainTextEdit` 展示格式化 JSON，或键值表）。弹窗为非模态、可复制（复用本次新增的右键复制能力）。

## Risks / Trade-offs

- [iOS 17+ 无 tunnel 时电源操作确认后才报错，体验略绕] → 文案为本地化 `TUNNEL_REQUIRED`；可选在构建时按 tunnel 状态禁用并 tooltip。
- [`shutdown` 后设备断连、UI 可能短暂报通信错误] → 操作下发成功即提示「已发送」；不轮询设备回执（Non-Goal）。
- [MobileGestalt 在边界版本(17.4) 行为差异] → 版本门控 + 逻辑层 `DeprecationError → MOBILEGESTALT_DEPRECATED` 双保险。
- [误触电源操作] → 强制二次确认、默认按钮为否。
- [提升 `_FeatureTile` 影响开发者工具 Tab] → 仅移动位置、签名不变，原引用改为从 common 导入并回归冒烟。

## Migration Plan

1. 提升 `_FeatureTile` 到 `slide6_ui/common/feature_tile.py`，开发者工具改为导入复用（行为不变）。
2. `device.py` 加 `_run_diagnostics` 与诊断方法；`toolkit_api.py` 加包装与统一 `_err`（含 `MOBILEGESTALT_DEPRECATED`、复用 `TUNNEL_REQUIRED`）。
3. 新增 `slide6_ui/diagnostics/`（Tab + 信息弹窗）；`main_window.py` 注册 Tab 并 `set_target`。
4. i18n：`diagnostics.*` 文案 + 诊断错误码（zh-CN/en-US），`i18n.validate()` 通过。
5. 验证：字节编译 + headless 冒烟（构造 Tab、版本门控显隐 MobileGestalt、确认弹窗路径、信息弹窗渲染）。

## Open Questions

- IORegistry / 诊断 info 默认查询参数：`info` 用 `"All"`；`ioregistry` 入口默认不带过滤（展示根），后续可加可选过滤输入（本期不做）。

# slide6-diagnostics Specification

## Purpose
定义「诊断」页面的能力与门控规范：电源控制与诊断信息卡片、确认弹窗、结果展示，以及在 tunnel/配对等前置不满足时的统一门控提示行为。
## Requirements
### Requirement: 诊断 Tab 入口

桌面应用 SHALL 在左侧 sidebar Tab 栏提供独立的「诊断」Tab（`DiagnosticsTab`）。该 Tab MUST 实现 `set_target(target)`，由主窗口在设备切换时分发；未选中设备时 MUST 显示「未选择设备」并禁用全部能力，不发起设备请求。所有阻塞调用 MUST 经由 `AsyncRunner` 在工作线程执行。Tab 内文案 MUST 全部经 i18n（`diagnostics.*`），错误展示 MUST 经 `localize_error`。

#### Scenario: 选中设备进入 Tab

- **WHEN** 已选中设备并进入「诊断」Tab
- **THEN** Tab 展示「电源控制」与「诊断信息」两个 section 的功能卡片

#### Scenario: 未选择设备

- **WHEN** 未选中任何设备
- **THEN** Tab 显示「未选择设备」，全部卡片禁用，不发起设备请求

### Requirement: 双 section 卡片网格

「诊断」Tab SHALL 以两个分区呈现功能卡片，复用卡片（标题 + 描述）与流式网格（`FlowLayout`）视觉：

- **Section 1「电源控制」**：`restart` / `shutdown` / `sleep` 三个卡片。
- **Section 2「诊断信息」**：`battery status` / `wifi status` / `diagnostic info` / `ioregistry info` 卡片，并按版本门控可选包含 `MobileGestalt` 卡片。

每个 section MUST 有本地化的 section 标题。卡片随窗口宽度自适应换行排布。

#### Scenario: 卡片分区展示

- **WHEN** 已选中设备
- **THEN** 「电源控制」展示 restart/shutdown/sleep 卡片，「诊断信息」展示 battery/wifi/info/ioregistry 卡片

### Requirement: 电源操作二次确认

「电源控制」section 的 `restart` / `shutdown` / `sleep` 卡片被点击时 MUST 先弹出本地化的二次确认对话框（默认选中「取消/否」），用户确认后才经 `AsyncRunner` 下发操作；用户取消时 MUST NOT 发起任何设备请求。操作完成后 MUST 以本地化状态提示结果；失败时 MUST 经 `localize_error` 展示。

#### Scenario: 确认后执行

- **WHEN** 用户点击 restart 卡片并在确认对话框选择「确定」
- **THEN** 应用下发重启请求并提示结果

#### Scenario: 取消则不执行

- **WHEN** 用户点击 shutdown 卡片并在确认对话框选择「取消」
- **THEN** 不发起任何设备请求

### Requirement: XPC tunnel 状态条与门控（iOS 17+）

「诊断」Tab 的全部功能在 iOS 17+ 设备上经 RSD 访问，依赖 XPC tunnel，但该 Tab MUST NOT 自带 tunnel 状态条或任何 tunnel 启动 / 停止 / 重启控制（tunnel 管理统一由「开发者工具」承担）。当目标设备为 iOS 17+ 且 tunnel 未运行时，全部功能卡片 MUST 置为 Disabled，并以 tooltip 与底部状态文案给出**非模态**引导，说明这些功能需要先启用 XPC tunnel、请前往「开发者工具」启动；当 tunnel 启动后（用户切回本 Tab 或触发刷新），卡片 MUST 自动启用。iOS < 17 设备 MUST NOT 因 tunnel 状态被门控。

#### Scenario: iOS 17+ 缺 tunnel 时禁用并引导

- **WHEN** 目标设备 iOS ≥ 17 且 XPC tunnel 未运行
- **THEN** 全部功能卡片置为 Disabled，并以 tooltip / 状态文案提示需先到「开发者工具」启动 XPC tunnel
- **AND** 本 Tab 不显示任何 tunnel 状态条或启动 / 停止 / 重启控制

#### Scenario: 在开发者工具启动 tunnel 后启用

- **WHEN** 用户在「开发者工具」启动 XPC tunnel 成功后切回「诊断」Tab（或触发本 Tab 刷新）
- **THEN** 本 Tab 重新探测到 tunnel 运行，全部功能卡片自动启用

#### Scenario: iOS 17 以下不门控

- **WHEN** 目标设备 iOS < 17
- **THEN** 不因 tunnel 状态禁用功能卡片，且不显示任何 tunnel 控制

### Requirement: 诊断信息只读展示

「诊断信息」section 各卡片被点击时 SHALL 经 `AsyncRunner` 查询并以只读弹窗呈现结果（可滚动、可复制）。查询失败 MUST 经 `localize_error` 提示。

#### Scenario: 查看电池状态

- **WHEN** 用户点击 battery status 卡片
- **THEN** 弹出只读窗口展示格式化的电池诊断数据

### Requirement: MobileGestalt 卡片版本门控

「诊断信息」section MUST 仅在目标设备 iOS < 17.4 时显示 `MobileGestalt` 卡片；iOS ≥ 17.4 时 MUST NOT 创建该卡片（Apple 自 17.4 弃用 MobileGestalt）。版本判定基于当前设备 `os_version` 的主次版本。

#### Scenario: 低版本显示

- **WHEN** 目标设备 iOS < 17.4
- **THEN** 「诊断信息」section 包含 MobileGestalt 卡片

#### Scenario: 高版本隐藏

- **WHEN** 目标设备 iOS ≥ 17.4
- **THEN** 「诊断信息」section 不显示 MobileGestalt 卡片


## MODIFIED Requirements

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

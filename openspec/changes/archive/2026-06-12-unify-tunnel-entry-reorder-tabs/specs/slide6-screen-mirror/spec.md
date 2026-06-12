## MODIFIED Requirements

### Requirement: 键鼠操作接入设备就绪前置检查

「键鼠操作」在启动 WDA / DVT 相关流程前 MUST 应用统一的设备就绪前置检查（见 `slide6-device-readiness`）。当前置条件不满足时，MUST 以**非模态**方式（画面区 overlay / 状态文案）给出可操作引导而非直接失败，且 MUST NOT 弹出任何模态对话框、MUST NOT 从键鼠操作侧自动拉起 tunnel：

- iOS 17+ 缺 tunnel 时：提示这些功能需要先启用 XPC tunnel，请前往「开发者工具」启动 XPC tunnel 并挂载 DeveloperDiskImage（不提供启动入口、不弹模态、不自动拉起）。
- 缺 DDI 时：提示前往「开发者工具」根 tab 挂载 DDI。
- tunnel 与 DDI 均就绪但 RSD 服务不工作时：提示重新挂载 DDI 或重启 tunnel（均在「开发者工具」操作）。

#### Scenario: iOS 17+ 缺 tunnel 进入键鼠操作

- **WHEN** iOS 17+ 设备 tunnel 未启用，用户选中设备 / 进入键鼠操作
- **THEN** 不弹出模态对话框、不自动拉起 tunnel
- **AND** 以非模态 overlay / 状态提示引导用户前往「开发者工具」启动 XPC tunnel 并挂载 DeveloperDiskImage

#### Scenario: iOS 17+ 缺 DDI 进入键鼠操作

- **WHEN** iOS 17+ 设备 tunnel 已就绪但 DDI 未挂载，用户进入键鼠操作
- **THEN** 以非模态提示引导前往「开发者工具」根 tab 挂载 DDI，而非直接 WDA 失败

#### Scenario: tunnel 与 DDI 就绪但 RSD 不工作

- **WHEN** iOS 17+ 设备 tunnel 与 DDI 均就绪，但目标 RSD 开发者服务不可用
- **THEN** 以非模态提示引导用户重新挂载 DDI 或在「开发者工具」重启 XPC tunnel

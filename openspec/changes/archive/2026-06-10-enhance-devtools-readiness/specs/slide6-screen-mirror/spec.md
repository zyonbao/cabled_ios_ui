## ADDED Requirements

### Requirement: 键鼠操作接入设备就绪前置检查

「键鼠操作」在启动 WDA / DVT 相关流程前 MUST 应用统一的设备就绪前置检查（见 `slide6-device-readiness`）。当前置条件不满足时，MUST 给出可操作引导而非直接失败：iOS 17+ 缺 tunnel 时提示并提供启动入口、缺 DDI 时提示前往「开发者工具」根 tab 挂载 DDI、tunnel 与 DDI 均就绪但 RSD 服务不工作时提示重新挂载 DDI 或重启 tunnel；iOS 17 以下缺 DDI 时提示挂载并提供 reload。

#### Scenario: iOS 17+ 缺 DDI 进入键鼠操作

- **WHEN** iOS 17+ 设备 tunnel 已就绪但 DDI 未挂载，用户进入键鼠操作
- **THEN** 提示前往「开发者工具」根 tab 挂载 DDI，而非直接 WDA 失败

#### Scenario: iOS 17- 缺 DDI 进入键鼠操作

- **WHEN** iOS 17 以下设备 DDI 未挂载，用户进入键鼠操作
- **THEN** 提示前往「开发者工具」根 tab 挂载 DDI，并提供 reload 重新检查

# slide6-device-readiness Specification

## Purpose
定义依赖开发者能力操作的统一设备就绪前置检查：按 iOS 版本判定 tunnel / DDI / RSD 前提是否满足，并在未就绪时输出可操作引导，避免直接失败或阻塞 UI。
## Requirements
### Requirement: 设备就绪前置检查矩阵

应用 SHALL 提供统一的设备就绪前置检查，用于在执行依赖开发者能力的操作前判定前置条件是否满足，并产出可操作的引导信息。检查 MUST 按设备主版本区分：

- iOS 17+：依次检查 `XPC tunnel 是否就绪`、`DDI 是否已挂载`、`目标 RSD 开发者服务是否可用`。
- iOS 17 以下：检查 `DDI 是否已挂载`。

检查 MUST 返回结构化结果，指明缺失项及其对应引导动作，MUST NOT 直接令调用方崩溃或静默失败；耗时探测 MUST 在工作线程执行，不阻塞 UI。

#### Scenario: iOS 17+ 全部就绪

- **WHEN** 对一台 iOS 17+ 设备执行就绪检查，且 tunnel 就绪、DDI 已挂载、目标 RSD 服务可用
- **THEN** 返回"就绪"，调用方可继续执行相关操作

#### Scenario: iOS 17 以下仅检查 DDI

- **WHEN** 对一台 iOS 17 以下设备执行就绪检查
- **THEN** 仅以 DDI 是否挂载为准，不检查 tunnel / RSD

### Requirement: 未就绪时的可操作引导

当就绪检查未通过时，应用 SHALL 给出明确、可操作的引导，而非直接失败：

- 缺 XPC tunnel（iOS 17+）：MUST 提示用户启用 XPC tunnel（并可经现有入口启动）。
- 缺 DDI 挂载：MUST 提示用户前往「开发者工具」根 tab 挂载 DDI；iOS 17 以下 MUST 额外提供 reload 按钮以重新检查 / 刷新状态。
- tunnel 就绪且 DDI 已挂载、但目标 RSD 服务不工作（iOS 17+）：MUST 提示用户重新挂载 DDI，且 MAY 提示可手动重启 XPC tunnel。

「键鼠操作」与「开发者工具」中依赖 DVT / WDA 的能力 MUST 在执行前应用上述就绪检查与引导。

#### Scenario: 缺 tunnel 引导（iOS 17+）

- **WHEN** iOS 17+ 设备未启用 XPC tunnel 且用户触发依赖该能力的操作
- **THEN** 提示需启用 XPC tunnel，并提供启动入口，而非直接失败

#### Scenario: 缺 DDI 引导（iOS 17+）

- **WHEN** iOS 17+ 设备 tunnel 就绪但 DDI 未挂载
- **THEN** 提示前往「开发者工具」根 tab 挂载 DDI

#### Scenario: 缺 DDI 引导（iOS 17-，带 reload）

- **WHEN** iOS 17 以下设备 DDI 未挂载且用户触发依赖该能力的操作
- **THEN** 提示前往「开发者工具」根 tab 挂载 DDI，并提供 reload 按钮重新检查状态

#### Scenario: RSD 服务不工作引导

- **WHEN** iOS 17+ 设备 tunnel 就绪、DDI 已挂载，但目标 RSD 开发者服务不可用
- **THEN** 提示用户重新挂载 DDI
- **AND** 可附带提示用户可手动重启 XPC tunnel


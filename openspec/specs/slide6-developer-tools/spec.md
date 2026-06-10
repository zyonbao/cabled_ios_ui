# slide6-developer-tools Specification

## Purpose
TBD - created by archiving change add-developer-tools-tab-phase1. Update Purpose after archive.
## Requirements
### Requirement: 开发者工具 Tab 入口

桌面应用 SHALL 在左侧 sidebar Tab 栏提供独立的「开发者工具」Tab（`DeveloperToolsTab`）。该 Tab MUST 实现 `set_target(target)`，由主窗口在设备切换时分发；未选中设备时 MUST 显示「未选择设备」并禁用全部能力，不发起设备请求。该 Tab MUST 提供 `shutdown`，由主窗口在退出时调用以释放可能存在的常驻定位会话。所有阻塞调用 MUST 经由 `AsyncRunner` 在工作线程执行。

#### Scenario: 选中设备进入 Tab

- **WHEN** 已选中设备并进入「开发者工具」Tab
- **THEN** Tab 自动刷新并展示当前设备的 DDI 挂载状态

#### Scenario: 未选择设备

- **WHEN** 未选中任何设备
- **THEN** Tab 显示「未选择设备」，功能位禁用，不发起设备请求

### Requirement: DDI 状态栏与挂载控制

「开发者工具」Tab SHALL 在顶部展示 DDI 挂载状态（已挂载 / 未挂载）。未挂载时 SHALL 提供「挂载」按钮，点击 MUST 弹出可选挂载方式（自动按版本 / 个性化镜像(17+) / 开发者镜像(<17) / 手动选本地镜像文件）；选择手动方式时 SHALL 经文件选择器收集所需镜像文件。已挂载时 SHALL 提供「卸载」按钮。挂载 / 卸载完成后 MUST 刷新状态并据此联动功能位的可用性。iOS 17+ MUST 在状态栏提示进程 / 定位能力依赖 XPC tunnel，并提供启动入口。

#### Scenario: 未挂载时挂载

- **WHEN** DDI 未挂载，用户点击「挂载」并选择一种方式
- **THEN** 应用按该方式挂载，成功后状态更新为「已挂载」并启用功能位

#### Scenario: 已挂载时卸载

- **WHEN** DDI 已挂载，用户点击「卸载」
- **THEN** 应用卸载 DDI，状态更新为「未挂载」并禁用功能位

### Requirement: 功能位 grid 与 DDI 门控

「开发者工具」Tab SHALL 以功能位 grid 展示「进程管理」「虚拟定位」两个能力卡片（布局便于后续扩展）。DDI 未挂载时所有功能位 MUST 置为 Disabled；DDI 挂载成功后 MUST 自动 enable。

#### Scenario: 未挂载禁用

- **WHEN** DDI 未挂载
- **THEN** 进程管理、虚拟定位功能位均不可点击，并提示需先挂载 DDI

#### Scenario: 挂载后启用

- **WHEN** DDI 挂载成功
- **THEN** 进程管理、虚拟定位功能位自动变为可用

### Requirement: 进程管理界面

「进程管理」功能位 SHALL 提供进程列表展示，支持按进程名筛选（大小写不敏感）、刷新；SHALL 支持按输入的 bundle id 启动进程；SHALL 支持选中进程后 kill（kill 前 MUST 二次确认）；SHALL 支持查看选中进程的明细（只读）。MUST NOT 提供进程属性的修改能力。

#### Scenario: 查看与筛选

- **WHEN** 进入进程管理并输入筛选关键字
- **THEN** 列表按进程名过滤展示 pid 与名称

#### Scenario: 按 bundle id 启动

- **WHEN** 用户输入 bundle id 并点击启动
- **THEN** 应用启动该应用并提示新进程 pid，刷新列表

#### Scenario: kill 选中进程

- **WHEN** 用户选中一个进程并点击 kill，确认二次提示
- **THEN** 终止该进程并刷新列表

#### Scenario: 查看进程明细

- **WHEN** 用户对某进程查看明细
- **THEN** 以只读方式展示该进程的属性信息

### Requirement: 虚拟定位界面

「虚拟定位」功能位 SHALL 提供经纬度输入用于设定单点虚拟定位，并提供清除（恢复真实 GPS）入口。除单点外，SHALL 提供两种轨迹回放入口：(1) **GPX 文件回放**——经文件选择器选择 `.gpx`，可选「忽略时间戳立即跑完」与时间抖动；(2) **手动多点轨迹**——用户可增删途经点（经纬度）并设定移动速度后开始回放。轨迹回放进行中 MUST 给出明确状态提示，并 MUST 可经「清除」中止。设定 / 回放 / 清除完成后 MUST 显示明确的状态文案。

#### Scenario: 设定坐标

- **WHEN** 用户输入合法经纬度并点击设定
- **THEN** 应用设定虚拟定位，状态提示已设定

#### Scenario: GPX 文件回放

- **WHEN** 用户选择一个 `.gpx` 文件并开始回放
- **THEN** 应用沿轨迹移动并提示「正在回放轨迹」，可经清除中止

#### Scenario: 手动多点轨迹回放

- **WHEN** 用户录入 ≥2 个途经点与速度并开始回放
- **THEN** 应用按速度沿途经点平滑移动并提示回放中

#### Scenario: 清除定位

- **WHEN** 用户点击清除
- **THEN** 应用恢复真实 GPS（含中止轨迹回放），状态提示已清除


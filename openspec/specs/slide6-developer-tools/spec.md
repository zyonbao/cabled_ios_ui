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

「开发者工具」Tab SHALL 以功能位 grid 展示「进程管理」「虚拟定位」两个能力卡片（布局便于后续扩展）。功能位的可用性 MUST 由统一的设备就绪前置检查（见 `slide6-device-readiness`）驱动，采用**禁用式门控**：就绪检查未通过时对应功能位 MUST 置为 Disabled，并以 tooltip 说明缺失项（缺 tunnel / 缺 DDI / RSD 服务不工作）；全部就绪后 MUST 自动 enable。按钮态 MUST 在设备切换、tunnel 面板操作完成、DDI 状态变化时重算刷新。

#### Scenario: 未就绪禁用并 tooltip 说明

- **WHEN** 就绪检查未通过（如 DDI 未挂载、或 iOS 17+ 缺 tunnel / RSD 服务不工作）
- **THEN** 进程管理、虚拟定位功能位置为 Disabled，tooltip 说明缺失的具体前置（需挂载 DDI / 需启用 tunnel / 需重挂 DDI 或重启 tunnel）

#### Scenario: 就绪后启用

- **WHEN** 全部前置就绪
- **THEN** 进程管理、虚拟定位功能位自动变为可用

#### Scenario: 状态变化后刷新按钮态

- **WHEN** 设备切换、tunnel 启停/重启完成或 DDI 状态变化
- **THEN** 重新运行就绪检查并据结果刷新各功能位的 enabled/disabled 与 tooltip

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

### Requirement: 系统日志区块入口

「开发者工具」Tab SHALL 容纳一个独立的系统日志区块（作为可扩展 Grid 的一部分），按当前设备主版本暴露对应入口：iOS 17+ 暴露 `oslog`，iOS 17 以下暴露 `syslog`。该区块 MUST 随主窗口的设备切换刷新；未选中设备时 MUST NOT 启动任何日志流。系统日志 MUST NOT 再以独立 sidebar tab 形式存在。日志流的具体采集与渲染行为遵循 `slide6-syslog-stream` 能力。

#### Scenario: 从开发者工具进入日志区块

- **WHEN** 选中设备并进入「开发者工具」Tab 的系统日志区块
- **THEN** 依设备版本显示 oslog（17+）或 syslog（17-）入口，可开始 / 停止实时日志

#### Scenario: 设备切换刷新日志区块

- **WHEN** 用户切换所选设备
- **THEN** 日志区块停止旧设备的流并按新设备版本切换入口

### Requirement: iOS 17+ XPC tunnel 状态面板

「开发者工具」Tab 顶部的 XPC tunnel 区块 SHALL 仅对 iOS 17+ 设备展示；iOS 17 以下 MUST 隐藏。该面板 MUST 反映当前 tunnel 运行状态并据此切换控制：未启动时提供「启动」按钮；已启动时提供「停止」与「重启」按钮。三者 MUST 复用系统授权（osascript）逻辑并经 `AsyncRunner` 在工作线程执行，操作进行中 MUST 禁用相应按钮、给出状态提示。

#### Scenario: iOS 17+ 未启动 tunnel

- **WHEN** iOS 17+ 设备且 tunnel 未运行
- **THEN** 面板显示「未启动」与「启动」按钮

#### Scenario: iOS 17+ 已启动 tunnel

- **WHEN** iOS 17+ 设备且 tunnel 正在运行
- **THEN** 面板显示「已启动」与「停止」「重启」按钮

#### Scenario: iOS 17 以下隐藏面板

- **WHEN** 选中 iOS 17 以下设备
- **THEN** 不展示 XPC tunnel 状态面板

### Requirement: 状态文案不撑宽窗口

「开发者工具」Tab 底部的状态 / 错误文案 MUST NOT 因内容变长而改变窗口宽度。文案超过 3 行时 MUST 对尾部做省略（`…`）；窗口宽度变化时 MUST 按当前宽度重新计算省略。完整文案 SHOULD 可经悬浮提示（tooltip）查看。

#### Scenario: 长文案不撑宽

- **WHEN** 底部出现很长的错误文案
- **THEN** 窗口宽度不变，文案在 3 行内按尾部省略显示

#### Scenario: 改变窗口宽度后重排

- **WHEN** 用户调整窗口宽度
- **THEN** 文案按新宽度重新计算 3 行省略

### Requirement: 子功能弹窗非模态且每子功能单例

「开发者工具」的子功能窗口（进程管理 / 虚拟定位等）MUST 以非模态方式打开，MUST NOT 因某个子窗口未关闭而阻塞主界面或其他子窗口。不同子功能 SHALL 可同时各打开一个并各自独立操作。**同一子功能 MUST 至多存在一个窗口**：当该子功能窗口已打开时再次触发，应用 MUST 将已有窗口前置（raise + activate），MUST NOT 新开重复窗口。应用退出 / 设备清理时 MUST 一并关闭这些子窗口。

#### Scenario: 不同子功能可并存

- **WHEN** 用户先后打开进程管理与虚拟定位窗口
- **THEN** 两个窗口可同时存在并各自独立操作，主界面不被阻塞

#### Scenario: 同一子功能再次触发前置已有窗口

- **WHEN** 进程管理窗口已打开，用户再次点击进程管理功能位
- **THEN** 将已存在的进程管理窗口前置（raise/activate），不新开第二个窗口

#### Scenario: 退出时关闭子窗口

- **WHEN** 应用退出或设备被清理
- **THEN** 已打开的子功能窗口被一并关闭，无悬挂窗口


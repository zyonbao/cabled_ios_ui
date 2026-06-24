# slide6-developer-tools Specification

## Purpose
定义「开发者工具」页面的统一能力入口与交互约束：DDI 挂载状态与控制、iOS 17+ 的 XPC tunnel 面板、进程管理/虚拟定位/性能监控/网络监控/条件诱导能力卡、系统日志入口，以及相关门控、状态刷新和窗口行为规范。
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

iOS 17+ 下，DDI 已挂载但 XPC tunnel 未启动时，应用 MUST NOT 继续探测 `RSD/DVT` 开发者服务状态；此时 MUST 直接提示用户先启动 XPC tunnel。只有在 XPC tunnel 已启动时，才允许继续探测 DVT / RSD readiness。若 tunnel 已启动但开发者服务仍不可用，SHOULD 提示用户可重挂 DDI 或手动重启 XPC tunnel，不得强制弹窗要求立即重启。

#### Scenario: 未挂载时挂载

- **WHEN** DDI 未挂载，用户点击「挂载」并选择一种方式
- **THEN** 应用按该方式挂载，成功后状态更新为「已挂载」并启用功能位

#### Scenario: 已挂载时卸载

- **WHEN** DDI 已挂载，用户点击「卸载」
- **THEN** 应用卸载 DDI，状态更新为「未挂载」并禁用功能位

#### Scenario: 已挂载但 tunnel 未启动

- **WHEN** iOS 17+ 设备 DDI 已挂载但 XPC tunnel 未启动
- **THEN** 应用直接提示用户先启动 XPC tunnel
- **AND** 不继续探测 `RSD/DVT` 开发者服务状态

#### Scenario: tunnel 已启动但开发者服务不可用

- **WHEN** iOS 17+ 设备 DDI 已挂载、XPC tunnel 已启动，但开发者服务仍不可用
- **THEN** 应用提示用户可重挂 DDI 或手动重启 XPC tunnel
- **AND** 不弹出“是否立即重启 tunnel”的强制确认框

### Requirement: 功能位 grid 与 DDI 门控

「开发者工具」Tab SHALL 以功能位 grid 展示「进程管理」「虚拟定位」「性能监控」「网络监控」「条件诱导」五个能力卡片（布局便于后续扩展）。功能位的可用性 MUST 由统一的设备就绪前置检查（见 `slide6-device-readiness`）驱动，采用**禁用式门控**：就绪检查未通过时对应功能位 MUST 置为 Disabled，并以 tooltip 说明缺失项（缺 tunnel / 缺 DDI / RSD 服务不工作）；全部就绪后 MUST 自动 enable。按钮态 MUST 在设备切换、tunnel 面板操作完成、DDI 状态变化时重算刷新。

#### Scenario: 未就绪禁用并 tooltip 说明

- **WHEN** 就绪检查未通过（如 DDI 未挂载、或 iOS 17+ 缺 tunnel / RSD 服务不工作）
- **THEN** 进程管理、虚拟定位、性能监控、网络监控、条件诱导功能位置为 Disabled，tooltip 说明缺失的具体前置（需挂载 DDI / 需启用 tunnel / 需重挂 DDI 或重启 tunnel）

#### Scenario: 就绪后启用

- **WHEN** 全部前置就绪
- **THEN** 进程管理、虚拟定位、性能监控、网络监控、条件诱导功能位自动变为可用

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

「虚拟定位」功能位 SHALL 提供经纬度输入用于设定单点虚拟定位，并提供清除（恢复真实 GPS）入口。除单点外，SHALL 提供两种轨迹回放入口：(1) **GPX 文件回放**——经文件选择器选择 `.gpx`；(2) **手动多点轨迹**——用户可增删途经点（经纬度）并设定移动速度后开始回放。轨迹回放进行中 MUST 给出明确状态提示，并 MUST 可经「清除」中止。设定 / 回放 / 清除完成后 MUST 显示明确的状态文案。

GPX 文件回放 SHALL 提供以下时间节奏控件与联动规则：

- **时间抖动开关**：SHALL 以独立开关控制；仅开关打开时才允许设置抖动毫秒值并在回放时施加抖动，关闭时 MUST NOT 施加抖动。
- **忽略时间戳开关**：SHALL 以独立开关控制。
  - 关闭时（按时间戳回放）：MUST 禁用 GPX 的节奏方式选择及其数值输入；时间抖动开关可用。
  - 打开时（忽略时间戳）：MUST 禁用时间抖动开关与抖动数值输入（与时间抖动互斥）；MUST 提供二选一的**节奏方式**——「固定间隔（秒）」或「指定速度（m/s）」，且仅当前选中方式对应的数值输入可用、另一方式的输入禁用。
- 发起回放时，UI MUST 按当前开关与所选节奏方式向平台层传入对应入参（忽略时间戳关闭时传时间抖动值或 0；忽略时间戳打开时传所选节奏方式与其数值，并将抖动置 0）。

#### Scenario: 设定坐标

- **WHEN** 用户输入合法经纬度并点击设定
- **THEN** 应用设定虚拟定位，状态提示已设定

#### Scenario: GPX 文件回放

- **WHEN** 用户选择一个 `.gpx` 文件并开始回放
- **THEN** 应用沿轨迹移动并提示「正在回放轨迹」，可经清除中止

#### Scenario: 时间抖动开关联动

- **WHEN** 时间抖动开关关闭
- **THEN** 抖动数值输入禁用且回放不施加抖动；开关打开后抖动数值输入可用并在回放时施加

#### Scenario: 忽略时间戳关闭时禁用节奏方式

- **WHEN** 忽略时间戳开关关闭
- **THEN** 节奏方式（固定间隔 / 速度）选择与其数值输入禁用，时间抖动开关可用

#### Scenario: 忽略时间戳打开时选择节奏方式且禁用抖动

- **WHEN** 忽略时间戳开关打开
- **THEN** 时间抖动开关与抖动数值输入禁用，节奏方式可选「固定间隔」或「速度」，且仅选中方式的数值输入可用

#### Scenario: 手动多点轨迹回放

- **WHEN** 用户录入 ≥2 个途经点与速度并开始回放
- **THEN** 应用按速度沿途经点平滑移动并提示回放中

#### Scenario: 清除定位

- **WHEN** 用户点击清除
- **THEN** 应用恢复真实 GPS（含中止轨迹回放），状态提示已清除

### Requirement: 性能监控界面

「性能监控」功能位 SHALL 提供实时监控界面，并基于 `sysmontap` 展示三个图表：

- CPU 信息图表；
- 内存信息图表；
- 网络与磁盘 IO 图表。

同一图表内 SHALL 支持多条指标线，并以不同颜色区分。多线图表 SHALL 支持点击图例切换单条指标线的显示/隐藏，且 MUST 至少保留一条可见线（不允许全部隐藏）。每条趋势图的可视窗口 MUST 限制在最近 10 分钟（滚动窗口）。当采集时间超过 10 分钟时，缓存 MUST 丢弃 10 分钟之前的数据，仅保留最近 10 分钟用于绘制；折线图等可视化 MUST 仅展示该 10 分钟缓存窗口。开始采集后 MUST 提供运行状态、采样频率与最后更新时间；停止采集后 MUST 停止后台采样并保持当前可视结果。图表更新 MUST 采用限速渲染，避免高频重绘阻塞主线程。

性能监控采样频率默认 SHOULD 为 `500ms`，允许范围 MUST 为 `200ms~2000ms`。控制语义 MUST 明确：Pause 仅暂停渲染、Stop 停止采样并回收任务、Clear 清空可视缓存。内存图表坐标轴上限 MUST 绑定设备物理内存。部分子线不可用时 MUST 以隐藏方式降级，并保持其余子线正常工作。

#### Scenario: 最近 10 分钟趋势窗口

- **WHEN** 性能监控持续采样超过 10 分钟
- **THEN** 折线图仅展示最近 10 分钟的数据窗口

#### Scenario: 启停采集

- **WHEN** 用户点击开始 / 停止采集
- **THEN** 应用分别启动 / 停止后台采样线程并更新运行状态文案

### Requirement: 网络监控界面

「网络监控」能力 SHALL 作为「开发者工具」Tab 内的功能卡片入口，点击后进入同一 Tab 下的 Network Monitor 子面板，MUST NOT 新增独立 sidebar Tab。子面板顶部 MUST 提供状态条，至少展示采集状态（Idle/Running/Paused）与缓存占用，并提供 Start/Stop 控制。主内容区 SHOULD 使用三栏布局：左侧进程列表（TopN + bundle id 搜索）、中间连接流列表（时间/协议/方向/本地-远端/字节）、右侧详情与趋势图（Rx/Tx 速率、连接数、错误数）。网络缓存 MUST 最多保留最近 10 分钟数据，超过 10 分钟的历史记录 MUST 丢弃；趋势图等可视化 MUST 仅展示该 10 分钟窗口并实时显示当前上下载速度；连接流字段按可获取能力降级显示。

网络监控 MUST 提供高频控制栏：Start/Stop、Pause、Clear、Auto-scroll、Export（CSV/JSON）；Export 能力 SHOULD 预留与后续 PCAP 关联扩展点。过滤器 MUST 支持按进程、协议（TCP/UDP）、方向（in/out）、host/port、时间窗口、关键词筛选，并支持「仅显示活跃连接」。

网络采集与渲染 MUST 采用后台线程采集 + 主线程限速渲染；UI 刷新 SHOULD 采用 200~500ms 批量节流。实现 MUST 使用 ring buffer 控制最大记录数，避免高吞吐场景下内存增长和 UI 卡顿。

网络监控后台采集线程/进程 MUST 与 Network Monitor 子面板窗口生命周期绑定：点击 Start 时创建并启动；点击 Stop 时停止并回收；用户关闭该子面板窗口时 MUST 自动停止并回收，MUST NOT 遗留孤儿线程/进程。

网络监控采样频率默认 SHOULD 为 `500ms`，允许范围 MUST 为 `200ms~2000ms`。Export（CSV/JSON）默认 MUST 导出当前过滤条件下、最近 10 分钟缓存窗口数据。字段缺失或部分能力不可用时 MUST 明确显示 `unsupported`/`unknown`，且不得中断整场会话。

#### Scenario: 趋势与实时速率

- **WHEN** 网络监控正在运行
- **THEN** 趋势视图实时更新上/下行折线，并显示当前上下载速度

#### Scenario: 连接视图切换

- **WHEN** 用户切换到连接视图
- **THEN** 应用展示当前可获取的连接信息，并可按进程筛选

#### Scenario: 功能卡片进入子面板

- **WHEN** 用户在「开发者工具」Tab 点击网络监控功能卡片
- **THEN** 进入同一 Tab 下的 Network Monitor 子面板（非独立新 Tab）

#### Scenario: 顶部状态条与控制栏

- **WHEN** 用户查看 Network Monitor 子面板
- **THEN** 顶部状态条显示采集状态与缓存占用，且控制栏提供 Start/Stop、Pause、Clear、Auto-scroll、Export 操作

#### Scenario: 关闭窗口自动回收采集任务

- **WHEN** Network Monitor 子面板窗口被关闭
- **THEN** 绑定的后台采集线程/进程自动停止并回收，不残留孤儿任务

### Requirement: 条件诱导界面

「条件诱导」功能位 SHALL 提供条件模板或参数化入口，用于设置并应用设备诱导条件（如弱网、温度/功耗相关条件，按底层可用能力呈现）。界面 MUST 显示当前诱导状态（未启用 / 已启用 + 条件摘要）；用户 MUST 可开始诱导与结束诱导。开始诱导前 SHOULD 显示条件确认；结束诱导后 MUST 刷新状态并清理会话资源。

#### Scenario: 开始诱导

- **WHEN** 用户选择条件并点击开始
- **THEN** 应用应用该条件并显示「已启用」状态及条件摘要

#### Scenario: 结束诱导

- **WHEN** 条件诱导已启用且用户点击结束
- **THEN** 应用停止诱导并恢复「未启用」状态

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

tunnel 状态变化后，面板标签、按钮组，以及依赖 tunnel 的功能位门控 MUST 立即联动刷新，不得要求用户再手动点击一次“刷新状态”才能恢复正确 UI。

#### Scenario: iOS 17+ 未启动 tunnel

- **WHEN** iOS 17+ 设备且 tunnel 未运行
- **THEN** 面板显示「未启动」与「启动」按钮

#### Scenario: iOS 17+ 已启动 tunnel

- **WHEN** iOS 17+ 设备且 tunnel 正在运行
- **THEN** 面板显示「已启动」与「停止」「重启」按钮

#### Scenario: 停止 tunnel 后立即刷新面板

- **WHEN** 用户点击「停止」且 tunnel 已停止
- **THEN** 面板立即更新为「未启动」状态，并显示「启动」按钮
- **AND** 依赖 tunnel 的功能位门控与状态提示同步刷新
- **AND** 不要求用户再手动点击“刷新状态”

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

### Requirement: 状态行间距与功能位卡片的视觉呈现

「开发者工具」Tab 顶部 DDI 状态行与 XPC Tunnel 状态行之间的纵向间距 SHALL 收紧、自然，且与该 Tab 内其它行的间距保持一致，MUST NOT 因 Tunnel 行容器的额外内边距而显著大于普通行间距。功能位卡片（进程管理 / 虚拟定位 / 系统日志）SHALL 将标题与描述分层呈现：标题 MUST 使用更突出的字体（更大或加粗），描述 MUST 使用更弱的次级字体（更小或次要色），使两者可清晰区分。该要求仅约束视觉呈现，MUST NOT 改变功能位的门控、点击行为与其它既有交互。

#### Scenario: 状态行间距收紧一致

- **WHEN** iOS 17+ 设备进入「开发者工具」Tab（DDI 行与 XPC Tunnel 行同时可见）
- **THEN** 两行之间的纵向间距收紧自然，与该 Tab 内普通行间距一致，无明显多余空隙

#### Scenario: 隐藏 Tunnel 行时不受影响

- **WHEN** 选中 iOS 17 以下设备（XPC Tunnel 行隐藏）
- **THEN** DDI 状态行与下方内容的间距仍自然一致，不出现因隐藏容器残留的异常空隙

#### Scenario: 卡片标题与描述具有视觉层级

- **WHEN** 查看功能位卡片
- **THEN** 标题以更突出的字体呈现、描述以更弱的次级字体呈现，二者可清晰区分

#### Scenario: 视觉调整不改变交互

- **WHEN** 功能位按既有门控处于可用 / 禁用态并被点击
- **THEN** 点击与禁用行为同改造前一致，仅文字的视觉层级发生变化

### Requirement: 轨迹回放实时进度展示

「虚拟定位」界面 SHALL 在轨迹回放（GPX / 手动）开始后以定时器轮询平台层进度，并实时刷新状态文案。轮询 MUST NOT 阻塞 UI 线程（经 `AsyncRunner` 在工作线程执行查询）。当 `current < total` 时状态 MUST 显示「正在回放轨迹（当前/总 个点）…」；当 `current >= total`（且 total>0）时 MUST 显示「已回放完成（总/总 个点）…」并停止轮询。用户点击清除、窗口关闭、或查询返回设备不可用时 MUST 停止轮询。该展示仅作用于轨迹回放，单点设定不触发轮询。

#### Scenario: 回放中实时刷新进度

- **WHEN** 轨迹回放进行中
- **THEN** 状态文案随轮询刷新为「正在回放轨迹（当前/总 个点）…」

#### Scenario: 回放完成提示

- **WHEN** 所有轨迹点已应用
- **THEN** 状态显示「已回放完成（总/总 个点）…」并停止轮询

#### Scenario: 关闭或清除停止轮询

- **WHEN** 用户清除定位或关闭虚拟定位窗口
- **THEN** 停止进度轮询


# dvt-network-op Specification

## Purpose
定义基于 DVT instruments 的网络监控能力：提供上/下行速率趋势、连接流与连接详情展示、实时速率、三栏子面板交互与高吞吐稳定性约束。

## Requirements
### Requirement: 网络采样会话

平台层 SHALL 提供 `start_network_session(target, sample_interval_ms)` 与 `stop_network_session(target)`。会话启动后 MUST 产出两类数据流：`throughput samples`（按时间片的上/下行速率）与 `connection events/snapshots`（连接相关信息，字段按可用能力降级）。采样 MUST 在后台线程执行；重复启动 MUST 先停旧会话再起新会话。

网络采样后台线程/进程 MUST 与 Network Monitor 子面板窗口生命周期绑定：`start_network_session` 创建并启动；`stop_network_session` 停止并回收；窗口关闭时 MUST 自动停止并回收。实现 MUST NOT 留下孤儿线程/进程持续采集。

采样频率 `sample_interval_ms` 默认值 SHOULD 为 `500ms`；允许范围 MUST 为 `200ms~2000ms`。超出范围 MUST 返回可读参数错误并拒绝启动。

#### Scenario: 启动后返回会话状态

- **WHEN** 用户开始网络监控
- **THEN** 返回 `{ok, data:{session_id, started_at}}`，并开始推送速率与连接数据

#### Scenario: 关闭窗口自动停止采样

- **WHEN** 用户关闭 Network Monitor 子面板窗口
- **THEN** 该窗口绑定的网络采样线程/进程自动停止并被回收

#### Scenario: 非法采样频率

- **WHEN** 用户提交小于 200ms 或大于 2000ms 的采样间隔
- **THEN** 返回可读参数错误并拒绝启动网络采样

### Requirement: 入口与子面板布局

UI 层 SHALL 将网络监控作为开发者工具页面内的子面板能力，而非独立 sidebar Tab。子面板 MUST 包含顶部状态条与主内容区；顶部状态条 MUST 展示 `Idle/Running/Paused` 状态与缓存占用。主内容区 SHOULD 采用三栏布局：

- 左栏：进程列表（TopN）与 bundle id 搜索；
- 中栏：连接流列表（时间、协议、方向、本地-远端、字节）；
- 右栏：选中对象详情与趋势图（Rx/Tx 速率、连接数、错误数）。

#### Scenario: 子面板三栏展示

- **WHEN** 用户进入网络监控子面板
- **THEN** 显示三栏信息并可联动选择进程与连接项

### Requirement: 趋势视图与实时速率

UI 层 SHALL 在趋势视图中以折线图展示上/下行速率，并实时显示当前上下载速度。趋势图 MUST 使用最近 10 分钟滚动窗口；MAY 支持 1m/5m/10m 快捷范围切换（默认 10m）。网络缓存最多保留 10 分钟数据，超过 10 分钟的历史数据 MUST 丢弃；窗口外数据 MUST 不参与实时绘图。

#### Scenario: 趋势滚动窗口

- **WHEN** 网络监控连续运行超过 10 分钟
- **THEN** 折线图自动滚动，仅保留最近窗口

#### Scenario: 超时网络数据淘汰

- **WHEN** 网络采样数据累计超过 10 分钟
- **THEN** 最旧数据被丢弃，缓存与图表均仅保留最近 10 分钟

#### Scenario: 实时速率显示

- **WHEN** 新速率样本到达
- **THEN** 界面更新当前上下载速度数值与趋势曲线

### Requirement: 高级控制栏与过滤器

UI 层 MUST 提供控制栏操作：Start、Stop、Pause、Clear、Auto-scroll、Export（CSV/JSON）。Pause MUST 仅暂停视图刷新，不中断后台采样；Stop MUST 停止会话采样；Clear MUST 清空当前视图缓存（不改变会话可按实现选择）。过滤器 MUST 支持进程、协议（TCP/UDP）、方向（in/out）、host/port、时间窗口、关键词与仅活跃连接开关。

控制语义进一步约束：`Stop` 后 MUST 回收后台采样任务并保留最后一次有效快照用于只读排查；`Clear` MUST 清空可视缓存并重置当前视图；`Pause` 不得影响后台样本写入缓存。

#### Scenario: Pause 保持采样

- **WHEN** 用户点击 Pause
- **THEN** 视图停止自动滚动与刷新，但后台采样继续

#### Scenario: 仅活跃连接过滤

- **WHEN** 用户启用“仅显示活跃连接”
- **THEN** 连接流列表仅展示活跃连接记录

### Requirement: 导出边界与一致性

`Export`（CSV/JSON）MUST 明确导出边界：默认导出“当前过滤条件下、当前缓存窗口（最多最近 10 分钟）”的数据。导出任务 SHOULD 在后台执行，避免阻塞主线程；导出失败 MUST 返回可读错误并保留现有 UI 状态。格式字段 SHOULD 稳定（时间戳、进程、协议、方向、本地端点、远端端点、字节数、速率样本）。

#### Scenario: 导出当前过滤窗口

- **WHEN** 用户应用过滤器后执行 Export
- **THEN** 导出文件仅包含过滤后、最近 10 分钟窗口内的数据

### Requirement: 连接信息视图

UI 层 SHALL 提供连接信息视图，展示当前可获取的连接信息（如进程、远端地址、连接状态、累计收发字节）；字段不可用时 MUST 明确显示降级状态而非空白误导。该视图 SHOULD 支持按进程筛选，并 SHOULD 支持从趋势图点击时间点联动到对应时刻连接快照。

#### Scenario: 按进程筛选连接

- **WHEN** 用户输入进程筛选条件
- **THEN** 仅展示匹配进程的连接信息

### Requirement: 网络能力降级与错误语义

当部分连接字段不可用或采样源返回缺失字段时，UI MUST 以 `unsupported` 或 `unknown` 明确标注，不得以空白掩盖。单条记录解析失败 MUST 被隔离处理并记录可读错误，MUST NOT 导致整场监控会话终止。

#### Scenario: 部分字段缺失降级

- **WHEN** 某连接记录缺少远端端口或协议信息
- **THEN** 该字段显示 `unknown`/`unsupported`，其余记录与趋势继续正常展示

### Requirement: 可操作性与渲染稳定性

网络监控 UI SHOULD 支持趋势点到连接快照的联动，以便定位峰值时刻。高频采样下 MUST 采用后台线程采集 + 主线程限速渲染；UI 刷新 SHOULD 使用 200~500ms 批量节流。实现 MUST 使用 ring buffer 控制最大记录数，避免高吞吐导致内存膨胀和主线程阻塞。

#### Scenario: 暂停滚动仍持续采样

- **WHEN** 用户开启暂停滚动
- **THEN** 图表停止自动跳到最新点，但后台采样不中断

#### Scenario: ring buffer 达上限

- **WHEN** 记录数达到 ring buffer 上限
- **THEN** 应丢弃最旧记录并保留最新窗口，UI 持续可交互且无明显卡顿


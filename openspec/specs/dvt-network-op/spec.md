# dvt-network-op Specification

## Purpose
定义基于 DVT Networking instrument（`com.apple.instruments.server.services.networking`）的网络监控能力：以事件流方式采集接口/连接/连接更新事件，聚合为连接流明细与上/下行速率趋势，提供三栏子面板交互、过滤、导出与高吞吐稳定性约束。

> 实测约束（pymobiledevice3 `NetworkMonitor`）：
> - 采集为**事件推送式**：`startMonitoring` 后设备持续 push 事件，`stopMonitoring` 结束；**没有设备侧采样间隔**，也没有会话 id。
> - 事件三类：`InterfaceDetectionEvent`(interface_index,name)、`ConnectionDetectionEvent`(local/remote 地址、interface_index、**pid**、serial_number、kind)、`ConnectionUpdateEvent`(rx/tx packets、rx/tx bytes、rx_dups、tx_retx、min_rtt、avg_rtt、connection_serial、time)。
> - 连接明细 MUST 以 `connection_serial` 关联 detection 与后续 update。
> - **`ConnectionUpdateEvent` 的 rx/tx 字节·包·重传·重复为「每区间增量」（非累计）**；每条连接的**首帧 update 携带监控前的历史累计**（可达数百 MB）。实时吞吐 MUST 跳过首帧（作为基线），仅累加后续增量，否则会出现首帧巨大假尖峰。
> - **进程归属不可用**：经真机确认 `pid` 恒为 `-2`（现代 iOS 隐私限制），sysmontap 也无 per-process 网络字节——故 MUST NOT 提供进程维度（无进程列表/进程过滤）。
> - 协议 `kind`：经真机确认 **1=TCP、2=UDP**（其余值标 `unknown`）；方向无显式字段，只能由本端发起等启发式推导（不可判定标 `unknown`）。
> - 端点仅 **IP 地址**（无反向 DNS）；大量连接 remote 为未指定/`port=0`（监听或未建连 socket），「仅活跃连接」过滤用于聚焦真实流。

## Requirements
### Requirement: 网络监控会话

平台层 SHALL 提供 `open_network_stream(target)`：成功返回与 Network Monitor 子面板生命周期绑定的句柄（暴露事件 `queue` 与 `close()`），失败返回可读错误信封。采集 MUST 在后台线程/事件循环执行（`startMonitoring`），不阻塞 UI；`close()` MUST `stopMonitoring` 并回收连接。句柄 MUST 与子面板窗口生命周期绑定：打开/Start 时创建，Stop/关闭窗口时回收；实现 MUST NOT 留下持有连接的孤儿任务。

采集为事件推送式，无设备侧采样间隔；UI 渲染/速率聚合 MAY 采用可配置节流间隔（如 200~500ms 批量刷新），该间隔仅影响前端刷新与速率换算窗口，MUST NOT 被当作设备采样频率，也 MUST NOT 因该值非法而拒绝启动会话。

#### Scenario: 启动后持续推送事件

- **WHEN** 用户开始网络监控
- **THEN** 平台层返回事件流句柄，并开始推送接口/连接/连接更新事件

#### Scenario: 关闭窗口自动停止采集

- **WHEN** 用户关闭 Network Monitor 子面板窗口
- **THEN** 句柄 `stopMonitoring` 并断开连接，后台采集停止并回收，无残留孤儿任务

### Requirement: 事件模型与连接聚合

平台层 SHALL 把原始事件归一化为可视化输入：

- **连接流**：以 `connection_serial` 为键，由 `ConnectionDetectionEvent` 建立条目（local/remote `IP:port`、interface、协议），由后续 `ConnectionUpdateEvent` 的每区间增量累加 rx/tx 字节与包数、重传/重复计数（rtt 取最新）；每条连接首帧为历史基线；
- **吞吐速率**：由各连接 update 的每区间增量按时间聚合（Σ rx 增量 / Δt、Σ tx 增量 / Δt，**排除首帧历史基线**），形成上/下行速率时间序列；
- **聚合分组**：MUST 提供按「远端 IP（host）/ 接口（interface）」的聚合（按字节/连接数 TopN），用于左栏导航（替代不可用的进程维度）。

字段映射 MUST 遵循真实能力并对缺失项降级：

- 协议 MUST 由 `kind` 推导（**1=TCP、2=UDP**，其余 `unknown`）；
- 方向（in/out）MUST 标注为推导值（如本端发起=outbound），无法判定时标 `unknown`；
- 远端/本端 MUST 展示为 `IP:port`（不做反向 DNS）；
- 「错误」MUST 定义为连接的 `tx_retx`（重传）/`rx_dups`（重复），并据此统计连接级错误计数；
- 进程归属不可用（`pid=-2`）：MUST NOT 依赖 pid，也 MUST NOT 提供进程列表/进程过滤。

#### Scenario: detection 与 update 聚合

- **WHEN** 同一连接先后产生 detection 与多次 update 事件
- **THEN** 连接流以 `connection_serial` 聚合为单条记录，并随 update 累加字节与速率

#### Scenario: 协议/方向无法判定

- **WHEN** 某连接的 `kind` 非 1/2 或方向无法推导
- **THEN** 对应字段显示 `unknown`，该记录其余字段与趋势继续正常展示

### Requirement: 入口与子面板布局

UI 层 SHALL 将网络监控作为开发者工具页面内的子面板能力，而非独立 sidebar Tab。子面板 MUST 包含顶部状态条与主内容区；顶部状态条 MUST 展示 `Idle/Running/Paused` 状态与缓存占用。主内容区 SHOULD 采用三栏布局：

- 左栏：按「远端 IP（host）/ 接口」聚合的 TopN（按字节/连接数）与 `IP:port` 搜索（进程维度不可用，故不提供进程列表）；
- 中栏：连接流列表（时间、协议、方向、本地-远端 `IP:port`、字节）；
- 右栏：选中对象详情与趋势图（Rx/Tx 速率、连接数、错误数）。

#### Scenario: 子面板三栏展示

- **WHEN** 用户进入网络监控子面板
- **THEN** 显示三栏信息，左栏按远端/接口聚合，点击联动中栏连接列表与右栏趋势

### Requirement: 趋势视图与实时速率

UI 层 SHALL 在趋势视图中以折线图展示由连接 update 聚合得到的上/下行速率，并实时显示当前上下载速度。趋势图 MUST 使用最近 10 分钟滚动窗口；MAY 支持 1m/5m/10m 快捷范围切换（默认 10m）。缓存最多保留 10 分钟数据，超过 10 分钟的历史数据 MUST 丢弃；窗口外数据 MUST 不参与实时绘图与导出。

#### Scenario: 趋势滚动窗口

- **WHEN** 网络监控连续运行超过 10 分钟
- **THEN** 折线图自动滚动，仅保留最近窗口

#### Scenario: 实时速率显示

- **WHEN** 新的连接 update 到达并完成增量聚合
- **THEN** 界面更新当前上下载速度数值与趋势曲线

### Requirement: 高级控制栏与过滤器

UI 层 MUST 提供控制栏操作：Start、Stop、Pause、Clear、Auto-scroll、Export（CSV/JSON）。`Pause` MUST 仅暂停视图刷新/自动滚动而不中断后台采集；`Stop` MUST `stopMonitoring` 并回收任务，SHOULD 保留最后一次有效快照用于只读排查；`Clear` MUST 清空可视缓存并重置当前视图。过滤器 MUST 支持协议（TCP/UDP/unknown）、host/port（`IP:port` 子串）、时间窗口、关键词与「仅活跃连接」开关；方向（in/out）过滤 MAY 提供（基于推导值）。进程过滤不提供（进程归属不可用）。

#### Scenario: Pause 保持采集

- **WHEN** 用户点击 Pause
- **THEN** 视图停止自动滚动与刷新，但后台采集继续写入缓存

#### Scenario: 仅活跃连接过滤

- **WHEN** 用户启用「仅显示活跃连接」
- **THEN** 连接流列表仅展示近期有 update 的活跃连接

### Requirement: 导出边界与一致性

`Export`（CSV/JSON）MUST 明确导出边界：默认导出「当前过滤条件下、当前缓存窗口（最多最近 10 分钟）」的数据。导出任务 SHOULD 在后台执行，避免阻塞主线程；导出失败 MUST 返回可读错误并保留现有 UI 状态。字段 SHOULD 稳定（时间戳、协议、方向、本地端点、远端端点、接口、累计字节、速率样本）。PCAP 文件级导出本阶段不实现，SHOULD 预留与速率/连接时间窗对齐的扩展位。

#### Scenario: 导出当前过滤窗口

- **WHEN** 用户应用过滤器后执行 Export
- **THEN** 导出文件仅包含过滤后、最近 10 分钟窗口内的数据

### Requirement: 网络能力降级与错误语义

当部分连接字段不可用或事件缺失字段时，UI MUST 以 `unknown`/`unsupported` 明确标注，不得以空白掩盖。单条事件解析失败 MUST 被隔离处理并记录可读错误，MUST NOT 导致整场监控会话终止。

#### Scenario: 部分字段缺失降级

- **WHEN** 某连接缺少协议、方向或远端端口信息
- **THEN** 对应字段显示 `unknown`/`unsupported`，其余记录与趋势继续正常展示

### Requirement: 可操作性与渲染稳定性

网络监控 UI SHOULD 支持趋势点到连接快照的联动以定位峰值时刻。高频事件下 MUST 采用后台采集 + 主线程限速渲染；UI 刷新 SHOULD 使用 200~500ms 批量节流。实现 MUST 使用 ring buffer 控制连接/样本最大记录数；后台事件队列 MUST 设上限并在溢出时丢弃最旧事件，避免高吞吐导致内存膨胀和主线程阻塞。

#### Scenario: 暂停滚动仍持续采集

- **WHEN** 用户开启暂停滚动
- **THEN** 图表停止自动跳到最新点，但后台采集不中断

#### Scenario: ring buffer / 队列达上限

- **WHEN** 记录或事件队列达到上限
- **THEN** 丢弃最旧数据并保留最新窗口，UI 持续可交互且无明显卡顿

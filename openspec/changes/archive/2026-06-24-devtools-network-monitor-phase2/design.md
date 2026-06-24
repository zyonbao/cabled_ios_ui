## Context

当前项目的性能监控已经建立了可复用的模式：`toolkit_api` 提供 open stream，`device.py` 在后台 loop 采样，UI 对话框按 10 分钟窗口渲染并做速率换算。网络监控可沿用同一套“后台采样 + 主线程限速渲染 + 生命周期绑定”的架构，但需要增加连接流模型、过滤器和导出边界控制。

目标能力由 `dvt-network-op` 和 `slide6-developer-tools` 两处 spec 已定义：Network Monitor 作为开发者工具子面板，具备状态条、三栏布局、控制栏、过滤器、10 分钟窗口和降级语义。

## 源码实测约束（pymobiledevice3 `NetworkMonitor`）

- 采集为**事件推送式**：`startMonitoring` 后持续 push、`stopMonitoring` 结束；**无设备侧采样间隔、无会话 id**。与 Performance（sysmontap 按间隔出样）不同——「采样频率 200~2000ms」不适用于网络，只能作为 UI 渲染/速率聚合节流。
- 事件三类：`InterfaceDetectionEvent`(index,name)、`ConnectionDetectionEvent`(local/remote 地址、interface、**pid**、serial、kind)、`ConnectionUpdateEvent`(rx/tx packets、rx/tx bytes、rx_dups、tx_retx、min/avg rtt、connection_serial、time)。
- 连接明细 MUST 以 `connection_serial` 关联 detection 与后续 update；吞吐速率由各连接 update 的字节增量聚合得到（无接口级字节计数流）。
- 真机抓样已确认（00008130，~12s/96 连接）：协议 `kind` **1=TCP、2=UDP**；**`pid` 恒为 -2 → 进程归属不可用**；大量连接 remote 为 `port=0`（监听/未建连）；端点仅 IP（无反向 DNS）。故**取消进程维度**，左栏改为按「远端 IP/接口」聚合 TopN；方向仍为启发式推导（不可判定 `unknown`）。

## Goals / Non-Goals

**Goals**

- 在开发者工具内落地 Network Monitor 子面板（不新增独立侧边 Tab）。
- 提供可控网络采样会话（Start/Stop/Pause/Clear）并与窗口生命周期强绑定。
- 同时展示趋势数据与连接流明细，支持高频过滤与导出。
- 保持高吞吐下 UI 稳定（批量刷新 + ring buffer + 10 分钟裁剪）。

**Non-Goals**

- 本阶段不实现 PCAP 抓包文件级分析（只预留关联扩展点）。
- 不引入新的外部可执行依赖或系统服务安装步骤。
- 不改动已上线的 Performance Monitor 交互语义。

## Decisions

### 决策 1：事件流句柄复用 Performance 的生命周期范式（但不沿用采样间隔语义）

平台层新增 `open_network_stream(target)` 返回句柄，句柄暴露事件 `queue` + `close()`；UI 定时 drain 队列做批量渲染。复用现有后台 loop + 线程生命周期 + 错误处理范式，降低心智成本与回归风险。**关键差异**：网络是事件推送、无设备采样间隔，故 open **不接受设备 interval、不做频率校验**；UI 侧的 200~500ms 仅用于渲染节流与速率聚合窗口。

### 决策 1b：连接以 `connection_serial` 聚合 + 按远端/接口分组（无进程维度）

后台把 detection 事件建连接条目、update 事件按 `connection_serial` 累加；并维护按「远端 IP / 接口」的聚合 TopN 供左栏导航（替代不可用的进程维度）。协议由 `kind` 推导（1=TCP/2=UDP，其余 unknown）、方向由本端发起等启发式推导（无法判定 unknown）。**不做 pid/进程富化**——真机确认 pid 恒为 -2。

### 决策 1c：后台事件队列设上限，溢出丢最旧

`NetworkMonitor` 的事件为推送且可能突发（连接风暴），后台 drain 与 UI 渲染都可能跟不上。句柄侧事件队列 MUST 有界（溢出丢最旧），与 UI 的 ring buffer/10 分钟裁剪共同防止内存与卡顿。

### 决策 2：三栏布局按“进程 -> 连接 -> 详情趋势”单向钻取

左栏提供进程筛选，驱动中栏连接列表；中栏选中连接后右栏展示趋势与详情。原因是用户反馈网络排障优先从进程定位，再落到连接粒度，最后看趋势。

### 决策 3：导出边界固定为“当前过滤条件 + 当前 10 分钟窗口”

`Export CSV/JSON` 仅导出当前过滤后的缓存窗口，避免导出数据和屏幕认知不一致。原因是可解释性强，也便于后续与 PCAP 时间窗对齐。

### 决策 4：缺失字段按 `unsupported/unknown` 标注，不抛弃整条连接

即使部分字段缺失，也保留连接记录并在字段位标注降级值。原因是网络流里字段缺失常见，直接丢记录会导致统计失真。

## Risks / Trade-offs

- 高吞吐/连接风暴时事件与连接列表暴涨：后台有界队列（溢出丢最旧）+ ring buffer + 批量渲染节流，控制内存和 UI 帧率。
- 过滤器组合过多可能导致查询慢：先做内存级过滤，必要时增加预索引。
- 不同设备字段差异会影响展示一致性：统一降级语义并在 tooltip 说明字段来源。
- 方向推导仍为不确定项：不可判定一律降级 `unknown`，避免误导。（`kind`→协议、pid 可用性已真机确认。）

## Migration Plan

1. ✅ **真机字段确认（已完成）**：`NetworkMonitor` 抓样确认 `kind` 1=TCP/2=UDP、`pid` 恒为 -2（进程维度取消）、大量 remote port=0（需「仅活跃」过滤）。
2. 打通平台层事件流句柄与最小数据模型（连接按 serial 聚合 + 吞吐速率聚合 + 远端/接口聚合 TopN + 有界队列）。
3. 落地 UI 子面板和控制栏，完成生命周期绑定。
4. 增加过滤器、导出、Auto-scroll 与降级标注。
5. 真机压测高吞吐场景，调优刷新间隔与缓存/队列上限。


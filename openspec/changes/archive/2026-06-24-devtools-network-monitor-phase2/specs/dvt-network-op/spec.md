## MODIFIED Requirements

### Requirement: 网络监控会话

平台层 SHALL 提供 `open_network_stream(target)`：成功返回与 Network Monitor 子面板生命周期绑定的句柄（暴露事件 `queue` 与 `close()`），失败返回可读错误信封。采集为事件推送式（`startMonitoring`/`stopMonitoring`），在后台执行、不阻塞 UI；`close()` MUST `stopMonitoring` 并回收。采集**没有设备侧采样间隔**：UI 渲染/速率聚合 MAY 用可配置节流（如 200~500ms），但 MUST NOT 当作设备采样频率、MUST NOT 因其非法而拒绝启动。句柄 MUST 与子面板窗口生命周期绑定：Start 创建、Stop 回收、关闭窗口自动停止，MUST NOT 残留孤儿任务。

#### Scenario: 关闭窗口自动停止网络采集

- **WHEN** 用户关闭 Network Monitor 子面板
- **THEN** 句柄 `stopMonitoring` 并断开，后台采集被停止并回收
- **AND** 后续不会残留孤儿线程/进程继续采集

### Requirement: 事件模型与连接聚合

平台层 SHALL 把 `NetworkMonitor` 的接口/连接/连接更新事件归一化为连接流（以 `connection_serial` 关联 detection 与 update）与上/下行速率（由连接 update 的字节增量按时间聚合），并提供按「远端 IP / 接口」聚合的 TopN 用于左栏导航。字段映射 MUST 遵循真实能力并降级：协议由 `kind` 推导（**1=TCP、2=UDP**，其余 `unknown`）；方向为推导值（未知 `unknown`）；端点展示 `IP:port`（无反向 DNS）；错误定义为 `tx_retx`/`rx_dups`。**进程归属不可用**（经真机确认 `pid` 恒为 `-2`）：MUST NOT 依赖 pid，也 MUST NOT 提供进程列表/进程过滤。

#### Scenario: detection 与 update 聚合

- **WHEN** 同一连接先后产生 detection 与多次 update
- **THEN** 连接流以 `connection_serial` 聚合为单条记录，并随 update 累加字节与速率

### Requirement: 趋势视图与实时速率

Network Monitor MUST 展示由连接 update 聚合得到的 `Rx/Tx` 速率趋势与连接/错误统计，连接区展示时间、协议、方向、本地-远端 `IP:port` 与字节。展示窗口 MUST 限制在最近 10 分钟，超出窗口数据 MUST 立即淘汰、不参与绘图与导出。

#### Scenario: 超过 10 分钟自动淘汰旧数据

- **WHEN** 网络监控持续超过 10 分钟
- **THEN** 视图仅保留最近 10 分钟数据，超时样本不再参与绘图与导出

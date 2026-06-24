## MODIFIED Requirements

### Requirement: 网络采样会话

网络监控 SHALL 提供可持续采样会话，支持 `Start / Stop / Pause / Clear`。会话采样 MUST 在后台执行，并与 Network Monitor 子面板窗口生命周期绑定：Start 创建、Stop 回收、关闭窗口自动停止。采样频率默认 SHOULD 为 `500ms`，允许范围 MUST 为 `200ms~2000ms`。

#### Scenario: 关闭窗口自动停止网络采样

- **WHEN** 用户关闭 Network Monitor 子面板
- **THEN** 后台采样会话被自动停止并回收
- **AND** 后续不会残留孤儿线程/进程继续采集

### Requirement: 趋势与连接展示

Network Monitor MUST 提供趋势与连接信息的并行展示能力：趋势区域展示 `Rx/Tx` 速率与连接/错误统计，连接区域展示时间、协议、方向、本地-远端与字节。展示窗口 MUST 限制在最近 10 分钟，超出窗口数据 MUST 立即淘汰。

#### Scenario: 超过 10 分钟自动淘汰旧数据

- **WHEN** 网络采样持续超过 10 分钟
- **THEN** 视图仅保留最近 10 分钟数据
- **AND** 超时历史样本不再参与绘图与导出

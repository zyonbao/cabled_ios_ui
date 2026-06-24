## ADDED Requirements

### Requirement: PCAP 抓包界面

「开发者工具」Tab SHALL 提供「PCAP 抓包」功能卡片并打开子面板（非独立 sidebar Tab）。（**状态：⏸ DEFERRED** — 实现暂缓，待 iOS 17/18 设备验证 pcapd 可用性；iOS 26 上被设备拒绝。）该能力为 lockdown 服务，**门控仅需 tunnel（iOS 17+），不需要 DDI**。子面板 MUST 提供：Start/Stop、进程(comm)/接口过滤、上限设置（包数 / 文件大小 / 时长，任一达到自动停）、状态条（包数 / 字节 / 时长 / 落盘路径）、以及滚动「最近 N 包」摘要表（时间 / 进程 / pid / 接口 / 协议族 / 长度）。开始抓包时 MUST 选择 `.pcap` 落盘路径；落盘文件 MUST 可被 Wireshark 打开。**不做逐层协议解析。** UI MUST 明确提示抓包仅本地落盘、注意隐私合规。采集 MUST 与窗口生命周期绑定，关闭窗口自动停止并关闭文件。

#### Scenario: 抓包到文件并查看摘要

- **WHEN** 用户选择 `.pcap` 路径并开始抓包
- **THEN** 状态条实时更新（包数/字节/时长），摘要表滚动展示最近 N 包，停止后文件可被 Wireshark 打开

#### Scenario: 关闭窗口自动停止

- **WHEN** PCAP 子面板窗口被关闭
- **THEN** 抓包自动停止并 flush 关闭文件，无残留采集任务

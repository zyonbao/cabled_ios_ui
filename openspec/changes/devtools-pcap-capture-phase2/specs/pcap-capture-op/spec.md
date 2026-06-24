## ADDED Requirements

### Requirement: 抓包会话与落盘

平台层 SHALL 提供 `open_pcap_stream(target, process, interface, out_path, limits)`：基于 `pcapd`（lockdown 服务，iOS 17+ 经 tunnel，**不需要 DDI**）抓包，边抓边经 `write_to_pcap` 写入 `out_path`（pcapng，Wireshark 可读）。采集 MUST 在后台执行、不阻塞 UI；可按进程（`comm`）/接口过滤。上限（最大包数 / 最大文件大小 / 最长时长）任一达到 MUST 自动停止并 flush 关闭文件。句柄 MUST 与子面板窗口生命周期绑定：Start 创建、Stop/关窗回收并关闭文件，MUST NOT 残留孤儿采集任务。

> 实测约束：iOS 26（beta）上 `com.apple.pcapd.shim.remote` 启动被设备拒绝（`StartServiceError`）；iOS 17/18 经 tunnel 支持。失败 MUST 返回可读错误信封而非崩溃。

#### Scenario: 抓包落盘并被 Wireshark 打开

- **WHEN** 用户开始抓包并指定 `.pcap` 路径
- **THEN** 数据包边抓边写入该文件，停止后文件可被 Wireshark 正常打开

#### Scenario: 上限自动停止

- **WHEN** 抓包达到任一上限（包数 / 文件大小 / 时长）
- **THEN** 自动停止采集并 flush 关闭文件

#### Scenario: 服务不可用降级

- **WHEN** 设备拒绝启动 pcapd（如 iOS 版本限制）
- **THEN** 返回可读错误信封，不崩溃

### Requirement: 实时摘要与降级

抓包进行中 UI MUST 提供状态（包数 / 字节 / 时长 / 落盘路径）与滚动「最近 N 包」摘要（时间、进程 `comm`/`pid`、接口、协议族、长度）；MUST 使用 ring buffer 限制摘要记录数并限速渲染，避免高吞吐卡顿。**不做逐层协议解析**（交 Wireshark）。字段缺失 MUST 以 `unknown` 标注，不中断会话。

#### Scenario: 实时摘要滚动

- **WHEN** 抓包进行中
- **THEN** 摘要表滚动展示最近 N 包，状态条实时更新包数/字节/时长

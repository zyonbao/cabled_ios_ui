# pcap-capture-op Specification

## Purpose
TBD - created by archiving change devtools-pcap-capture-phase2. Update Purpose after archive.
## Requirements
### Requirement: 抓包会话与落盘

平台层 SHALL 提供 `open_pcap_stream(target, out_path, process, interface, limits)`：基于 `pcapd`（lockdown 服务），**MUST 经 usbmux lockdown 连接，MUST NOT 走 RSD/tunnel**（RSD 路径设备返回 `ServiceProhibited`，Apple 自 iOS 17/18 起的全局限制，见 issue #1515）；**不需要 tunnel、不需要 DDI**。边抓边经 `write_to_pcap` 写入 `out_path`（pcapng，Wireshark 可读）。采集 MUST 在后台执行、不阻塞 UI；可按进程（`comm`）/接口过滤。上限（最大包数 / 最大文件大小 / 最长时长）任一达到 MUST 自动停止并 flush 关闭文件。句柄 MUST 与子面板窗口生命周期绑定：Start 创建、Stop/关窗回收并关闭文件（含打断 idle 阻塞），MUST NOT 残留孤儿采集任务。

> 实测（iOS 26）：usbmux 路径正常抓包，每包带真实 `comm`/`pid`。设备未配对/不可用等失败 MUST 返回可读错误信封而非崩溃。

#### Scenario: 抓包落盘并被 Wireshark 打开

- **WHEN** 用户开始抓包并指定 `.pcap` 路径
- **THEN** 数据包边抓边写入该文件，停止后文件可被 Wireshark 正常打开

#### Scenario: 上限自动停止

- **WHEN** 抓包达到任一上限（包数 / 文件大小 / 时长）
- **THEN** 自动停止采集并 flush 关闭文件

#### Scenario: 服务不可用降级

- **WHEN** 设备未配对/信任或 pcapd 不可用
- **THEN** 返回可读错误信封，不崩溃

### Requirement: 实时摘要与降级

抓包进行中 UI MUST 提供状态（包数 / 字节 / 时长 / 落盘路径）与滚动「最近 N 包」摘要（时间、进程 `comm`/`pid`、接口、协议族、长度）；MUST 使用 ring buffer 限制摘要记录数并限速渲染，避免高吞吐卡顿。**不做逐层协议解析**（交 Wireshark）。字段缺失 MUST 以 `unknown` 标注，不中断会话。

#### Scenario: 实时摘要滚动

- **WHEN** 抓包进行中
- **THEN** 摘要表滚动展示最近 N 包，状态条实时更新包数/字节/时长


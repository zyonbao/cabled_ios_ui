# Tasks

> **状态：⏸ DEFERRED** — task 0 为阻塞前置，未通过前不进入实现。

## 0. 阻塞前置：老系统设备验证 pcapd 可用性

- [ ] 0.1 在 iOS 17/18（非 beta）设备上确认 `pcapd.watch` 经 tunnel 可启动（当前 iOS 26 报 `StartServiceError`）
- [ ] 0.2 确认 `packet.comm/pid` 有值、`write_to_pcap` 产出能被 Wireshark 打开、协议族/接口字段可用

## 1. 平台层抓包（待 0 通过）

- [ ] 1.1 `ios_toolkit/device.py`：`PcapStreamHandle` 包 `pcapd.watch`，tee generator 边抓边 `write_to_pcap` 落盘 + 推摘要环形缓存 + 计数（包数/字节/时长）
- [ ] 1.2 上限（包数/MB/时长）任一触发自动停并 flush 关闭文件
- [ ] 1.3 `ios_toolkit/toolkit_api.py`：`open_pcap_stream(target, process, interface, out_path, limits)` → 句柄/错误信封（无需 DDI；17+ 仅需 tunnel）
- [ ] 1.4 句柄与窗口生命周期绑定：Start 创建、Stop/关窗回收并关闭文件

## 2. PCAP 子面板 UI

- [ ] 2.1 `developer_tools_tab.py`：「PCAP 抓包」入口与单例窗口
- [ ] 2.2 控制栏 Start/Stop + 进程(comm)/接口过滤 + 上限设置；Start 时选 `.pcap` 路径
- [ ] 2.3 状态条（包数/字节/时长/路径）+ 滚动「最近 N 包」摘要表（时间/进程/pid/接口/协议族/长度）；合规提示

## 3. 校验

- [ ] 3.1 py_compile / openspec validate / `i18n.validate()` 通过
- [ ] 3.2 真机验收：落盘 .pcap 可被 Wireshark 打开、上限自动停、关窗回收无残留

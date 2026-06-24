## Why

「开发者工具」缺少数据链路层抓包能力。排查网络问题（弱网/握手/重传）时无法在本工具内落地 `.pcap` 给 Wireshark 分析，需切外部工具。pcapd 还能提供**每包的进程名/pid**（与网络监控 instrument 的 pid=-2 不同），可做进程维度的抓包。

> 真机已验证（iOS 26）：pcapd 经 **usbmux lockdown** 正常抓包，每包带真实 `comm`/`pid`（如 `mDNSResponder`/182）、接口、协议族、长度。**关键：pcapd 必须走 usbmux，不能走 RSD/tunnel**——经 RSD 设备返回 `ServiceProhibited`（Apple 自 iOS 17/18 起的全局限制，非 iOS 26 特有，见 pymobiledevice3 issue #1515）。**既不需要 tunnel 也不需要 DDI。**

## What Changes

- 在 `DeveloperToolsTab` 增加「PCAP 抓包」功能卡片，打开子面板（非独立 sidebar Tab）。
- 平台层：`open_pcap_stream(target, process, interface, out_path, limits)` → 句柄，经 **usbmux lockdown** 包 `pcapd.watch()`，后台逐包：① 经 `write_to_pcap` 边抓边写 `.pcap`（tee generator）；② 推入有界摘要环形缓存 + 计数（包数/字节/时长）。
- UI：控制栏 Start/Stop + 进程(comm)/接口过滤 + 上限（包数/MB/时长，任一到自动停）；状态条（包数/字节/时长/落盘路径）；滚动「最近 N 包」摘要表（时间/进程/pid/接口/协议族/长度）。**不做逐层解析**（交 Wireshark）。
- 生命周期绑定（Stop/关窗回收并 flush 关闭文件）+ 合规提示（仅本地落盘）。

## Capabilities

### Added Capabilities

- `pcap-capture-op`：平台层抓包能力（usbmux 事件流落盘 + 摘要 + 上限/生命周期）。

### Modified Capabilities

- `slide6-developer-tools`：新增「PCAP 抓包」功能卡片与子面板。

## Impact

- 代码：`ios_toolkit/device.py`（`PcapStreamHandle`）、`ios_toolkit/toolkit_api.py`（`open_pcap_stream`）、`slide6_ui/developer_tools/`（新增 dialog + 入口）、i18n。
- Spec：`openspec/specs/pcap-capture-op/spec.md`、`openspec/specs/slide6-developer-tools/spec.md`。
- 依赖：`pcapng`（随 pymobiledevice3 安装）；**走 usbmux，无需 tunnel / DDI**。

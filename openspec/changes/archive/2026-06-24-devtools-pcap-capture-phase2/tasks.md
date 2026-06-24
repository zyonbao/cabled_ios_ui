# Tasks

## 0. 真机字段确认（实现前）

- [x] 0.1 已完成：pcapd 经 **usbmux lockdown** 在 iOS 26 正常抓包，每包带 `comm`/`pid`/接口/协议族/长度；RSD 路径 `ServiceProhibited`（Apple 全局限制，issue #1515）。→ 传输固定 usbmux，无需 tunnel/DDI

## 1. 平台层抓包

- [x] 1.1 `ios_toolkit/device.py`：`PcapStreamHandle` 经 `create_using_usbmux` 包 `pcapd.watch`，tee generator 边抓边 `write_to_pcap` 落盘 + 推摘要环形缓存 + 计数（包数/字节/时长）
- [x] 1.2 上限（包数/MB/时长）任一触发自动停并 flush 关闭文件；`close()` 走 future 取消打断 idle 阻塞
- [x] 1.3 `ios_toolkit/toolkit_api.py`：`open_pcap_stream(target, out_path, process, interface, limits)` → 句柄/错误信封（usbmux；无需 DDI/tunnel）
- [x] 1.4 句柄与窗口生命周期绑定：Start 创建、Stop/关窗回收并关闭文件，无残留

## 2. PCAP 子面板 UI

- [x] 2.1 `developer_tools_tab.py`：「PCAP 抓包」入口与单例窗口（非 DDI 门控的卡片）
- [x] 2.2 控制栏 Start/Stop + 进程(comm)/接口过滤 + 上限设置；Start 时选 `.pcap` 路径
- [x] 2.3 状态条（包数/字节/时长/路径）+ 滚动「最近 N 包」摘要表（时间/进程/pid/接口/协议族/长度）；合规提示

## 3. 校验

- [x] 3.1 py_compile / openspec validate / `i18n.validate()` 通过
- [x] 3.2 真机验收：落盘 .pcap 可被 Wireshark 打开、上限自动停、关窗回收无残留

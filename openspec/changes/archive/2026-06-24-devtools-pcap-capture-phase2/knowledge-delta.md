## 变更摘要

新增开发者工具「PCAP 抓包」子面板：经 usbmux 边抓边落 `.pcap`（Wireshark 可读）+ 实时摘要表。真机已验证可用（iOS 26）。

## 目标模块

slide6-developer-tools / pcap-capture-op

## 知识写入目标

`openspec/specs/pcap-capture-op/spec.md`、`openspec/specs/slide6-developer-tools/spec.md`

## 架构变更

- pcapd 为 lockdown 服务，**经 usbmux lockdown 访问，不走 RSD/tunnel、不需要 DDI**（RSD 路径被设备禁止：`ServiceProhibited`，issue #1515）。
- 句柄包 `pcapd.watch`，tee generator 同时落盘（`write_to_pcap`）与喂摘要环形缓存；`close()` 走 future 取消打断 idle 阻塞。

## 接口变更

- 新增 `open_pcap_stream(target, out_path, process, interface, limits)` → 句柄/错误信封。
- 摘要字段：时间、进程(comm)/pid、接口、协议族、长度（pcapd 提供每包进程归属，与网络监控 pid=-2 不同）。

## 平台支持

- ✅ iOS 26：usbmux 路径实测可抓包（`mDNSResponder`/182、`en`、AF_INET/INET6）。
- ❌ RSD/tunnel 路径：`ServiceProhibited`（Apple 自 iOS 17/18 起的全局限制）。

## 设计决策（WHY）

- 传输固定 usbmux：RSD 被禁；usbmux 无需 tunnel/DDI，门控更轻（类似系统日志）。
- tee generator 复用同一事件流落盘 + 摘要，落盘交 pymobiledevice3，不自写 pcapng。
- 不做逐层解析：Wireshark 已更好，避免重复造。

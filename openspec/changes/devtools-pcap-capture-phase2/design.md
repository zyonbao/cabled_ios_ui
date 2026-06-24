## Context

> **状态：⏸ DEFERRED** — 见 proposal。设计已成型，待 iOS 17/18 设备验证后实现。

PCAP 抓包基于 `pcapd`（lockdown 服务，iOS 17+ 经 tunnel 的 `com.apple.pcapd.shim.remote`，**不需要 DDI**）。`PcapdService.watch(packets_count, process, interface_name)` 逐包产出 `{comm, pid, interface_name, interface_type, protocol_family, seconds, microseconds, data}`；`write_to_pcap(file, gen)` 落 pcapng。

## 真机实测（iOS 26 + tunnel）

- `com.apple.pcapd.shim.remote` 已在 RSD 列表，但 `start` → `StartServiceError`（设备拒绝）。同 tunnel 上 DVT 与 webinspector shim 均正常 → pcapd 专属被拒，判定 iOS 26 限制。**实现暂缓，待老系统设备复测**。

## Goals / Non-Goals

**Goals**
- 边抓边写 `.pcap`（Wireshark 可打开），支持进程/接口过滤与上限（包数/大小/时长）。
- 实时摘要表（最近 N 包）+ 状态条；后台采集 + 限速渲染 + ring buffer。
- 句柄与窗口生命周期绑定。

**Non-Goals**
- 不做逐层协议解析（交 Wireshark）。
- 不做长期存储/轮转归档。

## Decisions

### 决策 1：tee generator —— 落盘与摘要复用同一事件流

参考 CLI：用一个包装 generator，对每包先记录摘要/计数，再 `yield` 给 `write_to_pcap` 落盘。落盘交给 pymobiledevice3，不自写 pcapng。

### 决策 2：上限任一触发即自动停

包数 / 文件大小(MB) / 时长(秒) 任一达到自动 Stop 并 flush 关闭文件。默认建议：50MB / 100k 包 / 600s。

### 决策 3：进程归属可用（与网络监控不同）

pcapd 提供每包 `comm`/`pid`，摘要表与过滤可按进程；但抓包为全量数据、开销大，需后台线程 + ring buffer + 限速渲染（复用网络监控范式）。

## Risks / Trade-offs

- **可用性（当前最大风险）**：iOS 26 被拒；需老系统验证。
- 抓包隐私/合规：UI 明确提示仅本地落盘、用途范围。
- 高吞吐落盘 + 渲染压力：限速渲染 + 摘要环形缓存；落盘走后台、避免阻塞。

## Migration Plan

1. ⏸ **阻塞项**：在 iOS 17/18（非 beta）设备上复测 `pcapd.watch` 经 tunnel 可用、`packet.comm/pid` 有值、`write_to_pcap` 产出能被 Wireshark 打开。
2. 平台层句柄（watch + tee 落盘 + 摘要环形缓存 + 上限自动停 + 生命周期）。
3. UI 子面板（控制栏 + 过滤 + 状态条 + 摘要表 + 合规提示）。
4. i18n、校验、真机验收。

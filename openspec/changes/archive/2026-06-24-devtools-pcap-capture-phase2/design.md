## Context

PCAP 抓包基于 `pcapd`（lockdown 服务）。`PcapdService.watch(packets_count, process, interface_name)` 逐包产出 `{comm, pid, epid, ecomm, svc, interface_name, interface_type, protocol_family, seconds, microseconds, data}`；`write_to_pcap(out, gen)` 写 pcapng（Wireshark 可读）。

## 真机实测（iOS 26）

- pcapd 经 **usbmux lockdown**（`create_using_usbmux`）正常抓包：`mDNSResponder`/pid 182、接口 `en`、AF_INET/INET6、含字节长度。**每包带真实进程名/pid**（网络监控拿不到）。
- pcapd 经 **RSD/tunnel** 被拒：设备返回 `ServiceProhibited`（pymobiledevice3 issue #1515，iOS 18.7.2 即如此 → Apple 全局限制，非 iOS 26 特有）。
- 结论：**走 usbmux，不走 RSD；无需 tunnel、无需 DDI**。

## Goals / Non-Goals

**Goals**
- 经 usbmux 边抓边写 `.pcap`，支持进程/接口过滤与上限（包数/大小/时长）。
- 实时摘要表（最近 N 包）+ 状态条；后台采集 + 限速渲染 + ring buffer。
- 句柄与窗口生命周期绑定。

**Non-Goals**
- 不做逐层协议解析（交 Wireshark）。
- 不做长期存储/轮转归档。
- 不走 RSD/tunnel（被设备禁止）。

## Decisions

### 决策 1：传输固定 usbmux lockdown（不走 RSD）

无论 iOS 版本，pcapd 一律 `create_using_usbmux(serial, autopair=False)` 连接；不使用 `_with_dvt` / RSD（会 `ServiceProhibited`）。因此该卡片**门控仅需配对设备，无需 tunnel / DDI**（比 DVT 卡片更轻，类似系统日志）。

### 决策 2：tee generator —— 落盘与摘要复用同一事件流

包一个 generator：对每包先记摘要/计数、判上限，再 `yield` 给 `write_to_pcap` 落盘（pcapng 写入交 pymobiledevice3，不自写）。`_closed` 或上限达到时 generator `return` → `write_to_pcap` 循环结束 → 文件 flush 关闭。idle 阻塞在 `watch()` 时，`close()` 走 future 取消打断（与其它 handle 一致）。

### 决策 3：上限任一触发即自动停

包数 / 文件大小(MB) / 时长(秒) 任一达到自动停并 flush。默认建议：50MB / 100k 包 / 600s。

### 决策 4：进程归属可用

pcapd 每包 `comm`/`pid` 有效，摘要表与过滤可按进程；抓包为全量数据、开销大，后台线程 + ring buffer（摘要）+ 限速渲染。

## Risks / Trade-offs

- 抓包隐私/合规：UI 明确提示仅本地落盘、用途范围。
- 高吞吐落盘 + 渲染压力：限速渲染 + 摘要环形缓存；落盘走后台。
- usbmux 大流量传输性能有限（社区有 go-ios 等更快方案）；本期够用，必要时再评估。
- 需设备已配对/信任（usbmux）；未配对给可读提示。

## Migration Plan

1. ✅ 真机确认（已完成）：usbmux 路径可抓包、带进程归属；RSD 路径 ServiceProhibited。
2. 平台层 `PcapStreamHandle`（usbmux watch + tee 落盘 + 摘要环形缓存 + 上限自动停 + 生命周期）。
3. UI 子面板（控制栏 + 过滤 + 状态条 + 摘要表 + 合规提示）。
4. i18n、校验、真机验收（落盘可被 Wireshark 打开、上限自动停、关窗回收）。

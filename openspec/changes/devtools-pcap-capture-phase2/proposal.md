> **状态：⏸ DEFERRED（暂缓）** — 唯一可测设备为 iOS 26（beta），pcapd 经 tunnel 被设备拒绝启动
> （`StartServiceError`，详见 Why）。本提案保留完整设计，待有 iOS 17/18（非 beta）设备验证后再落地实现。

## Why

「开发者工具」缺少数据链路层抓包能力。排查网络问题（弱网/握手/重传）时无法在本工具内落地 `.pcap` 给 Wireshark 分析，需切外部工具。pcapd 还能提供**每包的进程名/pid**（与网络监控 instrument 不同），可做进程维度的抓包。

### 暂缓原因（真机实测，iOS 26 + tunnel）

- `com.apple.pcapd.shim.remote` 在 RSD 服务列表中存在，但 `start` 直接 `StartServiceError`（设备侧拒绝、无详情）。
- 排除通用原因：同一条 tunnel 上 DVT（sysmontap/网络监控/条件诱导）与 `com.apple.webinspector.shim.remote` 均能正常启动；DDI 已挂载也无效 → **pcapd 专属被拒**。
- 联网调研：pcapd 在 **iOS 17/18 经 tunnel `shim.remote` 是支持的**，`StartServiceError` 通常是 tunnel 未起/未配对——但本环境 tunnel 正常。资料未覆盖 iOS 26。
- **结论**：高度判定为 **iOS 26（beta）对 pcapd 的限制/回归**，pymobiledevice3 侧无法绕过。需在 iOS 17/18 设备上复测确认实现可用。

## What Changes（待落地）

- 在 `DeveloperToolsTab` 增加「PCAP 抓包」功能卡片，打开子面板。
- 平台层：`open_pcap_stream(target, process, interface, out_path, limits)` → 句柄包 `pcapd.watch()`，后台 loop 逐包：① 经 `write_to_pcap` 边抓边写 `.pcap`；② 推入有界摘要环形缓存 + 计数。
- UI：控制栏 Start/Stop + 进程(comm)/接口过滤 + 上限（包数/MB/时长，任一到自动停）；状态条（包数/字节/时长/落盘路径）；滚动「最近 N 包」摘要表（时间/进程/pid/接口/协议族/长度）。**不做逐层解析**（交 Wireshark）。
- 生命周期绑定 + 合规提示（仅本地落盘）。

## Capabilities

### Added Capabilities

- `pcap-capture-op`：平台层抓包能力（事件流落盘 + 摘要 + 上限/生命周期）。

### Modified Capabilities

- `slide6-developer-tools`：新增「PCAP 抓包」功能卡片与子面板（**实现暂缓**）。

## Impact

- 代码（待落地）：`ios_toolkit/device.py`、`ios_toolkit/toolkit_api.py`、`slide6_ui/developer_tools/`、i18n。
- Spec：`openspec/specs/pcap-capture-op/spec.md`、`openspec/specs/slide6-developer-tools/spec.md`。
- 依赖：`pcapng`（随 pymobiledevice3 安装）；复用现有 tunnel（**不需要 DDI**）。

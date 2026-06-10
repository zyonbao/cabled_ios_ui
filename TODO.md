# slide6_ui 后续 Tab / 能力路线图

记录在「设备信息 / 键鼠 / App 列表 / 文件系统 / 相册」之外，后续计划新增的 Tab 与无 Tab 能力。
每项给出：定位、底层依赖（基于 `pymobiledevice3`）、是否需要 WDA / tunnel / DeveloperDiskImage、可行性评估与优先级建议。

> 约定：iOS 17+ 的多数 lockdown 之外服务需要 **XPC tunnel**（项目已具备授权拉起能力）；
> DVT / instruments 类服务还需 **挂载 DeveloperDiskImage（DDI）**；
> AFC / house-arrest / installation_proxy / lockdown 取值等**不需要** WDA 或 tunnel（iOS 16-）。

---

## 一、独立 Tab（计划新增）

### 1. Profile and application management（描述文件与 App 管理）✅ 已完成
- **状态**：已实现并归档（`archive/2026-06-09-add-profiles-crash-syslog-tabs`）。描述文件管理以对话框形式集成在「App 列表」Tab（拖拽安装 / 列表 / 多选移除）；App 列表对系统应用隐藏卸载入口。
- **定位**：独立 Tab。管理配置描述文件（.mobileconfig 安装/列出/移除）+ App 管理增强（已部分在「App 列表」实现）。
- **依赖**：`pymobiledevice3.services.mobile_config.MobileConfigService`（描述文件）、`installation_proxy`（App）。不需要 WDA / tunnel（iOS 16-）。
- **可行性**：**高**。描述文件列出/安装/移除是成熟 lockdown 服务；与现有 App 管理可整合到同一 Tab。
- **注意**：安装描述文件通常需设备端「设置」里手动确认（系统行为，UI 需提示）；移除受监管/MDM 限制。
- **优先级**：高（实现成本低、价值明确）。

### 2. Crash report collection（Crash 文件导出）✅ 已完成
- **状态**：已实现并归档（`archive/2026-06-09-add-profiles-crash-syslog-tabs`）。独立「Crash 报告」Tab：列表 / 文件名过滤 / 多选 + 右键导出与删除 / 导出可选保留原文件。
- **定位**：独立 Tab。列出并导出设备崩溃日志（.ips/.crash）。
- **依赖**：`pymobiledevice3.services.crash_reports.CrashReportsManager`（基于 AFC2 的 crash mover/copier）。不需要 WDA / tunnel。
- **可行性**：**高**。列出/拉取/清理崩溃日志为标准能力；可复用相册/文件系统的导出与多选删除模式。
- **优先级**：高（排障刚需，复用度高）。

### 3. Syslog and oslog streaming（系统日志查看 / 实时流）✅ 已完成
- **状态**：已实现并归档（`archive/2026-06-09-add-profiles-crash-syslog-tabs`）。独立「系统日志」Tab：syslog/oslog 下拉、实时流、关键字过滤、暂停/清空/另存；后台 `_bg_loop` 采集 + 限速渲染。oslog 经 `os_trace` 实现（免 tunnel）。
- **定位**：独立 Tab。实时 syslog 流式展示 + 关键字过滤 + 暂停/清空/另存。
- **依赖**：`pymobiledevice3.services.syslog.SyslogService`（旧 syslog_relay，iOS 16- 即可）；iOS 17+ 的 os_log 走 `os_trace`/DVT，更复杂。
- **可行性**：**中-高**。传统 syslog 简单可行；结构化 oslog（含子系统/类别/级别）在 17+ 需 tunnel + DVT，先做 syslog，再评估 oslog。
- **注意**：高吞吐流需后台线程 + 限速渲染（参考 mirror 的线程模型）；避免主线程刷爆。
- **优先级**：高（syslog 部分）/ 中（oslog 增强）。

### 4. DDI / DVT developer tooling（开发者工具，需挂载 DeveloperDiskImage）
- **定位**：独立「开发者工具」Tab，聚合多种 DVT/instruments 工具，采用「DDI 状态栏 + 功能位 grid」布局，DDI 挂载后逐步解锁能力。
- **⚠️ 待续验收（DDI mount）**：Phase 1 代码已实现并归档（`archive/2026-06-10-add-developer-tools-tab-phase1`，含虚拟定位轨迹回放 + 带地址栏的文件选择器），但 **DDI 挂载（mount/unmount）尚未通过真机验收**。当前排查效率低（缺执行日志），**先实现日志系统（见下方 openspec change `add-logging-system`），待日志完善后再回头排查 DDI 挂载并完成验收**。进程管理 / 虚拟定位（含轨迹回放）功能本身可在 DDI 已挂载（外部预挂载）时验证。
- **分期实施**：
  - **Phase 1（代码已归档，DDI mount 验收待续）**：DDI 挂载/卸载/状态 + 进程管理 + 虚拟定位（含 GPX/手动轨迹回放）。三项组成最小闭环：先把 DDI 挂载状态机与 DVT 连接底座打通，再落地两个高价值 DVT 工具。
    - **DDI**：Tab 顶部展示挂载状态；未挂载提供「挂载」（弹窗可选多种 `pymobiledevice3` 挂载方式：自动按版本 / 个性化镜像(17+) / 开发者镜像(<17) / 手动选本地镜像文件），已挂载提供「卸载」。挂载/卸载/状态走 usbmux lockdown（17+ 也不需 tunnel）。
    - **进程管理**：`device_info.DeviceInfo.proclist` 进程列表 + 按名筛选；`process_control.ProcessControl.launch` 按 bundle id 启动；`process_control.kill` 杀进程；选中查看进程明细（只读，不支持改）。
    - **虚拟定位**：<17 走 `simulate_location.DtSimulateLocation`（设完即生效）；17+ 走 DVT `location_simulation.LocationSimulation`，但模拟仅在 DTX 连接存活期间有效，需后台常驻定位会话，清除时取消会话。
    - **能力门控**：进程 / 定位以「功能位 grid」展示，DDI 未挂载时全部 Disabled，挂载成功后自动 enable（便于后续叠加 Phase 2 功能位）。
    - **tunnel 依赖**：iOS 17+ 的 DVT 能力（进程/定位）仍依赖 XPC tunnel（RSD），复用 `tunnel.py` + `_get_rsd_from_tunneld`；tunnel 未起时给出可读提示。
  - **Phase 2（后续）**：实时性能监控（`sysmontap`/`graphics`/`energy_monitor`）、网络监控（`network_monitor`）、条件诱导（`condition_inducer`）、设备/系统信息增强（`device_info`）、DVT 截图（`screenshot`）、高级 trace（`activity_trace_tap`/`core_profile_session_tap`/`notifications`）。这些功能位逐个叠加到同一 Tab 的 grid 上。
- **现状（项目已具备的 DDI/DVT 链路）**：
  - **已在用 1 个 DVT 服务**：WDA 的拉起依赖 `dvt.testmanaged.xcuitest.XCUITestService`（testmanagerd 测试会话）。见 `ios_toolkit/device.py` 的 `_run_wda_lockdown_async`（iOS ≤16，走 usbmux/lockdown）与 `_run_wda_rsd_async`（iOS 17+，走 `RemoteServiceDiscoveryService`）。**屏幕镜像 / 键鼠 / 手势等所有依赖 WDA 的能力，底层都经由这条 DVT 链路**。
  - **tunnel / RSD 已托管**：iOS 17+ 经 `slide6_ui/common/tunnel.py` + `ios_toolkit/tunneld_main.py` 授权拉起 root XPC tunnel，`device._get_rsd_from_tunneld` 查询 RSD 地址/端口。这正是 DVT/instruments 服务在 17+ 所需的**同一条底座**。
  - **DDI 目前未由本应用挂载**：运行 XCUITest（及后续 instruments）要求设备已挂载 DeveloperDiskImage，但应用**未实现自动挂载**——依赖外部预挂载（Xcode 曾连接过、或 `pymobiledevice3 mounter auto-mount`）。这是「4」要补齐的**核心缺口**。
  - **未接入的 DVT 能力**：instruments family（`device_info` / `process_control` / `sysmontap` / `screenshot` / `network_monitor` / `energy_monitor` 等）目前**完全未使用**。
- **失败表现（无 tunnel / DDI / WDA 时）**：会**显式报错**，但根因粒度不一：
  - iOS 17+ tunnel 未起：`_get_rsd_from_tunneld` 返回 None → `do_prepare` 抛 `RuntimeError("…cannot get RSD info from tunneld. Make sure ios_tunneld is running")`，UI 可读、根因清晰。
  - DDI 未挂载 / DVT 不可用：`XCUITestService.run` 失败致 runner 任务提前退出，`_wait_for_wda` 抛 `RuntimeError("WDA XCUITest runner exited… Underlying error: <pmd3 原始异常>")`——**能感知失败，但未单独区分"DDI 未挂载"这一根因**（待补：挂载状态预检 + 友好提示）。
- **依赖**：先 **挂载 DDI**（`pymobiledevice3.services.mobile_image_mounter`(auto_mount / lookup) / `amfi`；iOS 17+ 走个性化镜像 + `RemoteServiceDiscoveryService` + tunnel，DDI 为 `.dmg + trustcache + build_manifest`），再用 DVT instruments 服务（均复用已有 tunnel/RSD 底座，pmd3 9.16 模块均在 `services/dvt/instruments/`）。
- **可基于 DVT 实现的功能（候选清单，按价值排序；标注分期）**：
  1. **进程管理**（**Phase 1**）：进程列表（`device_info.DeviceInfo.proclist`）、按 bundleid 启动（`process_control.ProcessControl.launch`，支持参数/环境变量/暂停在 main）、杀进程（`process_control.kill`）。
  2. **位置模拟**（**Phase 1**）：设定/清除虚拟 GPS 坐标（<17 `simulate_location.DtSimulateLocation`；17+ `location_simulation.LocationSimulation`）。
  3. **实时性能监控**（Phase 2）：CPU/内存/线程/磁盘/网络的系统级与进程级采样（`sysmontap.Sysmontap`）、FPS/GPU 图形指标（`graphics`）、能耗（`energy_monitor`）。可做实时折线图 + 进程级 TopN。
  4. **网络监控**（Phase 2）：按进程的连接与收发字节（`network_monitor`）。
  5. **条件诱导**（Phase 2）：模拟弱网/高温等设备条件（`condition_inducer`），用于稳定性/性能测试。
  6. **设备/系统信息增强**（Phase 2）：内核、运行时、硬件信息（`device_info`），补充现有「设备信息」Tab。
  7. **DVT 截图**（Phase 2）：经 instruments 通道截图（`screenshot.Screenshot`），与现有 WDA/AFC 截图互为备选。
  8. **高级 trace（工程量大）**（Phase 2）：系统调用/活动追踪（`activity_trace_tap`）、core profile 采样（`core_profile_session_tap`）、通知监听（`notifications`，可测冷/热启动耗时）。
- **可行性**：**中（成本高、价值高）**。关键判断：XCUITest/DVT 链路与 tunnel 底座**已跑通**，新增 instruments 工具相当于"在既有 RSD/lockdown 之上多开几个 DVT channel"，**增量可控**；主要工程量集中在 **DDI 自动挂载**（资源获取/校验/缓存 + 17+ 个性化镜像）与各子工具的 UI / 采样限速。
- **待敲定细节（可先定）**：
  1. DDI 来源与缓存：本地选择 `.dmg` / 从 Xcode 路径探测（`/Applications/Xcode.app/…/DeviceSupport`）/ 按版本下载；17+ 走个性化镜像（`mobile_image_mounter` personalized 流程）；缓存目录与校验。
  2. 挂载状态机：预检是否已挂载（`mobile_image_mounter` lookup）→ 未挂载则提示选择/获取 → 挂载 → 各 DVT 工具解锁；提供卸载入口。
  3. 失败根因区分：将"DDI 未挂载 / tunnel 未起 / WDA 未装"分别给出可读提示（补齐当前 generic error）。
  4. Tab 内子工具布局（子 Tab 或左侧列表）。
  5. 与 tunnel 生命周期联动（DVT 必须在 tunnel 之上；复用 `tunnel.py` 的拉起/停止与 `_get_rsd_from_tunneld`）。
  6. 采样性能：`sysmontap` 高频采样需后台线程 + 限速渲染（复用 mirror / syslog 的线程模型）。
- **优先级**：Phase 1 进行中（DDI 挂载 + 进程管理 + 虚拟定位最小闭环，走 openspec）；Phase 2 按资源排期，逐个功能位叠加到同一 Tab。

### 5. Network sniffing（PCAP 抓包，数据链路层）
- **定位**：独立 Tab。开启远程虚拟接口抓包，落地 .pcap，可用 Wireshark 打开。
- **依赖**：`pymobiledevice3.services.pcapd.PcapdService`（rvictl 等价能力）。iOS 17+ 需 tunnel。
- **可行性**：**中-高**。pcapd 在 `pymobiledevice3` 可用；UI 侧主要是流式落盘 + 大小/时长限制 + 状态展示。
- **注意**：抓包涉及隐私/合规，UI 需明确提示用途与范围；只落地本地文件。
- **优先级**：中。

### 6. WebInspector automation（Safari / 应用内 WebView 调试）
- **定位**：独立 Tab。列出可调试的 Web 页面/上下文，桥接到本地 DevTools。
- **依赖**：`pymobiledevice3.services.web_protocol` / WebInspector（RemoteWebInspector）。设备需开启「Web 检查器」；iOS 17+ 需 tunnel。
- **可行性**：**中**。枚举页面可行；完整 DevTools 体验需把 WIP 协议桥接到 CDP/本地浏览器，工程量较大，首版可做「列出 + 基础命令」。
- **优先级**：中-低（依赖较重，价值面向特定调试场景）。

### 7. Backup and restore（数据备份与重置）
- **定位**：独立 Tab。mobilebackup2 完整/增量备份与恢复。
- **依赖**：`pymobiledevice3.services.mobilebackup2.Mobilebackup2Service`。不需要 WDA / tunnel（iOS 16-）。
- **可行性**：**中**。备份/恢复链路成熟，但耗时长、磁盘占用大、加密备份需密码管理；UI 要做进度、空间校验、加密开关与中断恢复。
- **注意**：恢复是破坏性操作，需强二次确认；加密密码绝不可落日志（遵循安全基线第 4 条）。
- **优先级**：中。

### 8. Firmware update + Recovery / DFU workflows（固件升级 + 刷机，合并为一个 Tab）
- **定位**：**合并**为「固件 / 恢复」单一 Tab：固件升级、进入/退出 Recovery、DFU 引导与刷机。
- **依赖**：`pymobiledevice3` 的 `restore`/`irecv`（recovery/DFU 设备走 USB，不经 lockdown/tunnel）；IPSW 获取与校验。
- **可行性**：**低-中（高风险）**。链路存在但极易变砖；DFU 进入依赖人工按键时序，自动化受限；强依赖正确 IPSW。
- **注意**：破坏性极强，必须多重确认 + 明确免责 + 严格 IPSW 校验；建议最后做或仅做「引导 + 状态展示」。
- **优先级**：低（高风险，单独排期）。

---

## 二、无 Tab 能力（作为工具/服务，供其他 Tab 复用）

### 9. Notification listen / post（notify_post() 系统通知监听/发送）
- **定位**：无独立 Tab。后台能力，供其他 Tab（如 DVT、调试场景）组合使用。
- **依赖**：`pymobiledevice3.services.notification_proxy.NotificationProxyService`（observe/post Darwin notifications）。iOS 17+ 需 tunnel。
- **可行性**：**高**。observe/post 简单可靠；可做成共享服务 + 可选的调试浮层/日志。
- **优先级**：中（作为底层能力，随需要它的 Tab 一起落地）。

### 10. Querying and setting SpringBoard options（SpringBoard 查询/设置）
- **定位**：无独立 Tab。设置类工具（如壁纸、图标状态、方向锁等可读写项），可嵌入「设备信息」或设置面板。
- **依赖**：`pymobiledevice3.services.springboard.SpringBoardServicesService`（取图标状态/壁纸等）。不需要 WDA / tunnel（iOS 16-）。
- **可行性**：**中-高**。读取类（图标布局、壁纸）可行；可写项较有限且随版本变化，需按设备验证。
- **优先级**：中-低。

---

## 三、近期小调整（已转入 openspec 变更处理）

以下三项体验/稳定性调整通过独立 openspec change 跟进，不在本路线图内逐项展开：

1. 相册缩略图改为 **Crop 居中裁剪填充**（替代当前的拉伸/letterbox 观感）。
2. 「文件系统」Tab 支持 **多选 + 右键批量操作**（批量下载 / 批量删除）。
3. 修复 **Ctrl+C 导致进程崩溃**（为 Qt 应用安装 SIGINT 处理，干净退出）。

---

## 优先级汇总（建议）

| 优先级 | 项目 |
|---|---|
| ✅ 已完成 | 1 描述文件管理、2 Crash 导出、3 Syslog/oslog 流（archive 2026-06-09） |
| 中 | 4 DDI/DVT 开发者工具（Phase 1 代码已归档，**DDI mount 验收待续**，待日志系统完善后排查；Phase 2 排期）、5 PCAP 抓包、7 备份恢复、9 通知监听 |
| 中-低 | 6 WebInspector、10 SpringBoard 设置 |
| 低（高风险） | 8 固件升级 + Recovery/DFU |

> 通用工程注意：所有需要 iOS 17+ 的服务复用现有 tunnel 生命周期；流式/大数据量能力（syslog/pcap/性能）一律后台线程采集 + 主线程限速渲染（参考 `mirror.py`）；破坏性操作（恢复/刷机/批量删除）统一走二次确认；密码/令牌等敏感信息严禁落日志（安全基线）。

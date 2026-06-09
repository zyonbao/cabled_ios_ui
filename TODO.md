# slide6_ui 后续 Tab / 能力路线图

记录在「设备信息 / 键鼠 / App 列表 / 文件系统 / 相册」之外，后续计划新增的 Tab 与无 Tab 能力。
每项给出：定位、底层依赖（基于 `pymobiledevice3`）、是否需要 WDA / tunnel / DeveloperDiskImage、可行性评估与优先级建议。

> 约定：iOS 17+ 的多数 lockdown 之外服务需要 **XPC tunnel**（项目已具备授权拉起能力）；
> DVT / instruments 类服务还需 **挂载 DeveloperDiskImage（DDI）**；
> AFC / house-arrest / installation_proxy / lockdown 取值等**不需要** WDA 或 tunnel（iOS 16-）。

---

## 一、独立 Tab（计划新增）

### 1. Profile and application management（描述文件与 App 管理）
- **定位**：独立 Tab。管理配置描述文件（.mobileconfig 安装/列出/移除）+ App 管理增强（已部分在「App 列表」实现）。
- **依赖**：`pymobiledevice3.services.mobile_config.MobileConfigService`（描述文件）、`installation_proxy`（App）。不需要 WDA / tunnel（iOS 16-）。
- **可行性**：**高**。描述文件列出/安装/移除是成熟 lockdown 服务；与现有 App 管理可整合到同一 Tab。
- **注意**：安装描述文件通常需设备端「设置」里手动确认（系统行为，UI 需提示）；移除受监管/MDM 限制。
- **优先级**：高（实现成本低、价值明确）。

### 2. Crash report collection（Crash 文件导出）
- **定位**：独立 Tab。列出并导出设备崩溃日志（.ips/.crash）。
- **依赖**：`pymobiledevice3.services.crash_reports.CrashReportsManager`（基于 AFC2 的 crash mover/copier）。不需要 WDA / tunnel。
- **可行性**：**高**。列出/拉取/清理崩溃日志为标准能力；可复用相册/文件系统的导出与多选删除模式。
- **优先级**：高（排障刚需，复用度高）。

### 3. Syslog and oslog streaming（系统日志查看 / 实时流）
- **定位**：独立 Tab。实时 syslog 流式展示 + 关键字过滤 + 暂停/清空/另存。
- **依赖**：`pymobiledevice3.services.syslog.SyslogService`（旧 syslog_relay，iOS 16- 即可）；iOS 17+ 的 os_log 走 `os_trace`/DVT，更复杂。
- **可行性**：**中-高**。传统 syslog 简单可行；结构化 oslog（含子系统/类别/级别）在 17+ 需 tunnel + DVT，先做 syslog，再评估 oslog。
- **注意**：高吞吐流需后台线程 + 限速渲染（参考 mirror 的线程模型）；避免主线程刷爆。
- **优先级**：高（syslog 部分）/ 中（oslog 增强）。

### 4. DDI / DVT developer tooling（开发者工具，需挂载 DeveloperDiskImage）
- **定位**：独立 Tab，聚合多种 DVT/instruments 工具。**先敲定细节、暂缓实现**，有资源再做。
- **依赖**：先 **挂载 DDI**（`pymobiledevice3.services.mobile_image_mounter` / `amfi`；iOS 17+ 走 `RemoteServiceDiscoveryService` + tunnel，DDI 为 `.dmg + trustcache + build_manifest`），再用 DVT 服务：
  - 进程列表 / 启动 / 杀进程（`dvt.instruments.device_info` / `process_control`）
  - 实时性能（CPU / 内存 / FPS / 能耗，`sysmontap` / `core_profile`）
  - 启动耗时、文件系统监控、网络统计等
- **可行性**：**中（成本高、价值高）**。挂载与 DVT 链路在 `pymobiledevice3` 已支持，但 17+ 强依赖 tunnel + DDI 资源获取/校验，工程量大。
- **待敲定细节（可先定）**：
  1. DDI 来源与缓存：本地选择 `.dmg`/从 Xcode 路径探测/按版本下载；缓存目录与校验。
  2. 挂载状态机：未挂载 → 提示选择/获取 → 挂载 → 各 DVT 工具解锁；卸载入口。
  3. Tab 内子工具的布局（子 Tab 或左侧列表）。
  4. 与 tunnel 生命周期联动（DVT 必须在 tunnel 之上）。
- **优先级**：中（先出设计，按资源排期实现）。

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
| 高 | 1 描述文件管理、2 Crash 导出、3 Syslog 流（传统 syslog 部分） |
| 中 | 5 PCAP 抓包、7 备份恢复、4 DDI/DVT（先出设计）、9 通知监听、3 oslog 增强 |
| 中-低 | 6 WebInspector、10 SpringBoard 设置 |
| 低（高风险） | 8 固件升级 + Recovery/DFU |

> 通用工程注意：所有需要 iOS 17+ 的服务复用现有 tunnel 生命周期；流式/大数据量能力（syslog/pcap/性能）一律后台线程采集 + 主线程限速渲染（参考 `mirror.py`）；破坏性操作（恢复/刷机/批量删除）统一走二次确认；密码/令牌等敏感信息严禁落日志（安全基线）。

# slide6_ui 后续 Tab / 能力路线图

当前 TODO 仅保留未完成项，已完成项应从本文件删除。

> 约定：iOS 17+ 的多数 lockdown 之外服务需要 **XPC tunnel**；DVT / instruments 类服务还需 **挂载 DeveloperDiskImage（DDI）**；AFC / house-arrest / installation_proxy / lockdown 取值等**不需要** WDA 或 tunnel（iOS 16-）。

---

## 一、独立 Tab（计划新增）

### 1. Backup and restore（数据备份与重置）
- **定位**：独立 Tab，mobilebackup2 完整/增量备份与恢复
- **依赖**：`pymobiledevice3.services.mobilebackup2.Mobilebackup2Service`
- **风险**：耗时长、磁盘占用大、加密密码严禁落日志；恢复需强二次确认
- **优先级**：中

### 2. Firmware update + Recovery / DFU workflows（固件升级 + 刷机）
- **定位**：合并为「固件 / 恢复」Tab
- **依赖**：`pymobiledevice3` 的 `restore` / `irecv`，IPSW 获取与校验
- **风险**：高风险、易变砖；建议先做“引导 + 状态展示”
- **优先级**：低

---

## 二、无 Tab 能力（复用）

### 4. Notification listen / post（系统通知监听与发送）
- **定位**：无独立 Tab，作为后台能力供其他 Tab 复用
- **依赖**：`pymobiledevice3.services.notification_proxy.NotificationProxyService`
- **优先级**：中

### 5. Querying and setting SpringBoard options（SpringBoard 查询/设置）
- **定位**：嵌入「设备信息」或设置面板
- **依赖**：`pymobiledevice3.services.springboard.SpringBoardServicesService`
- **优先级**：中-低

---

## 三、技术债 / 重构

1. **DVT stream-handle 基类抽取（DRY）**：`ios_toolkit/device.py` 中 `LogStreamHandle` / `PerformanceStreamHandle` / `ConditionInducerHandle` / `NetworkStreamHandle` 共享生命周期样板，建议提取 `_DvtStreamHandle`。

---

## 优先级汇总（建议）

| 优先级 | 项目 |
|---|---|
| 高 | 无 |
| 中 | 1 Backup and restore、4 Notification listen/post |
| 中-低 | 5 SpringBoard 查询/设置 |
| 低（高风险） | 2 Firmware update + Recovery / DFU |

> 注意：iOS 17+ 服务需复用 tunnel 生命周期；流式/大数据量能力一律后台线程采集 + 主线程限速渲染；破坏性操作统一二次确认；密码/令牌等敏感信息不落日志。

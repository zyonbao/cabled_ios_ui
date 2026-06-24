# Tasks

## 0. 真机字段确认（实现前）

- [x] 0.1 已完成：`NetworkMonitor` 真机抓样确认 `kind` **1=TCP/2=UDP**、**`pid` 恒为 -2（进程维度取消）**、大量连接 remote `port=0`（需「仅活跃」过滤）、端点仅 IP（无反向 DNS）

## 1. 平台层事件流采集

- [x] 1.1 `ios_toolkit/device.py` 新增 `NetworkMonitor` 事件流句柄（open/close/queue，`startMonitoring`/`stopMonitoring`），输出归一化的连接流与吞吐速率
- [x] 1.2 `ios_toolkit/toolkit_api.py` 暴露 `open_network_stream(target)`（返回句柄/错误信封；**无设备采样间隔、不做频率校验**，UI 节流另行处理）
- [x] 1.3 连接以 `connection_serial` 关联 detection+update 聚合；维护按「远端 IP/接口」聚合 TopN（左栏导航）；协议由 `kind`(1=TCP/2=UDP) 推导、方向启发式推导，不可判定 `unknown`；**不做 pid/进程富化**
- [x] 1.4 后台事件队列设上限（溢出丢最旧）；句柄与窗口生命周期约束：Start 创建、Stop 回收、关闭窗口自动 `stopMonitoring` 并断开

## 2. Network Monitor 子面板 UI

- [x] 2.1 `developer_tools_tab.py` 增加网络监控子面板入口与单例窗口管理（沿用 `_open_subwindow`）
- [x] 2.2 新增 Network Monitor 对话框：顶部状态条 + 三栏布局 + 控制栏（Start/Stop/Pause/Clear/Auto-scroll/Export）
- [x] 2.3 左栏按「远端 IP/接口」聚合 TopN，点击联动中栏；趋势图（Rx/Tx 速率、连接数、错误数=重传/重复）与连接流表格联动；UI 200~500ms 批量节流刷新

## 3. 过滤器与导出

- [x] 3.1 实现协议（TCP/UDP/unknown）、host/port（`IP:port` 子串）、关键词、仅活跃连接过滤；方向（in/out）过滤可选（基于推导值）。进程过滤不提供（进程归属不可用）
- [x] 3.2 实现 CSV/JSON 导出，导出边界固定为当前过滤条件 + 当前 10 分钟窗口（PCAP 仅预留扩展位）
- [x] 3.3 字段缺失统一显示 `unknown/unsupported`

## 4. 稳定性与验证

- [x] 4.1 落地 10 分钟滚动窗口 + ring buffer + 后台队列上限淘汰策略
- [x] 4.2 完成 py_compile / ReadLints / openspec validate / `i18n.validate()` 严格校验
- [x] 4.3 真机验收：高吞吐场景无明显卡顿，关闭窗口/Stop 两路径无孤儿采集任务

## Why

当前「开发者工具」已完成性能监控，但网络监控能力仍未落地。用户在回归与排障时无法在同一面板中同时观察实时吞吐、连接明细与进程维度过滤，导致网络问题定位需要依赖外部工具切换，效率低且上下文割裂。

此外，现有 OpenSpec 已定义了 Network Monitor 的核心交互（状态条、三栏布局、控制栏、过滤器、10 分钟窗口、生命周期绑定），需要对应代码实现以完成 Phase 2 闭环。

## What Changes

- 在 `DeveloperToolsTab` 中实现 Network Monitor 子面板入口与单例窗口管理（不新增独立 sidebar Tab）。
- 增加网络采样会话：Start/Stop/Pause/Clear 控制、窗口关闭自动回收、采样线程与窗口生命周期强绑定。
- 实现三栏主布局：
  - 左栏：进程 TopN 与 bundle id 搜索；
  - 中栏：连接流列表（时间/协议/方向/本地-远端/字节）；
  - 右栏：详情与趋势图（Rx/Tx 速率、连接数、错误数）。
- 实现控制栏高频操作：Start/Stop、Pause、Clear、Auto-scroll、Export（CSV/JSON，先保留 PCAP 关联扩展位）。
- 实现过滤器：进程、协议、方向、host/port、时间窗口、关键词、仅活跃连接。
- 落地 10 分钟滚动窗口与 ring buffer 限流，超过窗口的数据即时淘汰。
- 统一降级语义：字段缺失显示 `unsupported/unknown`，不中断整个会话。

## Capabilities

### Modified Capabilities

- `dvt-network-op`：从规范定义推进到可用实现，覆盖会话控制、趋势/连接双视图、过滤器与导出边界。
- `slide6-developer-tools`：新增网络监控子面板完整交互（入口、状态条、三栏布局、控制栏、生命周期回收）。

## Impact

- 代码：
  - `slide6_ui/developer_tools/developer_tools_tab.py`（网络监控入口与子窗口管理）
  - `slide6_ui/developer_tools/`（新增 network monitor dialog / widget）
  - `ios_toolkit/toolkit_api.py`（新增网络会话 open/close/query/export API）
  - `ios_toolkit/device.py`（网络采样句柄、流解析、缓存淘汰、线程回收）
  - `slide6_ui/languages/zh-CN.json`、`slide6_ui/languages/en-US.json`（Network Monitor 文案）
- Spec：
  - `openspec/specs/dvt-network-op/spec.md`
  - `openspec/specs/slide6-developer-tools/spec.md`
- 依赖：不新增第三方依赖，复用现有 `pymobiledevice3` DVT 链路与 UI 基础组件。

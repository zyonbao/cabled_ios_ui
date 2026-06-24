## 变更摘要

新增开发者工具内 Network Monitor 子面板能力，提供实时趋势、连接流与过滤导出闭环。

## 目标模块

slide6-developer-tools / dvt-network-op

## 知识写入目标

`openspec/specs/slide6-developer-tools/spec.md`、`openspec/specs/dvt-network-op/spec.md`

## 架构变更

- 增加网络事件流句柄层（平台）与子面板渲染层（UI）的双层分离。
- 基于 `NetworkMonitor`（事件推送、无设备采样间隔）：复用性能监控的后台 loop + 队列 + 生命周期范式，但去掉采样间隔语义；新增「连接按 `connection_serial` 聚合」「吞吐由连接 update 字节增量聚合」「按远端 IP/接口聚合 TopN」「后台有界队列」。真机确认 `kind` 1=TCP/2=UDP、`pid` 恒为 -2（取消进程维度）。

## 接口变更

- 新增 `open_network_stream(target)`（toolkit 层，返回事件流句柄/错误信封；无设备采样间隔、不做频率校验）。
- 会话控制语义：Start/Stop/Pause/Clear（Pause 仅暂停渲染）。
- 字段映射：协议=kind(1=TCP/2=UDP) 推导、方向=启发式推导、端点=IP:port、错误=tx_retx/rx_dups；不可判定降级 `unknown`。进程维度取消（pid 不可用）。

## 代码路径变更

- `ios_toolkit/device.py`
- `ios_toolkit/toolkit_api.py`
- `slide6_ui/developer_tools/developer_tools_tab.py`
- `slide6_ui/developer_tools/`（新增 network monitor UI）

## 平台支持

- iOS 17+ 依赖现有 tunnel / DVT 底座。
- 字段能力差异按 `unsupported/unknown` 降级展示。

## 设计决策（WHY）

- 将导出边界绑定“当前过滤 + 当前窗口”是为了保证导出数据和屏幕观察一致，降低排障歧义。
- 采用三栏布局是为了符合“进程定位 -> 连接定位 -> 趋势验证”的高频诊断路径。


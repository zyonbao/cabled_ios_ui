## 变更摘要

新增开发者工具内 Network Monitor 子面板能力，提供实时趋势、连接流与过滤导出闭环。

## 目标模块

slide6-developer-tools / dvt-network-op

## 知识写入目标

`openspec/specs/slide6-developer-tools/spec.md`、`openspec/specs/dvt-network-op/spec.md`

## 架构变更

- 增加网络采样句柄层（平台）与子面板渲染层（UI）的双层分离。
- 复用性能监控中的后台采样队列模型，新增连接流数据模型。

## 接口变更

- 新增 `open_network_stream(target, interval_ms)`（toolkit 层）。
- 会话控制语义与性能监控对齐：Start/Stop/Pause/Clear。

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


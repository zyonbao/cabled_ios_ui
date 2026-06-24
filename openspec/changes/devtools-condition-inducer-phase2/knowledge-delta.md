## 变更摘要

新增开发者工具条件诱导子面板，形成状态查询、开始/结束与安全确认的完整操作闭环。

## 目标模块

slide6-developer-tools / dvt-condition-inducer-op

## 知识写入目标

`openspec/specs/slide6-developer-tools/spec.md`、`openspec/specs/dvt-condition-inducer-op/spec.md`

## 架构变更

- 引入 `ConditionInducerHandle`（连接作用域）：持有单一 DVT 连接，统一管理枚举/apply/clear/state 与资源回收。
- 条件为连接作用域、单一活动条件（设备强制）、预定义 profile（无参数化）、无设备侧会话 id——均经真机实测确认。
- UI 子面板与平台句柄通过清晰生命周期边界连接，连接断开设备自动恢复。

## 接口变更

- 新增 `open_condition_inducer(target)`，返回连接作用域句柄；句柄提供 `models/apply/clear/state/close`。
- 能力降级：按设备 `availableConditionInducers` 返回动态渲染可用组/profile（过滤 `isInternal`），缺失组不显示。

## 代码路径变更

- `ios_toolkit/device.py`
- `ios_toolkit/toolkit_api.py`
- `slide6_ui/developer_tools/developer_tools_tab.py`
- `slide6_ui/developer_tools/`（新增 condition inducer UI）

## 平台支持

- 依赖现有 DVT/tunnel 基础设施。
- 不同设备模型能力差异通过降级语义处理。

## 设计决策（WHY）

- 强制开始前确认，是为了降低高风险诱导动作误触概率。
- 关闭窗口自动停止，是为了防止“界面退出但诱导仍生效”的测试污染。


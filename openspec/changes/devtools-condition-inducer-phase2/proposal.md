## Why

当前「开发者工具」缺少条件诱导（Condition Inducer）能力，导致弱网/受限资源等场景测试只能依赖外部手工步骤，难以复现、难以回放，也无法在测试过程中持续观察“当前诱导状态”。

OpenSpec 已定义条件诱导的目标交互（状态展示、条件配置、开始/结束、生命周期绑定与安全提示），但尚未进入实现阶段，需要独立推进以补齐 Phase 2 功能矩阵。

## What Changes

- 在 `DeveloperToolsTab` 增加 Condition Inducer 功能卡片，打开子面板（非独立 sidebar Tab）。
- 实现条件诱导句柄（连接作用域）控制：
  - 枚举设备返回的条件组与 profile（如弱网 / 热状态 / GPU 性能档），过滤 `isInternal` 项；
  - 展示当前状态（未启用 / 已启用 + 条件名称/摘要）；
  - 支持施加 profile、切换（先清后启）与结束诱导；
  - 开始前给出安全确认提示（对 `isDestructive` 显著标注），结束后确保状态回滚与资源回收。
- 单一活动条件：设备同一时刻仅允许一个活动条件，切换 profile MUST 先 `clear` 再 enable。
- 连接作用域 + 生命周期绑定：
  - 条件仅在句柄持有的 DVT 连接存活期间生效，连接断开设备自动恢复；
  - Start 创建并持有连接；Stop `clear()`；关闭窗口 `close()`（先 clear 再断开），防止残留诱导。
- 实现能力降级：
  - 不同设备/系统可用条件组不同，UI 按设备本次返回动态渲染；
  - 缺失组不显示，不影响可用组操作。
- 预留扩展位：
  - 后续可接入预设方案与导入导出（注：Condition Inducer 仅支持预定义 profile，无自定义参数）。

## Capabilities

### Modified Capabilities

- `dvt-condition-inducer-op`：从规范定义推进到可用实现，覆盖状态查询、开始/结束与安全确认。
- `slide6-developer-tools`：新增条件诱导功能卡片与子面板交互，并落实生命周期回收约束。

## Impact

- 代码：
  - `slide6_ui/developer_tools/developer_tools_tab.py`（条件诱导入口与子窗口管理）
  - `slide6_ui/developer_tools/`（新增 condition inducer dialog / widget）
  - `ios_toolkit/toolkit_api.py`（新增 `open_condition_inducer(target)` 入口，返回连接作用域句柄）
  - `ios_toolkit/device.py`（`ConditionInducerHandle`：枚举/apply/clear/state、连接保活与回收逻辑）
  - `slide6_ui/languages/zh-CN.json`、`slide6_ui/languages/en-US.json`（条件诱导文案）
- Spec：
  - `openspec/specs/dvt-condition-inducer-op/spec.md`
  - `openspec/specs/slide6-developer-tools/spec.md`
- 依赖：不新增第三方依赖，复用现有 DVT/tunnel 基础设施。

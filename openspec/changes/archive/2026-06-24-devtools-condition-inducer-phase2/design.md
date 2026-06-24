## Context

Developer Tools 目前已具备性能监控能力，但条件诱导能力仍缺失。弱网/受限资源等验证场景依赖外部手工步骤，无法在同一 UI 中快速启停和确认状态。`dvt-condition-inducer-op` 已定义了状态展示、开始/结束与安全提示语义，当前需要把规范落到平台和 UI。

## Goals / Non-Goals

**Goals**

- 在开发者工具内提供 Condition Inducer 子面板能力。
- 实现 query/start/stop 闭环，状态可见且可追踪。
- 后台诱导任务与窗口生命周期强绑定，避免孤儿任务。
- 在能力差异场景下给出稳定降级语义。

**Non-Goals**

- 本阶段不覆盖所有诱导模型细节（先落地可用模型 + 通用框架）。
- 不实现复杂策略编排（如多条件链式脚本化）。

## 真机/源码实测约束（pymobiledevice3 `ConditionInducer`）

- **连接作用域**：条件仅在持有 DVT 连接期间生效，连接断开设备自动恢复（实测 fresh 连接查到全 inactive）。CLI `condition set` 之后用 `wait_return()` 保活即印证。
- **单一活动条件**：已有活动条件时再次 enable 被设备拒绝（`A condition is already active`, code 3）。切换必须 `disableActiveCondition` 后再 enable。
- **预定义 profile，无参数化**：`enableConditionWithIdentifier:profileIdentifier:` 仅接受 group/profile 两个标识。
- **无设备侧会话 id**：活动状态只能由进程内句柄维护。
- 本机枚举到 3 组：`SlowNetworkCondition`(16)、`ThermalCondition`(3)、`GPUPerformanceState`(3)；group 含 `isActive/isDestructive/isInternal/activeProfile`，profile 含 `identifier/name/description`。

## Decisions

### 决策 1：连接作用域单句柄状态机（替代无状态 query/start/stop）

平台层用 `ConditionInducerHandle` 持有单一 DVT 连接，维护 idle/active(group,profile) 状态，UI 通过句柄读取状态。原因：条件是连接作用域的，无状态独立调用查询不到真实状态，且断开即恢复——必须像 `PerformanceStreamHandle`/`LogStreamHandle` 一样保活。

### 决策 2：单一活动条件 + 切换=先清后启

同一时刻只维护一个活动条件（设备强制）。`apply` 时若已有活动条件，先 `clear()` 再 enable。原因：设备拒绝叠加，跨组叠加不可行。

### 决策 3：开始诱导前强制确认

Start 前显示确认提示（展示条件名称/摘要，`isDestructive` 显著标注），防止误触长时间干扰设备。

### 决策 4：降级=按设备返回动态渲染（不使用 `unsupported` 标记）

UI 仅渲染设备本次 `availableConditionInducers` 返回的可用组/profile（过滤 `isInternal`），缺失组不显示。原因：设备能力差异由枚举结果天然体现，无需额外 unsupported 占位。

## Risks / Trade-offs

- 条件恢复失败导致残留：Stop 与 closeEvent 都执行 `clear()`，并以「断开连接自动恢复」作为最终兜底。
- 标识非法导致 enable 失败：`apply` 前校验 group/profile 标识存在并返回可读错误。
- 连接意外断开（拔线/tunnel 掉）：设备自动恢复，UI 状态需据句柄/流结束事件复位为 idle。
- 用户误解「已结束但尚未恢复」：状态文案明确区分 active / stopping / idle。

## Migration Plan

1. 先实现平台 query/start/stop 基础接口与状态模型。
2. 落地 UI 子面板与安全确认交互。
3. 补齐生命周期回收和降级标注。
4. 真机验证开始/结束/窗口关闭三条路径均无残留诱导。


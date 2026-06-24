## MODIFIED Requirements

### Requirement: 条件模型枚举与连接作用域

平台层 SHALL 提供 `open_condition_inducer(target)`：成功返回与窗口生命周期绑定的句柄（`ConditionInducerHandle`），失败返回可读错误信封。句柄打开时通过 `availableConditionInducers` 枚举设备支持的条件组（`identifier/name/isDestructive/isInternal/activeProfile/profiles[{identifier,name,description}]`），UI MUST 过滤 `isInternal` 项。诱导条件 MUST 为连接作用域：由单一长连接句柄持有 DVT 连接并维护活动状态，连接断开设备 MUST 自动恢复；实现 MUST NOT 以无状态独立调用查询/施加条件。

#### Scenario: 枚举可用条件模型

- **WHEN** 用户进入条件诱导界面
- **THEN** 展示设备返回的可用条件组与各组 profile（已过滤 internal），并显示当前是否有活动条件

### Requirement: 开始 / 切换 / 结束诱导（单一活动条件）

设备 MUST 同一时刻仅允许一个活动条件（已有活动条件时再次 enable 会被设备拒绝）。句柄 SHALL 提供 `apply(group_id, profile_id)`（已有活动条件时先 `clear` 再 enable 切换；标识不存在返回可读错误）、`clear()`（无活动条件时幂等成功）与 `state()`（返回当前 `(group, profile)` 或 `inactive`）。MUST NOT 依赖设备侧会话 id。

#### Scenario: 已有活动条件时切换

- **WHEN** 已有活动条件时用户选择另一 profile 开始
- **THEN** 平台层先停止旧条件再施加新条件，返回新的活动状态

#### Scenario: 无活动条件时结束

- **WHEN** 当前无活动条件，用户点击结束
- **THEN** 返回幂等成功并维持 `inactive` 状态

### Requirement: 能力降级语义

当设备未返回某类条件组时，UI MUST 仅渲染设备本次返回的可用模型并保持可操作，MUST NOT 因缺失某组而整页不可用。

#### Scenario: 设备仅返回部分条件组

- **WHEN** 平台层仅枚举到部分条件组
- **THEN** 已返回的条件组正常展示并可施加，缺失组不显示

# dvt-condition-inducer-op Specification

## Purpose
定义基于 DVT Condition Inducer 的条件诱导能力：枚举设备支持的预定义条件 profile（如弱网 / 热状态 / GPU 性能档），施加 / 切换 / 结束单一活动条件，并保证「连接作用域 + 窗口生命周期」一致的状态反馈与自动恢复。

> 实测约束（真机 + pymobiledevice3 `ConditionInducer`）：
> - 条件为**连接作用域**：仅在持有 DVT 连接期间生效，连接断开设备 MUST 自动恢复（无残留）。
> - 设备**同一时刻仅允许一个活动条件**；已有活动条件时再次 enable 会被设备拒绝（`A condition is already active`）。
> - 条件为**预定义 profile 选择**，无自定义参数（`enable` 仅接受 group/profile 两个标识）。
> - 设备侧**无条件会话 id**；活动状态只在持有连接的进程内句柄中维护。
## Requirements
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

### Requirement: 生命周期绑定与自动恢复

条件诱导句柄/后台连接 MUST 与条件诱导窗口生命周期绑定：打开窗口/开始诱导时创建并持有连接；Stop 时 `clear()` 停止当前条件；窗口关闭时 MUST `close()`（先 `clear()` 再断开连接，并以「断开自动恢复」作为兜底）。实现 MUST NOT 保留脱离窗口生命周期、仍持有连接的孤儿任务。设备切换 MUST 重建句柄（旧条件已随旧连接断开而恢复）。

#### Scenario: 关闭窗口自动结束并恢复

- **WHEN** 条件诱导窗口在诱导进行中被关闭
- **THEN** 句柄执行 `close()` 停止并断开连接，设备条件自动恢复，无残留诱导

### Requirement: UI 交互与安全提示

UI 层 SHALL 提供条件组/profile 选择入口、开始按钮、结束按钮与状态区块；状态区块 MUST 显示当前是否启用及条件名称/摘要。开始前 SHOULD 显示一次确认提示（说明会改变设备运行条件），对 `isDestructive` 组/profile MUST 在确认提示中显著标注。结束后 MUST 刷新状态并清理句柄资源。

#### Scenario: 开始后状态联动刷新

- **WHEN** 用户开始诱导成功
- **THEN** 状态区块立即切换为已启用并展示条件摘要，结束按钮变为可用，开始按钮反映「切换」语义

### Requirement: 能力降级语义

当设备未返回某类条件组时，UI MUST 仅渲染设备本次返回的可用模型并保持可操作，MUST NOT 因缺失某组而整页不可用。

#### Scenario: 设备仅返回部分条件组

- **WHEN** 平台层仅枚举到部分条件组
- **THEN** 已返回的条件组正常展示并可施加，缺失组不显示


# dvt-condition-inducer-op Specification

## Purpose
定义基于 DVT condition inducer 的条件诱导能力：展示当前诱导状态，支持条件选择、开始/结束控制，并保证会话生命周期与状态反馈一致。

## Requirements
### Requirement: 条件模型与状态查询

平台层 SHALL 提供可枚举的诱导条件模型（模板或参数化条件），并提供 `get_condition_state(target)` 返回当前状态：`inactive` 或 `active`（含条件摘要与开始时间）。状态查询 MUST 在设备切换后自动刷新，不阻塞 UI。

#### Scenario: 查询当前状态

- **WHEN** 用户进入条件诱导界面
- **THEN** 显示当前状态及条件摘要（若已启用）

### Requirement: 开始诱导

平台层 SHALL 提供 `start_condition(target, condition_payload)`。调用前 MUST 校验条件参数；非法参数 MUST 返回可读错误。若已有活动诱导会话，重复开始 MUST 先停止旧会话再应用新条件，避免多会话冲突。开始成功后 MUST 立即返回最新状态并记录会话标识。

#### Scenario: 启动条件成功

- **WHEN** 用户选择合法条件并点击开始
- **THEN** 返回 `{ok, data:{state:\"active\", condition_summary, session_id}}`

### Requirement: 结束诱导

平台层 SHALL 提供 `stop_condition(target)`。结束成功后 MUST 返回 `inactive` 状态；无活动会话时 MUST 返回幂等成功（例如 `{ok, data:{already_inactive:true}}`），不得抛异常导致 UI 失败。

#### Scenario: 无活动会话时结束

- **WHEN** 当前未启用任何诱导条件，用户点击结束
- **THEN** 返回幂等成功并维持 `inactive` 状态

### Requirement: UI 交互与安全提示

UI 层 SHALL 提供条件选择入口、开始按钮、结束按钮与状态区块；状态区块 MUST 显示当前是否启用及条件摘要。开始前 SHOULD 显示一次确认提示，说明该操作会改变设备运行条件。结束后 MUST 刷新状态并清理会话资源。

条件诱导执行任务的后台线程/进程 MUST 与条件诱导窗口生命周期绑定：开始诱导时创建并启动；结束诱导时停止并回收；窗口关闭时 MUST 自动停止并回收，防止孤儿线程/进程继续施加条件。

#### Scenario: 开始后状态联动刷新

- **WHEN** 用户开始诱导成功
- **THEN** 状态区块立即切换为已启用并展示条件摘要，结束按钮变为可用

#### Scenario: 关闭窗口自动结束诱导任务

- **WHEN** 条件诱导窗口被关闭
- **THEN** 绑定的诱导后台线程/进程自动停止并回收，状态回到未启用


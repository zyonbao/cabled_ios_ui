## ADDED Requirements

### Requirement: 发现系统中所有活动 tunneld 进程

应用 SHALL 提供发现当前系统中**所有** tunneld 进程的能力，不限于当前配置端口。发现 MUST 通过列举进程命令行实现（如 `ps`），且 MUST NOT 需要管理员权限。匹配 SHALL 按启动形态进行：Python 模式按 tunneld 的 Python 入口（`ios_toolkit.tunneld_main` 模块或 `tunneld_main.py` 文件/路径）匹配；MachO 模式按随包分发的 `cabled_ios_tunnel` 二进制文件/路径匹配。每个被发现的进程 SHALL 解析出 PID、运行用户、监听端口（从 `--port` 解析，解析失败标记为未知）、启动形态与完整命令行。

#### Scenario: 列出多个不同端口的 tunneld

- **WHEN** 系统中存在多个端口号不同的 tunneld 进程
- **THEN** 发现结果包含全部这些进程，并分别给出各自的端口与 PID

#### Scenario: 区分 Python 与 MachO 形态

- **WHEN** 发现到一个由 Python 入口启动的 tunneld 与一个由 `cabled_ios_tunnel` 启动的 tunneld
- **THEN** 前者标记为 Python 形态、后者标记为 MachO 形态

#### Scenario: 发现不需要管理员权限

- **WHEN** 应用执行 tunneld 进程发现
- **THEN** 不弹出任何系统授权框即可列出包括 root 进程在内的匹配进程

#### Scenario: 无活动进程

- **WHEN** 系统中没有任何匹配的 tunneld 进程
- **THEN** 发现结果为空，界面提示未发现活动 tunnel 进程

### Requirement: 多选批量结束 tunneld 且仅一次授权

应用 SHALL 允许用户从活动 tunneld 列表中多选若干进程并批量结束。批量结束 MUST 在**一次**系统授权（管理员密码只输入一次）内完成对所选全部进程的终止：在同一提权上下文内先发送 TERM、对仍存活者再发送 KILL。用于提权的命令字符串 MUST 仅由内部固定推导路径与经校验的正整数 PID 组成，MUST NOT 拼接任何界面或外部自由文本（命令行字段仅用于展示）。批量结束完成后 SHALL 刷新列表；授权被取消或结束失败 MUST NOT 崩溃，应用继续运行并允许重试。

#### Scenario: 批量结束只输入一次密码

- **WHEN** 用户勾选多个 tunneld 进程并点击批量结束
- **THEN** 系统授权框只出现一次
- **AND** 授权通过后所选全部进程在同一提权上下文内被终止（TERM 优先、KILL 兜底）

#### Scenario: 结束 root 进程

- **WHEN** 被选中的 tunneld 以 root 运行
- **THEN** 在该次提权上下文内将其终止

#### Scenario: 结束后刷新

- **WHEN** 批量结束执行完成
- **THEN** 列表刷新，已终止的进程不再出现

#### Scenario: 授权取消或失败

- **WHEN** 用户在系统授权框取消，或终止操作失败
- **THEN** 不崩溃，应用继续运行，列表保持可重试

### Requirement: 活动 tunnel 管理入口仅在开发者工具提供

应用 SHALL 仅在「开发者工具」tab 提供「活动 tunnel 管理」的入口（弹出列表与批量结束）。「诊断」与「键鼠操作」tab MUST NOT 提供该入口，以保持 XPC tunnel 管理的统一入口。

#### Scenario: 仅开发者工具可见

- **WHEN** 用户在「开发者工具」tab
- **THEN** 可见「管理活动 tunnel」入口并能打开管理列表

#### Scenario: 其它 tab 不含该入口

- **WHEN** 用户在「诊断」或「键鼠操作」tab
- **THEN** 界面中不出现活动 tunnel 管理入口

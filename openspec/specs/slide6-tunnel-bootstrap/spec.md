## Purpose

定义 Slide6 桌面应用的 XPC tunnel 引导能力：检测 iOS 17+ 设备所需的 tunnel 端口、按需以系统授权（管理员权限）拉起 tunneld，并在应用退出时按需询问是否停止 tunneld。
## Requirements
### Requirement: 选中 iOS 17+ 设备后检测 XPC tunnel 端口

应用 SHALL 在用户选中设备后、执行 `prepare` 之前，依据设备元数据判定 iOS 主版本；仅当设备为 iOS 17+ 时检测 `ios_toolkit` 使用的 XPC tunnel 端口（`127.0.0.1:49151`）是否有进程在监听。iOS 17 以下设备 SHALL 跳过该检测。当检测到 iOS 17+ 设备且 tunnel 未就绪时，应用 MUST NOT 弹出任何模态对话框、MUST NOT 从当前 tab 自动拉起 tunnel，而是以**非模态**的就地提示（画面区 overlay / 状态文案）引导用户前往「开发者工具」启动 XPC tunnel。

#### Scenario: 选中 iOS 17 以下设备

- **WHEN** 用户选中一台 iOS 主版本低于 17 的设备
- **THEN** 不进行 tunnel 检测、不弹出提示，直接继续 `prepare` 流程

#### Scenario: 选中 iOS 17+ 设备且 tunnel 已就绪

- **WHEN** 用户选中一台 iOS 17+ 设备且 tunnel 端口可连接
- **THEN** 不弹出任何提示，直接继续 `prepare` 流程

#### Scenario: 选中 iOS 17+ 设备且 tunnel 未就绪

- **WHEN** 用户选中一台 iOS 17+ 设备且 tunnel 端口无人监听
- **THEN** 不弹出模态对话框、不自动拉起 tunnel
- **AND** 以非模态就地提示（overlay / 状态栏）说明该功能需要先启用 XPC tunnel，引导用户前往「开发者工具」启动

### Requirement: 经系统授权以管理员权限拉起 tunneld

当用户在「开发者工具」tab 的 tunnel 控制入口点击「启动」时，应用 SHALL 通过 macOS 系统原生授权（osascript，管理员权限）拉起 tunneld，且被执行的命令路径固定、不拼接任何外部输入。tunneld 入口 SHALL 按运行环境解析：在冻结打包环境下执行随包分发的独立 `cabled_ios_tunnel` 二进制（位于 App bundle 内与主二进制同级）；在开发环境下回退为用项目解释器运行 `ios_toolkit.tunneld_main`。该方案为按需拉起，每次启动 tunnel 均触发一次系统授权。tunnel 的拉起 MUST 仅由「开发者工具」这一统一入口发起，其它 tab（诊断 / 键鼠操作）MUST NOT 提供拉起 tunnel 的操作。

#### Scenario: 用户在开发者工具点击启动并授权成功

- **WHEN** 用户在「开发者工具」tunnel 面板点击「启动」并通过系统授权框完成授权
- **THEN** 以管理员权限启动 tunneld
- **AND** 应用轮询 tunnel 端口直至就绪（带超时）后刷新面板为「运行中」

#### Scenario: 冻结环境下使用 bundled 二进制拉起

- **WHEN** 应用以冻结打包形态运行且用户在开发者工具点击启动 tunnel
- **THEN** 用于授权拉起的命令指向 App bundle 内随包分发的 `cabled_ios_tunnel` 二进制
- **AND** 不依赖任何外部 Python 解释器或源码树路径

#### Scenario: 开发环境回退到解释器方式

- **WHEN** 应用以未打包的源码形态运行且用户在开发者工具点击启动 tunnel
- **THEN** 用于授权拉起的命令以项目解释器运行 `ios_toolkit.tunneld_main`

#### Scenario: 每次拉起均需授权

- **WHEN** tunnel 未就绪且用户在开发者工具点击启动
- **THEN** 每一次拉起 tunnel 都会触发一次系统授权框（不做持久化免授权）

#### Scenario: 授权被取消或启动失败

- **WHEN** 用户在系统授权框取消，或 tunneld 启动后端口在超时内仍未就绪
- **THEN** 提示启动失败且不崩溃，应用继续运行，允许用户后续重试

#### Scenario: 其它 tab 不提供拉起入口

- **WHEN** 用户在「诊断」或「键鼠操作」tab 遇到 tunnel 未就绪
- **THEN** 这些 tab 仅给出引导提示，不提供启动 tunnel 的按钮或模态确认，用户需到「开发者工具」启动

### Requirement: 退出时按需询问是否停止 tunneld

应用退出时 SHALL 探测 tunnel 端口是否仍在运行；若在运行，则弹窗让用户选择是否停止 tunneld：用户选择停止才执行 kill，否则保留进程。若端口未在运行，则退出时不弹窗、不动作。

#### Scenario: 退出时 tunnel 在运行且用户选择停止

- **WHEN** 用户退出应用且 tunnel 端口仍在运行，并在弹窗中选择停止
- **THEN** 应用在一次提权操作内解析占用该端口的监听进程并停止它（root 进程的端口需特权 `lsof` 才可见）
- **AND** 停止 root 进程需再次特权，可能触发系统授权

#### Scenario: 退出时 tunnel 在运行但用户选择保留

- **WHEN** 用户退出应用且 tunnel 端口仍在运行，并在弹窗中选择保留
- **THEN** 不停止 tunneld，进程继续运行

#### Scenario: 退出时 tunnel 未运行

- **WHEN** 用户退出应用且 tunnel 端口未在运行
- **THEN** 退出时不弹窗、不尝试停止任何进程

### Requirement: 授权拉起的安全约束

拉起 tunneld 的过程 SHALL 使用系统原生授权框，校验被执行入口的存在性（冻结环境校验 bundled `cabled_ios_tunnel` 二进制，开发环境校验 `tunneld_main.py` 源文件），命令字符串不得包含任何用户输入，且不向该进程传递任何凭据。

#### Scenario: 命令路径固定且校验

- **WHEN** 应用构造用于授权拉起的命令
- **THEN** 命令仅由内部固定推导的二进制/解释器路径与 tunneld 入口组成
- **AND** 不包含任何来自界面或外部的可变输入

#### Scenario: 入口不存在时不弹授权框

- **WHEN** 应用在拉起前校验 tunneld 入口而该入口（冻结环境的 bundled 二进制或开发环境的源文件）不存在
- **THEN** 直接返回失败，不弹出系统授权框

### Requirement: DDI 挂载成功后按需重启 tunnel 刷新开发者服务

iOS 17+ 设备上，开发者服务（如 `com.apple.dt.testmanagerd.remote`）由设备 remoted 在 DDI 挂载后才暴露，且会被枚举进 **XPC tunnel 建立那一刻**的 RSD 服务表；若 tunnel 早于 DDI 挂载建立，其服务表不含这些服务，导致 WDA 报 `No such service: com.apple.dt.testmanagerd.remote`。为此，应用 SHALL 在 iOS 17+ 设备**挂载 DDI 成功后**，当检测到 XPC tunnel 已在运行时，重启该 tunnel，使 RSD 重新枚举此刻可用的开发者服务。

重启 tunnel 必然需要 root，但 MUST 仅触发**一次**系统授权完成「停止旧 tunneld + 重新拉起」：通过单条 `do shell script ... with administrator privileges` 在同一提权上下文内先终止占用端口的旧进程、再以后台方式重新拉起 tunneld，使授权框只出现一次。应用 MUST 先弹窗告知用户挂载已成功、需要重启 XPC tunnel 以启用开发者服务（键鼠 / WDA 等），用户确认后才触发该单次授权；用户取消则不重启，并提示在 tunnel 刷新前键鼠 / WDA 可能不可用。

仅 iOS 17+（`needs_tunnel`）适用；iOS<17 MUST 跳过。若挂载成功时 tunnel **未在运行**，MUST NOT 触发重启。重启失败或用户在系统授权框取消 MUST NOT 崩溃，应用继续运行并允许用户后续手动重试。

#### Scenario: iOS 17+ 挂载成功且 tunnel 已在运行

- **WHEN** iOS 17+ 设备挂载 DDI 成功，且 XPC tunnel 端口已在监听
- **THEN** 弹窗告知用户挂载成功、需要重启 XPC tunnel 以启用开发者服务，并请求管理员授权
- **AND** 用户确认并授权后，应用在**一次**系统授权内完成停止旧 tunneld 与重新拉起，轮询端口就绪后继续 DVT 就绪探测

#### Scenario: 重启仅触发一次授权

- **WHEN** 应用执行 tunnel 重启
- **THEN** 系统授权框只出现一次（停止与重新拉起在同一提权上下文内完成）

#### Scenario: iOS 17+ 挂载成功但 tunnel 未运行

- **WHEN** iOS 17+ 设备挂载 DDI 成功，但 XPC tunnel 端口无人监听
- **THEN** 不弹出重启提示、不触发授权

#### Scenario: iOS<17 挂载成功

- **WHEN** iOS 主版本低于 17 的设备挂载 DDI 成功
- **THEN** 不进行任何 tunnel 重启或提示

#### Scenario: 用户取消重启或授权失败

- **WHEN** 用户在重启提示中取消，或在系统授权框取消、或重启后端口在超时内仍未就绪
- **THEN** 不崩溃，应用继续运行，并提示在 tunnel 刷新前键鼠 / WDA 可能不可用，可稍后手动重启 tunnel 重试

### Requirement: tunnel 停止与重启控制入口

应用 SHALL 仅在 iOS 17+ 设备的「开发者工具」界面提供 XPC tunnel 的启动、停止与重启控制入口（统一入口，经系统授权执行）；「诊断」与「键鼠操作」MUST NOT 提供任何 tunnel 控制入口。停止 MUST 终止占用 tunnel 端口的 root 进程；重启 MUST 复用单次授权语义（停止 + 重新拉起仅一次密码）。控制入口的可见性与状态 MUST 与当前 tunnel 运行状态一致。

#### Scenario: 手动停止 tunnel

- **WHEN** iOS 17+ 设备 tunnel 正在运行，用户在「开发者工具」点击停止并完成授权
- **THEN** tunnel 进程被终止，面板切换为「未启动」

#### Scenario: 手动重启 tunnel 单次授权

- **WHEN** iOS 17+ 设备 tunnel 正在运行，用户在「开发者工具」点击重启
- **THEN** 在一次系统授权内完成停止与重新拉起，端口重新就绪

#### Scenario: 诊断与键鼠不含 tunnel 控制

- **WHEN** 用户进入「诊断」或「键鼠操作」tab
- **THEN** 界面中不出现 tunnel 的启动 / 停止 / 重启控制

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


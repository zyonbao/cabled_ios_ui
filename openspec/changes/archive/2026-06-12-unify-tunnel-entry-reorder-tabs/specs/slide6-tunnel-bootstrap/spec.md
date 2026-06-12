## MODIFIED Requirements

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

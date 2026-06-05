## MODIFIED Requirements

### Requirement: 经系统授权以管理员权限拉起 tunneld

当用户确认启动 tunnel 时，应用 SHALL 通过 macOS 系统原生授权（osascript，管理员权限）拉起 tunneld，且被执行的命令路径固定、不拼接任何外部输入。tunneld 入口 SHALL 按运行环境解析：在冻结打包环境下执行随包分发的独立 `cabled_ios_tunnel` 二进制（位于 App bundle 内与主二进制同级）；在开发环境下回退为用项目解释器运行 `executor_ios.tunneld_main`。该方案为按需拉起，每次启动 tunnel 均触发一次系统授权。

#### Scenario: 用户确认并授权成功

- **WHEN** 用户在提示中点击确认并通过系统授权框完成授权
- **THEN** 以管理员权限启动 tunneld
- **AND** 应用轮询 tunnel 端口直至就绪（带超时）后继续该设备的 `prepare` 流程

#### Scenario: 冻结环境下使用 bundled 二进制拉起

- **WHEN** 应用以冻结打包形态运行且用户确认启动 tunnel
- **THEN** 用于授权拉起的命令指向 App bundle 内随包分发的 `cabled_ios_tunnel` 二进制
- **AND** 不依赖任何外部 Python 解释器或源码树路径

#### Scenario: 开发环境回退到解释器方式

- **WHEN** 应用以未打包的源码形态运行且用户确认启动 tunnel
- **THEN** 用于授权拉起的命令以项目解释器运行 `executor_ios.tunneld_main`

#### Scenario: 每次拉起均需授权

- **WHEN** tunnel 未就绪且用户确认启动
- **THEN** 每一次拉起 tunnel 都会触发一次系统授权框（不做持久化免授权）

#### Scenario: 用户取消提示

- **WHEN** 用户在提示中选择取消
- **THEN** 不启动 tunneld，应用继续运行
- **AND** 提示该 iOS 17+ 设备在 tunnel 就绪前不可用，可重试或改选其他设备

#### Scenario: 授权被取消或启动失败

- **WHEN** 用户在系统授权框取消，或 tunneld 启动后端口在超时内仍未就绪
- **THEN** 提示启动失败且不崩溃，应用继续运行，允许用户后续重试

### Requirement: 授权拉起的安全约束

拉起 tunneld 的过程 SHALL 使用系统原生授权框，校验被执行入口的存在性（冻结环境校验 bundled `cabled_ios_tunnel` 二进制，开发环境校验 `tunneld_main.py` 源文件），命令字符串不得包含任何用户输入，且不向该进程传递任何凭据。

#### Scenario: 命令路径固定且校验

- **WHEN** 应用构造用于授权拉起的命令
- **THEN** 命令仅由内部固定推导的二进制/解释器路径与 tunneld 入口组成
- **AND** 不包含任何来自界面或外部的可变输入

#### Scenario: 入口不存在时不弹授权框

- **WHEN** 应用在拉起前校验 tunneld 入口而该入口（冻结环境的 bundled 二进制或开发环境的源文件）不存在
- **THEN** 直接返回失败，不弹出系统授权框

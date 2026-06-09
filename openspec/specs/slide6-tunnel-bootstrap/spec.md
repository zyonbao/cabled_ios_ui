## Purpose

定义 Slide6 桌面应用的 XPC tunnel 引导能力：检测 iOS 17+ 设备所需的 tunnel 端口、按需以系统授权（管理员权限）拉起 tunneld，并在应用退出时按需询问是否停止 tunneld。
## Requirements
### Requirement: 选中 iOS 17+ 设备后检测 XPC tunnel 端口

应用 SHALL 在用户选中设备后、执行 `prepare` 之前，依据设备元数据判定 iOS 主版本；仅当设备为 iOS 17+ 时检测 `ios_toolkit` 使用的 XPC tunnel 端口（`127.0.0.1:49151`）是否有进程在监听。iOS 17 以下设备 SHALL 跳过该检测。

#### Scenario: 选中 iOS 17 以下设备

- **WHEN** 用户选中一台 iOS 主版本低于 17 的设备
- **THEN** 不进行 tunnel 检测、不弹出提示，直接继续 `prepare` 流程

#### Scenario: 选中 iOS 17+ 设备且 tunnel 已就绪

- **WHEN** 用户选中一台 iOS 17+ 设备且 tunnel 端口可连接
- **THEN** 不弹出任何提示，直接继续 `prepare` 流程

#### Scenario: 选中 iOS 17+ 设备且 tunnel 未就绪

- **WHEN** 用户选中一台 iOS 17+ 设备且 tunnel 端口无人监听
- **THEN** 弹出提示，说明该设备需要 XPC tunnel 并询问是否现在以管理员权限启动

### Requirement: 经系统授权以管理员权限拉起 tunneld

当用户确认启动 tunnel 时，应用 SHALL 通过 macOS 系统原生授权（osascript，管理员权限）拉起 tunneld，且被执行的命令路径固定、不拼接任何外部输入。tunneld 入口 SHALL 按运行环境解析：在冻结打包环境下执行随包分发的独立 `cabled_ios_tunnel` 二进制（位于 App bundle 内与主二进制同级）；在开发环境下回退为用项目解释器运行 `ios_toolkit.tunneld_main`。该方案为按需拉起，每次启动 tunnel 均触发一次系统授权。

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
- **THEN** 用于授权拉起的命令以项目解释器运行 `ios_toolkit.tunneld_main`

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


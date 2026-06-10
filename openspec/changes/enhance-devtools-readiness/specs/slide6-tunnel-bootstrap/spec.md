## MODIFIED Requirements

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

## ADDED Requirements

### Requirement: tunnel 停止与重启控制入口

应用 SHALL 在 iOS 17+ 设备的开发者工具界面提供 XPC tunnel 的停止与重启控制入口（与启动一致经系统授权执行）。停止 MUST 终止占用 tunnel 端口的 root 进程；重启 MUST 复用单次授权语义（停止 + 重新拉起仅一次密码）。控制入口的可见性与状态 MUST 与当前 tunnel 运行状态一致。

#### Scenario: 手动停止 tunnel

- **WHEN** iOS 17+ 设备 tunnel 正在运行，用户点击停止并完成授权
- **THEN** tunnel 进程被终止，面板切换为「未启动」

#### Scenario: 手动重启 tunnel 单次授权

- **WHEN** iOS 17+ 设备 tunnel 正在运行，用户点击重启
- **THEN** 在一次系统授权内完成停止与重新拉起，端口重新就绪

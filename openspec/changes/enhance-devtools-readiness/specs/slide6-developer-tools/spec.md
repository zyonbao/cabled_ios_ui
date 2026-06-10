## MODIFIED Requirements

### Requirement: 功能位 grid 与 DDI 门控

「开发者工具」Tab SHALL 以功能位 grid 展示「进程管理」「虚拟定位」两个能力卡片（布局便于后续扩展）。DDI 未挂载时所有功能位 MUST 置为 Disabled；DDI 挂载成功后 MUST 自动 enable。点击 DVT 相关功能位前，应用 MUST 应用统一的设备就绪前置检查（见 `slide6-device-readiness`）：未就绪时 MUST 给出可操作引导（缺 tunnel / 缺 DDI / RSD 不工作）而非直接失败。

#### Scenario: 未挂载禁用

- **WHEN** DDI 未挂载
- **THEN** 进程管理、虚拟定位功能位均不可点击，并提示需先挂载 DDI

#### Scenario: 挂载后启用

- **WHEN** DDI 挂载成功
- **THEN** 进程管理、虚拟定位功能位自动变为可用

#### Scenario: 就绪未通过时引导

- **WHEN** 功能位可点击但就绪检查未通过（如 iOS 17+ 缺 tunnel 或 RSD 服务不工作）
- **THEN** 应用给出对应的可操作引导，不直接失败

## ADDED Requirements

### Requirement: iOS 17+ XPC tunnel 状态面板

「开发者工具」Tab 顶部的 XPC tunnel 区块 SHALL 仅对 iOS 17+ 设备展示；iOS 17 以下 MUST 隐藏。该面板 MUST 反映当前 tunnel 运行状态并据此切换控制：未启动时提供「启动」按钮；已启动时提供「停止」与「重启」按钮。三者 MUST 复用系统授权（osascript）逻辑并经 `AsyncRunner` 在工作线程执行，操作进行中 MUST 禁用相应按钮、给出状态提示。

#### Scenario: iOS 17+ 未启动 tunnel

- **WHEN** iOS 17+ 设备且 tunnel 未运行
- **THEN** 面板显示「未启动」与「启动」按钮

#### Scenario: iOS 17+ 已启动 tunnel

- **WHEN** iOS 17+ 设备且 tunnel 正在运行
- **THEN** 面板显示「已启动」与「停止」「重启」按钮

#### Scenario: iOS 17 以下隐藏面板

- **WHEN** 选中 iOS 17 以下设备
- **THEN** 不展示 XPC tunnel 状态面板

### Requirement: 状态文案不撑宽窗口

「开发者工具」Tab 底部的状态 / 错误文案 MUST NOT 因内容变长而改变窗口宽度。文案超过 3 行时 MUST 对尾部做省略（`…`）；窗口宽度变化时 MUST 按当前宽度重新计算省略。完整文案 SHOULD 可经悬浮提示（tooltip）查看。

#### Scenario: 长文案不撑宽

- **WHEN** 底部出现很长的错误文案
- **THEN** 窗口宽度不变，文案在 3 行内按尾部省略显示

#### Scenario: 改变窗口宽度后重排

- **WHEN** 用户调整窗口宽度
- **THEN** 文案按新宽度重新计算 3 行省略

### Requirement: 子功能弹窗非模态

「开发者工具」的子功能窗口（进程管理 / 虚拟定位等）MUST 以非模态方式打开，允许同时打开多个并各自独立操作；MUST NOT 因某个子窗口未关闭而阻塞主界面或其他子窗口。应用退出 / 设备清理时 MUST 一并关闭这些子窗口。

#### Scenario: 同时打开多个子功能窗口

- **WHEN** 用户先后打开进程管理与虚拟定位（或多个同类）窗口
- **THEN** 多个窗口可同时存在并各自独立操作，主界面不被阻塞

#### Scenario: 退出时关闭子窗口

- **WHEN** 应用退出或设备被清理
- **THEN** 已打开的子功能窗口被一并关闭，无悬挂窗口

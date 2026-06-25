# slide6-developer-tools (delta)

## MODIFIED Requirements

### Requirement: iOS 17+ XPC tunnel 状态面板

「开发者工具」Tab 顶部的 XPC tunnel 区块 SHALL 仅对 iOS 17+ 设备展示；iOS 17 以下 MUST 隐藏。该面板 MUST 反映当前 tunnel 运行状态并据此切换控制：未启动时提供「启动」按钮；已启动时提供「停止」与「重启」按钮。三者 MUST 复用系统授权（osascript）逻辑并经 `AsyncRunner` 在工作线程执行，操作进行中 MUST 禁用相应按钮、给出状态提示。

tunnel 状态变化后，面板标签、按钮组，以及依赖 tunnel 的功能位门控 MUST 立即联动刷新，不得要求用户再手动点击一次"刷新状态"才能恢复正确 UI。

该面板的「刷新状态」按钮点击时，除重读 tunnel 运行状态外，MUST 重跑设备就绪检查并据结果刷新依赖 tunnel 的功能位门控（与 DDI「刷新状态」一致）：iOS 17+ 在 tunnel 运行且 DDI 已挂载时 MUST 重新探测 RSD/DVT 服务可用性，再据结果刷新门控；tunnel 未运行时 MUST 清除过期的就绪态，使功能位保持禁用。MUST NOT 仅用缓存的就绪态重绘而漏掉 tunnel 自上次探测后的状态变化。

#### Scenario: iOS 17+ 未启动 tunnel

- **WHEN** iOS 17+ 设备且 tunnel 未运行
- **THEN** 面板显示「未启动」与「启动」按钮

#### Scenario: iOS 17+ 已启动 tunnel

- **WHEN** iOS 17+ 设备且 tunnel 正在运行
- **THEN** 面板显示「已启动」与「停止」「重启」按钮

#### Scenario: 停止 tunnel 后立即刷新面板

- **WHEN** 用户点击「停止」且 tunnel 已停止
- **THEN** 面板立即更新为「未启动」状态，并显示「启动」按钮
- **AND** 依赖 tunnel 的功能位门控与状态提示同步刷新
- **AND** 不要求用户再手动点击"刷新状态"

#### Scenario: 手动刷新 tunnel 状态联动门控

- **WHEN** iOS 17+ 设备 DDI 已挂载，用户在 tunnel 面板点击「刷新状态」
- **THEN** 重新读取 tunnel 运行状态并重跑就绪检查
- **AND** tunnel 运行时重新探测 RSD/DVT 并据结果刷新功能位门控（就绪则解锁功能位）
- **AND** tunnel 未运行时功能位保持禁用（清除过期就绪态）

#### Scenario: iOS 17 以下隐藏面板

- **WHEN** 选中 iOS 17 以下设备
- **THEN** 不展示 XPC tunnel 状态面板

## ADDED Requirements

### Requirement: DVT 连接底座

平台层 SHALL 提供内部 DVT 连接辅助，按 iOS 版本选择 service provider：iOS<17 经 usbmux lockdown，iOS 17+ 经 tunneld 的 RSD（复用 `_get_rsd_from_tunneld`）。当 iOS 17+ 且无法获取 RSD 时，MUST 返回可读错误，提示需先启动 XPC tunnel。所有 DVT 能力 MUST 要求 DDI 已挂载（未挂载时由 `pymobiledevice3` 抛错并以可读信封回传）。

#### Scenario: iOS 17+ 缺少 tunnel

- **WHEN** iOS 17+ 设备未运行 XPC tunnel 时调用任一 DVT 能力
- **THEN** 返回可读错误，提示先启动 XPC tunnel，而非 generic error

### Requirement: 列出进程

平台层 SHALL 提供 `list_processes(target)`，经 `DeviceInfo.proclist()` 返回当前进程列表，每项至少包含 `pid` 与 `name`，存在时一并返回 `realAppName`/`isApplication`/`startDate`。

#### Scenario: 列表成功

- **WHEN** DDI 已挂载（iOS 17+ 且 tunnel 已起）
- **THEN** 返回 `{ok, data:{processes:[{pid,name,...}, ...]}}`

### Requirement: 按 bundle id 启动进程

平台层 SHALL 提供 `launch_app_dvt(target, bundle_id)`，经 `ProcessControl.launch(bundle_id)` 启动应用并返回新进程 pid。空 bundle id MUST 返回 `BAD_TARGET`。

#### Scenario: 启动成功

- **WHEN** 提供合法 bundle id
- **THEN** 启动应用并返回 `{ok, data:{pid}}`

### Requirement: 杀进程

平台层 SHALL 提供 `kill_process(target, pid)`，经 `ProcessControl.kill(pid)` 终止指定进程。非法 pid MUST 返回 `BAD_TARGET`。

#### Scenario: kill 成功

- **WHEN** 提供存在的 pid
- **THEN** 终止该进程并返回 `{ok, data:{killed:true, pid}}`

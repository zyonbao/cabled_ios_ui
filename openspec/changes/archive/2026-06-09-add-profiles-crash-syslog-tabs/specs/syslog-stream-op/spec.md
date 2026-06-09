## ADDED Requirements

### Requirement: 提供系统日志流来源

平台能力层 SHALL 暴露两类设备系统日志实时流来源，供桌面应用的流线程消费，且 MUST NOT 依赖 WDA 或 XPC tunnel：

- `syslog`：基于 `SyslogService.watch()`，逐行产出原始 syslog 文本。
- `oslog`：基于 `OsTraceService.syslog()`，产出结构化条目（含 pid / subsystem / category / level / 消息），格式化为可读单行文本。

来源构造 MUST 接受目标 UDID，并支持被调用方随时取消 / 关闭，对应的 lockdown 连接在停止时 MUST 被释放。

#### Scenario: 订阅 syslog 流

- **WHEN** 以有效设备为 `syslog` 来源建立订阅
- **THEN** 随设备产生日志，订阅方持续收到逐行文本

#### Scenario: 订阅 oslog 流

- **WHEN** 以有效设备为 `oslog` 来源建立订阅
- **THEN** 订阅方持续收到结构化条目格式化后的单行文本（含 pid / subsystem / level）

#### Scenario: 停止订阅释放连接

- **WHEN** 调用方请求停止某个已建立的日志流
- **THEN** 流停止产出新行，且底层 lockdown 连接被关闭，无悬挂任务

### Requirement: 日志流错误以信号形式上报

当日志流建立失败或中途中断（如设备断开、所选来源在该设备不可用）时，来源 MUST 以错误形式通知订阅方，而非静默挂起或令应用崩溃。`oslog` 在特定设备 / 系统版本不可用时 MUST 以此机制回退，且不影响应用其余功能。

#### Scenario: 流来源不可用

- **WHEN** 在不支持的设备上建立 `oslog` 流
- **THEN** 订阅方收到一次错误通知，流进入停止态，应用其余功能不受影响

#### Scenario: 设备中途断开

- **WHEN** 活动日志流期间设备断开连接
- **THEN** 订阅方收到一次错误通知，流停止

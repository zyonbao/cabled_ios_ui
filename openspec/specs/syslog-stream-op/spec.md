# syslog-stream-op Specification

## Purpose
TBD - created by archiving change add-profiles-crash-syslog-tabs. Update Purpose after archive.
## Requirements
### Requirement: 提供系统日志流来源

平台能力层 SHALL 暴露两类设备系统日志实时流来源，供桌面应用的流线程消费，且 MUST NOT 依赖 WDA 或 XPC tunnel：

- `syslog`：基于 `SyslogService.watch()`，逐行产出原始 syslog 文本。
- `oslog`：基于 `OsTraceService.syslog()`，产出**结构化条目**（`SyslogEntry`：timestamp / pid / level / image_name / filename / message，以及取自 `label` 的 subsystem / category，后者可为空）。来源 MUST 向订阅方透传结构化字段（而非仅预格式化字符串），以支撑上层的列视图、行明细查看与按字段过滤；同时附带一个可读单行显示串供文本场景使用。

`oslog` 来源 SHALL 接受 `OsTraceService.syslog` 的真实读取参数：`pid`（int，默认 -1=全部进程）、`message_filter`（int 级别/类型位掩码，默认 65535=全部）、`stream_flags`（int 位掩码，见 `OsActivityStreamFlag`），未指定时使用各自默认值产出全部条目。注意 `message_filter` 为级别/类型掩码而非文本，因此「按 message 文本或 image_name 等字段过滤」属消费侧职责，不在源头参数内。来源构造 MUST 接受目标 UDID，并支持被调用方随时取消 / 关闭；停止时对应的 lockdown 连接与底层流任务 MUST 被干净释放，且 MUST 可被反复建立 / 关闭而不残留半关闭连接或悬挂任务。

#### Scenario: 订阅 syslog 流

- **WHEN** 以有效设备为 `syslog` 来源建立订阅
- **THEN** 随设备产生日志，订阅方持续收到逐行文本

#### Scenario: 订阅 oslog 流并获得结构化条目

- **WHEN** 以有效设备为 `oslog` 来源建立订阅
- **THEN** 订阅方持续收到结构化条目（含 pid / subsystem / level 等字段）及其可读单行显示串

#### Scenario: 按 pid 过滤 oslog

- **WHEN** 以指定 pid 过滤参数订阅 `oslog`
- **THEN** 订阅方仅收到该 pid 相关的条目（源头或消费侧过滤，结果等价）

#### Scenario: 反复停止 / 重建释放连接

- **WHEN** 调用方对同一设备反复建立并停止日志流
- **THEN** 每次停止后底层 lockdown 连接被关闭、无悬挂任务，后续重建仍能正常产出

### Requirement: 日志流错误以信号形式上报

当日志流建立失败或中途中断（如设备断开、所选来源在该设备不可用）时，来源 MUST 以错误形式通知订阅方，而非静默挂起或令应用崩溃。`oslog` 在特定设备 / 系统版本不可用时 MUST 以此机制回退，且不影响应用其余功能。

#### Scenario: 流来源不可用

- **WHEN** 在不支持的设备上建立 `oslog` 流
- **THEN** 订阅方收到一次错误通知，流进入停止态，应用其余功能不受影响

#### Scenario: 设备中途断开

- **WHEN** 活动日志流期间设备断开连接
- **THEN** 订阅方收到一次错误通知，流停止

### Requirement: 收集设备日志为 logarchive

平台能力层 SHALL 提供一次性的设备日志收集能力，将 oslog 数据收集并输出为 `.logarchive`（经 `OsTraceService` 的归档收集接口），供桌面应用导出。该能力 MUST 接受目标 UDID 与输出位置，MUST NOT 依赖 WDA / XPC tunnel，且与正在进行的实时流相互独立（互不干扰）。当设备 / 库不支持归档收集时 MUST 以错误形式上报而非崩溃。

#### Scenario: 收集 logarchive

- **WHEN** 调用方请求对某设备收集日志归档并指定输出位置
- **THEN** 平台层产出 `.logarchive` 于该位置；若同时存在实时流，二者互不影响

#### Scenario: 不支持归档时报错

- **WHEN** 设备或底层库不支持日志归档收集
- **THEN** 以错误形式返回，应用不崩溃


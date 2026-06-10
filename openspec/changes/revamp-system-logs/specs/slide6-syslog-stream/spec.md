## MODIFIED Requirements

### Requirement: 系统日志入口与来源选择

桌面应用 SHALL 将系统日志由独立 sidebar tab 迁移为「开发者工具」tab 内的独立日志区块（作为可扩展 Grid 的一部分）。系统日志 MUST NOT 再作为独立 sidebar tab 注册。入口按设备主版本分流且不再提供来源下拉框：iOS 17+ 设备 SHALL 仅暴露 `oslog` 入口，iOS 17 以下设备 SHALL 仅暴露 `syslog` 入口。日志区块 MUST 响应设备切换；未选中设备时 MUST NOT 启动任何流。

#### Scenario: iOS 17+ 暴露 oslog 入口

- **WHEN** 选中一台 iOS 17+ 设备并进入开发者工具的日志区块
- **THEN** 仅提供 `oslog` 入口（不显示来源下拉），开始后追加 oslog 实时日志

#### Scenario: iOS 17 以下暴露 syslog 入口

- **WHEN** 选中一台 iOS 17 以下设备并进入开发者工具的日志区块
- **THEN** 仅提供 `syslog` 入口（不显示来源下拉），开始后追加 syslog 实时日志

#### Scenario: 未选择设备不启动

- **WHEN** 未选中设备
- **THEN** 日志区块不启动任何流，并提示需先选择设备

### Requirement: 暂停 / 清空 / 另存

日志区块 SHALL 提供暂停、清空、另存三个控制：暂停 MUST 停止向视图渲染新行；清空 MUST 清空视图与缓冲；另存 MUST 将当前视图文本写入用户选择的本地文本文件。日志 MUST NOT 在用户未显式另存时自动落盘。开始/停止与暂停/继续的状态 MUST 联动：当用户停止流或切换设备时，暂停状态 MUST 复位（按钮回到「暂停」、`_paused` 为假），使下次开始处于非暂停态。

#### Scenario: 暂停渲染

- **WHEN** 用户点击暂停
- **THEN** 视图停止追加新行，后台采集不影响（再次开始后恢复）

#### Scenario: 停止后暂停状态复位

- **WHEN** 用户在暂停态下点击停止（或切换设备）后再次开始
- **THEN** 暂停按钮已复位为「暂停」、流以非暂停态正常输出新行

#### Scenario: 清空视图

- **WHEN** 用户点击清空
- **THEN** 视图与缓冲被清空

#### Scenario: 另存为文本

- **WHEN** 用户点击另存并选择目标文件
- **THEN** 当前视图文本写入该本地文件

## ADDED Requirements

### Requirement: 反复启停不丢失响应

日志区块的开始 / 停止 MUST 可反复操作而不进入无响应态：每次停止 MUST 干净释放后台采集线程、底层流任务与连接；每次开始 MUST 基于全新的流句柄。连续「开始→停止」多次后再次开始 MUST 仍能正常输出日志，无需重选设备或刷新状态。

#### Scenario: 连续启停后仍可开始

- **WHEN** 用户对同一设备连续执行多次「开始→停止」后再次点击开始
- **THEN** 视图重新开始追加实时日志，状态正常，无需重选设备

### Requirement: oslog 独立列视图、列选择、读取驱动过滤与导出

`oslog` 入口 MUST NOT 复用 syslog 的单行文本视图，SHALL 以**多列表格视图**呈现结构化日志，列取自 `SyslogEntry`：`pid`、`timestamp`、`level`、`filename`、`image_name`、`message`、`subsystem`、`category`。oslog 视图 SHALL 支持点击某条日志行查看其**完整结构化内容**（含上述全部字段与完整 message）。syslog 入口 MUST NOT 显示以下 oslog 专有控件。

**列选择（眼睛图标）**：表格上方 SHALL 提供一个眼睛图标按钮，点击弹出含上述 8 个字段复选框的浮窗；勾选并确认后 SHALL 即时更新表格的可见列（隐藏未勾选列、显示已勾选列）。列选择 MUST 为纯显示态，不影响采集与过滤数据。

**filter（眼睛右侧）**：SHALL 由「只读条件文本展示区 + filter 图标按钮」组成。点击 filter 图标 SHALL 弹出上述字段的输入浮窗；提交时每个字段 `strip()` 后为空者 MUST NOT 生效；生效字段 SHALL 以 `key=value&key=value`（如 `pid=1127&image_name=safari`）显示在条件文本区。与 syslog 的「仅对显示做过滤」不同，oslog filter MUST 驱动**读取**：`pid`（及可选 stream/level 掩码）下推到 `OsTraceService.syslog(pid=…, message_filter=…, stream_flags=…)` 并重新订阅流；其余字段（`image_name`/`filename`/`subsystem`/`category`/`message`/`level`）作为结构化条目的消费侧谓词。条件变更后视图 SHALL 相应重建。

**导出（对应 syslog 另存）**：oslog 入口 SHALL 提供「导出」按钮，点击 SHALL 在按钮位置弹出小浮窗，提供「导出为文本」与「导出为 `.logarchive`」两项；文本导出写出当前过滤后可见行，`.logarchive` 导出经平台层归档收集写入用户选择位置且 MUST NOT 影响正在进行的实时流。

#### Scenario: oslog 以多列表格呈现

- **WHEN** 用户在 oslog 入口开始日志流
- **THEN** 日志以多列表格显示（pid / timestamp / level / filename / image_name / message / subsystem / category），而非单行文本

#### Scenario: 眼睛图标选择可见列

- **WHEN** 用户点击眼睛图标并勾选/取消某些字段后确认
- **THEN** 表格即时仅显示已勾选的列，其余列隐藏

#### Scenario: filter 驱动读取并显示条件

- **WHEN** 用户点击 filter 图标，输入 `pid=1127`、`image_name=safari`（其余留空）并提交
- **THEN** 条件文本区显示 `pid=1127&image_name=safari`；应用以 `pid=1127` 重新订阅 oslog 流，并对条目按 `image_name` 含 `safari` 做消费侧过滤；清除条件后恢复全量

#### Scenario: 查看日志行结构化明细

- **WHEN** 用户点击 oslog 表格中的一条日志行
- **THEN** 展示该行的完整结构化字段（时间戳 / pid / 进程·镜像名 / subsystem / category / level / 完整 message）

#### Scenario: 导出浮窗选择文本或 logarchive

- **WHEN** 用户点击 oslog 「导出」按钮
- **THEN** 在按钮位置弹出浮窗含「导出为文本」「导出为 `.logarchive`」；选择后分别写出文本或收集 `.logarchive` 到所选位置，期间实时流不受影响

#### Scenario: syslog 入口不含 oslog 专有控件

- **WHEN** 在 iOS 17 以下设备的 syslog 入口
- **THEN** 不显示列视图 / 眼睛列选择 / filter 浮窗 / 导出浮窗等 oslog 专有控件（保留 syslog 现有文本视图与关键字过滤、另存为文本）

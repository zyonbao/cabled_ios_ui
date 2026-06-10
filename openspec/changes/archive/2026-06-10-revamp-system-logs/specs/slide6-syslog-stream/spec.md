## MODIFIED Requirements

### Requirement: 系统日志独立 Tab 与来源选择

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

日志区块 SHALL 提供暂停、清空、另存三个控制：暂停 MUST 停止向视图渲染新行；清空 MUST 清空视图与缓冲；另存 MUST 将当前视图文本写入用户选择的本地文本文件。日志 MUST NOT 在用户未显式另存时自动落盘。开始/停止与暂停/继续的状态 MUST 严格联动：

- 当「开始/停止」处于**待开始（"开始"）**态（未运行）时，「暂停/继续」MUST 为**「暂停」且禁用**；
- 当「开始/停止」处于**待停止（"停止"）**态（运行中）时，「暂停/继续」MUST **启用**，可在「暂停」/「继续」间切换；
- 停止流或切换设备时，暂停状态 MUST 复位（按钮回到「暂停」、禁用、`_paused` 为假），使下次开始处于非暂停态。

#### Scenario: 暂停渲染

- **WHEN** 用户点击暂停
- **THEN** 视图停止追加新行，后台采集不影响（再次开始后恢复）

#### Scenario: 暂停按钮随运行态启用/禁用

- **WHEN** 流未运行（按钮显示「开始」）
- **THEN**「暂停/继续」为「暂停」且禁用；点击「开始」运行后该按钮启用、可切换

#### Scenario: 停止后暂停状态复位

- **WHEN** 用户在暂停（「继续」）态下点击停止（或切换设备）后再次开始
- **THEN** 暂停按钮已复位为「暂停」且在停止后禁用、再次开始时启用，流以非暂停态正常输出新行

#### Scenario: 清空视图

- **WHEN** 用户点击清空
- **THEN** 视图与缓冲被清空

#### Scenario: 另存为文本

- **WHEN** 用户点击另存并选择目标文件
- **THEN** 当前视图文本写入该本地文件

## ADDED Requirements

### Requirement: 实时日志内存按字节封顶

syslog 与 oslog 的实时日志缓冲 SHALL 按**字节预算**（约 10MB）限制内存占用，而非按固定行数。超出预算时 SHALL 从最旧条目开始淘汰直至回到预算内，且 oslog 表格视图持有的结构化对象 MUST 随之释放（视图与缓冲保持一致，真正回收内存）。切换设备 SHALL 清空当前缓冲与视图。应用 MUST NOT 为实时日志做磁盘缓存或无限内存保留；完整历史经文本 / `.logarchive` 导出获取。

#### Scenario: 高频日志下内存有界

- **WHEN** 设备持续产生大量日志，累计远超内存预算
- **THEN** 最旧条目被淘汰，内存占用稳定在约 10MB 预算内，UI 仍可滚动查看预算内的历史

#### Scenario: 切换设备清空缓冲

- **WHEN** 用户切换所选设备
- **THEN** 当前日志缓冲与视图被清空，不残留上一设备的日志或其占用的内存

### Requirement: 反复启停不丢失响应

日志区块的开始 / 停止 MUST 可反复操作而不进入无响应态：每次停止 MUST 干净释放后台采集线程、底层流任务与连接；每次开始 MUST 基于全新的流句柄。连续「开始→停止」多次后再次开始 MUST 仍能正常输出日志，无需重选设备或刷新状态。

#### Scenario: 连续启停后仍可开始

- **WHEN** 用户对同一设备连续执行多次「开始→停止」后再次点击开始
- **THEN** 视图重新开始追加实时日志，状态正常，无需重选设备

### Requirement: oslog 独立列视图、列选择、读取驱动过滤与导出

`oslog` 入口 MUST NOT 复用 syslog 的单行文本视图，SHALL 以**多列表格视图**呈现结构化日志（为高吞吐流的响应性，SHALL 采用按需渲染的 model/view，而非逐单元格构造）。列取自 `SyslogEntry`，按顺序：`pid`、`timestamp`、`level`、`filename`、`image_name`、`subsystem`、`category`、`message`（`subsystem` 位于 `message` 之前，`message` 为末列且最宽）。**默认仅显示 `message` 列**，其余列默认隐藏（经眼睛图标按需开启）。oslog 视图 SHALL 支持双击某条日志行查看其**完整结构化内容**（含上述全部字段与完整 message）。syslog 入口 MUST NOT 显示以下 oslog 专有控件。

**列选择（眼睛图标）**：表格上方 SHALL 提供一个眼睛图标按钮，点击弹出含上述 8 个字段复选框的浮窗；勾选并确认后 SHALL 即时更新表格的可见列（隐藏未勾选列、显示已勾选列）。列选择 MUST 为纯显示态，不影响采集与过滤数据。

**filter（眼睛右侧）**：SHALL 为一个**点击即弹字段输入浮窗**的左对齐按钮（与 syslog 直接点击输入相对应，oslog 点击弹 popup）。浮窗提交时每个字段 `strip()` 后为空者 MUST NOT 生效；生效字段 SHALL 以 `key=value&key=value`（如 `pid=1127&image_name=safari`）显示在该按钮上，文本一行放不下时 SHALL tail 省略（`…`），完整条件串在 tooltip。与 syslog 的关键字过滤一致，oslog filter **仅作用于当前内存缓冲的显示**：8 个字段（含 `pid`）一律大小写不敏感子串匹配结构化条目，MUST NOT 重新订阅实时流或丢弃已采集历史；条件变更后视图 SHALL 据当前缓冲重建。

**导出（对应 syslog 另存）**：oslog 入口 SHALL 提供「导出」按钮，点击 SHALL 在按钮位置弹出小浮窗，提供「导出为文本」与「导出为 `.logarchive`」两项；文本导出写出当前过滤后可见行，`.logarchive` 导出经平台层归档收集写入用户选择位置且 MUST NOT 影响正在进行的实时流。

#### Scenario: oslog 以多列表格呈现

- **WHEN** 用户在 oslog 入口开始日志流
- **THEN** 日志以多列表格显示（列序 pid / timestamp / level / filename / image_name / subsystem / category / message），而非单行文本；默认仅 `message` 列可见

#### Scenario: 高吞吐流不阻塞 UI

- **WHEN** 设备产生高频 oslog（每秒大量条目）
- **THEN** 视图按需渲染、批量插入并仅在已处于底部时自动滚动，主线程保持响应，不出现界面无响应

#### Scenario: 眼睛图标选择可见列

- **WHEN** 用户点击眼睛图标并勾选/取消某些字段后确认
- **THEN** 表格即时仅显示已勾选的列，其余列隐藏（默认仅 `message` 勾选）

#### Scenario: filter 筛选内存日志并显示条件

- **WHEN** 用户点击 filter 按钮，输入 `pid=1127`、`image_name=safari`（其余留空）并提交
- **THEN** 按钮上显示 `pid=1127&image_name=safari`（过长则 tail 省略 `…`、tooltip 为完整串）；视图仅显示内存缓冲中 `pid` 含 `1127` 且 `image_name` 含 `safari` 的条目；实时流不重订阅、历史不丢失；清除条件后恢复显示全部缓冲

#### Scenario: 查看日志行结构化明细

- **WHEN** 用户点击 oslog 表格中的一条日志行
- **THEN** 展示该行的完整结构化字段（时间戳 / pid / 进程·镜像名 / subsystem / category / level / 完整 message）

#### Scenario: 导出浮窗选择文本或 logarchive

- **WHEN** 用户点击 oslog 「导出」按钮
- **THEN** 在按钮位置弹出浮窗含「导出为文本」「导出为 `.logarchive`」；选择后分别写出文本或收集 `.logarchive` 到所选位置，期间实时流不受影响

#### Scenario: syslog 入口不含 oslog 专有控件

- **WHEN** 在 iOS 17 以下设备的 syslog 入口
- **THEN** 不显示列视图 / 眼睛列选择 / filter 浮窗 / 导出浮窗等 oslog 专有控件（保留 syslog 现有文本视图与关键字过滤、另存为文本）

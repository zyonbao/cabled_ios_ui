## Why

「系统日志」目前是独立的 sidebar tab，syslog/oslog 仅靠下拉切换、oslog 能力很弱（只有关键字过滤、单行只读文本），且存在两个明显 bug：开始/停止与暂停/继续按钮状态不联动、反复开始结束几次后再开始无响应。日志属于诊断能力，更适合并入「开发者工具」并按设备版本拆成两个独立入口，同时把 oslog 做成可过滤、可导出、可查看结构化明细的实用工具。

## What Changes

- **BREAKING（UI 结构）**：移除独立的「系统日志」sidebar tab，将系统日志改为「开发者工具」tab 内的一个独立区块（Grid 入口）。按设备版本只暴露一个入口：iOS 17+ 显示 **oslog**，iOS 17 以下显示 **syslog**（不再用下拉框切换来源）。
- syslog 入口：保留现有展示逻辑（实时流 / 关键字过滤 / 暂停 / 清空 / 另存为文本，单行只读文本视图）。
- oslog 入口：**不复用 syslog 的单行文本视图**，改为独立的**多列表格视图**，列取自结构化 `SyslogEntry`：`pid / timestamp / level / filename / image_name / message / subsystem / category`。在此之上提供：
  - **列选择（眼睛图标）**：表格上方一个眼睛图标按钮，点击弹出复选框浮窗，可勾选上述 8 个字段的任意子集，确认后即时更新表格可见列。
  - **filter（眼睛右侧）**：一个点击即弹字段输入浮窗的左对齐按钮（与 syslog 直接点击输入相对应）。浮窗 strip 后为空的字段不生效；生效字段以 `k=v&k=v`（如 `pid=1127&image_name=safari`）显示在按钮上，过长则 tail 省略（`…`）、完整串在 tooltip。与 syslog 的关键字过滤一致，oslog filter **仅筛当前内存缓冲做显示**（8 字段含 pid 皆子串匹配），不重订阅实时流、不丢历史。
  - **导出（对应 syslog 的另存）**：点击导出按钮在按钮位置弹出小浮窗，可选「导出为文本」或「导出为 `.logarchive`」（后者经 `OsTraceService` 归档收集）。
  - **点击日志行查看完整结构化明细**（时间戳 / pid / 进程·镜像名 / subsystem / category / level / 完整 message 等）。
- **Bug 修复 #3**：开始/停止 与 暂停/继续 联动——点「停止/重新开始」时复位暂停状态与按钮文案。
- **Bug 修复 #4**：反复开始结束后再开始无响应——定位并修复日志流停止时的内部状态/底层连接未干净取消问题，使每次重新开始都能恢复输出。
- 平台能力层 `open_log_stream` 增强：oslog 向源头透传 `pid`（int，-1=全部）、`message_filter`（int 级别/类型位掩码）、`stream_flags`（int，见 `OsActivityStreamFlag`）三个真实参数，并向上传递**结构化条目**（`SyslogEntry`：pid/timestamp/level/image_name/filename/message/label.subsystem/label.category，而非仅预格式化字符串）以支撑列视图与行明细；新增 `.logarchive` 收集入口（`OsTraceService.collect/create_archive`）；保证停止时连接与任务干净释放。

## Capabilities

### Modified Capabilities

- `slide6-syslog-stream`: 由独立 sidebar tab 改为「开发者工具」内的版本化日志入口（17+ oslog / 17- syslog）；oslog 新增 pid/message/stream 过滤、`.logarchive` 导出、行明细查看；修复开始-暂停按钮联动与反复启停无响应两个 bug。
- `syslog-stream-op`: oslog 流支持 pid/message/stream 过滤参数与结构化条目透传；新增设备日志 `.logarchive` 收集能力；强化停止时的取消/连接释放语义。
- `slide6-developer-tools`: 「开发者工具」tab 容纳系统日志区块（按设备版本展示对应入口），作为可扩展 Grid 的一部分。

## Impact

- 代码：`slide6_ui/syslog/syslog_tab.py`（重构 / 拆分 / bug 修复）、`slide6_ui/developer_tools/developer_tools_tab.py`（容纳日志入口）、`slide6_ui/main_window.py`（移除独立 tab 注册、关闭时清理）、`ios_toolkit/device.py` 与 `ios_toolkit/toolkit_api.py`（`LogStreamHandle` 结构化透传 / 过滤参数 / logarchive 收集）。
- 依赖：复用现有 `pymobiledevice3` 的 `OsTraceService`（`syslog(pid=...)` 过滤与 archive 收集），无新增第三方依赖。
- 行为：用户不再通过下拉切换来源；导出新增 `.logarchive` 格式（与现有文本「另存」并存）。

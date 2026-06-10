## Context

`slide6_ui/syslog/syslog_tab.py` 当前：一个 `QComboBox` 选 syslog/oslog，`SyslogStreamThread` 从 `LogStreamHandle.queue` 取**已格式化字符串**逐批 emit，GUI 侧用 `QPlainTextEdit` 渲染，支持关键字过滤 / 暂停 / 清空 / 另存。平台侧 `LogStreamHandle`（`ios_toolkit/device.py`）在共享事件循环上跑 `SyslogService.watch()` 或 `OsTraceService.syslog()`，oslog 经 `_format_oslog_entry()` 拍平成单行后入队。

两个已知 bug：
- **#3**：`_toggle_start()` 停止 / `set_target()` 重选设备时不复位 `self._paused` 与 `pause_btn`，导致停止后暂停按钮仍停留在上次状态。
- **#4**：反复开始 / 停止几次后再开始无输出。`_stop_stream()` 调 `thread.stop()`（`requestInterruption` + `handle.close()` + `wait`），`handle.close()` 仅 `call_soon_threadsafe(future.cancel)`；`OsTraceService.syslog()` 的异步生成器在取消时底层 socket 可能未释放，疑似留下半关闭连接/未完成任务，使下次 `open_log_stream` 异常或无数据。需定位根因并保证幂等的干净关闭。

## Goals / Non-Goals

**Goals:**
- 移除独立「系统日志」sidebar tab；在「开发者工具」tab 内呈现为独立日志区块，按设备版本只暴露一个入口（17+ oslog / 17- syslog）。
- syslog 保持现有交互不变。
- oslog 增加 pid / message / stream flag 过滤、`.logarchive` 导出、点击行查看结构化明细。
- 修复 #3 / #4。

**Non-Goals:**
- 不改 syslog 的展示逻辑与文本「另存」。
- 不引入新的第三方依赖。
- 不做日志持久化/轮转（与现有「另存」一致，仅用户显式导出）。
- 不在本 change 内做 tab 切换自动聚焦、路径栏统一（属 Change C）。

## Decisions

1. **入口与版本分流**：日志区块嵌入「开发者工具」tab（不再是 sidebar tab）。`get_os_version` 已可用；`tunnel.ios_major()` ≥17 → oslog 入口，否则 syslog 入口。两种入口**不再共用同一视图组件**：syslog 用现有单行只读文本视图；oslog 用独立的多列表格视图（见决策 2）。共用的只是外层容器与「开始/停止·暂停/清空」控制条。下拉来源选择移除。
2. **结构化透传与 oslog 列视图**：`LogStreamHandle` 对 oslog 不再只入队字符串，改为入队结构化条目（dict，源自 `SyslogEntry`：`pid/timestamp/level/image_name/filename/message/subsystem/category`，其中 subsystem/category 取自 `label`，可为空）。oslog GUI 用 `QTableWidget`/`QTreeView` 行模型保存结构化对象，按列渲染；点击行弹出/侧栏展示完整字段。syslog 仍是纯字符串（明细=原始行）。`message`/`timestamp` 等保留原始值，显示按列格式化。
3. **oslog 列选择（眼睛图标）**：表格上方放一个眼睛图标按钮，点击弹出含 8 个字段复选框的浮窗（`QMenu` + `QWidgetAction`/`QCheckBox` 或小 popup），勾选确认后即时 `setColumnHidden` 更新可见列。默认全显。列选择是纯显示态，不影响采集与过滤。
4. **oslog filter（驱动读取，非仅显示过滤）**：眼睛右侧为「只读条件文本区 + filter 图标按钮」。点击图标弹出上述字段输入浮窗；提交时对每个字段 `strip()`，为空者不生效；生效字段拼成 `k=v&k=v`（如 `pid=1127&image_name=safari`）写入文本区。条件分两类落地：
   - **源头参数**（重新订阅流）：`pid`→`syslog(pid=int)`（-1=全部）；可选 `stream_flags`→`stream_flags`（int 位掩码，`OsActivityStreamFlag`）；可选 level/类型→`message_filter`（int 位掩码，默认 65535=全部）。
   - **消费侧谓词**（对结构化条目过滤）：`image_name/filename/subsystem/category/message` 子串匹配、`level` 等值匹配（库 API 无对应读取参数）。
   - 任一条件变更：若涉及源头参数则停旧流并以新参数重订阅、清空视图重建；仅消费侧字段变更则保留缓冲、对缓冲+后续条目重算可见性。区别于 syslog 的「仅隐藏已显示行」。
5. **oslog 导出浮窗**：oslog 工具条提供「导出」按钮，点击在按钮位置弹出小浮窗（`QMenu.exec(button.mapToGlobal(...))`）含两项——「导出为文本」（写出当前过滤后可见行的文本）与「导出为 `.logarchive`」（经平台层 `collect_logarchive` 收集，目录/文件选择，独立 RPC、不影响实时流）。syslog 维持现有「另存为文本」。
6. **`.logarchive` 导出（平台层）**：经 `OsTraceService.collect(out)`（输出 `.logarchive` 目录）或 `create_archive(io)` 实现一次性收集 API，与实时流解耦（独立 lockdown 连接，不影响正在进行的流）。
7. **Bug #3**：把"复位暂停"收敛进 `_stop_stream()` 与 `set_target()`：停止/重选设备时 `self._paused=False`、`pause_btn.setChecked(False)`、文案归位「暂停」。
8. **Bug #4**：让关闭可靠——`LogStreamHandle.close()` 在取消 future 后，确保底层服务/连接被 `await` 关闭（在 `_run` 的 finally 中关闭 lockdown/service，或对生成器做显式 `aclose()`），并让 `open_log_stream` 每次新建独立 handle、不复用残留状态；GUI 侧 `_stop_stream()` 保证线程对象与信号断连幂等。修复后以"开始→停止"循环≥5 次回归。

## Risks / Trade-offs

- **API 已核对（`pymobiledevice3.services.os_trace`）**：`OsTraceService.syslog(pid:int=-1, message_filter:int=65535, stream_flags:int=60)`；`collect(out)` / `create_archive(io)` 输出归档；`SyslogEntry` 含 pid/timestamp/level/image_name/filename/message/label(subsystem,category)。注意 `message_filter` 是**级别/类型位掩码而非文本**，故「按 message 文本过滤」只能消费侧实现；若后续库签名变动需复核。
- **结构化透传内存**：保存结构化对象比纯字符串占用略高；沿用 `_MAX_LINES` 上限裁剪即可控。
- **Bug #4 根因可能在 pymobiledevice3 生成器取消语义**：若库层取消不干净，需在我们侧加显式 `aclose()`/超时兜底，避免反向依赖库行为。
- UI 结构变动（移除 tab）属用户可见 BREAKING，但符合本次诉求。

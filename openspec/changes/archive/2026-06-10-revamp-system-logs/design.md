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
2. **结构化透传与 oslog 列视图（model/view）**：`LogStreamHandle` 对 oslog 不再只入队字符串，改为入队结构化条目（dict，源自 `SyslogEntry`：`pid/timestamp/level/image_name/filename/message/subsystem/category`，其中 subsystem/category 取自 `label`，可为空）。oslog GUI 用 `QTableView` + 自定义 `QAbstractTableModel`（数据仅存一份 dict，单元格按 `data()` 按需渲染），**不**用 `QTableWidget` 逐单元格构造——后者在流式场景下会因每行创建 8 个 item 而拖垮主线程。列序为 `pid/timestamp/level/filename/image_name/subsystem/category/message`（`subsystem` 在 `message` 前，`message` 末列 Stretch）。批量到达走 `beginInsertRows` + 块删除裁剪到 `_MAX_LINES`，且仅在已处于底部时 `scrollToBottom`；行高固定、列宽 Interactive（**禁用 ResizeToContents**，它每次插入都重算列宽）。双击行展示完整字段。syslog 仍是纯字符串（明细=原始行）。
3. **oslog 列选择（眼睛图标）**：表格上方放一个眼睛图标按钮，点击弹出含 8 个字段复选框的浮窗（`QMenu` + `QWidgetAction`/`QCheckBox`），勾选「应用」后即时 `setColumnHidden` 更新可见列。**默认仅 `message` 可见**，其余列默认隐藏；至少保留一列可见。列选择是纯显示态，不影响采集与过滤。
4. **oslog filter（消费侧，与 syslog 一致）**：filter **只筛当前内存缓冲做显示**，不再重订阅 `OsTraceService.syslog(...)`——避免丢历史、避免复杂的源头参数语义。8 个字段（含 `pid`）一律按**大小写不敏感子串匹配**结构化条目；条件变更只 `_rebuild_view()`，实时流与缓冲不受影响。UI 上眼睛右侧不是只读文本框，而是一个**点击即弹字段浮窗**的左对齐按钮（`_FilterButton`）：展示当前条件串 `k=v&k=v`，一行放不下时 **`Qt.ElideRight` tail 省略（…）**、完整串在 tooltip——与 syslog 的「点击直接输入」形成对照（oslog 是点击弹 popup 输入）。`open_log_stream` 仍以库默认参数采集全部（平台层保留 pid/message_filter/stream_flags 形参备用，但 UI 不再传）。
5. **oslog 导出浮窗**：oslog 工具条提供「导出」按钮，点击在按钮位置弹出小浮窗（`QMenu.exec(button.mapToGlobal(...))`）含两项——「导出为文本」（写出当前过滤后可见行的文本）与「导出为 `.logarchive`」（经平台层 `collect_logarchive` 收集，目录/文件选择，独立 RPC、不影响实时流）。syslog 维持现有「另存为文本」。
6. **`.logarchive` 导出（平台层）**：经 `OsTraceService.collect(out)`（输出 `.logarchive` 目录）或 `create_archive(io)` 实现一次性收集 API，与实时流解耦（独立 lockdown 连接，不影响正在进行的流）。
9. **内存按字节封顶（环形缓冲）**：syslog/oslog 的原始 payload 缓冲不再按行数（旧 `deque(maxlen=5000)`），改为**按字节预算（~10MB）**——`LogPanelBase` 维护 `_buffer` + 并行 `_sizes` 与运行总字节，超预算时从头淘汰最旧并回调 `_render_evicted`。oslog 的 `model._rows` 持有的是 `_buffer` 内 dict 的**引用**（无副本），故淘汰必须同步从 model 头部移除等量的「当前过滤命中」行，才能真正释放内存；filter 改变走 `_rebuild_view`（model.reset 为过滤后 buffer）重新对齐，pid 改变清 buffer+重订阅。切换设备清空 buffer。完整历史不靠内存保留，由文本 / `.logarchive` 导出兜底（不落盘缓存、不做磁盘分页）。syslog 文本控件另设 `_VIEW_BLOCK_LIMIT` 显示上限。
7. **Bug #3**：把"复位暂停"收敛进 `_stop_stream()` 与 `set_target()`：停止/重选设备时 `self._paused=False`、`pause_btn.setChecked(False)`、文案归位「暂停」。
8. **Bug #4（反复启停无数据）**：真机日志定位的根因有二，二者叠加：(a) `OsTraceService.syslog()` / `SyslogService.watch()` 这两个 async generator **自身不关闭底层 relay socket**——`gen.aclose()` 只终止生成器协程，`LockdownService` 的 `com.apple.os_trace_relay` / `syslog_relay` 连接仍半开挂在设备端 logd 上，第二轮新流虽 `StartActivity` 返回成功却不再被喂数据（日志表现为 `lockdown ready` 后再无 `first line`、`close: lines=0`）；(b) `close()` 用 `future.result()`，`future.cancel()` 后它**立即抛 `CancelledError` 返回**，根本没等协程 finally 跑完。修复：`_run` 持有 service 实例，finally 在 `gen.aclose()` 之后**显式 `await svc.close()`** 释放 relay socket；并新增 `threading.Event` `_done`，`_run` 完全收尾后 set，`close()` 改为 `self._done.wait(3.0)` 等待 relay 真正释放（超时打 WARNING）后才返回。`open_log_stream` 每轮新建独立 handle；GUI 侧 `_stop_stream()` 信号断连/线程回收幂等。真机连续「开始→停止」≥3 轮回归通过：每轮 stop 都见 `relay service socket closed` + `close: relay released`，每轮 start 都重新 `first line received` 并持续输出。

## Risks / Trade-offs

- **API 已核对（`pymobiledevice3.services.os_trace`）**：`OsTraceService.syslog(pid:int=-1, message_filter:int=65535, stream_flags:int=60)`；`collect(out)` / `create_archive(io)` 输出归档；`SyslogEntry` 含 pid/timestamp/level/image_name/filename/message/label(subsystem,category)。注意 `message_filter` 是**级别/类型位掩码而非文本**，故「按 message 文本过滤」只能消费侧实现；若后续库签名变动需复核。
- **结构化透传内存**：保存结构化对象比纯字符串占用略高；沿用 `_MAX_LINES` 上限裁剪即可控。
- **Bug #4 根因已坐实在 pymobiledevice3 生成器/服务清理语义**：库的流式 generator 不在 finally 关闭 relay socket，必须由我们侧持有 service 并显式 `svc.close()` + Event 同步等待清理完成，不能只依赖 `gen.aclose()` 或 `future.cancel()`。
- UI 结构变动（移除 tab）属用户可见 BREAKING，但符合本次诉求。

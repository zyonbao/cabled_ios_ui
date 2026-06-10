# Tasks

## 1. 平台层：oslog 结构化 / 过滤 / logarchive

- [x] 1.1 核对 `pymobiledevice3.services.os_trace` API：`OsTraceService.syslog(pid:int=-1, message_filter:int=65535, stream_flags:int=60)`；归档 `collect(out)` / `create_archive(io)`；`SyslogEntry` 字段（含 `label.subsystem/category`）、`OsActivityStreamFlag` 位掩码 —— 已确认
- [x] 1.2 `ios_toolkit/device.py` `LogStreamHandle`：oslog 入队结构化 payload（dict：pid/timestamp/level/image_name/filename/message/subsystem/category + display 串，`_oslog_entry_to_dict`），syslog 仍为纯字符串；新增对 `pid`/`message_filter`/`stream_flags` 三参数透传给 `syslog(...)`
- [x] 1.3 `LogStreamHandle._run/close()`：`_run` 持有 service 实例，finally 在 `gen.aclose()` 后**显式 `await svc.close()`** 关闭 relay socket（generator 自身不关）；新增 `threading.Event` `_done`，`_run` 收尾后 set，`close()` 改 `_done.wait(3.0)` 等 relay 真正释放（超时 WARNING）；保证幂等、无悬挂任务、无半关闭 relay socket（修复 bug #4 根因）
- [x] 1.4 新增 `iOSDevice.collect_logarchive(out_path)` 平台 API（私有事件循环 + `OsTraceService.collect`），独立 lockdown 连接、与实时流不干扰；失败以错误返回
- [x] 1.5 `ios_toolkit/toolkit_api.py`：扩展 `open_log_stream`（pid/message_filter/stream_flags 参数）+ 新增 `collect_logarchive` 包装

## 2. UI：迁移到开发者工具 + 版本分流

- [x] 2.1 `main_window.py`：移除独立「系统日志」sidebar tab 注册与 set_target/suppress/shutdown 引用；关闭清理改由开发者工具负责
- [x] 2.2 `developer_tools_tab.py`：新增「系统日志」Grid 入口（始终可用、不受 DDI gating），点击按 `get_os_version` 分流打开 `LogDialog`（非模态）；退出时停止其流线程
- [x] 2.3 重构 `syslog` 包：`log_panel.LogPanelBase` + `LogStreamThread` 共用开始/停止·暂停·清空与缓冲；`SyslogPanel` 保留单行文本视图与关键字过滤/另存；删除旧 `syslog_tab.py`

## 3. UI：oslog 独立列视图与增强

- [x] 3.1 `OslogPanel` 用 `QTableView` + `_OslogModel(QAbstractTableModel)`（按需渲染、批量 `beginInsertRows`+块裁剪、仅底部时滚动、固定行高、列宽 Interactive 禁用 ResizeToContents）；列序 pid/timestamp/level/filename/image_name/subsystem/category/message；双击行弹出完整字段明细。实测 10 万行流式 0.6s、稳定 5000 行上限
- [x] 3.2 列选择（眼睛图标）：眼睛按钮 → `QMenu`+`QWidgetAction` 复选框浮窗 → 「应用」即时 `setColumnHidden`（**默认仅 message 可见**、至少保留一列、纯显示态）
- [x] 3.3 filter（眼睛右侧）：`_FilterButton`（左对齐、点击弹 8 字段浮窗、条件串 tail 省略 `…`、完整串 tooltip）；strip 后非空拼成 `k=v&k=v`；**消费侧 only**——8 字段含 pid 一律子串匹配内存缓冲、`_rebuild_view`，不重订阅、不丢历史（`open_log_stream` 用库默认参数）
- [x] 3.4 导出按钮：点击在按钮位置 `QMenu` 弹出（文本 / `.logarchive`）；文本写当前过滤可见行，`.logarchive` 调 `api.collect_logarchive`（目录选择、结果提示、后台不阻塞实时流）

## 3b. 内存按字节封顶

- [x] 3b.1 `LogPanelBase`：`_buffer`+`_sizes`+运行字节，按 `_MAX_BYTES`(~10MB) 预算淘汰最旧并回调 `_render_evicted`；切设备 `_clear()`；`_payload_bytes` 估算
- [x] 3b.2 oslog `_render_evicted`：按「当前过滤命中数」从 model 头部 `remove_front`，释放共享 dict（实测 100k 行内存稳定在 ~10MB、视图与过滤后 buffer 始终一致）
- [x] 3b.3 syslog 文本控件 `_VIEW_BLOCK_LIMIT` 显示上限；缓冲同样字节封顶

## 4. Bug 修复

- [x] 4.1 #3 开始-暂停联动：待开始态「暂停/继续」=「暂停」且 **disabled**；运行态 **enabled** 可切换；`_start_stream` 启用、`_stop_stream`（含 `set_target`）复位为「暂停」+ disabled + `_paused=False`
- [x] 4.2 #4 反复启停无数据：真机日志定位双重根因——(a) `OsTraceService.syslog()`/`SyslogService.watch()` generator 自身不关 relay socket（`gen.aclose()` 只终止协程，设备端 relay 半开挂着，第二轮 `StartActivity` 成功但不喂数据）；(b) `close()` 用 `future.result()` 在 cancel 后立即抛 `CancelledError` 返回、不等 finally。修复：finally 显式 `await svc.close()` + `threading.Event` 同步等 relay 释放；配合信号断连幂等 + 每轮新建 handle。真机连续启停≥3 轮通过（每轮 stop 见 `relay released`、每轮 start 重新 `first line received`）
- [x] 4.3 临时排障日志收敛：链路埋点（open/lockdown/first line/relay released/start/stop/batch）定位完成后降为 DEBUG，仅保留 `close` 超时与流 ERROR 为 WARNING；`workers._Call._emit` 加 `shiboken6.isValid` 守卫，修复退出竞态 `Signal source has been deleted`

## 5. 验证

- [x] 5.1 lint 无误（仅余既有 basedpyright 相对导入误报）+ 导入/离屏构造冒烟（面板构建、oslog 批渲染与过滤、版本分流、日志 tile 不受 gating、bug#3 复位均通过）
- [x] 5.2 真机手验（iOS 17+ oslog）：多列表格展示、眼睛选列即时生效、filter 浮窗（字段消费侧过滤）、条件文本区显示 `k=v&k=v`、点击行看明细、导出浮窗、**连续启停≥3 轮均恢复数据（日志佐证 relay released + first line）**、暂停态停止后再开始正常、暂停按钮随运行态启用/禁用
- [x] 5.3 真机手验（iOS 17- syslog）：保留原有展示/过滤/暂停/清空/另存；无 oslog 专有控件；连续启停可恢复（与 oslog 共用 `LogPanelBase` close 修复路径）
- [x] 5.4 回归：未选设备不启动；设备切换正确切换入口并停止旧流

# Tasks

## 1. 平台层：oslog 结构化 / 过滤 / logarchive

- [x] 1.1 核对 `pymobiledevice3.services.os_trace` API：`OsTraceService.syslog(pid:int=-1, message_filter:int=65535, stream_flags:int=60)`；归档 `collect(out)` / `create_archive(io)`；`SyslogEntry` 字段（含 `label.subsystem/category`）、`OsActivityStreamFlag` 位掩码 —— 已确认
- [ ] 1.2 `ios_toolkit/device.py` `LogStreamHandle`：oslog 入队结构化 payload（dict：pid/timestamp/level/image_name/filename/message/subsystem/category + display 串），syslog 仍为纯字符串；新增对 `pid`/`message_filter`/`stream_flags` 三参数透传给 `syslog(...)`
- [ ] 1.3 `LogStreamHandle.close()`：在取消 future 后于 `_run` 的 finally 中显式关闭 service/生成器（`aclose()`）与 lockdown，保证幂等、无悬挂任务（修复 bug #4 根因）
- [ ] 1.4 新增 `collect_logarchive(udid, out_path)` 平台 API（`OsTraceService.collect`/`create_archive`），独立 lockdown 连接、与实时流不干扰；不支持时以错误返回
- [ ] 1.5 `ios_toolkit/toolkit_api.py`：扩展 `open_log_stream`（pid/message_filter/stream_flags 参数）+ 新增 `collect_logarchive` 包装

## 2. UI：迁移到开发者工具 + 版本分流

- [ ] 2.1 `main_window.py`：移除独立「系统日志」sidebar tab 注册；关闭时清理逻辑改为由开发者工具区块负责
- [ ] 2.2 `developer_tools_tab.py`：新增系统日志区块（Grid 入口），依 `get_os_version` 分流——17+ 显示 oslog 入口、17- 显示 syslog 入口
- [ ] 2.3 重构 `syslog/syslog_tab.py`：去掉来源下拉；syslog 模式保留单行文本视图与现有过滤/暂停/清空/另存；共用外层容器与「开始/停止·暂停/清空」控制条；设备切换 / 进入区块时初始化

## 3. UI：oslog 独立列视图与增强

- [ ] 3.1 oslog 用独立多列表格视图（`QTableWidget`/`QTreeView`），列 = pid/timestamp/level/filename/image_name/message/subsystem/category；行模型保存结构化对象，点击行弹出/侧栏展示完整字段
- [ ] 3.2 列选择（眼睛图标）：表格上方眼睛按钮 → 8 字段复选框浮窗 → 确认即时 `setColumnHidden` 更新可见列（默认全显，纯显示态）
- [ ] 3.3 filter（眼睛右侧）：只读条件文本区 + filter 图标按钮 → 弹出 8 字段输入浮窗；strip 后非空字段拼成 `k=v&k=v` 显示；`pid`(+可选 stream/level 掩码)下推 `syslog(...)` 重订阅，其余字段消费侧谓词；条件变更重建视图
- [ ] 3.4 导出按钮：点击在按钮位置弹出小浮窗（文本 / `.logarchive`）；文本写当前过滤可见行，`.logarchive` 调 `api.collect_logarchive`（目录/文件选择、进度与结果提示，不影响实时流）

## 4. Bug 修复

- [ ] 4.1 #3 开始-暂停联动：`_stop_stream()` 与 `set_target()` 复位 `_paused` 与 `pause_btn`（回到「暂停」）
- [ ] 4.2 #4 反复启停：`_stop_stream()` 信号断连 / 线程回收幂等，配合 1.3 验证连续「开始→停止」≥5 次后仍能开始

## 5. 验证

- [ ] 5.1 lint 无误 + 导入冒烟
- [ ] 5.2 真机手验（iOS 17+ oslog）：多列表格展示、眼睛选列即时生效、filter 浮窗（pid 重订阅 + 字段消费侧过滤）、条件文本区显示 `k=v&k=v`、点击行看明细、导出浮窗（文本 / `.logarchive` 可被 Console.app 打开）、连续启停可恢复、暂停态停止后再开始正常
- [ ] 5.3 真机手验（iOS 17- syslog）：保留原有展示/过滤/暂停/清空/另存；无 oslog 专有控件；连续启停可恢复
- [ ] 5.4 回归：未选设备不启动；设备切换正确切换入口并停止旧流

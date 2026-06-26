# Tasks

## 1. 共享 helper（slide6-desktop-shell）

- [x] 1.1 新增 `slide6_ui/common/table_perf.py`，提供 `batch_table_fill(table, auto_cols)` 上下文管理器：填充期 `auto_cols` 切 `Fixed` + `setUpdatesEnabled(False)`，结束恢复 `ResizeToContents` 再启重绘
- [x] 1.2 在 `table_perf.py` 顶部 docstring 写入团队约定（ResizeToContents + 循环填充 MUST 用本 helper；流式表用 Interactive + 行数上限）

## 2. 统一改造现有表格（slide6-desktop-shell）

- [x] 2.1 `developer_tools/process_dialog.py` `_render` 改用 helper（auto_cols=0,2,3），移除临时计时脚手架
- [x] 2.2 `common/afc_browser.py` 列表填充改用 helper（auto_cols=1,2）
- [x] 2.3 `app_manager/app_manager.py` `_render` 改用 helper（auto_cols=2,3）
- [x] 2.4 `crash/crash_tab.py` `_render` 改用 helper（auto_cols=1,2）
- [x] 2.5 `device_info/device_info.py` `_render` 改用 helper（auto_cols=0）
- [x] 2.6 `developer_tools/web_inspector_dialog.py` 填充改用 helper（auto_cols=0）
- [x] 2.7 `developer_tools/tunnel_manager_dialog.py` `_render` 改用 helper（auto_cols=PID/USER/PORT/MODE）
- [x] 2.8 `common/keymouse_settings_widget.py` `_render_rows` 改用 helper（auto_cols=1,2）
- [x] 2.9 `profiles/profiles_tab.py` `_render` 改用 helper（auto_cols=2,3）

## 3. 验证

- [x] 3.1 全部改动文件 `py_compile`/`ast.parse` 通过；每个用 `batch_table_fill` 的文件都 import 了它
- [x] 3.2 真机：进程管理刷新约 580 进程不再卡顿；文件浏览大目录、应用管理、崩溃日志等列宽显示正常、刷新流畅
- [x] 3.3 确认流式表（oslog / network_monitor / pcap）仍用 Interactive + 行数上限，未回退
- [x] 3.4 `openspec validate add-table-fill-perf-convention --strict`

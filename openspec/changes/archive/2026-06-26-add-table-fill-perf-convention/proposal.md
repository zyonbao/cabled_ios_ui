# Why

多个功能 Tab 的表格在数据量大时会冻结主线程数秒。根因是：列设为
`QHeaderView.ResizeToContents` 后，每次 `setItem` / `setCellWidget` 都会重新测量
**所有行**的列宽，逐行填充因此是 O(行²)。进程管理刷新约 580 个进程时主线程冻结
4–8 秒；文件浏览（大目录）、应用管理（数百 app）、崩溃日志（累积数百条）同样存在
该风险。排查已证实：后端取数据走后台线程、总耗时 <1s，卡顿完全发生在主线程填表。

此前 `syslog/oslog_panel.py` 已针对流式表用 `Interactive` 宽度 + 行数上限规避过该
坑，但其余表格各自直写填充循环，缺少统一约束，容易再次踩坑或被照抄扩散。

# What Changes

均落在 `slide6-desktop-shell`（桌面壳为各 Tab 提供的共享 UI 基础设施约定）：

1. **新增共享 helper** `slide6_ui/common/table_perf.py::batch_table_fill(table, auto_cols)`：
   填充期间把 `auto_cols`（即原 `ResizeToContents` 列）临时切到 `Fixed` 并暂停重绘，
   填充结束后恢复 `ResizeToContents` 做**一次**测量——把填充成本从 O(N²) 降回 O(N)。

2. **统一改造全部 9 处** `ResizeToContents` + 循环填充的表格走该 helper：
   进程管理、文件浏览、应用管理、崩溃日志、设备信息、Web Inspector、隧道管理、
   键鼠设置、描述文件。

3. **确立团队约定**：凡是含 `ResizeToContents` 列且会循环（重复）填充的 QTableWidget，
   填充时 MUST 使用 `batch_table_fill`；流式/追加表改用 `Interactive` 宽度 + 行数上限。
   约定写入 `table_perf.py` 顶部 docstring。

# Impact

- Affected specs: `slide6-desktop-shell`（新增「表格填充性能」要求）
- Affected code:
  - `slide6_ui/common/table_perf.py`（新增 helper + 约定 docstring）
  - `slide6_ui/developer_tools/process_dialog.py`、`common/afc_browser.py`、
    `app_manager/app_manager.py`、`crash/crash_tab.py`、`device_info/device_info.py`、
    `developer_tools/web_inspector_dialog.py`、`developer_tools/tunnel_manager_dialog.py`、
    `common/keymouse_settings_widget.py`、`profiles/profiles_tab.py`（填充改用 helper）
- 不改后端 / WDA；不改任何对外行为，仅消除主线程卡顿（列自适应显示效果不变）。
- 已确认无需改动的表：`syslog/oslog_panel.py`、`developer_tools/network_monitor_dialog.py`、
  `developer_tools/pcap_capture_dialog.py`（已用 Interactive 宽度且/或行数上限）。

# slide6-desktop-shell (delta)

## ADDED Requirements

### Requirement: 表格填充性能约定

桌面壳 SHALL 提供统一的表格填充助手 `slide6_ui/common/table_perf.py::batch_table_fill(table, auto_cols)`，在填充期间把 `auto_cols` 列临时由 `QHeaderView.ResizeToContents` 切换为 `Fixed` 并暂停重绘，填充结束后恢复 `ResizeToContents` 做一次测量，使逐行填充成本为 O(N) 而非 O(N²)。

凡是含至少一个 `ResizeToContents` 列、且会循环（重复）填充的 `QTableWidget`，其填充 MUST 通过 `batch_table_fill` 进行；SHALL NOT 在 `ResizeToContents` 生效时于该助手之外直接执行 `setRowCount` + `setItem`/`setCellWidget` 循环。流式/追加型表格 SHALL 改用 `Interactive` 列宽配合行数上限，而非 `ResizeToContents`。

填充改造 SHALL NOT 改变列的最终自适应显示效果，仅消除填充时的主线程卡顿。

#### Scenario: 大数据量表格刷新不卡顿

- **WHEN** 进程管理对话框刷新一台返回约 580 个进程的设备
- **THEN** 列表填充通过 `batch_table_fill` 完成，主线程不出现可感知的冻结
- **AND** PID / 名称 / App / 启动时间各列仍按内容自适应显示

#### Scenario: 既有含 ResizeToContents 列的表格均已纳管

- **WHEN** 审视进程管理、文件浏览、应用管理、崩溃日志、设备信息、Web Inspector、隧道管理、键鼠设置、描述文件这些含 `ResizeToContents` 列的表格
- **THEN** 它们的循环填充均通过 `batch_table_fill` 进行
- **AND** 不存在在 `ResizeToContents` 生效时于助手之外直接循环填充的表格

#### Scenario: 流式表使用固定宽度而非自适应

- **WHEN** 系统日志 / 网络监控 / 抓包等持续追加行的流式表格渲染
- **THEN** 这些表格使用 `Interactive` 列宽并对渲染行数设上限，不使用 `ResizeToContents`

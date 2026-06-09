## 1. 平台能力层：描述文件（mobile-config-op）

- [x] 1.1 在 `ios_toolkit/device.py` 的 `iOSDevice` 上新增 `list_profiles()`：经 `_bg_loop` 短连接 lockdown，调 `MobileConfigService.get_profile_list()`，归一化为 `{"profiles": [...]}`
- [x] 1.2 新增 `install_profile(path)`：读取 `.mobileconfig` 字节并调 `MobileConfigService.install_profile`，返回「已下发」语义
- [x] 1.3 新增 `remove_profile(identifier)`：调 `MobileConfigService.remove_profile`，捕获受限拒绝错误为 `{ok: False}`
- [x] 1.4 在 `ios_toolkit/toolkit_api.py` 新增 `list_profiles/install_profile/remove_profile` 包装（含 `path`/`identifier` 校验、`_prepare_device_basic`）

## 2. 平台能力层：Crash（crash-reports-op）

- [x] 2.1 在 `device.py` 新增 `list_crashes()`：经 `CrashReportsManager.ls(depth=1)` + `stat`，归一化为 `{"entries": [{name,isDir,size,mtime}]}`（与 `afc_list` 对齐）
- [x] 2.2 新增 `pull_crash(remote_path, local_dir, erase)`：调 `CrashReportsManager.pull`；`erase=True` 时导出后原子删除原文件
- [x] 2.3 新增 `clear_crash(remote_path)`：调 `crash.afc.rm` 删除单项（`clear()` 会按目录清空，故改用 rm）
- [x] 2.4 在 `toolkit_api.py` 新增 `list_crashes/pull_crash/clear_crash` 包装（含 `local_dir` 校验）

## 3. 平台能力层：系统日志流来源（syslog-stream-op）

- [x] 3.1 在 `device.py` 提供 `LogStreamHandle`（`open_log_stream`）：`syslog` 源经 `SyslogService.watch()` 逐行入线程安全队列，`close()` 取消协程并释放 lockdown
- [x] 3.2 `oslog` 源（`OsTraceService.syslog()`）经 `_format_oslog_entry` 结构化条目 → 单行文本（含 pid/level/subsystem/category）
- [x] 3.3 错误上报：协程内捕获异常/EOF 入队为 `(ERROR, msg)`/`(EOF, None)` 哨兵，连接在 `async with` 退出时释放，无悬挂任务

## 4. 描述文件 UI（slide6-profile-management）

- [x] 4.1 新增 `slide6_ui/profiles/` 模块与 `ProfilesDialog(QDialog)`，接收 `runner` 与 `get_target`
- [x] 4.2 实现描述文件表格（名称/标识符/类型/组织）+ 刷新 + 加载/失败状态文案，调用经 `AsyncRunner`
- [x] 4.3 实现安装：点击文件选择 + 拖拽 `.mobileconfig`（复用 `AppManagerTab` 拖拽校验范式），安装后提示「需在设备设置中确认」
- [x] 4.4 实现多选移除：二次确认 + 逐项移除 + 成功/失败汇总 + 刷新
- [x] 4.5 在 `slide6_ui/app_manager/app_manager.py` 工具栏新增「描述文件…」按钮，未选设备时提示

## 5. Crash 报告 UI（slide6-crash-reports）

- [x] 5.1 新增 `slide6_ui/crash/` 模块与 `CrashReportsTab(QWidget)`，实现 `set_target(target)`，未选设备显示「未选择设备」
- [x] 5.2 实现崩溃日志表格（名称/大小/时间）+ `ExtendedSelection` + 刷新，调用经 `AsyncRunner`
- [x] 5.3 实现多选导出（选目录 + 逐项 `pull_crash` + 汇总），复用 `DcimAlbumTab._export_selected` 范式
- [x] 5.4 实现右键 `CustomContextMenu`，含「导出」「删除」
- [x] 5.5 实现删除二次确认 + 逐项 `clear_crash` + 刷新
- [x] 5.6 实现导出「是否保留原文件」选项：不保留时用 `pull_crash(erase=True)` 原子删除，失败项不删除

## 6. 系统日志流 UI（slide6-syslog-stream）

- [x] 6.1 新增 `slide6_ui/syslog/` 模块；实现 `SyslogStreamThread(QThread)`：排空 `LogStreamHandle` 队列并 `lines_ready`/`stream_error`/`stream_eof` 批量上抛（参考 `mirror.py`）
- [x] 6.2 实现 `SyslogTab(QWidget)`：来源下拉（默认 syslog）、开始/停止、`set_target`，切换来源/设备时干净停止并重建线程
- [x] 6.3 实现限速渲染：线程侧 ~100ms 批量 flush + `QPlainTextEdit.setMaximumBlockCount` 上限裁剪
- [x] 6.4 实现关键字过滤（渲染侧大小写不敏感子串，条件变化对 deque 全量缓冲重套用）
- [x] 6.5 实现暂停（丢弃新行）/ 清空 / 另存为文本（仅显式另存才落盘）
- [x] 6.6 处理 `stream_error`/`stream_eof`：状态区提示并停止流，不影响其余功能

## 7. 主窗口集成

- [x] 7.1 在 `slide6_ui/main_window.py` 注册 `CrashReportsTab` 与 `SyslogTab`（置于「键鼠操作」之后，作为最后两个 Tab）
- [x] 7.2 在 `on_select_device` 中对两个新 Tab 分发 `set_target`
- [x] 7.3 在 `closeEvent` 中主动停止日志流线程，避免连接泄漏

## 8. 增强（评审反馈）

- [x] 8.0.1 Crash 报告 Tab 增加「按文件名过滤」输入框（大小写不敏感子串，作用于渲染；选择操作仅作用于可见条目）
- [x] 8.0.2 App 列表对系统应用（`appType == System`）隐藏「卸载」按钮，并在 `on_uninstall` 中防御性拦截
- [x] 8.0.3 修复 `app.py` SIGINT 处理重入：第二次 Ctrl+C 不再对已销毁窗口调 `close()`

## 9. 验证

- [x] 9.1 静态检查 / lint 新增模块，确保无导入与签名错误
- [~] 9.2 真机验证：描述文件**列表已验证**（iPhone 15/iOS 17.6.1，0 个）；安装确认 / 移除（含受限拒绝回显）需 GUI 交互验证
- [~] 9.3 真机验证：crash **列表（311 项）与导出（44KB .ips，保留原文件）已验证**；删除 / 不保留导出（破坏性）需 GUI 验证
- [x] 9.4 真机验证：syslog（2s/648 行）与 oslog（2s/7871 行）流、格式化、`close()` 干净均已验证；关键字过滤 / 暂停 / 清空 / 另存为 GUI 渲染逻辑待界面交互确认

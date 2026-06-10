## 1. 日志核心模块（ios_toolkit/logsys.py）

- [x] 1.1 新建 `ios_toolkit/logsys.py`：常量（默认目录 `~/Library/Logs/CablediOS`、文件名前缀 `cabledios_log_`、保留运行数 5、分片间隔 24h、分片 backupCount）、模块级状态（已挂载的自有 handler 引用）
- [x] 1.2 `_TimedShardHandler(RotatingFileHandler)`：`maxBytes=0`，重写 `shouldRollover`（距上次滚动 ≥24h 触发）与 `doRollover`（沿用父类 `.N` 数字后缀重命名 + 刷新下次滚动时刻）
- [x] 1.3 `_prune_old_runs(log_dir, keep=5)`：以 base 文件 `cabledios_log_*.log` 为运行锚点按 `start_time` 排序，删除第 6 个及更旧运行的全部文件（含 `.N` 分片）
- [x] 1.4 `setup_logging(enabled, log_dir)`：幂等——移除本模块旧 handler→（启用时）建目录 + `_prune_old_runs` + 挂 `_TimedShardHandler`(DEBUG) + 始终挂控制台 `StreamHandler`(INFO)；root 级别 DEBUG；统一格式（含毫秒）；自有 handler 打标记以便重建时识别
- [x] 1.5 `shutdown_logging()`：flush + 关闭并移除本模块自有 handler

## 2. 目录选择器（file_dialogs）

- [x] 2.1 `slide6_ui/common/file_dialogs.py`：新增 `open_directory(parent, caption, start_dir)`，按 `USE_NATIVE_FILE_DIALOG` 走原生 `getExistingDirectory` 或非原生（`DontUseNativeDialog`）目录选择

## 3. 启动接线与 tunneld

- [x] 3.1 `slide6_ui/app.py`：`main()` 创建窗口前读 `QSettings`（`settings/logging_enabled` 默认 True、`settings/logging_dir` 默认空→默认目录）并 `setup_logging(...)`；退出路径 `shutdown_logging()`
- [x] 3.2 `cabled_ios_tunnel.py` / `ios_toolkit/tunneld_main.py`：进程启动以默认配置 `setup_logging(...)`（独立进程、免 Qt）；进程结束 `shutdown_logging()`

## 4. Preferences UI（日志区）

- [x] 4.1 `slide6_ui/main_window.py`：新增 QSettings 键常量与读写辅助（`_logging_enabled` / `_logging_dir`）
- [x] 4.2 `_open_preferences` 增「日志」区：启用 `QCheckBox` + 目录 `QLineEdit` + 「浏览…」按钮（`open_directory`）；任一变更写回 `QSettings` 并即时 `setup_logging(...)` 重建（禁用时由 `setup_logging(enabled=False)` 移除文件 handler、仅保留控制台）

## 5. 接入执行日志（review 补点）

- [x] 5.1 平台层 `ios_toolkit/device.py`：模块级 logger + DDI 状态·挂载·卸载（方式/镜像路径/pmd3 原始异常）、进程列表·启动·kill、虚拟定位与轨迹回放（点数/版本分支/常驻会话起止）、`_get_rsd_from_tunneld`（tunnel 缺失）等关键路径与失败（`exc_info`）
- [x] 5.2 `ios_toolkit/toolkit_api.py`：模块级 logger + `_err` 统一记录失败原因（BAD_TARGET/NOT_IMPLEMENTED 走 debug 仅文件，其余 warning）
- [x] 5.3 `slide6_ui/common/workers.py`：`AsyncRunner` 后台任务异常统一 `logger.exception(...)`（避免被吞）
- [x] 5.4 `slide6_ui/common/tunnel.py`：tunnel 拉起/停止/状态日志
- [x] 5.5 `developer_tools/*`：DDI 挂载/卸载、进程管理与虚拟定位的进入/关键用户动作日志；其余 Tab 的失败统一由 `toolkit_api._err` 与 `AsyncRunner` 异常日志覆盖
- [x] 5.6 安全核查：仅记录 udid/方式/bundle id/pid/用户自填的模拟坐标与错误文案，无配对密钥/备份密码/令牌/个人数据（安全基线第 4、13 条）

## 6. 验证

- [x] 6.1 lint 无误 + 导入冒烟
- [x] 6.2 单测/手验：文件命名（`cabledios_log_<start_time>.log`）、级别分流（debug 仅文件、info+ 上控制台）、保留最近 5 次运行（含分片清理）
- [ ] 6.3 真机/桌面手验：Preferences 启用/禁用/改目录即时生效；退出 flush；tunneld 进程日志落盘
- [ ] 6.4 回归：开启日志后 DDI 挂载/卸载/状态路径可在日志中复盘根因（呼应 DDI mount 验收待续项）

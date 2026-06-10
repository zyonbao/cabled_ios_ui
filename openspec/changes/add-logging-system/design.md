## 设计

### 目标与约束

- **高内聚低耦合**：业务模块零侵入——只用标准库 `logging.getLogger(__name__)`，**不 import 我们的日志模块**。集中配置（handler / 格式 / 滚动 / 保留）只在一个独立模块完成。
- **跨进程可用**：GUI（`slide6_ui` / Qt）与 tunneld（`cabled_ios_tunnel.py`，独立进程、无 Qt）都要能落盘。配置模块放在底层包 `ios_toolkit`，避免对 `slide6_ui` / Qt 的反向依赖。
- **不破坏既有契约**：`toolkit_api` 仍返回 `{ok,data}`/`{error}`；日志是旁路观测，不改变控制流。

### 模块边界

```
ios_toolkit/logsys.py        # 唯一配置入口（独立模块）
  ├─ setup_logging(enabled, log_dir) -> dict   # 幂等：可重复调用以重建配置
  ├─ shutdown_logging()                        # flush + 关闭 handler（退出/换配置）
  ├─ _TimedShardHandler(RotatingFileHandler)   # 每 24h 触发 .log/.1/.2 滚动
  └─ _prune_old_runs(log_dir, keep=5)          # 仅保留最近 5 次运行日志（含分片）
```

- 业务模块（`device.py`、`toolkit_api.py`、各 Tab、`workers.py`、`tunnel.py`）只新增模块级 `logger = logging.getLogger(__name__)` 与日志语句。
- `logging.getLogger(__name__)` 形成 `ios_toolkit.device`、`slide6_ui.developer_tools.developer_tools_tab` 等层级 logger，便于按子系统过滤。

### 级别与 handler 装配

- root logger 级别设为 `DEBUG`（让所有记录有机会到达 handler，由各 handler 自行过滤）。
- **文件 handler**：级别 `DEBUG`（记录全部）。仅在「启用」时挂载。
- **控制台 handler**（`StreamHandler` → stderr）：级别 `INFO`（即 info/warning/error 同时上控制台），始终挂载（轻量，便于开发期与崩溃前观察），不受「启用」开关影响。
- 重复调用 `setup_logging` 时先移除我们之前加的 handler（用属性标记区分自有 handler，避免误删第三方 handler）再重建——保证「保存设置即时生效」且不重复输出。
- 格式：`%(asctime)s %(levelname)-7s %(name)s: %(message)s`（含毫秒）。

### 文件命名、24h 分片与保留（业内规范取舍）

- **每次运行一份**：进程启动时以 `start_time = datetime.now().strftime("%Y%m%d_%H%M%S")` 生成 `cabledios_log_<start_time>.log` 作为该次运行的 base 文件。
- **24h 分片**：`logging.handlers` 中，**数字后缀** `.1/.2/...` 是 `RotatingFileHandler` 的滚动命名约定（`.log` 最新、序号越大越旧），`TimedRotatingFileHandler` 则用日期后缀。用户示例为 `.log.1/.2/.3`，故采用「时间触发 + 数字后缀」：自定义 `_TimedShardHandler(RotatingFileHandler)`，`maxBytes=0`（禁用按大小滚动），重写 `shouldRollover` 为「距上次滚动 ≥ 24h 即滚动」，`doRollover` 沿用父类的 `.N` 重命名并刷新下次滚动时刻。`backupCount` 设为较大值（如 30）以容纳长时间运行的多日分片。
  - 例：连续运行 3 天 →
    ```
    cabledios_log_<start>.log     # 当前 24h 窗口
    cabledios_log_<start>.log.1   # 前一个 24h
    cabledios_log_<start>.log.2
    cabledios_log_<start>.log.3
    ```
- **保留最近 5 次运行**：`_prune_old_runs` 在 `setup_logging` 内执行——以 `cabledios_log_*.log`（base，无 `.N` 后缀）为「运行锚点」，按文件名内的 `start_time` 排序，删除第 6 个及更旧运行的**全部文件**（`<base>` 及其 `<base>.1/.2/...` 分片）。当前运行的 base 计入这 5 个。

### 配置来源与生命周期

- **GUI 进程**：`slide6_ui/app.py main()` 在创建窗口前，用 `QSettings(_SETTINGS_ORG, _SETTINGS_APP)` 读取 `settings/logging_enabled`（默认 True）与 `settings/logging_dir`（默认 `~/Library/Logs/CablediOS`），调用 `setup_logging(enabled, log_dir)`；`app.quit()` 前 / 窗口 `closeEvent` 末尾 `shutdown_logging()`。
- **Preferences**：`_open_preferences` 增「日志」区——启用 `QCheckBox` + 目录 `QLineEdit` + 「浏览…」按钮（`file_dialogs.open_directory`）。任一变更写回 `QSettings` 并立即 `setup_logging(...)` 重建（启用→开始落盘；禁用→移除文件 handler 并 `shutdown_logging` 关闭文件）。
- **tunneld 进程**：`cabled_ios_tunnel.py`/`tunneld_main.py` 启动时直接用默认配置（启用 + 默认目录）调用 `setup_logging(...)`（独立进程不读 QSettings，避免依赖 Qt）；其日志同样进入同一目录，文件名天然以各自 `start_time` 区分，不与 GUI 冲突。

### 日志补点（review 现有代码）

按「能复盘关键路径」补 DEBUG/INFO，并对失败补 WARNING/ERROR（带 `exc_info` 便于栈回溯）：

- `ios_toolkit/device.py`：设备连接/会话、`ddi_status`/`ddi_mount`/`ddi_unmount`（含所选方式、镜像路径、`pymobiledevice3` 原始异常）、`_with_dvt`/进程列表/启动/kill、虚拟定位与轨迹回放（路线点数、版本分支、常驻会话起止）、`_get_rsd_from_tunneld`（tunnel 缺失）。
- `ios_toolkit/toolkit_api.py`：各包装函数入口（target/参数摘要）与失败原因。
- `slide6_ui/common/workers.py`：`AsyncRunner` 后台任务异常统一 `logger.exception(...)`（当前易被吞）。
- `slide6_ui/common/tunnel.py`：tunnel 拉起/停止/状态。
- 各 Tab：进入/关键用户动作（挂载、回放、导出、kill 等）与失败。
- **安全**：严禁记录配对密钥、备份密码、令牌、个人数据；必要时仅记录是否存在/长度，遵循安全基线第 4、13 条。

### 备选与取舍

- **为何不用 `TimedRotatingFileHandler`**：它用日期后缀（`.2026-06-11`），与用户期望的 `.1/.2` 数字分片不一致；改用「时间触发 + `RotatingFileHandler` 数字命名」更贴合示例且仍是标准库语义。
- **控制台是否随开关关闭**：选择「控制台 INFO 始终开」，因为它轻量且对崩溃前观测有价值；「启用开关」只控制文件落盘（用户语义即「是否记录日志文件」）。
- **配置存储**：GUI 沿用既有 `QSettings`（与现有 Preferences 一致），不与 `~/.executor_ios.json` 混用，降低耦合。

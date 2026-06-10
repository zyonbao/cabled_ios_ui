## Why

排查 DDI 挂载等问题时发现**当前应用零执行日志**：`ios_toolkit` 失败仅以 `{ok,error}` 信封返回、异常被各处吞掉或仅冒泡到 UI 状态栏，真机现场无法复盘「发生了什么、卡在哪一步、底层 `pymobiledevice3` 抛了什么」。这直接拖慢了 DDI 挂载等疑难问题的定位效率。

需要一个**高内聚、低耦合**的日志系统：业务模块只用标准库 `logging.getLogger(__name__)` 记录（不依赖我们的实现），由一个独立模块在启动时集中配置文件落盘 + 控制台镜像；是否开启与落盘路径可在 Settings 配置。

## What Changes

- **新增独立日志模块**（`ios_toolkit/logsys.py`）：集中提供 `setup_logging(...)` / `shutdown_logging()`。其余模块一律 `logging.getLogger(__name__)`，**不 import 本模块**，保证低耦合。模块放在底层包 `ios_toolkit`，GUI（`slide6_ui`）与 tunneld 进程均可调用，且不引入对 Qt / `slide6_ui` 的反向依赖。
- **日志级别**：`debug / info / warning / error`。文件 handler 记录 `DEBUG` 及以上；控制台 handler 记录 `INFO` 及以上（即 info 以上同时输出到控制台）。
- **文件命名与滚动（按业内规范）**：
  - 每次进程启动生成一份执行日志 `cabledios_log_<start_time>.log`（`start_time` 形如 `YYYYMMDD_HHMMSS`）。
  - **单次运行超 24h 分片**：复用标准库 `RotatingFileHandler` 的数字后缀滚动语义（`.log` 为当前 24h 窗口，`.log.1`、`.log.2`… 为更早窗口），由按时间触发的自定义 handler 每 24h 触发一次 `doRollover`。
  - **最多保留最近 5 次执行日志**：启动时按 `start_time` 清理旧的运行日志（连同其分片 `<base>.log*`），只保留最新 5 次运行。
- **开关与路径可配置**：`Settings → Preferences` 新增「日志」区：启用开关 + 日志目录选择（浏览/手填）。经 `QSettings` 持久化；保存后即时重建日志配置。默认目录采用 macOS 约定 `~/Library/Logs/CablediOS`。
- **接入执行日志**：review 现有代码，在关键路径补充日志——平台层（设备连接 / DDI 状态·挂载·卸载 / DVT 进程·定位·轨迹 / tunnel/RSD 查询 / 异常根因）、`toolkit_api` 包装（调用入口与失败原因）、GUI（启动/退出、设备选择、`AsyncRunner` 后台异常、各 Tab 关键动作）、tunneld 进程启动/停止。敏感信息（配对记录、备份密码、令牌等）严禁落日志（遵循安全基线第 4 条）。

## Capabilities

### New Capabilities

- `app-logging`：日志子系统（独立模块、级别、文件命名/24h 分片/保留最近 5 次、控制台镜像、启用开关与路径来源、敏感信息脱敏）。
- `slide6-logging-settings`：`Settings → Preferences` 内的日志配置（启用开关 + 目录选择，`QSettings` 持久化，保存即时重建）。

### Modified Capabilities

- 无（业务模块仅新增 `logging` 调用，不改变其对外契约）。

## Impact

- 新增 `ios_toolkit/logsys.py`：`setup_logging(enabled, log_dir)` / `shutdown_logging()` + 自定义按时滚动 handler + 运行日志保留清理 + 控制台/文件 handler 装配。
- `slide6_ui/app.py`：`main()` 启动时从 `QSettings` 读取日志配置并调用 `setup_logging(...)`；退出时 `shutdown_logging()`。
- `slide6_ui/main_window.py`：`_open_preferences` 增加「日志」区（启用开关 + 目录选择），保存即时重建日志；新增 `QSettings` 键 `settings/logging_enabled`、`settings/logging_dir`。
- `slide6_ui/common/file_dialogs.py`：新增 `open_directory(...)` 目录选择（复用原生/非原生开关）。
- `cabled_ios_tunnel.py` / `ios_toolkit/tunneld_main.py`：tunneld 进程启动时按默认配置调用 `setup_logging(...)`（独立进程，免 Qt）。
- 多文件补充 `logger = logging.getLogger(__name__)` 与日志语句：`ios_toolkit/device.py`、`ios_toolkit/toolkit_api.py`、`slide6_ui/common/workers.py`、`slide6_ui/common/tunnel.py`、各 Tab（`developer_tools/*`、`syslog`、`crash`、`profiles`、`app_manager`、`file_system`、`album`、`device_info`、`keymouse/*`）。

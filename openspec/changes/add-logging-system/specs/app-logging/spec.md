## ADDED Requirements

### Requirement: 独立日志模块与低耦合接入

应用 SHALL 提供一个独立日志模块（`ios_toolkit/logsys.py`），集中完成日志配置。该模块 SHALL 暴露 `setup_logging(enabled, log_dir)`（幂等，可重复调用以重建配置）与 `shutdown_logging()`（flush 并关闭自有 handler）。业务模块 MUST 仅通过标准库 `logging.getLogger(__name__)` 记录日志，MUST NOT import 该日志模块，以保证低耦合。重复调用 `setup_logging` MUST 仅移除并重建本模块自己挂载的 handler，MUST NOT 影响第三方 handler，且 MUST NOT 造成重复输出。该模块 MUST 可被 GUI 与 tunneld 两个进程调用，且 MUST NOT 反向依赖 `slide6_ui` 或 Qt。

#### Scenario: 业务模块零侵入记录

- **WHEN** 任一业务模块调用 `logging.getLogger(__name__).info(...)`
- **THEN** 记录经集中配置的 handler 输出，业务模块无需 import 日志模块

#### Scenario: 重复配置不重复输出

- **WHEN** 运行中再次调用 `setup_logging(...)`（如保存设置）
- **THEN** 先移除本模块旧的 handler 再重建，单条日志只输出一次

### Requirement: 日志级别与控制台镜像

日志 SHALL 支持 `debug / info / warning / error` 级别。启用文件日志时，文件 handler MUST 记录 `DEBUG` 及以上的全部级别；控制台 handler MUST 记录 `INFO` 及以上级别（即 info/warning/error 同时输出到控制台），`DEBUG` MUST NOT 输出到控制台。失败路径 SHALL 以 `warning`/`error` 记录并尽量附带异常栈（`exc_info`）。

#### Scenario: info 以上同时上控制台

- **WHEN** 记录一条 `info`（或 `warning`/`error`）日志
- **THEN** 该日志同时出现在控制台与日志文件

#### Scenario: debug 仅入文件

- **WHEN** 记录一条 `debug` 日志且文件日志已启用
- **THEN** 该日志写入文件但不出现在控制台

### Requirement: 执行日志文件命名、24h 分片与保留

每次进程启动 SHALL 生成一份执行日志，命名为 `cabledios_log_<start_time>.log`（`start_time` 形如 `YYYYMMDD_HHMMSS`）。单次运行持续超过 24 小时 SHALL 进行分片：以业内 `RotatingFileHandler` 的数字后缀约定滚动（`.log` 为当前 24h 窗口，`.log.1`、`.log.2`… 依次更旧），由按时间触发的 handler 每 24 小时滚动一次。应用 SHALL 最多保留最近 5 次运行的执行日志：启动配置时 MUST 以 base 文件（`cabledios_log_*.log`，不含 `.N` 后缀）为运行锚点按 `start_time` 排序，删除第 6 个及更旧运行的全部文件（含其分片）。敏感信息（配对密钥、备份密码、令牌、个人数据）MUST NOT 写入日志。

#### Scenario: 单次运行命名

- **WHEN** 进程启动且文件日志启用
- **THEN** 生成 `cabledios_log_<start_time>.log` 作为该次运行日志

#### Scenario: 超 24 小时分片

- **WHEN** 单次运行持续超过 24 小时
- **THEN** 按 `.log` / `.log.1` / `.log.2` … 的数字后缀分片滚动

#### Scenario: 仅保留最近 5 次运行

- **WHEN** 启动时目录中已有超过 5 次运行的日志
- **THEN** 仅保留最新 5 次运行的日志（连同其分片），更旧的被清理

#### Scenario: 敏感信息脱敏

- **WHEN** 某路径涉及密码 / 令牌 / 配对密钥等敏感数据
- **THEN** 日志中 MUST NOT 出现其明文（必要时仅记录存在与否或长度）

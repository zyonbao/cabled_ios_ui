# slide6-logging-settings Specification

## Purpose
TBD - created by archiving change add-logging-system. Update Purpose after archive.
## Requirements
### Requirement: 日志设置项与持久化

桌面应用 SHALL 在 Settings 窗口的「Logging」标签中提供日志配置，包含：启用文件日志的开关，以及日志目录的选择（可经文件选择器浏览，亦可直接填写路径）。这些设置 MUST 经 `QSettings` 持久化（键 `settings/logging_enabled`、`settings/logging_dir`），下次启动 SHALL 沿用。日志目录为空时 MUST 回退到默认目录 `~/Library/CablediOS/Logs`，且目录输入框 MUST 以占位文案直接展示该默认路径（形如「默认:~/Library/CablediOS/Logs」），替代旧的"留空使用默认…"提示。

#### Scenario: 配置并持久化

- **WHEN** 用户在 Logging 标签勾选启用并选择/填写日志目录
- **THEN** 设置写入 `QSettings`，重启应用后仍生效

#### Scenario: 目录为空回退默认并展示默认占位

- **WHEN** 日志目录留空
- **THEN** 使用默认目录 `~/Library/CablediOS/Logs`，且输入框以"默认:~/Library/CablediOS/Logs"占位文案展示

### Requirement: 启动初始化与保存即时生效

GUI 进程 SHALL 在启动时读取日志设置并初始化日志系统；退出时 SHALL 关闭日志（flush 文件）。在 Preferences 中修改启用开关或目录并保存后 MUST 即时重建日志配置：启用即开始落盘，禁用 MUST 移除文件输出并关闭当前日志文件，变更目录 MUST 切换到新目录，均无需重启应用。

#### Scenario: 启动按配置初始化

- **WHEN** 应用启动且设置为「启用」
- **THEN** 在配置目录创建本次运行日志并开始记录

#### Scenario: 保存设置即时生效

- **WHEN** 用户在运行中切换启用开关或更改目录并保存
- **THEN** 日志系统即时重建（启用→落盘 / 禁用→停止落盘 / 改目录→切换），无需重启

#### Scenario: 退出关闭日志

- **WHEN** 应用退出
- **THEN** flush 并关闭日志文件，不留未写入内容


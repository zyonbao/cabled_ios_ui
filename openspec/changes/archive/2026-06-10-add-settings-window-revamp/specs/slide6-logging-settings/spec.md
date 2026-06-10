## MODIFIED Requirements

### Requirement: 日志设置项与持久化

桌面应用 SHALL 在 Settings 窗口的「Logging」标签中提供日志配置，包含：启用文件日志的开关，以及日志目录的选择（可经文件选择器浏览，亦可直接填写路径）。这些设置 MUST 经 `QSettings` 持久化（键 `settings/logging_enabled`、`settings/logging_dir`），下次启动 SHALL 沿用。日志目录为空时 MUST 回退到默认目录 `~/Library/CablediOS/Logs`，且目录输入框 MUST 以占位文案直接展示该默认路径（形如「默认:~/Library/CablediOS/Logs」），替代旧的"留空使用默认…"提示。

#### Scenario: 配置并持久化

- **WHEN** 用户在 Logging 标签勾选启用并选择/填写日志目录
- **THEN** 设置写入 `QSettings`，重启应用后仍生效

#### Scenario: 目录为空回退默认并展示默认占位

- **WHEN** 日志目录留空
- **THEN** 使用默认目录 `~/Library/CablediOS/Logs`，且输入框以"默认:~/Library/CablediOS/Logs"占位文案展示

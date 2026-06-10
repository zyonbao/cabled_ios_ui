## ADDED Requirements

### Requirement: 分组标签页式 Settings 窗口

桌面应用的 Settings 窗口 SHALL 以 3 个水平切换的标签页组织配置：`General`、`Logging`、`DeveloperDiskImage`。窗口 SHALL 复用单一 `QSettings(ios_ui_ta_proxy, slide6_console)` 实例；各项设置 SHALL 在变更时即时写回（无需独立"保存"按钮），与既有 Preferences 交互一致。

#### Scenario: 三标签可切换

- **WHEN** 用户打开 Settings
- **THEN** 顶部展示 `General` / `Logging` / `DeveloperDiskImage` 三个水平标签，点击可切换对应配置页

### Requirement: General 标签 — 退出时清理 XPC 隧道开关

`General` 标签 SHALL 提供「Ask to clean XPC tunnel on exit」开关，沿用既有持久化键 `settings/ask_clean_tunnel_on_exit` 与既有退出清理行为。

#### Scenario: 开关持久化

- **WHEN** 用户在 General 标签切换该开关
- **THEN** 值写入 `QSettings` 键 `settings/ask_clean_tunnel_on_exit`，重启后沿用，退出清理行为不变

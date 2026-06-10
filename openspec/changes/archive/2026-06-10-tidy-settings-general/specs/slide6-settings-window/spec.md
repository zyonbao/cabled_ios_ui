## MODIFIED Requirements

### Requirement: 分组标签页式 Settings 窗口

桌面应用的 Settings 窗口 SHALL 以 2 个水平切换的标签页组织配置：`General`、`DeveloperDiskImage`。窗口 SHALL 复用单一 `QSettings(ios_ui_ta_proxy, slide6_console)` 实例；各项设置 SHALL 在变更时即时写回（无需独立"保存"按钮），与既有 Preferences 交互一致。

#### Scenario: 两标签可切换

- **WHEN** 用户打开 Settings
- **THEN** 顶部展示 `General` / `DeveloperDiskImage` 两个水平标签，点击可切换对应配置页
- **AND** 不再存在独立的 `Logging` 标签

### Requirement: General 标签 — 退出时清理 XPC 隧道开关

`General` 标签 SHALL 提供「Ask to clean XPC tunnel on exit」开关，沿用既有持久化键 `settings/ask_clean_tunnel_on_exit` 与既有退出清理行为。

#### Scenario: 开关持久化

- **WHEN** 用户在 General 标签切换该开关
- **THEN** 值写入 `QSettings` 键 `settings/ask_clean_tunnel_on_exit`，重启后沿用，退出清理行为不变

## ADDED Requirements

### Requirement: General 标签 — 配置文件入口

`General` 标签 SHALL 在顶部展示应用配置文件路径（取自该 `QSettings` 实例的 backing 文件），并提供「Show in Finder」按钮。点击该按钮 SHALL 在 Finder 中定位并选中该配置文件。

#### Scenario: 在 Finder 中显示配置文件

- **WHEN** 用户点击 General 标签的「Show in Finder」按钮
- **THEN** 系统打开 Finder 并选中该应用的配置文件（`QSettings` backing 文件）

#### Scenario: 配置文件尚未生成时的回退

- **WHEN** 配置文件尚未落盘（用户从未修改过任何设置）
- **THEN** 应用先触发一次持久化（sync）再尝试定位；仍不存在时 SHALL 定位其父目录并提示文件尚未生成，而非静默失败

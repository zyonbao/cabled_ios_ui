# slide6-settings-window Specification

## Purpose
TBD - created by archiving change add-settings-window-revamp. Update Purpose after archive.
## Requirements
### Requirement: 分组标签页式 Settings 窗口

桌面应用的 Settings 窗口 SHALL 以 2 个水平切换的标签页组织配置：`General`、`DeveloperDiskImage`。窗口 SHALL 复用单一 `QSettings(ios_ui_ta_proxy, slide6_console)` 实例；各项设置 SHALL 在变更时即时写回（无需独立"保存"按钮），与既有 Preferences 交互一致。窗口高度 SHALL 自适应到最高标签页所需的自然高度，使切换标签时任一页的设置行不被挤压。

#### Scenario: 两标签可切换

- **WHEN** 用户打开 Settings
- **THEN** 顶部展示 `General` / `DeveloperDiskImage` 两个水平标签，点击可切换对应配置页
- **AND** 不再存在独立的 `Logging` 标签

#### Scenario: 切换标签不挤压内容

- **WHEN** 用户在标签页之间切换
- **THEN** 窗口高度足以完整显示最高标签页的全部设置行（含 XPC tunnel 的日志文件路径行），不出现行被压扁的情况

### Requirement: General 标签 — 退出时清理 XPC 隧道开关

`General` 标签 SHALL 提供「Ask to clean XPC tunnel on exit」开关，沿用既有持久化键 `settings/ask_clean_tunnel_on_exit` 与既有退出清理行为。

#### Scenario: 开关持久化

- **WHEN** 用户在 General 标签切换该开关
- **THEN** 值写入 `QSettings` 键 `settings/ask_clean_tunnel_on_exit`，重启后沿用，退出清理行为不变

### Requirement: General 标签 — 配置文件入口

`General` 标签 SHALL 在顶部展示应用配置文件路径（取自该 `QSettings` 实例的 backing 文件），并提供「Show in Finder」按钮。点击该按钮 SHALL 在 Finder 中定位并选中该配置文件。

#### Scenario: 在 Finder 中显示配置文件

- **WHEN** 用户点击 General 标签的「Show in Finder」按钮
- **THEN** 系统打开 Finder 并选中该应用的配置文件（`QSettings` backing 文件）

#### Scenario: 配置文件尚未生成时的回退

- **WHEN** 配置文件尚未落盘（用户从未修改过任何设置）
- **THEN** 应用先触发一次持久化（sync）再尝试定位；仍不存在时 SHALL 定位其父目录并提示文件尚未生成，而非静默失败

### Requirement: General 标签 — 语言选择

`General` 标签 SHALL 提供「语言 / Language」下拉（`简体中文` → `zh-CN`，`English` → `en-US`），当前值取自 `QSettings` 键 `settings/language`（默认 `zh-CN`）。用户切换 SHALL 立即写回该键，并提示「重启后生效」；SHALL NOT 在运行时动态重译已构建的界面。

#### Scenario: 展示并持久化语言选择

- **WHEN** 用户在 General 标签切换语言下拉
- **THEN** 选择值写入 `QSettings` 键 `settings/language`
- **AND** 弹出「重启后生效 / Restart to apply」提示

#### Scenario: 下次启动按所选语言加载

- **WHEN** 用户切换语言并重启应用
- **THEN** 界面文案以所选语言展示

### Requirement: General 标签 — 文件选择器开关

`General` 标签 SHALL 提供「文件选择器」分组，内含「使用应用内置的文件/文件夹选择器」开关。开关状态 SHALL 持久化于 `QSettings` 键 `settings/use_builtin_file_dialog`（默认关闭，即使用系统原生选择器）。分组 SHALL 附带简短说明，告知默认使用系统选择器、当系统选择器访问受限时可开启内置选择器；说明文案 SHALL NOT 暴露底层框架名（如 Qt）。

#### Scenario: 开关持久化并切换选择器

- **WHEN** 用户在 General 标签切换该开关
- **THEN** 值写入 `QSettings` 键 `settings/use_builtin_file_dialog`
- **AND** 后续文件/文件夹选取按开关状态使用应用内置或系统原生选择器

#### Scenario: 默认关闭

- **WHEN** 用户从未修改该开关
- **THEN** 开关处于关闭态，选取使用系统原生选择器


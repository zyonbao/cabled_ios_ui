# 整理 Settings：配置文件入口 + Logging 并入 General

## Why

当前 Settings 窗口分 `General` / `Logging` / `DeveloperDiskImage` 三个标签，其中 `General` 只有一个开关、`Logging` 只有「启用 + 目录」两项，内容稀疏且分散。用户排查问题时也无法快速定位应用的配置文件（`QSettings` 的 plist）。本次做两项轻量整理：

1. 在 `General` 顶部展示应用配置文件路径，并提供「Show in Finder」按钮，点击后在 Finder 中定位并选中该文件，便于排查 / 备份 / 重置。
2. 把 `Logging` 标签的内容并入 `General`（置于配置文件路径 section 之下），删除独立 `Logging` 标签，使 Settings 收敛为 `General` / `DeveloperDiskImage` 两个标签。

## What Changes

- `General` 新增「配置文件」section：只读展示 `QSettings.fileName()` 的路径 + 「Show in Finder」按钮（`open -R` 定位选中）。
- 将原 `Logging` 标签的「启用文件日志」开关与「日志目录」选择（浏览 + 直填 + 默认占位 + 即时生效）整体迁入 `General`，置于配置文件 section 下方。
- 移除独立 `Logging` 标签；Settings 标签收敛为 `General` / `DeveloperDiskImage`。
- 持久化键、默认目录、即时生效行为全部不变（`settings/logging_enabled`、`settings/logging_dir`、默认 `~/Library/CablediOS/Logs`）。

## Impact

- Affected specs: `slide6-settings-window`（标签从 3 个改为 2 个、General 内容扩充）、`slide6-logging-settings`（日志配置承载位置从 Logging 标签改为 General 标签，键 / 行为不变）。
- Affected code: `slide6_ui/main_window.py`（`_open_preferences` / `_build_general_tab` / `_build_logging_tab`）。
- 无平台层（`ios_toolkit`）改动；无新增依赖。
- 纯 UI 整理，低风险；用户既有 `QSettings` 值不受影响。

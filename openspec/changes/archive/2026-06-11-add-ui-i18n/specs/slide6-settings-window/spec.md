# slide6-settings-window Specification

## ADDED Requirements

### Requirement: General 标签 — 语言选择

`General` 标签 SHALL 提供「语言 / Language」下拉（`简体中文` → `zh-CN`，`English` → `en-US`），当前值取自 `QSettings` 键 `settings/language`（默认 `zh-CN`）。用户切换 SHALL 立即写回该键，并提示「重启后生效」；SHALL NOT 在运行时动态重译已构建的界面。

#### Scenario: 展示并持久化语言选择

- **WHEN** 用户在 General 标签切换语言下拉
- **THEN** 选择值写入 `QSettings` 键 `settings/language`
- **AND** 弹出「重启后生效 / Restart to apply」提示

#### Scenario: 下次启动按所选语言加载

- **WHEN** 用户切换语言并重启应用
- **THEN** 界面文案以所选语言展示

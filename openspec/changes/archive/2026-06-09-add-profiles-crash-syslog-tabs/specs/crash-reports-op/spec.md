## ADDED Requirements

### Requirement: 列出崩溃日志

平台能力层 SHALL 提供 `list_crashes(target)`，返回设备崩溃日志目录的顶层条目，使用统一 `{ok, data}` 信封。该操作 MUST 基于 `CrashReportsManager`（AFC2），且 MUST NOT 依赖 WDA 或 XPC tunnel。

成功时 `data` MUST 形如 `{"entries": [{"name", "isDir", "size", "mtime"}, ...]}`，字段结构与 `afc_list` 对齐，以便桌面 UI 复用多选 / 导出范式。列举 MUST 仅取顶层（depth=1），不递归展开海量子目录。

#### Scenario: 设备存在崩溃日志

- **WHEN** 调用 `list_crashes(target)` 且设备有崩溃日志
- **THEN** 返回 `ok=True`，`data.entries` 为数组，每项含 `name` 与 `size`

#### Scenario: 设备无崩溃日志

- **WHEN** 调用 `list_crashes(target)` 且无崩溃日志
- **THEN** 返回 `ok=True` 且 `data.entries` 为空数组

#### Scenario: 目标不存在

- **WHEN** 以未知 `target` 调用 `list_crashes`
- **THEN** 返回 `ok=False`，`error.kind` 为 `BAD_TARGET`

### Requirement: 导出崩溃日志

平台能力层 SHALL 提供 `pull_crash(target, remote_path, local_path)`，将单个崩溃日志从设备拉取到本地路径，调用 `CrashReportsManager.pull`。`local_path` 为空时 MUST 返回 `BAD_TARGET`。导出 MUST NOT 删除设备上的原文件（删除由独立操作完成）。

#### Scenario: 成功导出单个崩溃日志

- **WHEN** 以有效 `remote_path` 与可写 `local_path` 调用 `pull_crash`
- **THEN** 返回 `ok=True`，本地路径生成对应文件，设备原文件保留

#### Scenario: 缺少本地路径

- **WHEN** 调用 `pull_crash` 但 `local_path` 为空
- **THEN** 返回 `ok=False`，`error.kind` 为 `BAD_TARGET`

### Requirement: 删除崩溃日志

平台能力层 SHALL 提供 `clear_crash(target, remote_path)`，删除设备上指定的崩溃日志条目，调用 `CrashReportsManager.clear`。该操作为破坏性操作，调用方负责二次确认。

#### Scenario: 成功删除单项

- **WHEN** 以有效 `remote_path` 调用 `clear_crash`
- **THEN** 返回 `ok=True`，且该条目从后续 `list_crashes` 结果中消失

#### Scenario: 导出后不保留原文件

- **WHEN** 调用方先 `pull_crash` 成功，再对同一 `remote_path` 调用 `clear_crash`
- **THEN** 本地保留导出副本，设备上原崩溃日志被删除

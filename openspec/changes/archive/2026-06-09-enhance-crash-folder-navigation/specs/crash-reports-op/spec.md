## MODIFIED Requirements

### Requirement: 列出崩溃日志

平台能力层 SHALL 提供 `list_crashes(target, sub_path="/")`，返回崩溃日志目录中**指定子路径**下的条目（默认根 `/`），使用统一 `{ok, data}` 信封。该操作 MUST 基于 `CrashReportsManager`（AFC2），且 MUST NOT 依赖 WDA 或 XPC tunnel。

成功时 `data` MUST 形如 `{"entries": [{"name", "path", "isDir", "size", "mtime"}, ...]}`：`name` 为条目基名（用于显示），`path` 为相对崩溃日志根、无前导 `/` 的完整路径（用于后续导航 / 导出 / 删除）。列举 MUST 仅取该层（depth=1），不递归展开。

#### Scenario: 列出根目录

- **WHEN** 以默认 `sub_path` 调用 `list_crashes(target)`
- **THEN** 返回 `ok=True`，`data.entries` 为根目录下的条目数组，每项含 `name` 与 `path`

#### Scenario: 列出子目录

- **WHEN** 以某子目录的 `path` 作为 `sub_path` 调用 `list_crashes`
- **THEN** 返回 `ok=True`，`data.entries` 为该子目录下的条目，且每项 `path` 为相对崩溃日志根的完整路径

#### Scenario: 设备无崩溃日志

- **WHEN** 根目录下无任何崩溃日志
- **THEN** 返回 `ok=True` 且 `data.entries` 为空数组

#### Scenario: 目标不存在

- **WHEN** 以未知 `target` 调用 `list_crashes`
- **THEN** 返回 `ok=False`，`error.kind` 为 `BAD_TARGET`

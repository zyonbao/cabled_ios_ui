## Why

设备崩溃日志目录顶层包含子文件夹（如 `Assistant`、`DiagnosticLogs`、`Retired`），当前「Crash 报告」Tab 仅列出顶层且双击文件夹无反应，无法进入查看其中的崩溃日志，也看不到当前所处路径。需要像「文件系统」Tab 那样支持双击进入文件夹、返回上一级并显示当前路径。

## What Changes

- **toolkit_api `list_crashes` 支持子路径**：新增可选 `sub_path` 参数（默认根 `/`），列出指定子目录的条目；保持向后兼容。
- **Crash 报告 Tab 支持目录导航**：
  - 双击文件夹进入其内容；提供「上一级」入口返回父目录（不越过 crash 根）。
  - 顶部显示当前相对路径（根显示为 `/`）。
  - 导出 / 删除沿用现有逻辑，但对当前目录下的条目按其相对 crash 根的完整路径执行（嵌套条目可正确导出 / 删除）。
  - 文件名过滤、多选、右键菜单在每一层目录内继续生效。

## Capabilities

### New Capabilities

- 无。

### Modified Capabilities

- `crash-reports-op`: `list_crashes` 增加可选 `sub_path` 参数以列出崩溃日志的子目录。
- `slide6-crash-reports`: Crash 报告 Tab 增加目录导航（双击进入文件夹、返回上一级、显示当前路径）。

## Impact

- `ios_toolkit/toolkit_api.py`：`list_crashes(target, sub_path="/")`。
- `ios_toolkit/device.py`：`iOSDevice.list_crashes(sub_path="/")` 透传给 `CrashReportsManager.ls(sub_path, depth=1)`，条目名归一化为相对 crash 根的路径以供后续 pull/clear。
- `slide6_ui/crash/crash_tab.py`：当前路径状态、路径标签、上一级按钮、双击进入文件夹。
- 不影响 syslog / 描述文件 / 其它 Tab；`pull_crash` / `clear_crash` 契约不变（已接受相对 crash 根的路径）。

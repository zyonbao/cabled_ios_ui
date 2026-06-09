## Context

「Crash 报告」Tab 当前通过 `toolkit_api.list_crashes(target)` 调 `CrashReportsManager.ls("/", depth=1)` 只列顶层，条目名经 `lstrip("/")` 归一为基名。崩溃日志根下存在子目录（`Assistant` / `DiagnosticLogs` / `Retired` 等），无法进入。

真机验证的路径形态：

- `ls("/", depth=1)` 返回带前导 `/` 的项（如 `"/DiagnosticLogs"`、`"/foo.ips"`）。
- `ls("DiagnosticLogs", depth=1)` 返回**相对 crash 根的完整路径**（如 `"DiagnosticLogs/Audio"`，无前导 `/`）。

`pull_crash` / `clear_crash` 已接受「相对 crash 根、无前导 `/`」的 entry（既有实现与真机验证均如此），因此目录导航只需把「完整相对路径」作为条目主键贯穿即可。

## Goals / Non-Goals

**Goals:**

- `list_crashes` 支持可选 `sub_path`，列出任意子目录；默认根，向后兼容。
- Tab 支持双击进入文件夹、返回上一级（不越根）、显示当前路径，复用文件系统 Tab 的交互范式。
- 导出 / 删除 / 过滤 / 多选 / 右键在每层目录内正确作用于该层条目。

**Non-Goals:**

- 不引入可编辑路径输入框（仅只读路径标签 + 上一级按钮，保持 Crash Tab 轻量）。
- 不改变 `pull_crash` / `clear_crash` 契约。

## Decisions

### 决策 1：条目同时携带显示名与完整相对路径

`list_crashes` 返回的每个条目新增 `path` 字段（相对 crash 根、无前导 `/` 的完整路径），`name` 保留为基名用于显示。UI 的双击进入、导出、删除一律以 `path` 为准；表格展示用 `name`。这样无论在第几层，pull/clear 都能用 `path` 精确定位。

- stat 统一用绝对形式 `"/" + path` 调 `crash.afc.stat(...)`，规避顶层带 `/`、子层不带 `/` 的差异。

### 决策 2：当前路径状态在 UI 维护，越根保护

Tab 维护 `cur_path`（相对根，根为 `""`）。`list_crashes(sub_path)` 中 `sub_path` 传 `cur_path or "/"`。返回上一级取 `posixpath.dirname`，并夹在根（`""`）不向上越界。设备切换 / 刷新时重置到根。

## Risks / Trade-offs

- [子目录极深 / 海量条目] → 仍按 `depth=1` 单层列举，逐层进入，避免一次性递归拉全。
- [过滤态下进入目录] → 进入目录即重新列举该层并清空过滤上下文（过滤只作用于当前层渲染），行为直观。
- [路径形态跨 iOS 版本差异] → 统一以 `lstrip("/")` 归一 + 绝对 stat，已在 iPhone 15/iOS 17.6.1 验证。

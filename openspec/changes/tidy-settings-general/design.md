## Context

- Settings 由 `slide6_ui/main_window.py._open_preferences()` 构建：`QTabWidget` 加 `General` / `Logging` / `DeveloperDiskImage` 三页，`QSettings(ios_ui_ta_proxy, slide6_console)` 单例即时写回，无独立保存按钮。
- `_build_general_tab()`：仅一个「Ask to clean XPC tunnel on exit」开关。
- `_build_logging_tab()`：「启用文件日志」开关 + 「目录」行（`QLineEdit` 占位「默认:<DEFAULT_LOG_DIR>」+ 浏览按钮 + `editingFinished`/`toggled` 即时 `_save_logging()` → `_apply_logging()`）。
- `QSettings.fileName()` 返回该实例的 backing 文件路径（macOS 上为 `~/Library/Preferences/com.<org>.<app>.plist` 一类）。

## Goals / Non-Goals

**Goals:**
- General 顶部展示配置文件路径 + 「Show in Finder」按钮（定位并选中文件）。
- Logging 控件整体迁入 General（配置文件 section 下方），删除 Logging 标签。
- 键 / 默认目录 / 即时生效行为零变更。

**Non-Goals:**
- 不改日志系统本身、不改持久化键、不改 DDI 标签。
- 不做 i18n（后续单独 proposal）；不做 web 部署。

## Decisions

1. **配置文件路径展示**：用 `self.settings.fileName()` 取路径，以只读 `QLineEdit`（或可选中的 `QLabel`）展示，右侧「Show in Finder」按钮。
2. **Show in Finder 实现**：`subprocess.run(["open", "-R", path])` —— `-R` 在 Finder 中定位并选中该文件。路径来自 `QSettings.fileName()`（应用内部生成，非外部输入），不拼接用户输入；文件可能尚未落盘（首次未写过设置），则回退 `open -R` 其父目录或提示「尚未生成」。
3. **Logging 迁入 General**：把 `_build_logging_tab()` 的控件与 `_save_logging` / `_browse_dir` / `_apply_logging` 逻辑搬进 `_build_general_tab()`，按「配置文件 section → 分隔 → 日志 section（启用开关 + 目录行）→ XPC 清理开关」自上而下排列。删除 `_build_logging_tab()` 与 `tabs.addTab(..., "Logging")`。
4. **标签收敛**：`_open_preferences()` 只加 `General` / `DeveloperDiskImage` 两页。
5. **行为不变**：日志的持久化键、默认目录占位、即时生效（`_apply_logging()`）原样保留，只是承载控件换了父标签。

## Risks / Trade-offs

- **配置文件尚未生成**：首次运行若用户没改过任何设置，plist 可能还没落盘 → `open -R` 可能失败。缓解：按钮点击时先判断文件是否存在，不存在则 `self.settings.sync()` 触发落盘后再定位，仍失败则定位父目录并提示。
- **跨平台**：`open -R` 是 macOS 专属；本应用即为 macOS 桌面应用，无需兼容其他平台。

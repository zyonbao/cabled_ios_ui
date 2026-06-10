# Tasks

## 1. General 标签：配置文件入口

- [x] 1.1 在 `_build_general_tab()` 顶部加「配置文件」section（`_build_config_file_group`）：只读 `QLineEdit` 展示 `self.settings.fileName()` + 「Show in Finder」按钮
- [x] 1.2 实现 Show in Finder（`_reveal_settings_file`）：`subprocess.run(["open", "-R", path])`；文件不存在先 `self.settings.sync()` 再定位，仍不存在则 `open` 父目录并 `_set_status` 提示「配置文件尚未生成」

## 2. Logging 迁入 General

- [x] 2.1 将日志「启用文件日志」开关 + 目录行（占位 / 浏览 / 直填 / `editingFinished`+`toggled` 即时 `_save_logging`→`_apply_logging`）整体搬入 `_build_general_tab()`（`_build_logging_group`），置于配置文件 section 之下
- [x] 2.2 删除原 `_build_logging_tab()`，并移除 `_open_preferences()` 中的 `tabs.addTab(..., "Logging")`
- [x] 2.3 标签收敛为 `General` / `DeveloperDiskImage`；General 自上而下：配置文件 section → 日志 section → 「Ask to clean XPC tunnel on exit」开关

## 3. 验证

- [x] 3.1 lint 无误（仅既有 basedpyright 相对导入告警）+ 导入冒烟（`slide6_ui.main_window` OK，`_build_logging_tab` 已移除）
- [ ] 3.2 手验：打开 Settings 仅两个标签；General 显示配置文件路径，点击 Show in Finder 能定位选中；日志开关/目录在 General 内可改且即时生效、重启沿用；持久化键不变

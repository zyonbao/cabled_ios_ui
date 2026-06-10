# Tasks

## 1. 基础设施

- [x] 1.1 新建 `slide6_ui/languages/` 目录与空骨架 `zh-CN.json` / `en-US.json`（嵌套结构，顶层命名空间：`common` / `main_window` / `dev_tools` / `keymouse` / `profiles` / `crash` / `app_manager` / `device_info` / `file_system` / `album` / `syslog`）
- [x] 1.2 新建 `slide6_ui/i18n.py`：`init(lang=None)`（解析顺序 入参 > `settings/language` > `zh-CN`，非法回退 zh-CN）、展平 catalog 到 `{dotted_key: template}`、`t(key, **kwargs)`（缺失回退 zh-CN→返回 key；`format(**kwargs)` 失败记 warning 返回原模板）。仅标准库，不 import 任何 slide6_ui 子模块
- [x] 1.3 catalog 定位用 `Path(__file__).parent / "languages"`，开发态可加载；新增 `validate()`：对比 zh-CN/en-US key 集合（缺失/多余）+ 用 `string.Formatter().parse()` 比对每个共有 key 的具名占位符集合（不一致告警）
- [x] 1.4 在 `slide6_ui/app.py` 入口（`QApplication` 创建后、构建窗口前）调用 `i18n.init()`

## 2. 语言选择 UI

- [x] 2.1 `main_window._build_general_tab()` 新增「语言 / Language」`QComboBox`（简体中文→zh-CN、English→en-US），读 `settings/language`（默认 zh-CN）
- [x] 2.2 切换时写回 `settings/language` + `QMessageBox` 提示「重启后生效 / Restart to apply」；不做运行时重译

## 3. 逐文件文案迁移（替换硬编码中文为 t(...)；f-string→具名占位符模板）

- [x] 3.1 `common/`：`afc_browser.py`、`file_dialogs.py`、`readiness.py`、`sidebar_tabs.py`、`tunnel.py`（含 osascript 提示）
- [x] 3.2 `main_window.py`（含菜单、状态栏、Settings 文案）
- [x] 3.3 `developer_tools/`：`developer_tools_tab.py`、`location_dialog.py`、`process_dialog.py`
- [x] 3.4 `keymouse/`：`keymouse_tab.py`、`gestures.py`、`keyboard.py`、`mirror.py`
- [x] 3.5 `profiles/profiles_tab.py`
- [x] 3.6 `crash/crash_tab.py`
- [x] 3.7 `app_manager/app_manager.py`
- [x] 3.8 `device_info/device_info.py`
- [x] 3.9 `file_system/file_system_tab.py`
- [x] 3.10 `album/dcim_album.py`
- [x] 3.11 `syslog/`：`syslog_panel.py`、`oslog_panel.py`、`log_panel.py`、`log_dialog.py`
- [x] 3.12 同步补全两份 catalog 的对应 key；每文件迁移后冒烟该模块可正常构建

## 4. 打包

- [x] 4.1 `packaging/build_macos_app.sh` 两处 Nuitka 调用各加 `--include-data-dir="$REPO_ROOT/slide6_ui/languages=slide6_ui/languages"`

## 5. 验证

- [x] 5.1 `validate()` 通过：zh-CN/en-US key 集合一致，无遗漏；lint 无新增告警 + 导入冒烟
- [x] 5.2 手验：默认 zh-CN 文案与现状一致；切到 en-US 重启后各 tab/子窗口/弹窗英文展示；带插值文案（如挂载结果、路径提示）参数正确
- [x] 5.3 打包冒烟：app 内含 `languages/*.json`，en-US 模式英文可加载

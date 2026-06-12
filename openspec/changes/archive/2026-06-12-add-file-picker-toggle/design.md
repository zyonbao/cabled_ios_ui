## Context

`slide6_ui` 是进程内 PySide6 桌面应用。多个 Tab 需要本地文件/文件夹选取：安装 IPA、安装 .mobileconfig、挂载 DDI 选镜像、AFC 导入/导出、截图/日志/oslog 保存、相册导出、崩溃导出、GPX 选择等。历史上仅 `file_dialogs.py` 提供了"打开单文件"的内置带路径栏对话框，其余调用点直接使用 `QFileDialog` 静态方法（默认走系统原生面板），造成体验割裂；且系统原生面板在未签名/未沙盒场景下可能访问受限。

## Goals / Non-Goals

**Goals:**
- 所有本地选取统一收口到 `file_dialogs.py`，对外暴露 4 个 helper：`open_existing_file` / `open_existing_files` / `save_file` / `open_directory`。
- 应用内置选择器统一为同一个带路径栏的对话框，覆盖打开/多选/保存/选目录四种模式。
- 提供「系统原生 ↔ 应用内置」全局开关，默认系统原生；可即时切换，无需重启。

**Non-Goals:**
- 不改设备端 AFC 文件浏览器（`afc_browser` 的设备目录树导航不在本次范围）。
- 不引入代码签名/沙盒 entitlements 的工程改造。
- 不做选择器记忆"上次目录"等增强。

## Decisions

- **单一组件多模式**：将 `_PathBarFileDialog` 泛化，构造参数支持 `file_mode` / `accept_mode` / `show_dirs_only` / `default_name`，由四个 helper 复用，保证内置选择器在所有用途上的一致外观与路径栏行为。
- **开关语义以"内置"为准**：持久化键 `settings/use_builtin_file_dialog`（默认 `False` ＝系统原生）。提供 `use_builtin_file_dialog()`，并以 `use_native_file_dialog()` 返回其取反，供 helper 内部判定；每次弹窗即时读取 `QSettings`，因此偏好变更立刻生效。
- **路径栏长路径显示头部**：`QLineEdit` 在 `setText` 后光标默认在末尾会滚动到尾部，统一在初始化及目录变化回调中 `setCursorPosition(0)`，使长路径从头部显示。
- **保存语义**：路径栏对"目录/已存在文件/不存在路径"分别处理——进入目录、选中并（仅打开模式）自动确认、保存模式跳到父目录并预填文件名。
- **Settings 自适应高度**：`QTabWidget.sizeHint()` 仅反映当前页，改为取所有标签页自然高度的最大值再加上标签栏/按钮/边距，按最高标签页定高，避免切换标签时挤压行；并给 XPC tunnel 分组与日志文件输入行设置最小高度兜底。

## Risks / Trade-offs

- **默认值变更**：默认从（此前会话内的）内置改为系统原生，符合"默认用系统、受限时切内置"的诉求；受限系统上的用户需手动开启内置选择器。
- **高度估算时机**：高度依据显示前的 `sizeHint()` 计算，极端内容下可能仍偏紧；可后续在 `show` 后二次 `adjustSize` 兜底（当前未做）。
- **统一收口的回归面**：所有调用点改为走 helper，需保证各处过滤器（`name_filters`）与默认路径参数迁移正确；已对全部调用点完成迁移并校验无 `QFileDialog` 直接残留（除 `file_dialogs.py` 自身）。

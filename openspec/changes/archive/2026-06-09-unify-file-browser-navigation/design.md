## Context

`AfcBrowserPanel` 通过在 `_on_list` 中向表格首行插入一个 `{"name": "..", "_parent": True}` 行来提供返回上一级，双击该行调用 `_go_up()`。多处代码对 `_parent` 做特判（`_row_actions` / `_show_context_menu` / `_selected_entries` / `_current_entry` / `_make_export_mime` / `_on_double_click`）。相册与 Crash 报告则用顶部「上一级」按钮 + 双击文件夹进入，无 `..` 行。

## Goals / Non-Goals

**Goals:**

- 三个浏览组件统一为「上一级按钮」返回风格。
- `AfcBrowserPanel` 行为等价（仍能返回上一级、进入文件夹、跳转路径），仅交互入口从 `..` 行改为按钮。

**Non-Goals:**

- 不移除可编辑路径输入框（用户确认保留）。
- 不改动相册 / Crash（已是目标风格）。
- 不改动 AFC 契约或导入/导出/删除逻辑。

## Decisions

### 决策 1：导航栏新增「上一级」按钮，移除 `..` 行

在 `nav` 布局最前加入 `up_btn = QPushButton("上一级")`，接线到既有 `_go_up()`。`_on_list` 不再插入 `..` 行，直接渲染 `entries`。随之移除 `_parent` 特判：`_on_double_click` 仅处理文件夹进入；`_row_actions` / `_show_context_menu` / `_selected_entries` / `_current_entry` / `_make_export_mime` 去掉 `_parent` 判断（不再有该行，逻辑简化）。

- 按钮可始终可点击（根目录时 `_go_up` 直接 no-op），与相册一致即可；为更清晰可在根目录禁用，本次保持与相册一致的简单实现（始终可点、根目录无效）。

### 决策 2：路径输入框保持可编辑

`path_edit` 与 `_on_path_entered` / `_display_path` / `_parse_path` 全部保留，回车跳转能力不变。

### 决策 3：相册只读路径标签改为可编辑输入框

`DcimAlbumTab` 的 `path_label`（`QLabel`）改为 `path_edit`（`QLineEdit`），回车经 `_on_path_entered` 跳转。为保持相册仅浏览 `/DCIM` 的设计约束，跳转目标用 `posixpath.normpath` 规范化（折叠 `..`，杜绝越出 AFC media 根的路径穿越），并夹在 `/DCIM` 根内（越界收敛到 `/DCIM`）。「上一级」按钮已存在，行为不变。

Crash 报告的同类改造（只读标签 → 可编辑输入框）归属 `enhance-crash-folder-navigation` 变更，其 `_on_path_entered` 同样以 `normpath("/" + text)` 归一为相对崩溃日志根的路径，杜绝 `..` 越界。

## Risks / Trade-offs

- [移除 `_parent` 分支遗漏] → 通读所有引用 `_parent` 的位置一并清理；移除后 `..` 行不再出现，相关分支成为无效死代码，必须删除以免误导。
- [行为回归] → 双击文件夹进入、上一级返回、路径跳转三条路径手动 / 真机回归。

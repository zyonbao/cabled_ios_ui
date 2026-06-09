## 1. AfcBrowserPanel 导航统一

- [x] 1.1 在 `_build_ui` 的 `nav` 布局最前新增 `up_btn = QPushButton("上一级")`，接线到 `_go_up()`
- [x] 1.2 `_on_list` 移除插入 `..` 行的逻辑，直接渲染 `entries`
- [x] 1.3 `_on_double_click` 移除 `_parent` 分支，仅保留进入文件夹
- [x] 1.4 清理 `_row_actions` / `_show_context_menu` / `_selected_entries` / `_current_entry` / `_make_export_mime` 中的 `_parent` 特判（死代码）

## 2. 相册路径可编辑

- [x] 2.1 `dcim_album.py`：`path_label`（`QLabel`）改为 `path_edit`（`QLineEdit`），接线 `returnPressed`
- [x] 2.2 新增 `_on_path_entered`：`normpath` 归一并夹在 `/DCIM` 根内（越界收敛到根）
- [x] 2.3 `set_target` / `_refresh` / 设备清空分支同步改用 `path_edit.setText`

## 3. 工具栏顺序与上一级禁用态统一

- [x] 3.1 三处导航栏统一为 **上一级 - 路径编辑框 - 刷新** 顺序（`afc_browser` 本就如此；`dcim_album` 由「路径-上一级-刷新」调整；`crash_tab` 将独立路径行并入工具栏）
- [x] 3.2 `afc_browser`：`_refresh` / 设备清空分支按 `cur_path != "/"` 设置 `up_btn` 启用态
- [x] 3.3 `dcim_album`：`_refresh` / 设备清空分支按 `cur_path != _DCIM_ROOT` 设置 `up_btn` 启用态
- [x] 3.4 `crash_tab`：`_update_path` 按 `bool(cur_path)` 设置 `up_btn` 启用态（已具备）

## 4. 验证

- [x] 4.1 导入冒烟：`AfcBrowserPanel` / `DcimAlbumTab` / `CrashReportsTab`
- [ ] 4.2 真机/手动回归：三处的工具栏顺序一致、根目录「上一级」禁用、非根启用、路径回车跳转与双击进入均正常

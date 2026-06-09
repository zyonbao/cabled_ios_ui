## Why

应用内多个目录浏览组件的导航交互不一致，体现在两方面：

1. **返回上一级**：相册（`DcimAlbumTab`）与 Crash 报告（`CrashReportsTab`）使用**「上一级」按钮**，而被「文件系统」Tab 与「App 列表」沙盒/Documents 浏览器复用的 `AfcBrowserPanel` 使用**列表内 `..` 返回行**。
2. **路径展示**：`AfcBrowserPanel` 提供**可编辑路径输入框（回车跳转）**，而相册与 Crash 报告仅为**只读路径标签**，无法快速跳转。
3. **工具栏顺序与按钮态**：导航元素排列顺序不一致（相册为「路径-上一级-刷新」，其余为「上一级-路径…」）；「上一级」按钮启用态也不统一（部分始终可点）。

统一为「**上一级按钮 - 可编辑路径输入框 - 刷新** 的固定顺序 + 可编辑路径回车跳转 + 上一级按钮在根目录禁用/非根启用」风格。

## What Changes

- `AfcBrowserPanel`（`common/afc_browser.py`）顶部导航栏新增「上一级」按钮，行为等价于现有 `_go_up()`；移除列表内的 `..` 返回行；双击文件夹进入子目录的行为保持不变。其可编辑路径输入框已具备，无需改动。
- `DcimAlbumTab`（`album/dcim_album.py`）的只读路径标签改为**可编辑路径输入框**，回车跳转到目标路径，并夹在 `/DCIM` 根内（不越出相册域）。「上一级」按钮已具备。
- Crash 报告 Tab 的可编辑路径改动归属并随 `enhance-crash-folder-navigation` 变更落地（该变更引入其路径展示），本变更不重复其规格。
- 影响范围：所有使用 `AfcBrowserPanel` 的位置（「文件系统」Tab、「App 列表」的 `AfcBrowserDialog`）获得一致的「上一级」按钮；相册获得可编辑路径，三处浏览器最终统一为同一导航范式。

## Capabilities

### New Capabilities

- 无。

### Modified Capabilities

- `slide6-file-system`: 文件系统 Tab 的返回上一级由「`..` 行双击」改为「上一级按钮」。
- `slide6-app-manager`: App 文件浏览器的返回上一级由「`..` 行双击」改为「上一级按钮」。
- `slide6-dcim-album`: 相册 Tab 的只读路径标签改为可编辑路径输入框（回车跳转，夹在 `/DCIM` 根内）。

## Impact

- `slide6_ui/common/afc_browser.py`：导航栏新增「上一级」按钮并接线到 `_go_up()`；`_on_list` 不再插入 `..` 行；移除随之多余的 `_parent` 行分支（双击 / 右键 / 选择等）。
- `slide6_ui/album/dcim_album.py`：路径标签 `QLabel` 改为 `QLineEdit`，新增 `_on_path_entered`（`normpath` 归一并夹在 `/DCIM` 内）。
- 不改动 `toolkit_api` 契约；Crash 的可编辑路径在 `enhance-crash-folder-navigation` 落地。

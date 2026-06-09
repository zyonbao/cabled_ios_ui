## Why

描述文件管理目前以**对话框**形式挂在「App 列表」Tab 的「描述文件…」按钮下，入口较深、与其它能力（相册 / 文件系统 / Crash / 系统日志）的「独立 sidebar Tab」范式不一致。将其提升为**独立 sidebar Tab**，入口更直观、与现有布局一致。

同时，描述文件目前只能安装 / 移除，缺少**导出**。`MobileConfigService.get_profile_list()` 的返回里已包含每个描述文件的原始字节（`ProfileManifest[identifier]['Data']`），可直接落地为 `.mobileconfig`，因此一并补上导出能力。

## What Changes

- 新增独立「描述文件」sidebar Tab（`ProfilesTab`），承载原对话框的全部能力（列表 / 安装 / 拖拽安装 / 多选移除）。
- 从「App 列表」Tab 移除「描述文件…」按钮及其对话框入口。
- 平台能力层新增 `export_profile(target, identifier, local_path)`：从 `get_profile_list` 的 `ProfileManifest` 取出原始字节写入本地 `.mobileconfig`。
- 「描述文件」Tab 新增「导出选中…」：单选弹「另存为」、多选弹「选择目录」并逐项导出，汇总成功 / 失败数量。
- Tab 实现 `set_target`，由主窗口在设备切换时分发；未选设备显示「未选择设备」。

## Capabilities

### New Capabilities

- 无（描述文件能力归属已有 `mobile-config-op` / `slide6-profile-management`）。

### Modified Capabilities

- `mobile-config-op`: 新增 `export_profile` 操作。
- `slide6-profile-management`: 由「App 列表对话框」改为「独立 sidebar Tab」，并新增导出。

## Impact

- `ios_toolkit/device.py`：新增 `export_profile(identifier, local_path)`（复用 `get_profile_list`，取 `ProfileManifest` 原始字节）。
- `ios_toolkit/toolkit_api.py`：新增 `export_profile(target, identifier, local_path)` 包装。
- `slide6_ui/profiles/profiles_tab.py`（新增 `ProfilesTab`）、`slide6_ui/profiles/__init__.py`：导出 Tab；移除/废弃 `profiles_dialog.py`。
- `slide6_ui/main_window.py`：注册「描述文件」Tab 并在 `on_select_device` 分发 `set_target`。
- `slide6_ui/app_manager/app_manager.py`：移除「描述文件…」按钮、`on_profiles_clicked` 与对话框导入。

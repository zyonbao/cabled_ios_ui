## MODIFIED Requirements

### Requirement: 文件系统 Tab

`slide6_ui` SHALL 在左侧 Tab 栏提供「文件系统」Tab，通过 `root="media"` 的 AFC 函数浏览设备**媒体分区**目录树（不含 App 沙盒），交互与 App 文件浏览器一致：顶部导航栏 SHALL 按统一顺序 **「上一级」按钮 - 可编辑路径输入框 - 「刷新」按钮** 排列（其后可接组件特有按钮，如「添加文件夹」）；「上一级」按钮 SHALL 在非根目录启用、在根目录禁用；可编辑路径回车跳转；双击文件夹进入子目录；每个条目右侧提供导入/导出/重命名/删除操作并支持等价右键菜单。该 Tab 无需 WDA 或 tunnel，选中设备即可用。

#### Scenario: 浏览媒体分区

- **WHEN** 用户选中设备并进入「文件系统」Tab
- **THEN** 通过 `afc_list(target, "", "media", path)` 列出媒体分区目录内容，双击文件夹进入子目录

#### Scenario: 点击上一级返回

- **WHEN** 用户在非根目录点击「上一级」按钮
- **THEN** 列表返回父目录并刷新

#### Scenario: 根目录禁用上一级

- **WHEN** 当前处于根目录
- **THEN**「上一级」按钮为禁用态，进入子目录后恢复启用

#### Scenario: 未选中设备

- **WHEN** 未选中有效设备
- **THEN**「文件系统」Tab 列表为空并提示未选择设备，且不触发加载

#### Scenario: 导入/导出文件或文件夹

- **WHEN** 用户对条目执行导出，或选择/拖入本地文件或文件夹执行导入
- **THEN** 分别通过 `afc_pull` / `afc_push`（`root="media"`，递归）完成传输并刷新列表

#### Scenario: 删除条目二次确认

- **WHEN** 用户对某条目执行删除
- **THEN** 弹出确认对话框，确认后通过 `afc_rm` 删除并刷新

#### Scenario: 新建文件夹与重命名

- **WHEN** 用户点击"添加文件夹"或对条目执行重命名
- **THEN** 分别通过 `afc_mkdir` / `afc_rename` 完成并刷新

# slide6-file-system Specification

## Purpose
定义桌面应用「文件系统」Tab 的能力：通过 `root="media"` 的 AFC 浏览设备媒体分区目录树（不含 App 沙盒），提供导入/导出/删除（二次确认）/新建文件夹/重命名，以及多选与右键批量下载/删除；批量能力仅在本 Tab 开启，「App 列表」沙盒浏览保持单选不变。
## Requirements
### Requirement: 文件系统 Tab

`slide6_ui` SHALL 在左侧 Tab 栏提供「文件系统」Tab，通过 `root="media"` 的 AFC 函数浏览设备**媒体分区**目录树（不含 App 沙盒），交互与 App 文件浏览器一致：可编辑相对路径（回车跳转）、非根目录顶部 `..` 行双击返回、每个条目右侧提供导入/导出/重命名/删除操作并支持等价右键菜单。该 Tab 无需 WDA 或 tunnel，选中设备即可用。

#### Scenario: 浏览媒体分区

- **WHEN** 用户选中设备并进入「文件系统」Tab
- **THEN** 通过 `afc_list(target, "", "media", path)` 列出媒体分区目录内容，双击文件夹进入子目录

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

### Requirement: 文件系统 Tab 多选与右键批量操作

「文件系统」Tab 内嵌的 AFC 浏览面板 SHALL 支持**多选**（ExtendedSelection），并在列表右键菜单中提供**批量下载**与**批量删除**。批量能力 SHALL 仅对「文件系统」Tab 开启（通过面板的可选开关），而「App 列表」沙盒浏览对话框 SHALL 保持单选默认、行为不变。批量下载 SHALL 弹出目标目录选择，随后逐项 `afc_pull` 到该目录并汇总成功/失败数量（保持单项导出的字节与时间语义）。批量删除 SHALL 弹出**一次汇总二次确认**（展示选中数量及示例名称），确认后逐项 `afc_rm` 并刷新列表；取消则不删除任何项。

#### Scenario: 多选后右键批量下载

- **WHEN** 用户在「文件系统」Tab 多选若干文件并右键选择「批量下载到…」，选定本地目录
- **THEN** 逐项经 `afc_pull` 下载到该目录，并汇总成功/失败数量

#### Scenario: 多选后右键批量删除并确认

- **WHEN** 用户多选若干项并右键选择「批量删除」，在汇总确认框中确认
- **THEN** 逐项经 `afc_rm` 删除并刷新列表

#### Scenario: 批量删除取消

- **WHEN** 用户在批量删除汇总确认框中取消
- **THEN** 不删除任何项，列表保持不变

#### Scenario: App 沙盒浏览不受影响

- **WHEN** 用户从「App 列表」打开某 App 的沙盒/Documents 浏览对话框
- **THEN** 该对话框仍为单选、无批量操作菜单，既有行为不变


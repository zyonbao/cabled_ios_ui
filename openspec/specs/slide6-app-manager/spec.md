# slide6-app-manager Specification

## Purpose
TBD - created by archiving change add-app-list-and-file-manager. Update Purpose after archive.
## Requirements
### Requirement: App 列表展示

`slide6_ui` SHALL 在「App 列表」Tab 通过 `toolkit_api.list_apps(target)` 展示当前设备已安装 App，每行至少显示名称与 bundleId，并提供一个「操作」列。「操作」列 SHALL 依据该 App 的能力按需展示 `Documents`、`Sandbox`、`卸载` 按钮：开启 fileSharing 时展示 `Documents`，沙盒可访问时展示 `Sandbox`，`卸载` 始终展示。列表加载在后台线程执行，避免界面卡顿。

#### Scenario: 选中设备后加载列表

- **WHEN** 已连接设备并切换到「App 列表」Tab（或点击列表刷新）
- **THEN** 后台调用 `list_apps(target)` 并在完成后展示 App 列表
- **AND** 每行的「操作」列依据能力展示 `Documents`/`Sandbox`/`卸载` 按钮

#### Scenario: 未连接设备

- **WHEN** 未选中有效设备
- **THEN**「App 列表」Tab 显示空列表或提示，且不触发加载

### Requirement: App 搜索与筛选

`slide6_ui` SHALL 提供按关键字搜索 App（匹配名称或 bundleId，不区分大小写），以及按"文件已共享"（fileSharing）与"沙盒可访问"进行筛选。

#### Scenario: 关键字搜索

- **WHEN** 用户在搜索框输入关键字
- **THEN** 列表实时过滤为名称或 bundleId 命中关键字的 App

#### Scenario: 按 fileSharing 筛选

- **WHEN** 用户启用"文件已共享"筛选
- **THEN** 列表仅显示 `fileSharing=true` 的 App

#### Scenario: 按沙盒可访问筛选

- **WHEN** 用户启用"沙盒可访问"筛选
- **THEN** 列表仅显示 `sandboxAccessible=true` 的 App

### Requirement: 安装与卸载 App

`slide6_ui` SHALL 支持通过点击按钮选择 `.ipa` 或将 `.ipa` 拖拽到列表区来安装 App，并支持对选中 App 执行卸载。安装/卸载完成后自动刷新列表。

#### Scenario: 点击选择 IPA 安装

- **WHEN** 用户点击"安装 IPA"并选择一个 `.ipa` 文件
- **THEN** 后台调用 `install_app(target, ipa_path)`，完成后刷新列表并提示结果

#### Scenario: 拖拽 IPA 安装

- **WHEN** 用户将 `.ipa` 文件拖入列表区
- **THEN** 触发与点击安装一致的安装流程；非 `.ipa` 文件被忽略并提示

#### Scenario: 安装失败提示

- **WHEN** `install_app` 返回错误（如签名不匹配）
- **THEN** 展示可读失败原因，且不影响现有列表

#### Scenario: 卸载 App

- **WHEN** 用户对选中 App 点击卸载并确认
- **THEN** 后台调用 `uninstall_app(target, bundle_id)`，完成后从列表移除并提示结果

### Requirement: App 文件浏览器与导入导出

`slide6_ui` SHALL 为开启 fileSharing 的 App 提供浏览 `Documents` 及其子目录的入口，为沙盒可访问的 App 提供浏览整个容器的入口。文件浏览器 SHALL：

- 顶部以**可编辑的相对路径输入框**展示当前路径（documents 根显示为 `Documents/...`、container 根显示为绝对沙盒路径），用户编辑后回车 SHALL 跳转到目标路径；路径右侧提供「刷新」与「添加文件夹」按钮。
- 当当前路径非根目录时，条目列表顶部 SHALL 显示一个 `..` 行，双击 `..` 返回上一级；`..` 行不提供任何条目操作。
- 每个条目右侧以图标按钮形式提供操作：文件夹提供 导入（上传，导入到该文件夹）、导出（下载）、重命名（✎）、删除（叉）；文件提供 导出（下载）、重命名（✎）、删除（叉）。删除 SHALL 弹出二次确认；重命名 SHALL 以当前名称预填输入框。
- 条目 SHALL 支持鼠标右键上下文菜单，菜单项与该条目能力对应（导入到此文件夹 / 导出 / 重命名 / 删除）；`..` 行不响应右键菜单。
- 支持文件与文件夹的导出（pull）与导入（push），既包含通过按钮触发，也包含通过拖拽：拖入外部文件/文件夹导入到当前目录，将条目拖出到 Finder 导出到本地。

#### Scenario: 浏览 fileSharing App 的 Documents

- **WHEN** 用户对 `fileSharing=true` 的 App 点击 `Documents`
- **THEN** 通过 `afc_list(target, bundle_id, "documents", path)` 列出目录内容，双击文件夹进入子目录，双击 `..` 或编辑路径框回车返回/跳转

#### Scenario: 浏览沙盒可访问 App 的容器

- **WHEN** 用户对 `sandboxAccessible=true` 的 App 点击 `Sandbox`
- **THEN** 通过 `afc_list(target, bundle_id, "container", path)` 列出容器内容

#### Scenario: 不满足条件时无对应入口

- **WHEN** App 既未开启 fileSharing 也不可访问沙盒
- **THEN**「操作」列仅展示 `卸载`，不出现 `Documents`/`Sandbox`

#### Scenario: 导出文件或文件夹到本地

- **WHEN** 用户在某条目上点击导出（或将其拖拽到 Finder）
- **THEN** 文件弹出"另存为"、文件夹弹出"选择目录"，确认后通过 `afc_pull(...)` 将文件/整个文件夹写入本地

#### Scenario: 导入文件或文件夹

- **WHEN** 用户点击某文件夹的导入按钮选择本地文件，或将外部文件/文件夹拖入浏览器
- **THEN** 通过 `afc_push(...)` 将其写入目标设备目录（拖入时为当前目录，点击文件夹导入时为该文件夹）并刷新列表

#### Scenario: 删除条目二次确认

- **WHEN** 用户点击某条目的删除图标
- **THEN** 弹出确认对话框，确认后通过 `afc_rm(...)` 删除并刷新列表

#### Scenario: 重命名条目

- **WHEN** 用户点击某条目的重命名图标或右键菜单"重命名"，输入新名称（不含 `/`）
- **THEN** 通过 `afc_rename(...)` 将其重命名为同目录下的新名称并刷新列表

#### Scenario: 右键上下文菜单

- **WHEN** 用户在某条目（非 `..`）上点击鼠标右键
- **THEN** 弹出菜单，依据能力提供 导入到此文件夹 / 导出 / 重命名 / 删除


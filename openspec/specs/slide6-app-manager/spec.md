# slide6-app-manager Specification

## Purpose
定义「App 列表」页面能力：应用清单展示、搜索与筛选、安装与卸载动作、按能力暴露 Documents/Sandbox 入口，并与底层 app inventory / AFC 能力协同。
## Requirements
### Requirement: App 列表展示

`slide6_ui` SHALL 在「App 列表」Tab 通过 `toolkit_api.list_apps(target)` 展示当前设备已安装 App，每行至少显示名称与 bundleId，并提供一个「操作」列。「操作」列 SHALL 依据该 App 的能力按需展示 `Documents`、`Sandbox`、`卸载` 按钮：开启 fileSharing 时展示 `Documents`，沙盒可访问时展示 `Sandbox`。`卸载` 按钮 SHALL 仅对**非系统应用**展示（`appType` 为 `System` 的内置应用不可卸载，故不展示卸载入口）。列表加载在后台线程执行，避免界面卡顿。

#### Scenario: 选中设备后加载列表

- **WHEN** 已连接设备并切换到「App 列表」Tab（或点击列表刷新）
- **THEN** 后台调用 `list_apps(target)` 并在完成后展示 App 列表
- **AND** 每行的「操作」列依据能力展示 `Documents`/`Sandbox` 按钮，并对非系统应用展示 `卸载`

#### Scenario: 未连接设备

- **WHEN** 未选中有效设备
- **THEN**「App 列表」Tab 显示空列表或提示，且不触发加载

#### Scenario: 系统应用不展示卸载

- **WHEN** 某 App 的 `appType` 为 `System`
- **THEN** 该行「操作」列不展示 `卸载` 按钮

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

`slide6_ui` SHALL 支持通过点击按钮选择 `.ipa` 或将 `.ipa` 拖拽到列表区来安装 App，并支持对选中的**非系统应用**执行卸载。系统应用（`appType` 为 `System`）不提供卸载能力。安装/卸载完成后自动刷新列表。

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

- **WHEN** 用户对选中的非系统 App 点击卸载并确认
- **THEN** 后台调用 `uninstall_app(target, bundle_id)`，完成后从列表移除并提示结果

#### Scenario: 系统应用不可卸载

- **WHEN** 某 App 为系统应用
- **THEN** 不展示卸载入口；即便程序内触发卸载亦被拦截并提示「系统应用不支持卸载」

### Requirement: App 文件浏览器与导入导出

`slide6_ui` SHALL 为开启 fileSharing 的 App 提供浏览 `Documents` 及其子目录的入口，为沙盒可访问的 App 提供浏览整个容器的入口。文件浏览器 SHALL：

- 顶部导航栏 SHALL 按统一顺序 **「上一级」按钮 - 可编辑路径输入框 - 「刷新」按钮** 排列，其后接「添加文件夹」按钮。「上一级」按钮 SHALL 在非根目录启用、在根目录禁用。可编辑路径输入框 SHALL 将**当前上下文的根统一显示为 `/`**（`Documents` 浏览的根显示为 `/` 而非 `Documents`，container 浏览的根亦为 `/`），其下层级以 `/` 起的相对上下文路径表示；用户编辑后回车 SHALL 跳转到目标路径。底层真实 AFC 路径映射不变。
- 条目列表 SHALL **不**包含 `..` 返回行；返回上一级统一经由顶部「上一级」按钮。
- 每个条目右侧以图标按钮形式提供操作：文件夹提供 导入（上传，导入到该文件夹）、导出（下载）、重命名（✎）、删除（叉）；文件提供 导出（下载）、重命名（✎）、删除（叉）。删除 SHALL 弹出二次确认；重命名 SHALL 以当前名称预填输入框。
- 条目 SHALL 支持鼠标右键上下文菜单，菜单项与该条目能力对应（导入到此文件夹 / 导出 / 重命名 / 删除）。
- 支持文件与文件夹的导出（pull）与导入（push），既包含通过按钮触发，也包含通过拖拽：拖入外部文件/文件夹导入到当前目录，将条目拖出到 Finder 导出到本地。

#### Scenario: 浏览 fileSharing App 的 Documents

- **WHEN** 用户对 `fileSharing=true` 的 App 点击 `Documents`
- **THEN** 通过 `afc_list(target, bundle_id, "documents", path)` 列出目录内容，路径框根显示为 `/`，双击文件夹进入子目录，点击「上一级」按钮或编辑路径框回车返回/跳转

#### Scenario: Documents 根显示为 /

- **WHEN** 用户处于某 App `Documents` 浏览的根
- **THEN** 路径框显示 `/`（而非 `Documents`），「上一级」按钮禁用

#### Scenario: 点击上一级返回

- **WHEN** 用户在非根目录点击「上一级」按钮
- **THEN** 列表返回父目录并刷新

#### Scenario: 根目录禁用上一级

- **WHEN** 当前处于根目录
- **THEN**「上一级」按钮为禁用态，进入子目录后恢复启用

#### Scenario: 浏览沙盒可访问 App 的容器

- **WHEN** 用户对 `sandboxAccessible=true` 的 App 点击 `Sandbox`
- **THEN** 通过 `afc_list(target, bundle_id, "container", path)` 列出容器内容

#### Scenario: 右键上下文菜单

- **WHEN** 用户在某条目上点击鼠标右键
- **THEN** 弹出菜单，依据能力提供 导入到此文件夹 / 导出 / 重命名 / 删除


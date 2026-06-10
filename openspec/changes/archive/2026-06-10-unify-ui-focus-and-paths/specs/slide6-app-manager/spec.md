## MODIFIED Requirements

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

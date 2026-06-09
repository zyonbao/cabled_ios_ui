## MODIFIED Requirements

### Requirement: 描述文件管理入口

桌面应用 SHALL 在左侧 sidebar Tab 栏提供独立的「描述文件」Tab（不再作为「App 列表」Tab 的对话框入口）。该 Tab MUST 实现 `set_target(target)`，由主窗口在设备切换时分发；未选中设备时 MUST 显示「未选择设备」状态，不发起设备请求。

#### Scenario: 选中设备进入 Tab

- **WHEN** 已选中设备并进入「描述文件」Tab
- **THEN** Tab 自动加载并展示当前设备的描述文件列表

#### Scenario: 未选择设备

- **WHEN** 未选中任何设备
- **THEN**「描述文件」Tab 显示「未选择设备」，列表为空，不发起设备请求

### Requirement: 描述文件列表展示

「描述文件」Tab SHALL 以表格展示当前设备的描述文件，至少包含名称与标识符列；存在类型 / 组织等信息时 SHALL 一并展示。列表 SHALL 支持刷新，并在加载 / 失败时显示状态文案。所有阻塞调用 MUST 经由 `AsyncRunner` 在工作线程执行，不阻塞 GUI 线程。

#### Scenario: 展示描述文件

- **WHEN** 列表加载成功
- **THEN** 表格按描述文件逐行显示名称与标识符，状态显示总数

#### Scenario: 加载失败

- **WHEN** 列表加载失败
- **THEN** 状态文案显示失败原因，表格保持为空或上一次内容

### Requirement: 安装描述文件

「描述文件」Tab SHALL 支持通过点击选择文件或拖拽安装 `.mobileconfig` 文件。拖拽 MUST 仅接受扩展名为 `.mobileconfig` 的本地文件；非法拖入 MUST 给出明确提示。安装下发后 MUST 提示用户「需在设备『设置』中手动确认安装」。

#### Scenario: 点击安装

- **WHEN** 用户通过文件选择器选择一个 `.mobileconfig` 文件
- **THEN** 应用下发安装并提示需在设备端确认

#### Scenario: 拖拽安装

- **WHEN** 用户拖入一个 `.mobileconfig` 文件
- **THEN** 应用下发安装并提示需在设备端确认

#### Scenario: 拖入非法文件

- **WHEN** 用户拖入非 `.mobileconfig` 文件
- **THEN** 提示仅支持 `.mobileconfig`，不发起安装

### Requirement: 多选移除描述文件

「描述文件」Tab SHALL 支持多选并批量移除描述文件。移除前 MUST 弹出二次确认。移除完成后 MUST 刷新列表并汇总成功 / 失败数量；个别条目失败（如受监管限制）MUST 不中断其余条目处理。

#### Scenario: 批量移除确认

- **WHEN** 用户多选若干描述文件并点击移除
- **THEN** 弹出包含数量的二次确认对话框

#### Scenario: 移除完成汇总

- **WHEN** 用户确认移除
- **THEN** 逐项移除后刷新列表，状态显示成功与失败数量

## ADDED Requirements

### Requirement: 导出描述文件

「描述文件」Tab SHALL 支持导出选中的描述文件到本地 `.mobileconfig`，经 `export_profile` 取回设备上的原始字节。单选时 SHALL 弹出「另存为」（预填 `<名称>.mobileconfig`）；多选时 SHALL 弹出目录选择并逐项导出（以 `<标识符>.mobileconfig` 命名避免重名），完成后汇总成功 / 失败数量。所有阻塞调用 MUST 经由 `AsyncRunner` 执行。未选中任何条目时 MUST 给出提示而非报错。

#### Scenario: 单选导出

- **WHEN** 用户选中一个描述文件并点击「导出选中…」，在另存对话框确认路径
- **THEN** 该描述文件原始字节写入所选文件，状态提示已导出

#### Scenario: 多选导出

- **WHEN** 用户多选若干描述文件并点击「导出选中…」，选定目标目录
- **THEN** 逐项导出到该目录并汇总成功 / 失败数量

#### Scenario: 未选中条目

- **WHEN** 未选中任何描述文件即点击「导出选中…」
- **THEN** 提示先选择要导出的描述文件，不发起设备请求

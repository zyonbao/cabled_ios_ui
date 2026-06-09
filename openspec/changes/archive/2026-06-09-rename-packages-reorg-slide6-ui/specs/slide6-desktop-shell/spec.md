## MODIFIED Requirements

### Requirement: 桌面应用启动与入口

`slide6_ui` SHALL 提供一个可通过 `python3 -m slide6_ui.app` 启动的 PySide6 桌面应用，并在进程内直接复用 `ios_toolkit.toolkit_api`，不依赖任何 HTTP 服务。主窗口 SHALL 采用左侧纵向多 Tab 布局：顶部为设备选择控件与"刷新设备列表"按钮，左侧自上而下依次为「设备信息」「键鼠操作」「App 列表」三个 Tab。「键鼠操作」Tab 承载画面区域、状态指示与设备动作控件。顶部 SHALL NOT 展示系统版本 / UDID 等设备明细（改由「设备信息」Tab 承载）。选中设备后 SHALL 默认切换到「设备信息」Tab（避免自动支付 WDA/镜像启动开销）。

#### Scenario: 启动主窗口

- **WHEN** 用户执行 `python3 -m slide6_ui.app`
- **THEN** 弹出主窗口，顶部显示设备选择控件与刷新按钮，左侧自上而下显示「设备信息」「键鼠操作」「App 列表」三个 Tab
- **AND**「键鼠操作」Tab 显示画面区域、状态指示与设备动作控件
- **AND** 顶部不展示系统版本 / UDID
- **AND** 进程内不监听任何 HTTP 端口

#### Scenario: 选中设备默认进入设备信息 Tab

- **WHEN** 用户在下拉框选中一个设备
- **THEN** 界面默认切换到「设备信息」Tab，且不自动启动 WDA/镜像

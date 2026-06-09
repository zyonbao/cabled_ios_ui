## MODIFIED Requirements

### Requirement: 桌面应用启动与入口

`slide6_console` SHALL 提供一个可通过 `python3 -m slide6_console.app` 启动的 PySide6 桌面应用，并在进程内直接复用 `executor_ios.toolkit_api`，不依赖任何 HTTP 服务。主窗口 SHALL 采用左侧纵向多 Tab 布局：顶部为设备选择控件与"刷新设备列表"按钮，左侧自上而下依次为「设备信息」「键鼠操作」「App 列表」三个 Tab。「键鼠操作」Tab 承载画面区域、状态指示与设备动作控件。顶部 SHALL NOT 展示系统版本 / UDID 等设备明细（改由「设备信息」Tab 承载）。选中设备后 SHALL 默认切换到「设备信息」Tab（避免自动支付 WDA/镜像启动开销）。

#### Scenario: 启动主窗口

- **WHEN** 用户执行 `python3 -m slide6_console.app`
- **THEN** 弹出主窗口，顶部显示设备选择控件与刷新按钮，左侧自上而下显示「设备信息」「键鼠操作」「App 列表」三个 Tab
- **AND**「键鼠操作」Tab 显示画面区域、状态指示与设备动作控件
- **AND** 顶部不展示系统版本 / UDID
- **AND** 进程内不监听任何 HTTP 端口

#### Scenario: 选中设备默认进入设备信息 Tab

- **WHEN** 用户在下拉框选中一个设备
- **THEN** 界面默认切换到「设备信息」Tab，且不自动启动 WDA/镜像

### Requirement: 帧率与 MJPEG 流参数配置

应用 SHALL 在「键鼠操作」Tab 的右侧操作区提供帧率切换（5/10/15/20 fps），并通过 `toolkit_api.configure_mjpeg(target, framerate, scaling_factor, quality)` 应用到 WDA broadcaster。

#### Scenario: 切换帧率

- **WHEN** 用户在已连接状态于「键鼠操作」Tab 切换帧率
- **THEN** 调用 `configure_mjpeg` 应用新帧率，画面按新帧率刷新

## ADDED Requirements

### Requirement: 设备信息 Tab

应用 SHALL 提供「设备信息」Tab（位于左侧 Tab 列首位），通过 `toolkit_api.device_info(target)` 读取当前设备的 lockdown 全量属性，并以键/值表格形式尽可能详细地展示（如 DeviceName、ProductType、ProductVersion、BuildVersion、SerialNumber、UniqueDeviceID 等，有则展示）。常用标识字段 SHALL 优先排列，其余按字段名排序。该 Tab SHALL 提供刷新与按字段/值筛选能力，并 SHALL 支持复制单元格内容（双击复制；右键菜单提供复制字段名/值/字段=值）。读取在后台线程执行，无需 WDA 或 tunnel。

#### Scenario: 选中设备展示设备信息

- **WHEN** 用户选中一个设备（或在「设备信息」Tab 点击刷新）
- **THEN** 后台调用 `device_info(target)` 并将返回的属性以键/值表格展示

#### Scenario: 未选中设备

- **WHEN** 未选中有效设备
- **THEN**「设备信息」Tab 表格为空并提示未选择设备，且不触发读取

#### Scenario: 筛选设备信息

- **WHEN** 用户在筛选框输入关键字
- **THEN** 表格仅显示字段名或值命中关键字的行

#### Scenario: 复制字段或值

- **WHEN** 用户双击某单元格，或在某行右键选择复制项
- **THEN** 对应的字段名 / 值 / "字段=值" 被写入系统剪贴板

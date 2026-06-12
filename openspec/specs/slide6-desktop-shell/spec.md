## Purpose

定义 `slide6_ui` PySide6 桌面应用主壳（设备发现/选择、左侧多 Tab 布局、WDA 准备生命周期、画面区域、设备动作与帧率配置等），为各功能 Tab 提供统一的进程内入口与设备生命周期管理。
## Requirements
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

### Requirement: 设备发现与选择

应用 SHALL 通过 `toolkit_api.list_targets()` 列出 USB 设备，并在选择控件中区分已安装与未安装 WDA 的设备。

#### Scenario: 列出设备并标识 WDA 状态

- **WHEN** 应用启动或用户点击刷新
- **THEN** 列出所有 USB 设备，未安装 WDA 的设备显示"未装 WDA"标识

#### Scenario: 未检测到设备

- **WHEN** 没有任何 USB 设备
- **THEN** 画面区域显示"未检测到 USB 设备"提示，且不进入镜像状态

#### Scenario: 选择未装 WDA 的设备

- **WHEN** 用户选中一个未安装 WDA 的设备
- **THEN** 画面区域显示黑屏与"该设备未安装 WebDriverAgent (WDA)"提示
- **AND** 不启动镜像与控制

### Requirement: WDA 准备生命周期与状态展示

选中已装 WDA 的设备时，应用 SHALL 调用 `toolkit_api.prepare(target)` 启动 WDA，并在后台线程执行以避免界面卡顿，期间展示进度状态。

#### Scenario: 准备成功进入连接

- **WHEN** 用户选中一个已装 WDA 的设备
- **THEN** 显示"正在启动 WebDriverAgent…"状态
- **AND** `prepare` 成功后状态变为"已连接"并开始屏幕镜像

#### Scenario: 准备失败

- **WHEN** `prepare` 调用返回错误或超时
- **THEN** 显示启动失败状态与错误信息，且不进入镜像

#### Scenario: 准备期间切换设备

- **WHEN** 在某设备 `prepare` 仍在进行时，用户切换到另一设备
- **THEN** 丢弃前一设备的过期回调，不污染当前设备的状态与画面

### Requirement: 画面区域按设备逻辑尺寸布局

应用 SHALL 通过 `toolkit_api.window_size(target)` 获取设备逻辑窗口尺寸，并据此维持画面区域的宽高比。

#### Scenario: 应用设备宽高比

- **WHEN** 设备准备完成并取得 `window_size`
- **THEN** 画面区域以该宽高比显示，并在窗口缩放时保持比例

### Requirement: 设备动作（HOME / App Switcher / 截图）

应用 SHALL 提供 HOME、App Switcher、截图保存按钮，分别调用 `toolkit_api.key_event(target,"HOME")`、`toolkit_api.app_switcher(target)`、`toolkit_api.screenshot(target)`。

#### Scenario: 触发 HOME

- **WHEN** 已连接状态下用户点击 HOME
- **THEN** 调用 `key_event(target,"HOME")`，设备回到主屏

#### Scenario: 打开 App Switcher

- **WHEN** 已连接状态下用户点击 App Switcher
- **THEN** 调用 `app_switcher(target)` 并在未确认生效时给出可重试提示

#### Scenario: 保存截图

- **WHEN** 已连接状态下用户点击截图
- **THEN** 调用 `screenshot(target)` 获取 PNG
- **AND** 弹出"另存为"对话框由用户选择保存位置后写入文件

### Requirement: 帧率与 MJPEG 流参数配置

应用 SHALL 在「键鼠操作」Tab 的右侧操作区提供帧率切换（5/10/15/20 fps），并通过 `toolkit_api.configure_mjpeg(target, framerate, scaling_factor, quality)` 应用到 WDA broadcaster。

#### Scenario: 切换帧率

- **WHEN** 用户在已连接状态于「键鼠操作」Tab 切换帧率
- **THEN** 调用 `configure_mjpeg` 应用新帧率，画面按新帧率刷新

### Requirement: 选中设备后提供刷新按钮

`slide6_ui` SHALL 在选中设备后提供一个"刷新"按钮，点击后执行与重新选中当前设备**完全一致**的逻辑（停旧流 → `prepare` → 取 `window_size` 与 `orientation` → `configure_mjpeg` → 重连视频流），并沿用 generation 计数丢弃过期回调。该按钮用于设备旋转后手动重新同步，区别于"刷新设备列表"。

#### Scenario: 点击刷新重新同步当前设备

- **WHEN** 已选中并连接某设备时用户点击刷新按钮
- **THEN** 触发与重新选中该设备一致的流程，重新取得方向与尺寸并重连画面

#### Scenario: 未选中有效设备时不可用

- **WHEN** 未选中设备或选中的是未装 WDA 的设备
- **THEN** 刷新按钮不可用（或点击不进入镜像流程）

#### Scenario: 刷新期间切换设备

- **WHEN** 刷新流程仍在进行时用户切换到另一设备
- **THEN** 丢弃前一次刷新的过期回调，不污染当前设备状态与画面

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

### Requirement: 侧边 Tab 顺序

应用 SHALL 以固定顺序在左侧 Tab 栏排列功能页：**设备信息 / 相册 / 文件系统 / App 列表 / 描述文件 / Crash 报告 / 开发者工具 / 键鼠操作 / 诊断**。信息类「设备信息」SHALL 置于首位；「开发者工具」「键鼠操作」「诊断」这三个偏高级 / 重的能力 SHALL 连续排列且顺序严格为「开发者工具 → 键鼠操作 → 诊断」（键鼠操作的 tunnel / DDI 依赖统一由其上方的「开发者工具」承担，诊断紧随其后）。

#### Scenario: Tab 顺序

- **WHEN** 应用启动
- **THEN** 左侧 Tab 依次为 设备信息、相册、文件系统、App 列表、描述文件、Crash 报告、开发者工具、键鼠操作、诊断

#### Scenario: 三个高级 Tab 的相对顺序

- **WHEN** 应用启动后查看「开发者工具」「键鼠操作」「诊断」三者
- **THEN** 它们连续排列，且顺序为 开发者工具 → 键鼠操作 → 诊断

### Requirement: 设备切换保留当前 Tab

应用启动时 SHALL 默认选中「设备信息」Tab（即首位 Tab）。当用户切换所选设备时，应用 SHALL **保留**用户当前所在的 Tab，而非每次都重置/跳回「设备信息」。

#### Scenario: 启动默认 Tab

- **WHEN** 应用启动
- **THEN** 当前选中的 Tab 为「设备信息」

#### Scenario: 切换设备保留 Tab

- **WHEN** 用户当前停留在「相册/文件系统/App 列表/键鼠操作」中的某个 Tab，并切换所选设备
- **THEN** 仍停留在原 Tab，不被重置回「设备信息」

### Requirement: Tab 与刷新后的当前页默认不自动聚焦控件

切换到任意侧边 Tab、刷新并重选当前设备后的当前页，或进入任意子页面 / 对话框时，应用 MUST NOT 自动将键盘焦点落到任何控件（包括输入框、按钮、复选框等）。焦点应保持中性，由用户主动点选控件后再交互。唯一例外：键鼠操作打开键盘输入捕获时，MUST 自动聚焦捕获输入框以便立即接收按键。

#### Scenario: 切换到含输入框的 Tab

- **WHEN** 用户切换到「设备信息 / App 列表 / Crash 报告 / 系统日志」等含输入框的 Tab
- **THEN** 当前页不自动聚焦任何控件

#### Scenario: 进入子页面 / 对话框

- **WHEN** 用户打开某个含输入框的子页面或对话框
- **THEN** 不自动聚焦其中的任何控件

#### Scenario: 刷新后当前页保持无焦点

- **WHEN** 用户刷新并重选当前设备，且当前停留在某个功能页
- **THEN** 刷新完成后该页不自动聚焦任何控件

#### Scenario: 键盘捕获例外

- **WHEN** 用户在键鼠操作中打开键盘输入捕获
- **THEN** 自动聚焦捕获输入框（保持现状）

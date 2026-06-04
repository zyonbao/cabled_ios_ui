## ADDED Requirements

### Requirement: 桌面应用启动与入口

`slide6_console` SHALL 提供一个可通过 `python3 -m slide6_console.app` 启动的 PySide6 桌面应用，并在进程内直接复用 `executor_ios.toolkit_api`，不依赖任何 HTTP 服务。

#### Scenario: 启动主窗口

- **WHEN** 用户执行 `python3 -m slide6_console.app`
- **THEN** 弹出主窗口，显示设备选择控件、画面区域、状态指示与设备动作按钮
- **AND** 进程内不监听任何 HTTP 端口

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

应用 SHALL 提供帧率切换（5/10/15/20 fps），并通过 `toolkit_api.configure_mjpeg(target, framerate, scaling_factor, quality)` 应用到 WDA broadcaster。

#### Scenario: 切换帧率

- **WHEN** 用户在已连接状态切换帧率
- **THEN** 调用 `configure_mjpeg` 应用新帧率，画面按新帧率刷新

## Purpose

桌面应用屏幕镜像——消费 WDA MJPEG broadcaster 实时渲染画面，处理解码/断流/设备切换并按屏幕方向渲染与映射坐标。
## Requirements
### Requirement: 消费 WDA MJPEG broadcaster 渲染实时画面

应用 SHALL 在后台线程连接设备的 MJPEG broadcaster（`device.mjpeg_local_port`），完成握手后按 multipart 边界解析出每帧 JPEG，并在主线程渲染到画面控件。

#### Scenario: 建立流并渲染

- **WHEN** 设备准备完成进入连接状态
- **THEN** 后台线程连接 `127.0.0.1:<mjpeg_local_port>`，发送触发字节并消费 WDA 的 HTTP 头
- **AND** 持续解析 JPEG 帧并在主线程刷新画面

#### Scenario: 端口不可用

- **WHEN** 设备的 `mjpeg_local_port` 不可用
- **THEN** 显示画面流不可用的错误提示，且不崩溃

### Requirement: 解码与线程边界

应用 SHALL 在后台线程完成 JPEG 解码，仅通过信号把解码后的图像传回主线程绘制，主线程不得执行阻塞的网络或解码操作。

#### Scenario: 后台解码主线程绘制

- **WHEN** 后台线程收到一帧完整 JPEG
- **THEN** 在后台线程解码为图像并通过信号发回主线程
- **AND** 主线程仅负责把图像绘制到画面控件

### Requirement: 断流处理

当画面流中断时，应用 SHALL 停止渲染并提示用户，而不是冻结或崩溃。

#### Scenario: 流中断

- **WHEN** 已连接状态下 MJPEG 连接被关闭或读取失败
- **THEN** 显示"画面流已中断"提示，并允许用户重新选择设备重试

### Requirement: 设备切换时清理流资源

切换设备或停止镜像时，应用 SHALL 使旧的流线程失效并关闭其连接，避免过期帧污染新设备画面。

#### Scenario: 切换设备停止旧流

- **WHEN** 用户从设备 A 切换到设备 B
- **THEN** 设备 A 的流线程被标记失效并关闭连接
- **AND** 画面只显示设备 B 的帧

### Requirement: 按屏幕方向渲染画面与坐标映射

`slide6_ui` 的画面控件 SHALL 在准备设备后取得 `ios_toolkit.toolkit_api.orientation(target)`，并据此渲染 MJPEG 画面：当帧方向与 `window_size`（当前方向）不一致时按 `degrees` 把帧旋转 90°/270° 使其与当前方向对齐；当帧方向已一致但朝向为 `PORTRAIT_UPSIDE_DOWN` 时额外旋转 180°（仅凭宽高比无法识别 180° 翻转）。旋转后再 letterbox 居中绘制，使画面朝向与设备一致、宽高比正确，且手势坐标映射到 `window_size`（当前方向）空间在四方向下都正确。

#### Scenario: 竖屏渲染

- **WHEN** 设备为竖屏
- **THEN** 画面不旋转，按竖屏宽高比 letterbox 显示
- **AND** 点按/滑动映射到设备坐标正确

#### Scenario: 横屏渲染与点击

- **WHEN** 设备为横屏（左或右）
- **THEN** 画面以横屏宽高比正立显示且不变形
- **AND** 用户点击画面某处时映射出的设备坐标对应该可视位置

#### Scenario: 倒置竖屏渲染

- **WHEN** 设备为倒置竖屏（`PORTRAIT_UPSIDE_DOWN`）
- **THEN** 画面额外旋转 180° 正立显示，而非保持倒置

#### Scenario: 方向获取失败回退

- **WHEN** `orientation` 查询失败或返回未知方向
- **THEN** 按竖屏（不旋转）渲染，且不崩溃

### Requirement: 键鼠操作接入设备就绪前置检查

「键鼠操作」在启动 WDA / DVT 相关流程前 MUST 应用统一的设备就绪前置检查（见 `slide6-device-readiness`）。该检查 MUST 在以下时机重新执行：用户切换到「键鼠操作」Tab、当前设备被刷新/重选且「键鼠操作」为活动页、以及配对状态刚从未配对变为已配对且当前停留在「键鼠操作」页。当前置条件不满足时，MUST 以**非模态**方式（全页 gate overlay / 状态文案）给出可操作引导而非直接失败，且 MUST NOT 弹出任何模态对话框、MUST NOT 从键鼠操作侧自动拉起 tunnel：

- iOS 17+ 缺 tunnel 时：提示这些功能需要先启用 XPC tunnel，请前往「开发者工具」启动 XPC tunnel 并挂载 DeveloperDiskImage（不提供启动入口、不弹模态、不自动拉起）。
- 缺 DDI 时：提示前往「开发者工具」根 tab 挂载 DDI。
- tunnel 与 DDI 均就绪但 RSD 服务不工作时：提示重新挂载 DDI 或重启 tunnel（均在「开发者工具」操作）。

当 readiness 未通过时，`ScreenView` MUST 保持静默：MUST NOT 启动 `prepare` / WDA / `window_size` / `orientation` / MJPEG / frame render 流程，MUST NOT 做渲染检测，MUST NOT 显示内部画面提示文案。只有 readiness 全通过后，才允许进入后续渲染链路。

#### Scenario: iOS 17+ 缺 tunnel 进入键鼠操作

- **WHEN** iOS 17+ 设备 tunnel 未启用，用户选中设备 / 进入键鼠操作
- **THEN** 不弹出模态对话框、不自动拉起 tunnel
- **AND** 以全页 gate overlay / 状态提示引导用户前往「开发者工具」启动 XPC tunnel 并挂载 DeveloperDiskImage
- **AND** `ScreenView` 不启动任何 WDA / 渲染相关流程

#### Scenario: iOS 17+ 缺 DDI 进入键鼠操作

- **WHEN** iOS 17+ 设备 tunnel 已就绪但 DDI 未挂载，用户进入键鼠操作
- **THEN** 以全页 gate overlay / 状态提示引导前往「开发者工具」根 tab 挂载 DDI，而非直接 WDA 失败
- **AND** `ScreenView` 不启动任何 WDA / 渲染相关流程

#### Scenario: tunnel 与 DDI 就绪但 RSD 不工作

- **WHEN** iOS 17+ 设备 tunnel 与 DDI 均就绪，但目标 RSD 开发者服务不可用
- **THEN** 以全页 gate overlay / 状态提示引导用户重新挂载 DDI 或在「开发者工具」重启 XPC tunnel
- **AND** `ScreenView` 不启动任何 WDA / 渲染相关流程

#### Scenario: 配对后切到键鼠操作触发复检

- **WHEN** 设备刚完成配对且用户切换到「键鼠操作」Tab
- **THEN** 重新执行 readiness 检查，而不是复用旧的渲染态
- **AND** 若 tunnel / DDI / RSD 任一未就绪，则显示对应 gate overlay 并保持 `ScreenView` 静默

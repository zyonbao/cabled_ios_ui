## Why

现有 `web_console` 是浏览器端控制台，依赖 FastAPI + 浏览器，且天然无法完成"检测/授权拉起本机特权进程"等桌面级能力。为后续把 iOS 设备控制台作为独立桌面应用分发（内置 Python runtime、可做端口检测与授权等），需要一个与 `web_console` 功能对等的 PySide6 桌面版 `slide6_console`，直接在进程内复用 `executor_ios.toolkit_api`，去掉 HTTP 中间层。

本变更覆盖"与 `web_console` 功能对等"的范围，并额外补充一项桌面端独有能力：在选中设备后、当该设备为 iOS 17+ 时检测 XPC tunnel 端口，缺失时经系统授权以管理员方式拉起 tunneld（这是浏览器端做不到、而 iOS 17+ 设备又必需的前置条件）。tunnel 端口的完整可配置化、横屏朝向处理等仍为后续独立变更。

## What Changes

- 新增 `slide6_console/` 目录（与 `executor_ios` / `web_console` 同级），基于 PySide6 实现桌面 GUI。
- 桌面应用直接 `import executor_ios.toolkit_api`，**不经过 HTTP**；删除/不引入 FastAPI 依赖。
- 实现与 `web_console` 对等的全部交互功能：
  - 设备列表选择（含"未装 WDA"标识与黑屏提示）
  - WDA 启动准备（`prepare`）与状态展示
  - 实时屏幕镜像（消费 WDA MJPEG broadcaster，桌面端解码渲染）
  - 鼠标点按 / 拖拽滑动 → 设备坐标映射（基于 `window_size` 逻辑尺寸）
  - HOME / App Switcher / 截图保存
  - 帧率切换（5/10/15/20 fps）与 MJPEG 参数配置
  - 键盘镜像：文本/中文 IME 输入、编辑键（回车/退格/Tab/Esc）、导航键（方向/Home/End/PageUp/Down）、组合键（⌘/⌃/⌥/⇧）
- 新增 `slide6_console/requirements.txt`（仅 PySide6 等桌面栈依赖）与 `README.md`。
- 选中设备后，若该设备为 iOS 17+，则检测 XPC tunnel 端口（`executor_ios` 当前使用的 `127.0.0.1:49151`）是否有进程在监听；若无，则弹窗提示用户需要启动 XPC tunnel。iOS 17 以下设备不需要 tunnel，跳过检测。
- 用户确认后，经 macOS 系统原生授权（管理员权限）拉起 `executor_ios.tunneld_main`（即 `tunneld_main.py`）；采用 osascript 方案，每次拉起 tunnel 都触发一次系统授权。随后轮询端口就绪并继续设备准备流程。

## Capabilities

### New Capabilities

- `slide6-desktop-shell`: PySide6 桌面应用外壳——设备发现/选择、WDA 准备生命周期、连接状态与提示、窗口布局（按设备逻辑尺寸维持宽高比），以及 HOME / App Switcher / 截图保存 / 帧率与流参数配置等设备动作。
- `slide6-screen-mirror`: 在桌面端消费 WDA 的 MJPEG broadcaster 并连续渲染设备画面（后台线程读取 multipart 流、解码 JPEG、回主线程刷新），含断流处理与设备切换时的资源清理。
- `slide6-gesture-input`: 鼠标手势到设备坐标的映射——点按与拖拽滑动的区分、基于 WDA 逻辑窗口尺寸的归一化换算、转发到 `tap` / `swipe`。
- `slide6-keyboard-input`: 宿主键盘到设备聚焦控件的镜像——普通文本与 IME 组合输入、编辑键、导航键、修饰组合键的分流与串行化发送。
- `slide6-tunnel-bootstrap`: 选中 iOS 17+ 设备后检测 XPC tunnel 端口是否就绪；缺失时弹窗提示，用户确认后经系统原生授权（osascript，每次拉起均授权）以管理员权限拉起 `tunneld_main`，并处理授权取消/失败/启动后复检等情况。

### Modified Capabilities

<!-- 无：本变更不改变 executor_ios 既有能力的 spec 级行为，仅在进程内复用其 toolkit_api。 -->

## Impact

- 新增代码目录：`slide6_console/`（GUI 壳、屏幕镜像线程、手势/键盘处理、入口、README、requirements）。
- 复用但不修改：`executor_ios/toolkit_api.py` 及 `executor_ios/device.py`（直接函数调用，含 `device.mjpeg_local_port` 访问）。
- 新增依赖：PySide6（桌面 GUI）。`web_console` 保持不变，二者可共存。
- tunnel 拉起经 macOS `osascript ... with administrator privileges` 触发系统授权框，复用 `executor_ios.tunneld_main` 既有入口（不修改其实现）。
- 不改变 `executor_ios` 对外协议与现有 specs。
- 安全：以管理员权限拉起进程属高风险操作——使用系统原生授权、固定/校验被拉起的脚本路径、避免任何外部输入拼接命令、不传递任何凭据。

## Context

`web_console` 当前由三部分组成：

- `web_server.py`：FastAPI，把 `executor_ios.toolkit_api` 的能力包装成 `/api/*` HTTP 接口，并通过 `/api/stream` 把 WDA 的 MJPEG broadcaster（`device.mjpeg_local_port`）以 `multipart/x-mixed-replace` 转发给浏览器。
- `web/`：前端单页应用（`app.js` / `index.html` / `style.css`），负责设备选择、画面渲染、坐标换算、键盘镜像。
- 复用 `executor_ios`：`toolkit_api` 是纯同步函数（`list_targets / prepare / window_size / tap / swipe / key_event / send_keys / key_chord / configure_mjpeg / app_switcher / screenshot` 等），底层 `device.py` 管理多设备、端口转发与 WDA 生命周期。

`slide6_console` 要做的是：用 PySide6 桌面应用替换"浏览器 + FastAPI"，**在同一进程内直接调用 `toolkit_api`**，并自己消费 MJPEG 流渲染。功能范围与 `web_console` 完全对等。

关键约束：

- `toolkit_api` / `device` 的 WDA 调用是**阻塞同步**的，不能在 Qt 主线程里直接调用（会卡 UI）。
- MJPEG 是长连接流，必须在后台线程读取，解码后通过信号回主线程刷新。
- 键盘镜像需要复刻 `web_console` 已验证的"按键种类分流"策略（文本/IME → type；编辑键 → key；导航键与组合键 → chord），这套是踩坑后的最优解，不能简化。

## Goals / Non-Goals

**Goals:**

- 提供与 `web_console` 功能对等的 PySide6 桌面控制台 `slide6_console`。
- 去掉 HTTP 层，GUI 进程内直接复用 `executor_ios.toolkit_api`，不修改 `executor_ios`。
- 屏幕镜像、点按/滑动、HOME/App Switcher/截图、帧率与流参数、键盘镜像（含中文 IME 与组合键）全部可用。
- UI 不卡顿：所有阻塞调用与流读取放后台线程。

**Non-Goals:**

- 不做 tunnel 端口可配置 / 检测 / 授权拉起 sudo（后续独立变更）。
- 不解决横屏/朝向问题（保持与 `web_console` 现状一致）。
- 不做打包/签名/分发（后续独立处理）。
- 不改动 `web_console`，二者共存。
- 不引入 executor / NDJSON 入口。

## Decisions

### 决策 1：进程内直调 `toolkit_api`，不保留 HTTP 层

GUI 直接 `from executor_ios import toolkit_api as api` 调用。

- 理由：`web_server.py` 的 `/api/*` 全是薄包装，桌面端无需网络分发，直调更简单、更快、少一层故障点。
- 备选：保留 FastAPI、PySide6 用 `QWebEngineView` 嵌网页 —— 否决，等于把整个 web 方案再套一层，还要维护 HTTP + 浏览器内核，违背"桌面化"初衷。

### 决策 2：阻塞调用走 `QThreadPool` / `QRunnable`，结果用信号回主线程

设备准备（`prepare` 首次可能数十秒）、`window_size`、`tap`、`swipe`、键盘命令等都提交到线程池执行，完成后用 Qt 信号更新 UI。

- 理由：`toolkit_api` 同步阻塞，主线程直调会冻结界面。
- 备选：`asyncio` + `qasync` —— 否决，`toolkit_api` 本身是同步的，引入事件循环徒增复杂度，线程池更直接。

### 决策 3：MJPEG 用独立 `QThread` 读取 + `QImage.fromData` 解码

复刻 `web_server.py` 的握手逻辑：连 `127.0.0.1:device.mjpeg_local_port`，发送 `GET / HTTP/1.0\r\n\r\n` 触发推流，消费 WDA 的 HTTP 头，然后按 multipart boundary 切出每帧 JPEG，`QImage.fromData()` 解码，经信号 `frameReady(QImage)` 回主线程绘制到 `QLabel`。

- 帧率/参数通过 `api.configure_mjpeg(target, framerate, scaling, quality)` 调整（与 web 端一致）。
- 设备切换/停止时用 `generation` 计数失效旧线程（沿用 `app.js` 的 generation 思路），关闭 socket。
- 理由：与现有后端零改动对接；Qt 原生解码渲染高效。
- 备选：`QMediaPlayer` —— 否决，对 multipart MJPEG 支持差。

### 决策 4：坐标映射在 `QLabel` 上做，与 `app.js` 等价

记录画面显示区域的实际矩形，鼠标坐标归一化到 `[0,1]` 后乘以 `window_size` 的逻辑宽高；按位移阈值（约 8px）区分点按与滑动，滑动按住时长映射 `durationMs`（夹在 120~1500ms）。

- 理由：与 `web_console` 行为对齐，避免 Retina/缩放问题（`window_size` 是逻辑点）。

### 决策 5：键盘镜像复刻 web 端分流策略，并串行化发送

- 文本/中文 IME：用一个聚焦的输入捕获控件 + `QInputMethodEvent`/`keyPressEvent`，组合完成后走 `api.send_keys`。
- 编辑键（Enter/Backspace/Tab/Esc）：走 `api.key_event`。
- 导航键（方向/Home/End/PageUp/Down）与一切 ⌘/⌃/⌥/⇧ 组合键：走 `api.key_chord`。
- 所有键盘命令进**单一 FIFO 队列**，由一个 worker 串行发送，连续文本合并成一次请求（复刻 `app.js` 的 `kbdQueue`，避免乱序）。

- 理由：这套分流是 `web_console` 在真机上验证过的唯一可用组合，必须保留；串行化解决快速输入乱序。
- 备选：直接用 Qt 全局按键 —— 不可行，IME 候选词与组合键语义需要分流处理。

### 决策 6：目录与依赖

```text
slide6_console/
  __init__.py
  app.py            # 入口：QApplication + 主窗口
  main_window.py    # 主窗口：设备选择/状态/布局/动作按钮
  mirror.py         # MJPEG 读取线程 + 画面 widget
  gestures.py       # 鼠标手势 → tap/swipe 映射
  keyboard.py       # 键盘镜像与命令队列
  workers.py        # QRunnable 封装阻塞 toolkit_api 调用
  requirements.txt  # PySide6
  README.md
```

- 与 `executor_ios` / `web_console` 同级，运行时 `python3 -m slide6_console.app`。

### 决策 7：选中 iOS 17+ 设备后检测 tunnel 端口，缺失则经系统授权拉起 tunneld

新增 `slide6_console/tunnel.py`，**在用户选中设备、判定其为 iOS 17+ 之后、执行 `prepare` 之前**触发：

- **触发时机**：不在应用启动时检测。用户选中设备后，先从该设备元数据（`list_targets` 返回的 `metadata.os_version`）解析主版本号；**仅当 iOS 主版本 ≥ 17** 才进入 tunnel 检测。iOS 17 以下设备不需要 tunnel，直接跳到 `prepare`。
- **检测**：对 `127.0.0.1:49151`（`executor_ios` 当前使用的 tunneld 端口）做 socket 连接探测；连得上即视为 tunnel 已就绪，直接继续 `prepare`。端口值集中为一个常量，便于后续做成可配置。
- **提示**：端口无人监听时，弹出 `QMessageBox` 说明"该 iOS 17+ 设备需要 XPC tunnel，是否现在以管理员权限启动？"，用户可确认或取消。
- **授权拉起（osascript，每次都授权）**：用户确认后，通过 macOS `osascript -e 'do shell script "<cmd>" with administrator privileges'` 触发系统原生授权框，以 root 启动 `tunneld_main`。**采用 osascript 按需拉起方案——每次启动 tunnel 都会弹一次系统授权框**（不做 LaunchDaemon 持久化）。被拉起的命令固定为"当前 Python 解释器 + `-m executor_ios.tunneld_main`"（打包后则为内置 `ios_tunneld` 二进制路径），路径在代码内构造、不接收任何外部输入。
- **复检**：授权成功后轮询端口直至就绪（带超时），再继续该设备的 `prepare` 流程；取消或失败则提示该 iOS 17+ 设备暂不可用，但应用仍可运行、可重选设备或重试（已就绪/低版本设备不受影响）。

已确认的实现细节：

- **开发态拉起命令**：使用项目 `.venv` 的**绝对路径解释器**，并 `cd` 到仓库根目录后执行 `-m executor_ios.tunneld_main`（保证 root 环境能导入 `executor_ios` 与 `pymobiledevice3`）。打包态则替换为内置 `ios_tunneld` 二进制的绝对路径。**不修改 `tunneld_main.py`**（保持其原始入口，不做自我 daemon 化）。
- **非阻塞拉起（真机踩坑结论）**：`osascript ... with administrator privileges` 会让 `do shell script` 一直等到被拉起命令的 stdout/stderr 到 EOF 才返回；而 tunneld（uvicorn + pymobiledevice3）长期持有这些 fd，导致 osascript 直到超时才返回（实测卡满 120s）。因此**用 `subprocess.Popen` 起 osascript 但不等它返回**：tunneld 以前台方式挂在 osascript 下运行（普通后台进程，不是自我 detach 的守护进程），代码改为**轮询端口**确认就绪、用 osascript 提前退出判定"用户取消/失败"。这样授权后几秒即可继续 `prepare`。
- **生命周期：app 退出时按需询问是否停止 tunneld**。退出时先探测 tunnel 端口是否仍在运行；若在运行则弹窗让用户选择是否 kill：选择 kill 才停止，否则保留。**停止实现**：tunneld 以 root 运行，非特权 `lsof` 看不到其端口，故在一次提权 shell 内 `lsof -ti tcp:49151` 找出 pid 并 `kill`（tunneld 不可靠响应 SIGTERM，故 TERM 后补 `kill -9` 兜底）。因此用户选择 kill 时会再弹一次系统授权框；若端口未在运行则退出时不弹窗、不动作。
- **iOS 版本判定**：复用 `device.py` 的 `_ios_major_version()` 同款解析（`os_version.split('.')[0]`，`os_version` 形如 `"17.2.1"`），解析失败保守按"需要 tunnel"处理。
- **平台范围**：本次仅在 macOS 验收（`executor_ios` 当前也仅支持 macOS USB 真机）。

理由：iOS 17+ 启动 WDA 必须有 tunneld（见 `device.py` 的 `_get_rsd_from_tunneld`），而 tunneld 必须 root 运行；低版本设备不需要，故把检测下沉到"选中设备且为 iOS 17+"时按需触发，避免无谓地在启动时打扰用户。复用既有 `tunneld_main` 入口、不改 `executor_ios`。

备选：
- 应用启动时统一检测 —— 否决（本次调整点）：低版本设备根本不需要 tunnel，启动即弹授权会打扰用户；按需触发更合理。
- 让用户自己开终端 `sudo python -m executor_ios.tunneld_main` —— 否决，体验差、易出错。
- 安装 LaunchDaemon 持久化（只授权一次）—— 本次明确不采用；更适合客户机量产分发，作为后续打包变更的选项。本次采用 osascript 每次授权。

安全（遵循高风险操作准则）：使用系统原生授权框而非自行收集密码；被执行的脚本/二进制路径写死并校验存在性；命令字符串不拼接任何用户输入，杜绝注入；不向该进程传递任何凭据；端口仅绑定 `127.0.0.1`。

## Risks / Trade-offs

- [MJPEG 解码在高 fps / 高分屏下 CPU 偏高] → 默认 10~20fps，沿用 `configure_mjpeg` 的 scaling/quality 下采样；解码在后台线程，必要时丢帧只渲染最新帧。
- [`device.mjpeg_local_port` 是内部属性，直接访问耦合 device 实现] → 与 `web_server.py` 现状一致，风险可控；若后续 `toolkit_api` 暴露正式接口再切换。
- [中文 IME 在不同平台（macOS/Windows）行为差异] → 以 `QInputMethodEvent` 的 commit 事件为准触发发送，先在 macOS 验证，Windows 作为后续打包阶段回归项。
- [线程池阻塞调用与设备切换竞态] → 用 generation 计数 + 切换时丢弃过期回调，复刻 web 端做法。
- [PySide6 体积大] → 仅本变更范围内不处理；打包裁剪（排除未用 Qt 模块）留给后续打包变更。
- [`osascript` 授权拉起仅适用 macOS] → 本变更聚焦 macOS（`executor_ios` 当前也仅支持 macOS USB 真机）；Windows 不需要 XPC tunnel，其检测/提权方案留待 Windows 适配时单独设计。
- [tunneld 端口写死 49151] → 本次以常量集中管理便于探测；完整可配置化（`~/.executor_ios.json`）作为后续独立变更。
- [tunneld 以 root 拉起属高风险] → 系统原生授权 + 写死脚本路径 + 命令不拼接外部输入 + 仅绑定 127.0.0.1；授权取消时降级（该 iOS 17+ 设备不可用）而非阻塞整个应用。
- [osascript 每次拉起都需授权，体验上多一次弹框] → 本次有意接受此权衡（不引入 LaunchDaemon 的安装复杂度）；若 tunnel 已在运行则不会重复弹（先探测后拉起）。量产场景的"一次授权"留作后续 LaunchDaemon/SMAppService 变更。
- [退出时停止 root tunneld 需再次特权] → 退出时仅在 tunnel 仍运行时弹窗征询；用户选择 kill 才触发停止（在提权 shell 内 `lsof + kill`，TERM 后补 `kill -9`，并因此再弹一次系统授权），选择保留则不动作。把"是否承担退出时的二次授权"交给用户即时决定。
- [osascript `do shell script` 会阻塞至被拉起命令 stdio 到 EOF] → tunneld 长期持有 fd 会卡满超时；改为 `Popen` 非阻塞起 osascript + 轮询端口确认就绪、osascript 早退判定取消，避免主流程被授权调用拖死。
- [iOS 主版本解析依赖 `metadata.os_version` 字符串] → 解析失败时保守视为需要 tunnel（按 iOS 17+ 处理）或回退到设备端版本判断，避免漏起 tunnel 导致 prepare 失败。
- [授权后 tunneld 启动需要时间] → 拉起后带超时轮询端口直至就绪，避免误判为失败。

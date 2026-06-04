## 1. 脚手架与依赖

- [x] 1.1 创建 `slide6_console/` 目录与 `__init__.py`（与 `executor_ios` / `web_console` 同级）
- [x] 1.2 创建 `slide6_console/requirements.txt`，加入 PySide6 依赖
- [x] 1.3 创建 `slide6_console/app.py` 入口：构建 `QApplication` 与主窗口，支持 `python3 -m slide6_console.app` 启动
- [x] 1.4 在 `app.py` 中 `from executor_ios import toolkit_api as api`，验证进程内可调用且无 HTTP 监听

## 2. 阻塞调用线程化（workers）

- [x] 2.1 创建 `slide6_console/workers.py`：用 `QThreadPool` + `QRunnable` 封装阻塞的 `toolkit_api` 调用，结果/异常通过信号回主线程
- [x] 2.2 提供 generation 计数机制，切换设备时丢弃过期回调

## 3. 主窗口与设备生命周期（slide6-desktop-shell）

- [x] 3.1 创建 `slide6_console/main_window.py`：设备下拉选择、刷新按钮、状态指示、画面区域、动作按钮、帧率选择
- [x] 3.2 调用 `api.list_targets()` 填充设备列表，标识"未装 WDA"
- [x] 3.3 无设备时显示"未检测到 USB 设备"提示
- [x] 3.4 选中未装 WDA 设备：黑屏 + "该设备未安装 WebDriverAgent (WDA)"提示，不进入镜像
- [x] 3.5 选中已装 WDA 设备：iOS 17+ 先经第 8 组 tunnel 检测/拉起，再后台 `api.prepare(target)`，展示"正在启动 WebDriverAgent…"状态
- [x] 3.6 prepare 成功后取 `api.window_size(target)`，按宽高比布局画面区域，窗口缩放保持比例
- [x] 3.7 prepare 失败/超时：展示失败状态与错误信息
- [x] 3.8 prepare 期间切换设备：用 generation 丢弃过期回调，状态/画面不串台

## 4. 设备动作（slide6-desktop-shell）

- [x] 4.1 HOME 按钮 → 后台 `api.key_event(target, "HOME")`
- [x] 4.2 App Switcher 按钮 → 后台 `api.app_switcher(target)`，未确认生效时给可重试提示
- [x] 4.3 截图按钮 → `api.screenshot(target)` 取 PNG，弹"另存为"对话框由用户选择保存位置
- [x] 4.4 帧率选择（5/10/15/20）→ `api.configure_mjpeg(target, framerate, scaling, quality)`

## 5. 屏幕镜像（slide6-screen-mirror）

- [x] 5.1 创建 `slide6_console/mirror.py`：`QThread` 连接 `127.0.0.1:device.mjpeg_local_port`
- [x] 5.2 复刻握手：发送触发字节 `GET / HTTP/1.0\r\n\r\n`，消费 WDA HTTP 响应头
- [x] 5.3 按 multipart boundary 切分并提取每帧 JPEG 字节
- [x] 5.4 后台线程 `QImage.fromData()` 解码，通过 `frameReady(QImage)` 信号回主线程
- [x] 5.5 主线程把 `QImage` 绘制到画面控件（仅渲染最新帧，必要时丢帧）
- [x] 5.6 端口不可用时显示流不可用提示，不崩溃
- [x] 5.7 断流（连接关闭/读取失败）显示"画面流已中断"并允许重试
- [x] 5.8 设备切换/停止时使旧线程失效并关闭连接，清理资源

## 6. 手势输入（slide6-gesture-input）

- [x] 6.1 创建 `slide6_console/gestures.py`：记录画面显示矩形，鼠标坐标归一化到 `[0,1]` 并钳制
- [x] 6.2 归一化坐标乘以 `window_size` 逻辑宽高得到设备坐标
- [x] 6.3 按位移阈值（约 8px）区分点按/滑动
- [x] 6.4 点按 → `api.tap(target, x, y)`
- [x] 6.5 滑动 → `api.swipe(...)`，`durationMs` 由按住时长映射并夹在 120~1500ms
- [x] 6.6 手势完成后若键盘镜像开启则把焦点拉回键盘捕获控件

## 7. 键盘镜像（slide6-keyboard-input）

- [x] 7.1 创建 `slide6_console/keyboard.py`：键盘镜像开关，仅已连接且开启时捕获
- [x] 7.2 用键盘捕获控件 + `QInputMethodEvent` 处理文本与中文 IME，组合完成（commit）后 `api.send_keys`
- [x] 7.3 编辑键（Enter/Backspace/Tab/Esc，无修饰）→ `api.key_event`
- [x] 7.4 导航键（方向/Home/End/PageUp/PageDown）→ `api.key_chord`
- [x] 7.5 带 ⌘/⌃/⌥/⇧ 修饰的组合键 → `api.key_chord`（基础键 + 修饰集合）
- [x] 7.6 实现单一 FIFO 命令队列 + 串行 worker，连续文本合并为一次 `send_keys`，保证不乱序

## 8. 设备选择后的 tunnel 检测与授权拉起（slide6-tunnel-bootstrap）

- [x] 8.1 创建 `slide6_console/tunnel.py`：以常量集中 tunnel 端口（`127.0.0.1:49151`），提供 socket 探测函数判断 tunnel 是否就绪
- [x] 8.2 选中设备后从 `metadata.os_version` 解析 iOS 主版本；仅当 ≥17 才进入检测，低版本直接继续 `prepare`（解析失败时保守按需要 tunnel 处理）
- [x] 8.3 iOS 17+ 设备执行端口探测；已就绪则静默继续 `prepare`
- [x] 8.4 未就绪时弹出 `QMessageBox` 提示"该 iOS 17+ 设备需要 XPC tunnel，是否现在以管理员权限启动？"
- [x] 8.5 用户确认后，用 `osascript ... with administrator privileges` 拉起"`.venv` 绝对路径解释器 + cd 仓库根 + `-m executor_ios.tunneld_main`"（打包态换内置 `ios_tunneld` 绝对路径）；命令路径固定、不拼接外部输入、校验路径存在（每次拉起均触发系统授权）
- [x] 8.6 记录本会话拉起的 tunneld pid，拉起后带超时轮询端口直至就绪，再继续该设备 `prepare` 流程
- [x] 8.7 用户取消/授权失败/超时：提示该 iOS 17+ 设备不可用但应用继续运行，允许重试或改选设备
- [x] 8.8 app 退出时探测 tunnel 是否仍运行；运行则弹窗征询是否停止——选停止才 kill（优先会话 pid，否则解析端口监听 pid，需再次特权），选保留则不动作；未运行则不弹窗
- [ ] 8.9 真机自测：选中 iOS 17+ 设备且 tunnel 未启动→弹窗→授权→tunneld 起来→设备可用；选中低版本设备不弹窗；退出时 tunnel 在运行→弹窗选停止则被 kill、选保留则继续运行

## 9. 文档与自测

- [x] 9.1 创建 `slide6_console/README.md`：依赖、启动方式、已实现功能、tunnel 启动授权说明、与 `web_console` 的关系、已知限制
- [ ] 9.2 真机自测：设备选择、画面镜像、点按/滑动、HOME/App Switcher/截图、帧率切换
- [ ] 9.3 真机自测：英文输入、中文 IME、编辑键、导航键、组合键（⌘C/⌘V/⇧→ 等），并记录至少 3 条自测记录

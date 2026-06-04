# web_console

`web_console` 是基于 `executor_ios` 能力层的浏览器端交互控制台：在网页里实时镜像 USB 连接的 iOS 设备画面，并用鼠标进行点按 / 滑动操作。

本目录与 `executor_ios` 同级，运行时通过 `executor_ios.toolkit_api` 复用其设备管理、端口转发与 WDA 生命周期逻辑。

## 目录结构

```text
web_console/
  __init__.py
  web_server.py        # FastAPI 服务：设备列表/准备/截图流/坐标尺寸/点击/滑动/HOME
  requirements.txt     # 仅 Web 栈依赖（fastapi / uvicorn）
  web/                 # 前端静态资源
    index.html
    app.js
    style.css
```

## 环境依赖

先安装 `executor_ios` 的依赖，再安装本目录的 Web 依赖：

```bash
python3 -m pip install -r executor_ios/requirements.txt
python3 -m pip install -r web_console/requirements.txt
```

## 启动

在仓库根目录（`executor_ios` 与 `web_console` 的父目录）执行：

```bash
python3 -m web_console.web_server            # 默认 http://127.0.0.1:8787
python3 -m web_console.web_server --port 9000
```

iOS 17+ 设备仍需先运行 `ios_tunneld`（见 `executor_ios/README.md`）。

## 使用

1. 顶部下拉框选择设备（未安装 WDA 的设备标记为“未装 WDA”）。
2. 选中未安装 WDA 的设备时，画面区域显示黑屏并提示“该设备未安装 WebDriverAgent (WDA)”。
3. 选中已安装 WDA 的设备会自动启动 WDA（首次可能数十秒），随后以约 10 fps 持续截图镜像，帧率可在顶部切换（5/10/15/20 fps）。
4. 在画面上单击 = 点按；按住拖动 = 滑动；右侧提供 HOME 快捷键。

网页坐标到设备坐标的换算基于 WDA 逻辑窗口尺寸（`GET /session/{sid}/window/size`），与 Retina 像素无关。

## HTTP 接口（供二次开发）

```text
GET  /api/devices                 # 设备列表（含 WDA 安装状态）
POST /api/prepare {target}        # 启动并确认 WDA 就绪
GET  /api/window_size?target=...  # WDA 逻辑窗口尺寸（点）
GET  /api/screenshot?target=...   # 单帧 PNG（image/png，禁用缓存）
POST /api/tap   {target,x,y}
POST /api/swipe {target,x1,y1,x2,y2,durationMs}
POST /api/key   {target,key}      # 如 HOME / ENTER / BACKSPACE / 方向键
POST /api/type  {target,text}     # 把文本打到设备当前聚焦的输入框（键盘镜像）
POST /api/chord {target,key,modifiers}  # 组合键，如 {key:"c",modifiers:["meta"]} = ⌘C
POST /api/app_switcher {target}   # 打开后台多任务视图
GET  /api/stream?target=...       # MJPEG 实时画面（multipart/x-mixed-replace）
POST /api/stream_config {target,framerate,scalingFactor,quality}
```

## 键盘输入（Mac → iOS 无缝输入）

点击「键盘输入: 关 / 开」开启捕获后，**先点设备屏幕上的输入框唤起键盘**，再用 Mac 键盘打字：

- 普通字符 / 粘贴 / 中文 IME（拼音）→ 走 `POST /api/type`（WDA `FBTypeText`，打到当前聚焦控件）。
- 回车、退格、Tab、Esc、方向键 → 走 `POST /api/key`。
- 方向键 / Home / End / PageUp / PageDown 及一切 ⌘/⌃/⌥/⇧ 组合键 → 走 `POST /api/chord`（WDA `/wda/element/0/keyboardInput`，即 `typeKey:modifierFlags:`）。这是 iOS 上唯一能移动光标、扩展选择、识别硬件修饰键的 API。
- 回车 / 退格 / Tab / Esc → 走 `POST /api/key`（W3C 按键）。**注意**：这台 WDA 的 `typeKey` 对 Return/Delete 是 no-op，反而 W3C 按键有效；而 W3C 对方向键无效——两条通道刚好互补，所以按键种类分流到不同接口。
- 已验证可用：方向键移动光标、⇧+方向键逐字选择、⌥+方向键按词移动、⌘A 全选、⌘C/⌘V 复制粘贴、回车换行、退格删除。
- ⌥⌫（删词）/ ⌘⌫（删到行首）：iOS 两条通道都不直接支持「修饰键+退格」，因此用**组合方案模拟**——先用 ⌥⇧← / ⌘⇧← 选中对应范围，再删除选区。已真机验证。

> 实现要点（避坑）：
> - WDA 的 `keyboardInput` dict 形式（带 `modifierFlags`）有个长期 bug，不会解析常量名，所以**带修饰键**时必须传按键的字面值；**无修饰键**时用字符串形式传 `XCUIKeyboardKey` 常量名由 WDA 解析。
> - 方向键的字面值是 Unicode 箭头字符 `←↑→↓`（U+2190~2193），**不是** AppKit 的 NSEvent 功能键码（U+F70x）。
> - 依赖 WDA 5.12+ 且用 Xcode 15+ 构建；更老的 WDA 没有该端点（返回 404）。

前端用一个隐藏输入框捕获击键，因此中文输入法的候选词、组合输入都能正常工作；点屏幕后会自动把焦点拉回隐藏输入框，保持键盘持续可用。

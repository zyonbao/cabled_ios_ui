# slide6_console

`slide6_console` 是基于 PySide6 的 iOS 设备桌面控制台，是 `web_console` 的桌面对等实现：在窗口里实时镜像 USB 连接的 iOS 设备画面，并用鼠标点按 / 滑动、宿主键盘输入进行操作。

与 `web_console` 不同，它**在进程内直接复用 `executor_ios.toolkit_api`**（无 HTTP 层），并能在选中 iOS 17+ 设备时检测并经系统授权拉起 XPC tunnel。

## 目录结构

```text
slide6_console/
  __init__.py
  app.py            # 入口：QApplication + 主窗口
  main_window.py    # 主窗口：设备选择/准备/布局/动作按钮/退出处理
  mirror.py         # MJPEG 读取线程 + 画面 widget（含手势）
  gestures.py       # 鼠标坐标 → 设备坐标映射、点按/滑动判定
  keyboard.py       # 键盘镜像（捕获控件 + 串行发送线程）
  tunnel.py         # XPC tunnel 检测与授权拉起/停止
  workers.py        # 线程池封装阻塞的 toolkit_api 调用
  requirements.txt  # PySide6
```

## 环境依赖

- macOS
- 先安装 `executor_ios` 依赖，再安装本目录的 PySide6 依赖：

```bash
python3 -m pip install -r executor_ios/requirements.txt
python3 -m pip install -r slide6_console/requirements.txt
```

## 启动

在仓库根目录（`executor_ios` 与 `slide6_console` 的父目录）执行：

```bash
python3 -m slide6_console.app
```

应用不监听任何 HTTP 端口。

## 使用

1. 顶部下拉框选择设备（未安装 WDA 的设备标记为“未装 WDA”）。
2. 选中未装 WDA 的设备：画面区域显示黑屏与提示，无法控制。
3. 选中已装 WDA 的设备：
   - 若为 **iOS 17+** 且 XPC tunnel 未运行，会弹窗询问是否以管理员权限启动 tunnel；确认后弹出系统授权框，授权成功并就绪后继续。
   - 启动 WDA（首次可能数十秒），随后以 MJPEG 持续镜像，帧率可在顶部切换（5/10/15/20 fps）。
4. 在画面上单击 = 点按；按住拖动 = 滑动；右侧提供 HOME / 应用切换 / 截图保存。
5. 点击“键盘输入: 开”后，在键盘捕获框聚焦，再用宿主键盘打字（支持中文 IME、编辑键、导航键、⌘/⌃/⌥/⇧ 组合键）。

网页坐标到设备坐标的换算基于 WDA 逻辑窗口尺寸（`window_size`），与 Retina 像素无关。

## XPC Tunnel（iOS 17+）

- 仅在选中 **iOS 17+** 设备且 tunnel 端口（`127.0.0.1:49151`）无人监听时触发。
- 采用 `osascript ... with administrator privileges` 按需拉起 `executor_ios.tunneld_main`，**每次拉起都会弹一次系统授权框**（不做持久化）。
- 开发态使用项目 `.venv` 的绝对路径解释器并 `cd` 到仓库根目录执行；打包态应替换为内置的 `cabled_ios_tunnel` 二进制路径。
- **退出时**：若检测到 tunnel 仍在运行，会弹窗询问是否停止；选择停止会再触发一次管理员授权（停止 root 进程需要特权），选择保留则进程继续运行以便下次复用。

## 键盘输入分流（与 web_console 一致）

- 普通字符 / 粘贴 / 中文 IME → `send_keys`（提交后发送）。
- 回车 / 退格 / Tab / Esc（无修饰）→ `key_event`。
- 方向键 / Home / End / PageUp / PageDown 及一切 ⌘/⌃/⌥/⇧ 组合键 → `key_chord`。
- 所有键盘命令进单一 FIFO 队列串行发送，连续文本合并为一次请求，避免乱序。

> macOS 提示：Qt 默认交换 Control/Meta，因此 `Qt.ControlModifier` 对应 Command 键、`Qt.MetaModifier` 对应物理 Control 键；本实现已按此映射回 iOS 语义。

## 已实现能力

- 设备列表与选择（含未装 WDA 标识与提示）
- WDA 准备与状态展示（后台线程，不卡 UI）
- 实时屏幕镜像（MJPEG，后台解码、主线程渲染、断流处理、切换清理）
- 点按 / 滑动（基于逻辑尺寸的坐标映射）
- HOME / 应用切换 / 截图（另存为对话框）
- 帧率切换与 MJPEG 参数配置
- 键盘镜像（文本 / IME / 编辑键 / 导航键 / 组合键，串行化发送）
- iOS 17+ 选中后 tunnel 检测与授权拉起、退出时按需停止

## 已知限制

- 仅支持 macOS（tunnel 授权为 macOS 专有；`executor_ios` 当前也仅支持 macOS USB 真机）。
- 不处理横屏 / 朝向（与 `web_console` 现状一致）。
- tunnel 端口当前为常量 `49151`（集中在 `tunnel.py`），完整可配置化为后续工作。
- 不含打包 / 代码签名（后续单独处理）。
```

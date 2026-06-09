# slide6_console

`slide6_console` 是基于 PySide6 的 iOS 设备桌面控制台，是 `web_console` 的桌面对等实现：在窗口里实时镜像 USB 连接的 iOS 设备画面，并用鼠标点按 / 滑动、宿主键盘输入进行操作。界面采用多 Tab 布局——「键鼠操作」承载镜像与键鼠控制，「App 列表」承载 App 管理与沙盒文件管理，「文件系统」承载设备媒体分区（不含 App 沙盒）的 AFC 文件管理，「相册」承载 DCIM 媒体的缩略图浏览 / 查看 / 导出 / 删除。

与 `web_console` 不同，它**在进程内直接复用 `executor_ios.toolkit_api`**（无 HTTP 层），并能在选中 iOS 17+ 设备时检测并经系统授权拉起 XPC tunnel。

## 目录结构

```text
slide6_console/
  __init__.py
  app.py            # 入口：QApplication + 主窗口
  main_window.py    # 主窗口：顶部信息栏 + Tab 布局 + 设备生命周期
  app_manager.py    # 「App 列表」Tab：App 装卸/搜索/筛选 + 文件浏览器对话框
  afc_browser.py    # 可复用 AFC 浏览面板 AfcBrowserPanel + 对话框包装 AfcBrowserDialog
  file_system_tab.py# 「文件系统」Tab：内嵌 root="media" 的 AFC 浏览面板（媒体分区，不含沙盒）
  dcim_album.py     # 「相册」Tab：DCIM 缩略图网格 + 本地缓存 + 大图查看 + 导出 + 多选删除
  mirror.py         # MJPEG 读取线程 + 画面 widget（含手势）
  gestures.py       # 鼠标坐标 → 设备坐标映射、点按/滑动判定
  keyboard.py       # 键盘镜像（捕获控件 + 串行发送线程）
  tunnel.py         # XPC tunnel 检测与授权拉起/停止
  workers.py        # 线程池封装阻塞的 toolkit_api 调用
  requirements.txt  # PySide6 + pillow-heif（HEIC 解码）
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

1. 顶部下拉框选择设备（未安装 WDA 的设备标记为“未装 WDA”）；设备明细（系统版本 / UDID / 型号等）改由左侧「设备信息」Tab 展示。
2. **「键鼠操作」Tab**：
   - 选中未装 WDA 的设备：画面区域显示黑屏与提示，无法镜像控制（App 管理仍可用，见下）。
   - 选中已装 WDA 的设备：若为 **iOS 17+** 且 XPC tunnel 未运行，会弹窗询问是否以管理员权限启动 tunnel；启动 WDA（首次可能数十秒），随后以 MJPEG 持续镜像。
   - 画面上单击 = 点按；按住拖动 = 滑动；右侧操作区提供帧率切换（5/10/15/20 fps）、HOME / 应用切换 / 截图、键盘输入、文本发送与剪贴板读写。
3. **「App 列表」Tab**（无需 WDA / tunnel，选中任意设备即可用）：
   - 展示已安装 App，每行「操作」列按能力显示 `Documents` / `Sandbox` / `卸载` 按钮；支持按名称 / bundleId 搜索，按「文件共享」「沙盒可访问」筛选。
   - 点击“安装 IPA…”或把 `.ipa` 拖入列表区安装。
   - 文件浏览器：顶部为可编辑的相对路径输入框（回车跳转）+「刷新」「添加文件夹」；非根目录列表顶部显示 `..`，双击返回上一级；每行右侧按钮支持 导入（文件夹）/ 导出 / 重命名 / 删除（二次确认），亦可右键调出同样的操作菜单；支持文件与文件夹的拖入导入、拖出 Finder 导出。
4. **「文件系统」Tab**（无需 WDA / tunnel，选中任意设备即可用）：经 `com.apple.afc` 浏览设备**媒体分区**（如 `DCIM`、`Downloads`、`PhotoData` 等，**不含 App 沙盒**——沙盒浏览仍在「App 列表」Tab）。复用与 App 文件浏览器相同的 `AfcBrowserPanel`：可编辑路径栏跳转、刷新 / 添加文件夹、`..` 返回上一级，每行支持 导入 / 导出 / 重命名 / 删除（二次确认），并支持拖入导入、拖出 Finder 导出。该 Tab 还支持**多选**（Cmd/Shift 点选），多选后右键可**批量下载到本地目录**或**批量删除**（一次汇总二次确认）。
5. **「相册」Tab**（无需 WDA / tunnel，选中任意设备即可用）：以缩略图网格展示 `/DCIM` 下相册子目录与媒体文件。
   - 缩略图按设备（UDID）落地到本地磁盘缓存（内容为小 JPEG，按原图 `(size, mtime)` 与裁剪策略版本失效，跨会话持久），自上而下渐进生成、限制并发；命中缓存直接使用。缩略图优先复用 iOS 端缓存（`PhotoData/Thumbnails/V2/DCIM/<相册>/<文件名>/` 下的小 JPG），缺失时读原图生成（HEIC/HEIF 经 `pillow-heif` 解码，其余经 `QImage`）；视频与无法解码 / 超大文件显示占位图标（视频不提取首帧）。所有缩略图（含 iOS 端缓存来源）统一以**正方形居中裁剪（Crop）**落地，网格观感一致、无变形或留边。
   - 双击图片弹出大图查看（HEIC 经 `pillow-heif`、其余经 `QImage` 解码后按窗口适配）；双击相册子目录进入、「上一级」返回。
   - 「导出选中」把多选媒体经 `afc_pull` 拉到本地目录（字节与内嵌元数据原样保留，并按设备 mtime 回写本地时间戳，HEIC 导出仍为 HEIC）。
   - 「删除选中」对多选项弹出一次汇总二次确认（数量 + 示例名），确认后逐项 `afc_rm` 并刷新。
   - 相册 Tab **不提供**“导入到相册”：经 AFC 写入 `/DCIM` 能否登记进 Photos 相册取决于系统索引、无法保证；如需向设备写文件，请用「文件系统」Tab 的 AFC 导入。
6. **「设备信息」Tab**（无需 WDA / tunnel，选中设备后默认进入）：以键 / 值表格尽可能详细地展示当前设备的 lockdown 全量属性（DeviceName / ProductType / ProductVersion / SerialNumber 等），支持刷新与按字段 / 值筛选；双击单元格或右键菜单可复制字段名 / 值。

坐标到设备坐标的换算基于 WDA 逻辑窗口尺寸（`window_size`），与 Retina 像素无关。

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
- App 管理：列表 / 搜索 / 筛选（文件共享、沙盒可访问）/ 安装 IPA（点击或拖拽）/ 卸载
- App 文件管理：浏览 Documents 或沙盒容器、文件 / 文件夹导入与导出（含拖拽）、重命名、删除、新建文件夹
- 设备文件系统（媒体分区，不含沙盒）：经 `com.apple.afc` 浏览、导入 / 导出、重命名、删除、新建文件夹；多选 + 右键批量下载 / 批量删除
- 相册（DCIM）：缩略图网格（优先复用 iOS 端缩略图、正方形居中裁剪、本地磁盘缓存、限并发渐进）、大图查看（HEIC 经 pillow-heif）、带元数据导出、多选删除（汇总二次确认）
- 退出行为：终端前台运行时按 Ctrl+C 触发与关闭窗口一致的干净退出（不崩溃）
- 设备信息：lockdown 全量属性键 / 值展示，支持筛选

## 已知限制

- 仅支持 macOS（tunnel 授权为 macOS 专有；`executor_ios` 当前也仅支持 macOS USB 真机）。
- 不处理横屏 / 朝向（与 `web_console` 现状一致）。
- tunnel 端口当前为常量 `49151`（集中在 `tunnel.py`），完整可配置化为后续工作。
- 不含打包 / 代码签名（后续单独处理）。
- **安装 IPA 受签名限制**：仅能安装由本设备可信任证书（开发 / 企业证书或本机 Apple ID 描述文件）签名的 `.ipa`，否则设备端拒绝安装——这是 iOS 系统行为。
- **沙盒访问范围**：整个沙盒容器仅对带 `get-task-allow` 的开发签名 App 开放；App Store 正式包仅在开启文件共享时可访问 `Documents`。
- 文件夹导入 / 导出为递归操作，且**拖拽导出会先把所选内容同步拉取到本地临时目录**再发起拖拽，大文件 / 大目录会有可感知耗时。
- **相册不提供“导入到相册”**：经 AFC 写入 `/DCIM` 是否被 Photos 相册索引取决于系统行为，无法保证可见，故首版不提供该入口（写文件请用「文件系统」Tab）。
- **HEIC 解码依赖 `pillow-heif`**（自带 `libheif`），不依赖 Qt 的可选 heif 图像插件，以便打包确定性；若该依赖缺失，HEIC 项会退化为占位图标。
- **缩略图本地缓存**位于应用数据目录（`QStandardPaths.AppDataLocation`）下的 `dcim_thumbs/<UDID>/`，按原图 `(size, mtime)` 失效、跨会话复用；首次浏览大相册会逐张渐进生成缩略图（优先复用 iOS 端缓存，仅在缺失时读原图）。
- 媒体分区中部分目录（如 `PhotoData/CPL/...`）可能受系统限制无法访问，相关操作会以错误状态友好提示，不会崩溃。

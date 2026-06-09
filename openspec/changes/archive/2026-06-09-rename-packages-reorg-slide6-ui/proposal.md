## Why

三个顶层包的命名与职责表达不够清晰：`executor_ios`（纯逻辑层）、`slide6_console`（UI 层）、`web_console`（Web 逻辑层）的名字未能直观反映各自定位，且 `slide6_console` 把所有 sidebar Tab 与其组件平铺在单层目录，`main_window.py` 还内联承载了「键鼠操作」整条 mirror 生命周期，随功能增长可维护性下降。本次在**不改变运行逻辑**的前提下做一次结构与命名整理。

## What Changes

- 顶层包改名（仅重命名 + 修正 import，行为不变）：
  - `executor_ios` → `ios_toolkit`（纯逻辑/平台能力层）
  - `slide6_console` → `slide6_ui`（PySide6 桌面 UI 层）
  - `web_console` → `web_page`（Web 相关逻辑）
- **BREAKING**（对外契约）：broker 调用入口由 `python3 -B -m executor_ios.toolkit_cli` 变为 `python3 -B -m ios_toolkit.toolkit_cli`；Studio broker 侧需同步更新调用路径（本次仅更新契约文档，无法改动 broker 代码）。
- `slide6_ui` 内按 sidebar 模块分文件夹：`device_info/`、`album/`、`file_system/`、`app_manager/`、`keymouse/`；公用部分（`workers`、`afc_browser`、`sidebar_tabs`、`tunnel`）归入 `common/`。
- 将「键鼠操作」Tab 从 `main_window.py` 逐字抽取为 `keymouse/keymouse_tab.py` 的独立 `KeymouseTab`（代码搬迁 + 重新接线，行为不变），`MainWindow` 仅保留顶栏、Tab 容器、设备列表与对各 Tab 的设备选择委托。
- 同步更新打包脚本（`--include-package`、`ICON_SRC`、预检提示）、根入口（`CablediOS.py`、`cabled_ios_tunnel.py`、`ios_tunneld.py`）、`.gitignore`、各 `requirements.txt` 与活跃文档；历史 `openspec/changes/archive/**`、`openspec/archive/**` 不动。
- 冗余清理：`.gitignore` 新增 `.idea/`、修正 `screenshot.png` 路径；tunneld 三件套、`toolkit_cli`、`local_api_test` 各有用途，保留。

## Capabilities

### New Capabilities

（无。slide6_ui 目录重组与 KeymouseTab 抽取均为无行为变更的内部结构调整，不引入新能力。）

### Modified Capabilities

仅涉及规范性表述中的**包名/模块名/入口路径标识符**重命名，不改变任何行为契约（共 16 个 spec）：

- `json-cli`: CLI 启动命令由 `-m executor_ios.toolkit_cli` 改为 `-m ios_toolkit.toolkit_cli`。
- `nuitka-macos-packaging`: 打包源包 `executor_ios`/`slide6_console`、入口 `slide6_console.app:main`、图标 `slide6_console/AppIcon.png` 等标识符改名。
- `slide6-desktop-shell`: 启动命令 `-m slide6_console.app`、进程内复用 `executor_ios.toolkit_api` 的包名改名。
- `slide6-tunnel-bootstrap`: 端口归属包 `executor_ios`、开发态 tunneld 模块 `executor_ios.tunneld_main` 的包名改名。
- `slide6-screen-mirror`: 画面控件所属包 `slide6_console` 改名。
- `orientation-op`: 提供接口的模块 `executor_ios.toolkit_api` 改名。
- `credential-input`: 凭据模块导入路径 `executor_ios.secrets`、目录 `executor_ios/` 改名。
- `web-console-orientation`: 提供方向端点的 `web_console` 改名为 `web_page`。
- `web-console-long-press`: 提供长按端点的 `web_console` 改名为 `web_page`。
- `device-info-op`: 提供 `device_info` 的模块 `executor_ios.toolkit_api` 改名。
- `app-inventory-op`: 提供 `list_apps`/`install_app`/`uninstall_app` 的模块 `executor_ios.toolkit_api` 改名。
- `app-file-transfer-op`: 提供 `afc_list`/`afc_pull`/`afc_push`/`afc_rm`/`afc_mkdir`/`afc_rename` 的模块 `executor_ios.toolkit_api` 改名。
- `afc-filesystem-op`: 提供 `root="media"` AFC 系列与 `afc_read` 的模块 `executor_ios.toolkit_api` 改名。
- `slide6-app-manager`: 提供「App 列表」Tab 的 `slide6_console` 改名为 `slide6_ui`。
- `slide6-dcim-album`: 提供「相册」Tab 的 `slide6_console` 改名为 `slide6_ui`。
- `slide6-file-system`: 提供「文件系统」Tab 的 `slide6_console` 改名为 `slide6_ui`。

## Impact

- 代码：`ios_toolkit/*`、`slide6_ui/*`（含新增子包 `common/device_info/album/file_system/app_manager/keymouse` 及 `keymouse_tab.py`）、`web_page/*`、根入口 `CablediOS.py` / `cabled_ios_tunnel.py`。
- 跨包导入：`from executor_ios import ...` → `from ios_toolkit import ...`（slide6_ui 各文件、web_page/web_server.py）；`CablediOS.py` 的 `slide6_console.app` → `slide6_ui.app`。
- 打包：`packaging/build_macos_app.sh` 的 `--include-package`、`ICON_SRC`、预检提示与注释。
- 工程配置：`.gitignore`（`screenshot.png` 路径、新增 `.idea/`）、各 `requirements.txt` 随包移动。
- 对外契约：broker 子进程调用路径变更（见 BREAKING），需 Studio 侧同步。
- 文档：各 `README`、`docs/`、`openspec/specs` 当前能力 spec、`openspec/products`；历史 archive 不动。

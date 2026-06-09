## Context

仓库当前有三个顶层 Python 包：`executor_ios`（设备通信/平台能力的纯逻辑层）、`slide6_console`（PySide6 桌面 UI）、`web_console`（Web 端逻辑）。包名未能直观表达职责；`slide6_console` 把全部 sidebar Tab 与其组件平铺单层，`main_window.py`（约 800 行）内联承载「键鼠操作」整条 mirror/WDA 生命周期。

导入现状（决定改名工作量）：包内大量**相对导入**（`from .x import`），跨包用**绝对导入**（`from executor_ios import toolkit_api`、`from slide6_console.app import main`）。`web_console` 不依赖 `slide6_console`，二者都只依赖 `executor_ios`。

约束：**不改变任何运行逻辑**，只做重命名与文件搬迁；通过逐处更新 import 与逐字搬迁保证行为不变。

## Goals / Non-Goals

**Goals:**
- 三个顶层包改名，职责更清晰：`ios_toolkit` / `slide6_ui` / `web_page`。
- `slide6_ui` 按 sidebar 模块分文件夹，公用部分集中到 `common/`。
- 「键鼠操作」Tab 从 `main_window.py` 抽出为独立 `KeymouseTab`，瘦身主壳。
- 同步打包脚本、入口、`.gitignore`、requirements 与活跃文档，保证可运行、可打包。

**Non-Goals:**
- 不改变任何行为、API 语义、协议或交互。
- 不重写历史 `openspec/changes/archive/**` 与 `openspec/archive/**`。
- 不改 Studio broker 代码（仅更新对外契约文档，提示其同步调用路径）。
- 不做大规模死代码删除（仅清理工程杂物配置）。

## Decisions

### 决策 1：用 `git mv` 保留历史

整目录改名与单文件搬迁均使用 `git mv`，保留文件历史与 blame。**备选**：直接新建 + 删除旧文件。**否决**：丢失历史，diff 噪声大。

### 决策 2：子包 `__init__.py` re-export 公开类，降低 import 改动

每个 sidebar 子包的 `__init__.py` re-export 其公开类（如 `album/__init__.py` 暴露 `DcimAlbumTab`），使 `main_window` 中 `from .album import DcimAlbumTab` 形式的引用层级改动最小，且对外保持稳定入口。

### 决策 3：`common/` 收纳跨模块共享件

`workers.py`（`AsyncRunner`，被多个 Tab 用）、`afc_browser.py`（被 `file_system` 与 `app_manager` 共用）、`sidebar_tabs.py`（侧栏容器）、`tunnel.py`（XPC tunnel 引导，shell 基础设施）归入 `slide6_ui/common/`。相对导入相应调整为 `from ..common.x import ...`。**备选**：`tunnel.py` 留在 `slide6_ui/` 根（仅 `main_window` 使用）。可接受，但本次统一放 `common/` 以求整齐。

### 决策 4：KeymouseTab 逐字抽取 + 委托接线（行为不变）

新建 `keymouse/keymouse_tab.py` 的 `KeymouseTab(QWidget)`，承接原 `_build_keymouse_tab` 的控件与全部 keymouse 专属状态/方法（手势、键盘、剪贴板、截图、fps、刷新，以及 `_start_mirror_flow`→`_begin_stream`→`stop_stream`/`_teardown_mirror` 整条 mirror/WDA 生命周期）。`MainWindow` 保留顶栏（设备下拉/刷新/状态）、Tab 容器、`load_devices`，并在 `on_select_device`/`_on_tab_changed` 中把 keymouse 相关部分委托给 `self.keymouse_tab`（接口如 `set_target/on_enter/on_leave`）；`on_select_device` 对其它四个 Tab 的 `set_target` 仍留在 `MainWindow`。代码逐字搬迁、信号原样重连，保证行为不变。**备选**：仅把 `mirror/keyboard/gestures` 移入 `keymouse/`、构建逻辑留在 `main_window`。**否决**：与本次"主壳瘦身"目标不符（已与用户确认抽取）。

### 决策 5：spec delta 仅做标识符重命名

renamed identifiers 出现在 16 个活跃能力 spec 的规范性表述中（executor_ios 系：`json-cli`/`orientation-op`/`credential-input`/`slide6-tunnel-bootstrap`/`slide6-desktop-shell`/`nuitka-macos-packaging`/`device-info-op`/`app-inventory-op`/`app-file-transfer-op`/`afc-filesystem-op`；slide6_console 系：`slide6-screen-mirror`/`slide6-desktop-shell`/`slide6-app-manager`/`slide6-dcim-album`/`slide6-file-system`；web_console 系：`web-console-orientation`/`web-console-long-press`），本次以 `MODIFIED Requirements` 完整复制原需求块并仅替换包名/模块名/入口路径，不改任何行为契约。归档后这些 live spec 即与新命名一致。

## Risks / Trade-offs

- [KeymouseTab 与 `MainWindow` 深度耦合，抽取可能引入回归] → 逐字搬迁、信号原样重连；单列为独立阶段并独立 commit，便于回退；离屏启动 + 真机冒烟（镜像/点按/键盘/截图/剪贴板/fps/刷新/Tab 进出 teardown）。
- [broker 调用路径变更属对外 BREAKING] → 在契约文档显著标注新路径 `-m ios_toolkit.toolkit_cli`，提示 Studio 侧同步；本仓库范围内无法改 broker。
- [跨包相对/绝对导入遗漏导致 import 失败] → 分阶段验证：`import` 冒烟、CLI 冒烟、离屏启动、完整打包。
- [16 个 spec delta 机械改名易遗漏/错配 header] → 完整复制原需求块、保持 header 完全一致，归档前 `openspec validate --strict`。
- [打包脚本路径/include-package 遗漏导致冻结产物缺包] → 阶段 2 完整跑一次 `build_macos_app.sh`，确认 exit 0 且产物离屏可启动。

## Migration Plan

1. 阶段 1：`git mv` 三个顶层包改名 + 修正跨包/根入口 import；`import` 冒烟 + CLI 冒烟 + 离屏启动。
2. 阶段 2：更新 `build_macos_app.sh`（include-package/ICON_SRC/预检/注释）、`.gitignore`；完整打包验证。
3. 阶段 3：`slide6_ui` 内建 `common/` 与各 sidebar 子文件夹，`git mv` 并修正相对导入；离屏逐 Tab 验证。
4. 阶段 4：抽取 `KeymouseTab`（独立 commit）；真机冒烟。
5. 阶段 5：同步活跃文档与 16 个 live spec（经归档 delta 落地）。

回滚策略：各阶段独立 commit；任一阶段回归可单独 `git revert` 该阶段而不影响其余。

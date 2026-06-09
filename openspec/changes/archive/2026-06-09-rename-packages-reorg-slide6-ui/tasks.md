## 1. 阶段 1：顶层包改名（git mv + import 修正）

- [x] 1.1 `git mv executor_ios ios_toolkit`、`git mv slide6_console slide6_ui`、`git mv web_console web_page`
- [x] 1.2 修正跨包绝对导入：`slide6_ui/*` 与 `web_page/web_server.py` 的 `from executor_ios import ...` → `from ios_toolkit import ...`
- [x] 1.3 修正根入口：`CablediOS.py` 的 `slide6_console.app` → `slide6_ui.app`；`cabled_ios_tunnel.py` 与 `ios_toolkit/ios_tunneld.py` 的 `executor_ios.tunneld_main` → `ios_toolkit.tunneld_main`
- [x] 1.4 修正 `ios_toolkit` 内部对自身的绝对引用（如 docstring/注释中 `executor_ios.*` 模块路径）与 `__init__`/README docstring 中跨包描述（数据存储字面量 `~/.executor_ios.json`、`_SETTINGS_APP`、`~/.slide6_console` 刻意保留并加注释，避免遗弃用户数据）
- [x] 1.5 验证：`python -c "import ios_toolkit, slide6_ui, web_page"` 通过；`echo '{"op":"list_targets","args":{}}' | python -m ios_toolkit.toolkit_cli` 返回 JSON；离屏启动 GUI 无 import 错误

## 2. 阶段 2：打包脚本与工程配置

- [x] 2.1 `packaging/build_macos_app.sh`：multidist 与 fallback 两处 `--include-package=executor_ios/slide6_console` → `ios_toolkit/slide6_ui`
- [x] 2.2 `packaging/build_macos_app.sh`：`ICON_SRC` 改为 `slide6_ui/AppIcon.png`；预检提示中的 requirements 路径（`ios_toolkit/requirements.txt`、`slide6_ui/requirements.txt`）；顶部注释中的包名/路径
- [x] 2.3 `.gitignore`：`executor_ios/screenshot.png` → `ios_toolkit/screenshot.png`；新增 `.idea/`
- [x] 2.4 验证：完整执行 `packaging/build_macos_app.sh`，确认 exit 0（BUILD_EXIT=0）且产物 `CablediOS.app` 离屏可启动、bundle 内含 `cabled_ios_tunnel` 入口与 HEIC 依赖（`_pillow_heif.so`、`libheif.1.21.2.dylib`）

## 3. 阶段 3：slide6_ui 内按 sidebar 模块分文件夹

- [x] 3.1 新建 `slide6_ui/common/`，`git mv` `workers.py`/`afc_browser.py`/`sidebar_tabs.py`/`tunnel.py` 并加 `__init__.py`
- [x] 3.2 新建 `device_info/`、`album/`、`file_system/`、`app_manager/` 子包，`git mv` 对应单文件并在各 `__init__.py` re-export 公开类（`DeviceInfoTab`/`DcimAlbumTab`/`FileSystemTab`/`AppManagerTab`）
- [x] 3.3 修正相对导入层级：`file_system_tab.py`/`app_manager.py` 的 `from .afc_browser`/`from .workers` → `from ..common.afc_browser`/`from ..common.workers`；`device_info.py`/`dcim_album.py` 的 `from .workers` → `from ..common.workers`
- [x] 3.4 修正 `main_window.py` 对各 Tab 的导入为子包路径（`from .album import DcimAlbumTab`、`from .file_system import FileSystemTab`、`from .common import tunnel`、`from .common.sidebar_tabs/workers`）
- [x] 3.5 验证：离屏启动 GUI 构造全部五个 Tab 无报错（编译 + 子包导入 + 离屏 boot 通过；交互式切换/真机冒烟见阶段 4.5）
- [x] 3.6 回归修复：`tunnel.py` 移入 `common/` 多一层目录后，`_repo_root()` 基于 `__file__` 的层级失配（少算一层），导致 dev 模式 `_tunneld_entry_exists()` 误判、`launch_tunneld()` 静默失败；改为向上查找含 `ios_toolkit/` 的祖先目录解析仓库根，去除写死层级（打包/frozen 路径不受影响，走 bundled `cabled_ios_tunnel`）

## 4. 阶段 4：抽取 KeymouseTab（独立 commit，最高风险）

- [x] 4.1 新建 `slide6_ui/keymouse/`，`git mv` `mirror.py`/`keyboard.py`/`gestures.py` 进入（`mirror.py` 的 `from .gestures` 仍为同级，无需改；`keyboard.py` 用绝对 `ios_toolkit` 引用，无需改）
- [x] 4.2 新建 `keymouse/keymouse_tab.py` 的 `KeymouseTab(QWidget)`，逐字搬迁 `_build_keymouse_tab` 控件与 keymouse 专属状态（screen/info_size/info_orient/reload_btn/fps_combo/kbd_capture/kbd_sender/mirror_thread/fps/kbd_on/win_size/orientation/dev）
- [x] 4.3 搬迁 keymouse 专属方法：手势（on_tap/on_long_press/on_swipe）、键盘（on_toggle_keyboard/_set_keyboard/_refocus_keyboard）、动作（on_home/on_switcher/on_screenshot/_save_screenshot/_orient_screenshot/on_send_text/_on_send_done/on_set_pasteboard/on_get_pasteboard/_show_pasteboard/_copy_to_host/on_fps_changed）、mirror 生命周期（_start_mirror_flow/_gate_tunnel/_after_tunnel/_tunnel_failed/_prepare_device/_on_prepared/_on_winsize/_on_orientation/_prepare_failed/_begin_stream/_on_stream_error/stop_stream/_teardown_mirror）、`_connected_buttons`/`_fill_info`
- [x] 4.4 `MainWindow` 保留顶栏/Tab 容器/菜单/`load_devices`/`on_select_device`/`closeEvent`，委托接口为 `select_device/on_enter/on_leave/set_overlay/shutdown`；`on_select_device` 对其它四个 Tab 的 `set_target` 保留，keymouse 相关委托给 `self.keymouse_tab`；刷新按钮经 `reload_callback` 重连到 `on_select_device` 以保留"刷新即全量重选"行为；状态栏经 `set_status` 回调更新
- [x] 4.5 验证：离屏启动 + 结构/委托接线验证通过（编译、import、离屏 boot、Tab 进出不误启 mirror、空选 select_device、close 调用 shutdown）；真机冒烟由用户在物理设备执行，并据此发现/修复 dev 模式隧道启动回归（见 3.6）

## 5. 阶段 5：活跃文档与 live spec 同步

- [x] 5.1 更新 README：`ios_toolkit/README.md`、`slide6_ui/README.md`（含目录结构树同步到 common/各 sidebar 子包/keymouse）、`web_page/README.md`、`packaging/README.md` 中的包名/路径/模块调用；`requirements.txt` 注释；`web_page/web/app.js` 的 `mirror.py` 路径改为 `slide6_ui/keymouse/mirror.py`
- [x] 5.2 更新 `docs/`：`PYTHON-PLATFORM-EXECUTOR-CONTRACT.zh-CN.md`（新增 iOS 包改名为 `ios_toolkit`、broker 入口 `-m ios_toolkit.toolkit_cli` 的 BREAKING 注记）、`ios-protocols-overview.md`、`docs/TODO.md`（保留真实配置文件字面量 `~/.executor_ios.json`）
- [x] 5.3 更新 `openspec/products/executor-ios/executor-ios-project.md` 中的包名/模块名引用（产品/能力名 `executor-ios` 连字符形式保持不变）
- [x] 5.4 历史 `openspec/changes/archive/**` 与 `openspec/archive/**` 保持不动（不改名）
- [x] 5.5 运行 `openspec validate "rename-packages-reorg-slide6-ui" --strict` 通过（"is valid"）；归档后 `openspec validate --specs` 中本次涉及的 16 个 live spec 与新命名一致

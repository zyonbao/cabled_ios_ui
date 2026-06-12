## Why

桌面应用里本地文件/文件夹的选取入口存在两套体验：少数走应用内置（Qt 非原生）带"路径跳转栏"的对话框，多数直接调用系统原生面板。这导致同一应用内交互不一致；并且在部分系统（如未签名/未沙盒的 macOS 包）上，系统原生面板可能出现无法弹出、无法导航或返回空选择等访问受限问题，用户此时缺少可靠的兜底方式。

## What Changes

- 将所有本地文件/文件夹选取统一收口到单一模块，提供四种用途的 helper：选取单个文件、选取多个文件、保存文件、选取目录。
- 应用内置选择器统一为同一个带"路径跳转栏"的对话框（可粘贴/输入绝对路径回车跳转），覆盖上述全部用途，体验一致。
- 在 `Settings → General` 新增「使用应用内置的文件/文件夹选择器」开关，控制全局使用系统原生选择器还是应用内置选择器；默认使用系统原生选择器。该偏好持久化于 `QSettings`，每次弹窗即时读取，无需重启。
- 修正内置选择器路径栏在长路径下只显示尾部的问题，统一显示路径头部。
- Settings 窗口高度自适应到最高标签页，避免切换标签时 XPC tunnel 等分组的行被挤压。

## Capabilities

### New Capabilities
- `slide6-file-picker`: 桌面应用本地文件/文件夹选取的统一入口、内置带路径栏选择器的行为，以及系统/内置选择器的切换逻辑。

### Modified Capabilities
- `slide6-settings-window`: General 标签新增「文件选择器」开关（系统原生 vs 应用内置）的 UI 与持久化要求。

## Impact

- 受影响代码：`slide6_ui/common/file_dialogs.py`（统一 helper 与内置选择器）、`slide6_ui/main_window.py`（General 开关、Settings 自适应高度）、以及全部本地选取调用点（`crash`、`afc_browser`、`app_manager`、`keymouse`、`developer_tools`、`syslog`/`oslog`、`profiles`、`album`、`location_dialog`）。
- 受影响配置：新增 `QSettings` 键 `settings/use_builtin_file_dialog`（默认关闭＝系统原生）。
- 受影响文案：`slide6_ui/languages/{zh-CN,en-US}.json` 的 `settings.file_dialog.*`。
- 无对外 API / 依赖变化。

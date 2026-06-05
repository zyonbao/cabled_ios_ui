## Why

当前 slide6 桌面端与 web 端控制台能镜像键盘、转发手势，但在「直接文本输入」「剪贴板读写」上仍有缺口，且 slide6 键盘镜像开启时缺乏明显的退出入口与就地输入提示。这些是 QA 在真机调试时的高频需求（快速灌入一段文本、设置/读取设备剪贴板），需要补齐。

## What Changes

- **slide6 键盘捕获就地化**：键盘镜像开启时，原「键盘输入: 关/开」按钮所在位置 SHALL 就地替换为「键盘捕获输入框 + 退出（叉）按钮」；点击叉退出键盘镜像模式并恢复为原按钮。（web 端键盘捕获交互不改动）
- **文本输入框 + 发送（两端新增）**：slide6 与 web 各新增一个独立的文本输入框，右侧为「发送」按钮；点击发送把输入框内容通过 `toolkit_api.send_keys` 一次性发送到设备当前聚焦控件。此输入框独立于键盘镜像捕获框。
- **set pasteboard（两端新增）**：新增「设置剪贴板」按钮，点击弹出带「确认 / 取消」的输入窗口；确认后把内容写入目标设备剪贴板。
- **get pasteboard（两端新增）**：新增「读取剪贴板」按钮，点击弹出文本展示窗口展示设备当前剪贴板内容，允许鼠标选中复制（web 端可不强制支持选中）；若剪贴板为非文本内容，提示「非文本内容」且不提供复制。
- **底层能力新增**：`executor_ios` 新增 `get_pasteboard` / `set_pasteboard`（基于 WDA `/wda/getPasteboard`、`/wda/setPasteboard`），web 端新增对应 HTTP 端点。

## Capabilities

### New Capabilities
- `pasteboard-op`: `toolkit_api` 与 `device` 层的设备剪贴板读写能力，以及 web 控制台暴露的对应 HTTP 端点。
- `console-text-send`: 两端控制台「独立文本输入框 + 发送按钮」一次性向设备聚焦控件发送文本的 UI 行为。
- `console-pasteboard-ui`: 两端控制台 set/get 剪贴板的 UI 行为（设置弹窗 + 确认/取消、读取展示弹窗 + 非文本提示）。

### Modified Capabilities
- `slide6-keyboard-input`: 键盘镜像开启时的 UI 形态变化——原切换按钮位置就地替换为「捕获输入框 + 退出叉」，提供明确的退出入口。

## Impact

- 代码：
  - `executor_ios/device.py`、`executor_ios/toolkit_api.py`：新增 `get_pasteboard` / `set_pasteboard`。
  - `web_console/web_server.py`：新增 `/api/get_pasteboard`、`/api/set_pasteboard`、`/api/send_text`（或复用 `/api/type`）端点。
  - `web_console/web/index.html`、`web_console/web/app.js`、`style.css`：新增文本发送、剪贴板按钮与弹窗。
  - `slide6_console/main_window.py`、`slide6_console/keyboard.py`：键盘开启就地化布局、文本发送区、剪贴板对话框。
- 依赖：无新增第三方依赖（沿用 `requests` / WDA HTTP）。
- 兼容性：纯增量功能，不破坏现有 API 与 UI 行为。
- 风险：WDA 剪贴板读写要求 WDA 应用处于前台，存在 iOS 平台限制（详见 design.md 可行性评估）。

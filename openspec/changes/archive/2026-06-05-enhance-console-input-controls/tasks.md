## 1. 底层剪贴板能力（executor_ios）

- [x] 1.1 在 `executor_ios/device.py` 的 `iOSDevice` 新增 `set_pasteboard(text)`：UTF-8→base64，调用 `_post_with_session_retry("/session/{sid}/wda/setPasteboard", {...})`，返回 `_ok`/`_err`
- [x] 1.2 在 `iOSDevice` 新增 `get_pasteboard()`：调用 `/wda/getPasteboard`，对 `value`（base64）尝试 UTF-8 解码，返回 `{"text", "isText"}`，解码失败/为空置 `isText=false`
- [x] 1.3 在 `executor_ios/toolkit_api.py` 新增 `set_pasteboard(target, text)` 与 `get_pasteboard(target)`，复用 `_prepare_device` 与统一 envelope
- [x] 1.4 为 set/get 编写冒烟测试（`local_api_test.py`：中文/emoji 往返、非文本 `isText=false`、设备不存在 `BAD_TARGET`）

## 2. web 端点（web_console/web_server.py）

- [x] 2.1 新增 `PasteboardSetBody`（`target`、`text`）与复用 `TargetBody`
- [x] 2.2 新增 `POST /api/set_pasteboard` 代理到 `api.set_pasteboard`，沿用 `_raise_if_error`
- [x] 2.3 新增 `POST /api/get_pasteboard` 代理到 `api.get_pasteboard`，返回含 `text`/`isText`
- [x] 2.4 确认文本发送复用现有 `POST /api/type`（`send_keys`），无需新端点

## 3. web 前端：文本发送 + 剪贴板（web_console/web）

- [x] 3.1 `index.html` 新增「文本输入框 + 发送按钮」区块与「设置剪贴板 / 读取剪贴板」按钮，默认 disabled
- [x] 3.2 `app.js` 在已连接/断开时同步启用/禁用上述控件（参照现有 `els.*` 与 `stopStream`/`onSelectDevice`）
- [x] 3.3 实现发送按钮：非空时 `postJson('/api/type', {target, text})`，成功后清空输入框，失败走 `flashStatus` 且保留内容
- [x] 3.4 实现设置剪贴板模态：textarea + 确认/取消，确认调用 `/api/set_pasteboard`
- [x] 3.5 实现读取剪贴板模态：调用 `/api/get_pasteboard`，`isText` 为真展示文本，为假提示「非文本或空内容」且不展示文本区
- [x] 3.6 在 `style.css` 增补输入区与模态层样式

## 4. slide6 键盘就地化（slide6_console）

- [x] 4.1 在 `main_window.py` 的 sidebar 把 `kbd_btn` 包进一个容器，新增「退出叉」按钮与开启态布局（`KeyboardCapture` + 叉）
- [x] 4.2 改造 `_set_keyboard`：开启时隐藏切换按钮、显示「捕获框 + 叉」并聚焦；关闭时恢复切换按钮
- [x] 4.3 退出叉 `clicked` 连接到 `_set_keyboard(False)`；保留现有 `KeyboardCapture`/`KeyboardSender` 信号链路

## 5. slide6 文本发送 + 剪贴板（slide6_console）

- [x] 5.1 在 sidebar 新增「文本输入框（QLineEdit）+ 发送按钮」，未连接禁用、连接后启用（参照 `_begin_stream`/`stop_stream` 的按钮启停）
- [x] 5.2 发送按钮：非空时经 `runner.submit(api.send_keys, ...)` 发送，成功后清空输入框，失败 `_flash` 且保留内容
- [x] 5.3 新增「设置剪贴板」按钮 + 输入对话框（确认/取消），确认经 `runner.submit(api.set_pasteboard, ...)`
- [x] 5.4 新增「读取剪贴板」按钮：`runner.submit(api.get_pasteboard, ...)`，`isText` 真用只读可选中 `QPlainTextEdit` 展示，假显示「非文本或空内容」提示且不放文本区
- [x] 5.5 把新增按钮纳入连接/断开时的统一启停集合（`_connected_buttons`）

## 6. 验证

- [x] 6.1 真机验证：set 后 get 往返一致（含中文/emoji）；非文本（先复制图片）时 get 提示非文本
- [x] 6.2 真机验证：两端文本发送可灌入聚焦输入框；slide6 键盘开启就地显示输入框+叉、点叉可退出
- [x] 6.3 记录 WDA 前台限制下的实际表现，必要时补充 UI 提示文案

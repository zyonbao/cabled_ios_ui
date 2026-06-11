## Context

文本发送框（`keymouse_tab.py` 的 `send_input`）原为 `QLineEdit`，单行展示、仅按钮发送。与键盘镜像捕获框（`KeyboardCapture`）相互独立，底层经 `toolkit_api.send_keys(target, text)` 一次性发送。

## Decisions

### 决策 1：用 `QTextEdit` 子类实现自适应高度
新增 `SendTextEdit(QTextEdit)`，`setAcceptRichText(False)` 保持纯文本。高度通过 `document().size().height()` 计算并 `setFixedHeight` 钳制在 `[1, 5]` 行之间，超过则保持 5 行高度并由 `ScrollBarAsNeeded` 显示竖向滚动条；`LineWrapMode.WidgetWidth` 自动换行、关闭横向滚动条。`textChanged` 与 `resizeEvent` 触发重算（宽度变化会改变换行行数）。

- 选用 `QTextEdit` 而非 `QPlainTextEdit`：前者 `document().size()` 直接给像素高度，便于稳定计算自适应高度。

### 决策 2：Enter 发送 / Shift+Enter 换行，兼容 IME
重写 `keyPressEvent`：无修饰的 Enter 发出 `send_requested` 信号（复用既有 `on_send_text`）；带 Shift 的 Enter 落到父类插入换行。输入法组合态下 Enter 由 IME 消费（确认候选），不会到达 `keyPressEvent`，因此组合中按 Enter 不会误发送。

### 决策 3：保留发送按钮
按钮继续可用，便于鼠标操作与可发现性；用 `Qt.AlignTop` 固定在第一行，避免框变高时按钮居中漂移。

## Risks / Trade-offs

- [多行文本含换行符发送] → `send_keys`（WDA typeText）会把换行一并输入，能否真正换行取决于设备端输入框是单行还是多行，属设备侧行为，本次不处理。
- [自适应高度递归] → `setFixedHeight` 触发 `resizeEvent` 再次计算，值收敛后不再变化，无限循环风险可忽略。

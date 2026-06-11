# Tasks

## 1. 多行自适应输入框

- [x] 1.1 新增 `SendTextEdit(QTextEdit)`：`setAcceptRichText(False)`、`LineWrapMode.WidgetWidth`、竖向 `ScrollBarAsNeeded`、横向 `ScrollBarAlwaysOff`
- [x] 1.2 `_adjust_height`：按 `document().size().height()` 计算并 `setFixedHeight`，钳制在 1~5 行，超过封顶并显示竖向滚动条；`textChanged` 与 `resizeEvent` 触发重算
- [x] 1.3 `_build_ui`：将 `send_input` 由 `QLineEdit` 改为 `SendTextEdit`，发送按钮以 `Qt.AlignTop` 钉在第一行

## 2. Enter 发送 / Shift+Enter 换行

- [x] 2.1 `keyPressEvent`：无修饰 Enter 发出 `send_requested` 信号；Shift+Enter 落父类插入换行；组合态 Enter 由 IME 消费不发送
- [x] 2.2 接线：`send_input.send_requested` 连到 `on_send_text`（替换原 `returnPressed`）；`on_send_text` 改用 `toPlainText()` 读取

## 3. 文案与提示

- [x] 3.1 占位文案保持简短（`keymouse.send_placeholder` 不变）；新增 `keymouse.send_tip`（zh-CN/en-US）作为输入框 tooltip 提示 Enter/Shift+Enter

## 4. 验证

- [x] 4.1 字节编译通过；zh-CN/en-US JSON 校验通过；无 lint 报错
- [ ] 4.2 手验（带屏运行）：粘贴多行按多行展示并自适应、超 5 行滚动；Enter 发送、Shift+Enter 换行、组合态 Enter 不误发；按钮仍可发送

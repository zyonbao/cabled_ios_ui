## Why

「键鼠操作」Tab 的独立文本发送框此前是单行 `QLineEdit`：粘贴含回车的多行内容会被压成一行展示，看不全；发送只能点「发送」按钮，输入体验不顺手。希望它像常见聊天输入框那样多行展示、随内容自适应高度，并支持 Enter 发送、Shift+Enter 换行。

## What Changes

- 文本发送框由单行 `QLineEdit` 改为多行可自适应高度的输入框：
  - 粘贴/输入多行内容按多行展示；
  - 高度随内容自动增长，最多 5 行，超过后高度封顶并出现竖向滚动条上下查看；
  - 自动换行（不出横向滚动条）。
- 新增键盘发送：按 Enter 直接发送（无需点按钮），Shift+Enter 插入换行；输入法组合（拼音选字）态的 Enter 用于确认候选、不触发发送。
- 「发送」按钮保留可用，钉在第一行，框变高时不随之居中漂移。
- 仅为桌面端（slide6）文本发送框的呈现与交互增强，不改变底层发送通道（仍走 `toolkit_api.send_keys`）、门控与失败处理逻辑。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `console-text-send`：新增「多行文本输入与自适应高度」「Enter 发送 / Shift+Enter 换行」两项要求（桌面端）。

## Impact

- 代码：`slide6_ui/keymouse/keymouse_tab.py`（新增 `SendTextEdit(QTextEdit)`，替换 `send_input`、接线与读取改用 `toPlainText()`）。
- 文案：`slide6_ui/languages/zh-CN.json`、`en-US.json` 新增 `keymouse.send_tip`（Enter/Shift+Enter 提示，作为输入框 tooltip）。
- 行为：发送通道、门控、成功清空 / 失败保留逻辑不变；不涉及 web 端。
- 无新增依赖。

## Why

`Key/Mouse` tab 现在缺少一个低频调试入口，无法直接查看 WDA 当前抓取到的原始 UI XML。

底层 `dump_ui(target)` 能力已经存在，所以这次只需要补桌面端入口，不需要新增 WDA 能力。

## What Changes

- 在 `Key/Mouse` tab 新增一个低频调试按钮：`UI XML`
- 按钮位置放在剪切板操作区下方
- 点击后调用现有 `toolkit_api.dump_ui(target)`
- 用 `QPlainTextEdit` 弹窗展示返回的原始 XML
- 弹窗提供复制按钮，把 XML 复制到本机剪贴板
- 抓取失败时显示错误状态

## Impact

- 受影响 spec：
  - `slide6-desktop-shell`
- 受影响代码：
  - `slide6_ui/keymouse/keymouse_tab.py`
  - `slide6_ui/languages/*.json`

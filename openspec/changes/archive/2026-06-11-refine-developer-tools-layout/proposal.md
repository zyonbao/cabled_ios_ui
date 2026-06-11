## Why

「开发者工具」Tab 顶部的 DeveloperImage（DDI）状态行与 XPC Tunnel 状态行之间的纵向间距偏大且不一致——Tunnel 行被额外包进一个带默认内边距的 `QWidget` 包装器，使两行间距比普通行间距更大、显得松散不自然。同时下方功能位卡片把标题与描述用同一字体直接拼接（`title\nsubtitle`），缺乏视觉层级，标题与说明文字难以区分、辨识度低。

## What Changes

- 收紧并统一 DDI 状态行与 XPC Tunnel 状态行之间的纵向间距：去除 Tunnel 行包装器的多余内边距，使两行间距更小、更自然且与其它行一致。
- 功能位卡片（进程管理 / 虚拟定位 / 系统日志）改为标题与描述分层呈现：标题使用更突出的字体（更大 / 加粗），描述使用更弱的次级字体（更小 / 次要色），提升辨识度。
- 仅为视觉呈现层调整，不改变功能位的门控逻辑、点击行为与既有交互。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `slide6-developer-tools`：新增「状态行与功能位卡片的视觉呈现」要求——约束状态行间距收紧一致，以及功能位卡片标题/描述的视觉层级区分。

## Impact

- 代码：`slide6_ui/developer_tools/developer_tools_tab.py`（`_build_ui` 的行间距与布局、`_make_tile` 的卡片渲染；syslog 卡片同步样式）。
- 行为：纯展示层调整，不影响门控、点击与异步调用逻辑；不涉及 i18n 文案键变更。
- 无新增依赖。

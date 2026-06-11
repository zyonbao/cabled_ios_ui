# slide6-developer-tools Specification

## ADDED Requirements

### Requirement: 状态行间距与功能位卡片的视觉呈现

「开发者工具」Tab 顶部 DDI 状态行与 XPC Tunnel 状态行之间的纵向间距 SHALL 收紧、自然，且与该 Tab 内其它行的间距保持一致，MUST NOT 因 Tunnel 行容器的额外内边距而显著大于普通行间距。功能位卡片（进程管理 / 虚拟定位 / 系统日志）SHALL 将标题与描述分层呈现：标题 MUST 使用更突出的字体（更大或加粗），描述 MUST 使用更弱的次级字体（更小或次要色），使两者可清晰区分。该要求仅约束视觉呈现，MUST NOT 改变功能位的门控、点击行为与其它既有交互。

#### Scenario: 状态行间距收紧一致

- **WHEN** iOS 17+ 设备进入「开发者工具」Tab（DDI 行与 XPC Tunnel 行同时可见）
- **THEN** 两行之间的纵向间距收紧自然，与该 Tab 内普通行间距一致，无明显多余空隙

#### Scenario: 隐藏 Tunnel 行时不受影响

- **WHEN** 选中 iOS 17 以下设备（XPC Tunnel 行隐藏）
- **THEN** DDI 状态行与下方内容的间距仍自然一致，不出现因隐藏容器残留的异常空隙

#### Scenario: 卡片标题与描述具有视觉层级

- **WHEN** 查看功能位卡片
- **THEN** 标题以更突出的字体呈现、描述以更弱的次级字体呈现，二者可清晰区分

#### Scenario: 视觉调整不改变交互

- **WHEN** 功能位按既有门控处于可用 / 禁用态并被点击
- **THEN** 点击与禁用行为同改造前一致，仅文字的视觉层级发生变化

# console-text-send Specification

## ADDED Requirements

### Requirement: 多行文本输入与自适应高度（桌面端）

slide6 桌面端文本发送输入框 SHALL 支持多行文本的输入与展示，并随内容自适应高度：单行内容时保持单行高度，内容增多时自动增高，最多显示 5 行；超过 5 行时 SHALL 保持 5 行高度并提供竖向滚动条上下查看。输入框 SHALL 自动换行（按宽度折行），MUST NOT 出现横向滚动条。

#### Scenario: 粘贴多行内容按多行展示

- **WHEN** 用户向文本发送输入框粘贴含换行符的多行内容
- **THEN** 内容按多行展示，输入框高度随之增高，而非压成一行

#### Scenario: 超过 5 行封顶并滚动

- **WHEN** 输入框内容超过 5 行可显示高度
- **THEN** 输入框高度保持在 5 行，并出现竖向滚动条供上下查看

#### Scenario: 单行内容保持单行高度

- **WHEN** 输入框为空或仅一行内容
- **THEN** 输入框维持单行高度

### Requirement: Enter 发送与 Shift+Enter 换行（桌面端）

slide6 桌面端文本发送输入框 SHALL 支持按 Enter 直接发送当前内容（等价于点击「发送」按钮，走 `toolkit_api.send_keys`），并支持 Shift+Enter 在输入框内插入换行。当宿主输入法处于组合（preedit）状态时，按 Enter SHALL 用于确认候选而 MUST NOT 触发发送。「发送」按钮 SHALL 继续保留且可用。

#### Scenario: 按 Enter 发送

- **WHEN** 输入框有内容且未处于输入法组合态，用户按下 Enter（不含 Shift）
- **THEN** 当前内容通过 `send_keys` 发送到设备，等价于点击发送按钮

#### Scenario: Shift+Enter 换行不发送

- **WHEN** 用户按下 Shift+Enter
- **THEN** 在输入框内插入换行，不发起发送

#### Scenario: 输入法组合态 Enter 不发送

- **WHEN** 宿主输入法正在组合（如拼音选字）时用户按下 Enter
- **THEN** Enter 用于确认候选词，不触发发送

#### Scenario: 发送按钮仍可用

- **WHEN** 用户点击「发送」按钮
- **THEN** 与按 Enter 一致，把当前内容发送到设备

## MODIFIED Requirements

### Requirement: 条件诱导界面

「开发者工具」Tab SHALL 提供条件诱导功能卡片并打开子面板，子面板 MUST 展示当前状态、条件摘要与 Start/Stop 操作。开始诱导前 SHOULD 显示安全确认提示，结束后 MUST 清理会话资源。

#### Scenario: 关闭子面板自动停止诱导

- **WHEN** 条件诱导子面板在诱导进行中被关闭
- **THEN** 诱导任务自动停止并回收
- **AND** 不会残留后台诱导任务

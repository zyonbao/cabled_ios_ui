# Tasks

## 1. 平台层条件诱导能力

- [x] 1.1 `ios_toolkit/device.py` 增加 `ConditionInducerHandle`（连接作用域）：保活单一 DVT 连接，枚举模型，维护 idle/active(group,profile) 状态
- [x] 1.2 句柄方法：`models()` 枚举（过滤 `isInternal`）、`apply(group_id, profile_id)`（已有活动条件先 `clear` 再 enable）、`clear()`（幂等）、`state()`、`close()`（clear+断开）
- [x] 1.3 `ios_toolkit/toolkit_api.py` 增加 `open_condition_inducer(target)` 入口（返回句柄 / 错误信封）
- [x] 1.4 标识合法性校验与可读错误信封（group/profile 不存在、设备无可用模型）

## 2. UI 子面板落地

- [x] 2.1 `developer_tools_tab.py` 新增条件诱导入口与单例窗口管理（沿用 `_open_subwindow`）
- [x] 2.2 新增 Condition Inducer 对话框：状态区、条件组/profile 选择区、Start(施加/切换)/Stop 控制
- [x] 2.3 Start 前安全确认弹窗（`isDestructive` 显著标注），Stop 后状态与摘要刷新

## 3. 生命周期与降级

- [x] 3.1 Start 创建并持有连接，Stop `clear()`，closeEvent `close()` 自动停止并断开
- [x] 3.2 按设备返回动态渲染可用组/profile，缺失组不显示
- [x] 3.3 异常路径兜底（apply 失败保持原状态 / 连接断开复位为 idle，依赖断开自动恢复）

## 4. 验证

- [x] 4.1 py_compile / ReadLints / openspec validate 严格校验通过
- [x] 4.2 真机验证：施加、切换(先清后启)、结束、关闭窗口四路径无残留诱导状态
- [x] 4.3 i18n 文案补齐并通过 `i18n.validate()`


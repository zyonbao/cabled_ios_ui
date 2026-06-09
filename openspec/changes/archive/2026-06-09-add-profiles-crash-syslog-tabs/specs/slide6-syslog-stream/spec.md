## ADDED Requirements

### Requirement: 系统日志独立 Tab 与来源选择

桌面应用 SHALL 新增独立「系统日志」Tab，并在 `MainWindow` 中注册。Tab SHALL 提供下拉框在 `syslog` 与 `oslog` 两种来源间切换，默认选中 `syslog`。Tab MUST 实现 `set_target(target)`；未选中设备时 MUST NOT 启动任何流。

#### Scenario: 选择来源并开始

- **WHEN** 选中设备并选择某来源后开始流
- **THEN** 视图开始持续追加该来源的实时日志行

#### Scenario: 切换来源重建流

- **WHEN** 在活动流期间切换来源下拉
- **THEN** 当前流被干净停止，按新来源重建流

#### Scenario: 未选择设备不启动

- **WHEN** 未选中设备
- **THEN** Tab 不启动任何流，并提示需先选择设备

### Requirement: 实时流采集与限速渲染

日志采集 MUST 在后台线程执行，并通过限速机制（批量缓冲 + 周期性刷新 + 上限行数裁剪）向视图渲染，避免高吞吐刷爆 GUI 线程。视图行数超过上限时 MUST 从最旧行裁剪。

#### Scenario: 高吞吐不卡死

- **WHEN** 设备产生高频日志
- **THEN** 视图以限速方式平滑追加，超出上限的旧行被裁剪，UI 保持可响应

#### Scenario: 流错误提示

- **WHEN** 底层流建立失败或中断（如 `oslog` 在该设备不可用）
- **THEN** Tab 在状态区提示错误并停止流，应用其余功能不受影响

### Requirement: 关键字过滤

Tab SHALL 提供关键字过滤输入；过滤为大小写不敏感子串匹配，在渲染侧应用且 MUST NOT 丢弃后台采集的数据。修改过滤条件时 MUST 对当前已缓冲的全量行重新套用。

#### Scenario: 输入关键字过滤

- **WHEN** 用户输入关键字
- **THEN** 视图仅显示匹配该关键字的行（大小写不敏感）

#### Scenario: 清除关键字

- **WHEN** 用户清空关键字
- **THEN** 视图恢复显示全部已缓冲行

### Requirement: 暂停 / 清空 / 另存

Tab SHALL 提供暂停、清空、另存三个控制：暂停 MUST 停止向视图渲染新行；清空 MUST 清空视图与缓冲；另存 MUST 将当前视图文本写入用户选择的本地文本文件。日志 MUST NOT 在用户未显式另存时自动落盘。

#### Scenario: 暂停渲染

- **WHEN** 用户点击暂停
- **THEN** 视图停止追加新行，后台采集不影响（再次开始后恢复）

#### Scenario: 清空视图

- **WHEN** 用户点击清空
- **THEN** 视图与缓冲被清空

#### Scenario: 另存为文本

- **WHEN** 用户点击另存并选择目标文件
- **THEN** 当前视图文本写入该本地文件

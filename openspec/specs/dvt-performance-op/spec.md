# dvt-performance-op Specification

## Purpose
定义基于 DVT instruments 的性能监控能力：采集并展示 CPU / GPU / Memory 等可获取指标，统一实时采样、10 分钟滚动窗口绘图与导出数据结构。

## Requirements
### Requirement: 性能采样会话

平台层 SHALL 提供 `start_performance_session(target, metrics, sample_interval_ms)` 与 `stop_performance_session(target)`。采样 MUST 在后台线程执行，不阻塞 UI；重复启动 MUST 先关闭旧会话再创建新会话。`metrics` 为请求指标集合（如 CPU/GPU/Memory），平台层 MUST 按设备可用能力返回实际生效指标并显式标记不可用项。采样失败 MUST 返回可读错误信封，而非崩溃。

性能采样后台线程/进程 MUST 与性能监控窗口生命周期绑定：调用 `start` 时创建并启动；调用 `stop` 时停止并回收；窗口被关闭时 MUST 自动执行停止与回收。实现 MUST NOT 保留脱离窗口生命周期的后台采样任务。

采样频率 `sample_interval_ms` 默认值 SHOULD 为 `500ms`；允许范围 MUST 为 `200ms~2000ms`。超出范围的请求 MUST 被拒绝并返回可读参数错误，MUST NOT 静默回退到未知值。

#### Scenario: 启动采样并返回生效指标

- **WHEN** 用户请求开始性能采样
- **THEN** 返回 `{ok, data:{session_id, enabled_metrics, unsupported_metrics}}`

#### Scenario: 重复启动覆盖旧会话

- **WHEN** 已有采样会话时再次启动
- **THEN** 平台层先停止旧会话，再启动新会话并返回新会话标识

#### Scenario: 关闭窗口回收采样会话

- **WHEN** 用户关闭性能监控窗口
- **THEN** 平台层自动停止并回收该窗口绑定的后台采样线程/进程

#### Scenario: 非法采样频率

- **WHEN** 用户提交小于 200ms 或大于 2000ms 的采样间隔
- **THEN** 返回可读参数错误并拒绝启动采样

### Requirement: 10 分钟缓存窗口与数据淘汰

平台层与 UI 协作 MUST 支持最近 10 分钟滚动窗口：缓存最多保留 10 分钟数据，超过窗口的历史数据 MUST 立即丢弃，不得继续累积。折线图等实时可视化 MUST 仅使用该 10 分钟缓存窗口。时间窗口计算 MUST 基于事件时间戳而非到达顺序，避免采样抖动导致窗口错位。

#### Scenario: 超出窗口自动裁剪

- **WHEN** 性能采样持续超过 10 分钟
- **THEN** 实时折线图仅展示最近 10 分钟数据

#### Scenario: 超时数据被丢弃

- **WHEN** 新样本写入导致缓存覆盖超过 10 分钟
- **THEN** 超过 10 分钟的最旧样本被立即淘汰，缓存始终不超过 10 分钟

### Requirement: 图表渲染与状态反馈

UI 层 SHALL 将性能指标以折线图展示，并显示采样状态（运行中/已停止）、采样频率、最后更新时间。高频采样下 MUST 采用限速渲染（例如固定 FPS 或节流刷新）以避免主线程卡顿。

控制语义 MUST 明确：`Pause` 仅暂停图表刷新而不停止后台采样；`Stop` 停止采样并回收后台任务；`Clear` 清空当前可视缓存并重置图表显示。`Stop` 后 SHOULD 保留最后一次有效快照用于只读查看，直到用户执行 `Clear` 或重新 `Start`。

#### Scenario: 停止采样后冻结曲线

- **WHEN** 用户停止性能采样
- **THEN** 后台采样停止，图表保留最后一帧结果并更新状态为已停止

#### Scenario: Pause 不停止采样

- **WHEN** 用户点击 Pause
- **THEN** 图表停止刷新但后台采样继续进行

### Requirement: 性能能力降级与错误语义

当部分指标不可用（例如设备不支持 GPU 指标）时，平台层与 UI MUST 以 `unsupported` 明确标识该指标，并继续展示其他可用指标。单指标失败 MUST NOT 导致整场会话失败；仅在采样会话整体不可启动时才返回全局失败。

#### Scenario: 单指标不可用降级

- **WHEN** 用户请求 CPU/GPU/Memory 但设备仅支持 CPU/Memory
- **THEN** 会话成功启动，GPU 标记为 `unsupported`，CPU/Memory 正常展示


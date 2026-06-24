# dvt-performance-op Specification

## Purpose
定义基于 DVT `sysmontap` 的性能监控能力：采集并展示 **CPU 信息 / 内存信息 / 网络与磁盘 IO 信息** 三类指标，统一实时采样、10 分钟滚动窗口绘图与导出数据结构。

## Requirements
### Requirement: 性能采样会话

平台层 SHALL 提供 `open_performance_stream(target, interval_ms)`：成功时返回与窗口生命周期绑定的实时采样流句柄（`PerformanceStreamHandle`，经 `close()` 停止并回收），失败时返回可读错误信封。采样 MUST 在后台线程/事件循环执行，不阻塞 UI。UI 层 MUST 防止同一窗口并发开启多个采样流（采样进行中禁用 Start，Stop / 关闭窗口时经 `close()` 回收句柄）。采样源为 `sysmontap`，至少应产出以下三类可视化输入（按设备可用能力降级）：

- CPU 信息：`SystemCPUUsage.CPU_TotalLoad` 按活动核数（`EnabledCPUs`/`CPUCount`）归一化到 0~100%，降级时用 `PerCPUUsage` 每核均值或进程 `cpuUsage`；
- 内存信息：系统已用内存（active + wired + compressed，按 16KB 页换算）与设备物理内存容量（`physMemSize`）；
- 网络与磁盘 IO：累计字节计数（如 `netBytesIn/Out`、`diskBytesRead/Written`）及其速率换算输入。

采样失败 MUST 返回可读错误信封，而非崩溃。

采样流 MUST 与性能监控窗口生命周期绑定：Start 时经 `open_performance_stream` 创建并启动；Stop 时经句柄 `close()` 停止并回收；窗口被关闭时 MUST 自动 `close()` 回收。实现 MUST NOT 保留脱离窗口生命周期的后台采样任务。

采样频率 `sample_interval_ms` 默认值 SHOULD 为 `500ms`；允许范围 MUST 为 `200ms~2000ms`。超出范围的请求 MUST 被拒绝并返回可读参数错误，MUST NOT 静默回退到未知值。

#### Scenario: 启动采样并返回采样流

- **WHEN** 用户请求开始性能采样
- **THEN** 平台层返回实时采样流句柄，UI 据此开始绘制；采样无法启动时返回可读错误信封

#### Scenario: 采样进行中禁止重复开启

- **WHEN** 性能监控窗口已在采样
- **THEN** Start 处于禁用态，不会创建第二个采样流；再次点击功能位仅前置已有窗口

#### Scenario: 关闭窗口回收采样流

- **WHEN** 用户关闭性能监控窗口
- **THEN** 平台层自动 `close()` 停止并回收该窗口绑定的采样流

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

UI 层 SHALL 以三个图表展示三类指标：

- CPU 图表（单或多线）；
- 内存图表（以内存使用量为主，坐标轴上限绑定设备物理内存）；
- 网络与磁盘 IO 图表（同图多线展示入/出网速与磁盘读/写速率）。

同一图表内 MAY 通过不同颜色区分多条指标线。UI MUST 显示采样状态（运行中/已停止）、采样频率、最后更新时间。高频采样下 MUST 采用限速渲染（例如固定 FPS 或节流刷新）以避免主线程卡顿。

控制语义 MUST 明确：`Pause` 仅暂停图表刷新而不停止后台采样；`Stop` 停止采样并回收后台任务；`Clear` 清空当前可视缓存并重置图表显示。`Stop` 后 SHOULD 保留最后一次有效快照用于只读查看，直到用户执行 `Clear` 或重新 `Start`。

#### Scenario: 停止采样后冻结曲线

- **WHEN** 用户停止性能采样
- **THEN** 后台采样停止，图表保留最后一帧结果并更新状态为已停止

#### Scenario: Pause 不停止采样

- **WHEN** 用户点击 Pause
- **THEN** 图表停止刷新但后台采样继续进行

### Requirement: 性能能力降级与错误语义

当部分指标不可用时，平台层与 UI MUST 以隐藏子线方式降级，并继续展示其他可用指标。单指标失败 MUST NOT 导致整场会话失败；仅在采样会话整体不可启动时才返回全局失败。

#### Scenario: 子线缺失降级

- **WHEN** 设备未返回某类子线（例如 GPU）
- **THEN** 会话成功启动，已返回的 CPU/内存/IO 指标正常展示，缺失子线以隐藏方式处理


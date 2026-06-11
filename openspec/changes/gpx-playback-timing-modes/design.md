## Context

GPX 轨迹回放当前由 `ios_toolkit/device.py` 的 `_parse_gpx_steps(path, disable_sleep, timing_randomness_range, default_interval_s=1.0)` 把 GPX 点解析为 `(lat, lon, delay)` 步骤列表，回放器 `_drive_route` 在每个点应用前 `sleep(delay)`。现状语义：

- 第一个点 delay=0；
- `disable_sleep=True` → 所有 delay=0（尽快跑完）；
- 否则点带时间戳 → delay=相邻时间差，且 `timing_randomness_range>0` 时叠加 `±N ms` 随机抖动；
- 点无时间戳 → 退化为固定 `default_interval_s`（1 秒）。

UI 在 `slide6_ui/developer_tools/location_dialog.py` 的 GPX 页签提供「忽略时间戳」复选框与一个抖动 `QSpinBox`（始终可编辑），经 `api.play_route_gpx(target, path, disable_sleep, jitter)` 调用。

约束：`play_route_gpx` 仅本仓库内部调用（UI + `toolkit_api`），无 CLI / 外部消费者；可放心调整入参。已存在 `_haversine_m` 距离辅助函数，可复用于速度模式。

## Goals / Non-Goals

**Goals:**
- 时间抖动成为**独立开关**：仅开关打开时才允许设置并施加抖动。
- 忽略时间戳成为**明确开关**，且打开时**禁用时间抖动**（互斥）。
- 忽略时间戳打开时，提供**二选一**的节奏方式：固定间隔（秒）/ 指定速度（m/s）。
- UI 联动启用/禁用控件，使可用项与当前模式一致、语义直观。

**Non-Goals:**
- 不改动单点设定、手动多点轨迹（`play_route_manual`）、清除逻辑。
- 不改动 iOS 版本分流与常驻会话机制。
- 不引入新的第三方依赖。

## Decisions

### 决策 1：`play_route_gpx` 新入参集合

将后端入参重构为显式表达两种语义（替换原 `disable_sleep` / 单一 jitter）：

```
play_route_gpx(
    target,
    path,
    ignore_timestamps: bool = False,
    timing_randomness_range: int = 0,     # 抖动毫秒；0 表示不抖动（开关关闭时 UI 传 0）
    ignore_mode: str = "interval",        # 仅当 ignore_timestamps=True 时有效: "interval" | "speed"
    interval_s: float = 1.0,              # interval 模式：每点固定等待秒数
    speed_mps: float = 5.0,               # speed 模式：按 haversine 距离/速度计算每段等待
)
```

`_parse_gpx_steps` 对应重构为按以下矩阵生成每个非首点的 delay：

| ignore_timestamps | 模式 | delay 计算 | 抖动 |
|---|---|---|---|
| False | （按时间戳） | 相邻时间差（<0 归 0）；无时间戳点退化为 `interval_s` 兜底 | `timing_randomness_range>0` 时叠加 `±N ms` |
| True | interval | `interval_s` | 不施加 |
| True | speed | `haversine_m(prev,cur) / speed_mps` | 不施加 |

说明：
- 抖动只在「按时间戳回放」分支生效（与互斥约束一致）。
- speed 模式 `speed_mps<=0` MUST 返回 `BAD_TARGET`；interval 模式 `interval_s<0` MUST 返回 `BAD_TARGET`（允许 0 = 尽快跑完，保留原 `disable_sleep` 的快速能力）。
- 保留 `_MAX_ROUTE_STEPS` 上限与首点 delay=0 规则。

**理由**：显式参数让「忽略时间戳 + 节奏方式」语义清晰、可独立校验；抖动用 `timing_randomness_range`（0=关）表达，避免再加一个布尔参数，UI 开关关闭时直接传 0。
**备选**：保留 `disable_sleep` 再叠加模式参数 → 语义重叠、容易出现「disable_sleep=True 又 speed 模式」的歧义组合，弃用。

### 决策 2：`toolkit_api.play_route_gpx` 入参校验与透传

`toolkit_api.play_route_gpx` 同步更新签名，做前置校验（path 必填、文件存在；`ignore_mode` 合法；speed/interval 取值合法）后透传给 `device.play_route_gpx`。返回结构不变：`{ok, data:{playing, source:"gpx", points}}`。

### 决策 3：UI 控件与联动规则（GPX 页签）

控件：
- 「忽略时间戳」`QCheckBox`（默认关）。
- 节奏方式选择：两个互斥单选（`QRadioButton`：固定间隔 / 速度）+ 各自数值输入（间隔 `QDoubleSpinBox` 秒；速度 `QDoubleSpinBox` m/s）。
- 「时间抖动」`QCheckBox`（默认关）+ 抖动 `QSpinBox`（ms，沿用 0–60000、step 100）。

联动：
- 忽略时间戳 **关**：节奏方式单选与两个数值输入禁用；时间抖动开关可用；抖动 `QSpinBox` 仅在抖动开关开时可用。
- 忽略时间戳 **开**：时间抖动开关与抖动 `QSpinBox` 禁用并视觉置灰；节奏方式单选可用，选中项对应的数值输入可用、另一个禁用。

调用映射：
- 忽略时间戳关：`ignore_timestamps=False, timing_randomness_range=(抖动开?值:0)`。
- 忽略时间戳开：`ignore_timestamps=True, timing_randomness_range=0, ignore_mode=("interval"|"speed"), interval_s=..., speed_mps=...`。

### 决策 4：i18n

在 `zh-CN.json` / `en-US.json` 新增键（沿用 `location.*` 命名）：抖动开关、忽略时间戳（已存在 `location.gpx_ignore_ts`，文案保持/微调）、节奏方式标题、固定间隔标签与单位、速度标签与单位（m/s）。`location.jitter` 复用。

## Risks / Trade-offs

- [内部 API 入参 BREAKING] → 仅 3 处调用（device 定义、toolkit_api 包装、UI），同一变更内全部更新；无外部消费者。
- [speed 模式相邻点距离为 0（重复点）导致 delay=0 堆积] → 距离为 0 时 delay 自然为 0，可接受（与 interval=0 行为一致）；受 `_MAX_ROUTE_STEPS` 保护。
- [用户误以为抖动在忽略时间戳下仍生效] → UI 在忽略时间戳开时直接禁用并置灰抖动控件，从交互上消除歧义。
- [GPX 无时间戳但用户未开忽略时间戳] → 维持原兜底（固定 `interval_s`/1 秒），行为可预期。

## Open Questions

- 默认值取定（无需阻塞实现，按下列默认）：固定间隔默认 1.0 s（范围 0–3600）、速度默认 5.0 m/s（范围 0.1–1000）、抖动开关默认关。如需调整可在实现 PR 评审时微调。

## MODIFIED Requirements

### Requirement: 轨迹回放

平台层 SHALL 提供沿轨迹移动的虚拟定位能力，复用与单点设定相同的「路线回放会话」与版本分流（iOS<17 经 `DtSimulateLocation`；iOS 17+ 经 DVT `LocationSimulation` 并维持后台常驻连接使模拟持续生效）。回放为长时间运行过程，平台层 MUST 在后台逐点 `set` 坐标且 MUST 在第一个点生效后即返回（不阻塞等待整条轨迹跑完），并 MUST 可被 `clear_location` / `shutdown` 中止。重复发起 MUST 先释放旧会话。空轨迹 MUST 返回 `BAD_TARGET`。

平台层 SHALL 提供两种轨迹来源：

- `play_route_gpx(path, ignore_timestamps, timing_randomness_range, ignore_mode, interval_s, speed_mps)`：解析 GPX 文件轨迹点为 `(lat, lon, delay)` 步骤，第一个点 delay 恒为 0。每个非首点的 delay 按以下语义计算：
  - **`ignore_timestamps` 为假（按时间戳回放）**：点带时间戳时按相邻点时间差计算 delay（负值归 0），并在 `timing_randomness_range`（毫秒）大于 0 时对 delay 叠加 `±N ms` 随机抖动（结果不小于 0）；点缺时间戳时退化为固定间隔 `interval_s`（兜底）。
  - **`ignore_timestamps` 为真（忽略时间戳）**：MUST NOT 施加时间抖动；并按 `ignore_mode` 二选一计算 delay——`"interval"` 模式各点固定等待 `interval_s` 秒；`"speed"` 模式按相邻点 haversine 距离除以 `speed_mps` 计算每段等待。
  - 入参校验：`ignore_mode` 非法、`"speed"` 模式 `speed_mps` 非正、或 `interval_s` 为负 MUST 返回 `BAD_TARGET`（`interval_s` 允许为 0 表示各点间不等待、尽快跑完）。GPX 解析失败 / 无有效轨迹点 MUST 返回可读错误。生成步骤数 MUST 受统一上限约束。
- `play_route_manual(waypoints, speed_mps, tick_s)`：对给定途经点序列，按 haversine 距离与给定速度（米/秒）自研插值，按固定 tick（秒）生成中间点并平滑逐点设定。途经点不足 2 个或速度非正 MUST 返回 `BAD_TARGET`。

#### Scenario: GPX 带时间戳真实回放

- **WHEN** 选择带时间戳的 GPX 文件回放且未忽略时间戳
- **THEN** 按相邻点时间差还原速度逐点移动，第一个点生效后即返回，连接保持以维持模拟

#### Scenario: GPX 按时间戳回放并启用时间抖动

- **WHEN** 未忽略时间戳且 `timing_randomness_range` 大于 0
- **THEN** 在相邻点时间差基础上对每段等待叠加 `±N ms` 随机抖动（不小于 0）

#### Scenario: GPX 忽略时间戳按固定间隔

- **WHEN** 启用忽略时间戳且 `ignore_mode="interval"`
- **THEN** 各点间按 `interval_s` 固定等待逐点设定，且不施加任何时间抖动

#### Scenario: GPX 忽略时间戳按指定速度

- **WHEN** 启用忽略时间戳且 `ignore_mode="speed"` 并给定正速度
- **THEN** 各段按 haversine 距离除以 `speed_mps` 计算等待逐点设定，且不施加任何时间抖动

#### Scenario: 手动多点按速度移动

- **WHEN** 提供 ≥2 个途经点与正速度
- **THEN** 平台层按距离与速度插值出中间点，平滑沿途逐点设定

#### Scenario: 中止轨迹

- **WHEN** 轨迹回放进行中用户请求清除
- **THEN** 中止回放会话并恢复真实 GPS

#### Scenario: 非法轨迹入参

- **WHEN** 轨迹为空 / 手动途经点不足 2 个 / 速度非正 / GPX 忽略时间戳速度模式速度非正 / 固定间隔为负 / `ignore_mode` 非法
- **THEN** 返回 `BAD_TARGET`

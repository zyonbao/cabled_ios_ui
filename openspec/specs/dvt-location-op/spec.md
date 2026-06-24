# dvt-location-op Specification

## Purpose
定义基于 DVT 的虚拟定位能力：单点定位设置、清除恢复真实定位、GPX/多点轨迹回放及中止控制，并约束输入校验与状态反馈一致性。
## Requirements
### Requirement: 设定虚拟定位

平台层 SHALL 提供 `set_location(target, latitude, longitude)`，按 iOS 版本分流：iOS<17 经 `DtSimulateLocation.set`（设定后持续生效）；iOS 17+ 经 DVT `LocationSimulation.set`。因 iOS 17+ 的模拟仅在 DTX 连接存活期间有效，平台层 MUST 维持一个后台常驻定位会话使模拟在调用返回后持续生效，并 MUST 在设定生效后才返回成功。重复设定 MUST 先释放旧会话再建立新会话。非法经纬度 MUST 返回 `BAD_TARGET`。

#### Scenario: iOS<17 设定

- **WHEN** iOS<17 设备设定坐标
- **THEN** 经 `DtSimulateLocation` 设定，返回 `{ok}` 且模拟持续生效

#### Scenario: iOS 17+ 设定并保持

- **WHEN** iOS 17+ 设备设定坐标
- **THEN** 建立常驻定位会话，设定生效后返回 `{ok}`，连接保持以维持模拟

#### Scenario: 重复设定

- **WHEN** 已有定位会话时再次设定
- **THEN** 先释放旧会话，再以新坐标建立会话

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

### Requirement: 清除虚拟定位

平台层 SHALL 提供 `clear_location(target)`，恢复设备真实 GPS：iOS<17 调用 `DtSimulateLocation.clear`；iOS 17+ 取消常驻定位会话（关闭连接即停止模拟），并尽力调用一次 `clear()`。该清除同样 MUST 中止正在进行的轨迹回放会话。无活动会话时 MUST 返回可读结果而非崩溃。平台层 MUST 提供 `shutdown` 路径在退出 / 换设备时取消常驻会话（含轨迹回放），避免悬挂连接。

#### Scenario: 清除生效

- **WHEN** 用户请求清除虚拟定位
- **THEN** 取消模拟、恢复真实 GPS，返回 `{ok}`

#### Scenario: 退出释放会话

- **WHEN** 应用退出或切换设备
- **THEN** 取消任何活动的常驻定位会话，不留悬挂连接

### Requirement: 轨迹回放进度查询

平台层 SHALL 在轨迹回放期间维护实时进度，并提供 `get_route_progress(target)` 返回快照 `{current, total, playing}`：`total` 为本次轨迹总点数，`current` 为已应用点数，`playing` 表示是否仍在逐点移动。进度维护 MUST 线程安全（回放运行于后台事件循环线程，查询来自其它线程）。发起新回放 MUST 重置进度（`current=0`、`total=点数`、`playing=true`）；每应用一个点 MUST 递增 `current`；全部点应用完成 MUST 置 `playing=false`（iOS 17+ 即使保持连接以维持定位也视为运动完成）；回放被取消 / 启动失败 / 超时 MUST 置 `playing=false`。设备不存在时 `get_route_progress` MUST 返回可读错误而非崩溃。

#### Scenario: 回放中查询进度

- **WHEN** 轨迹回放进行中调用 `get_route_progress`
- **THEN** 返回 `current < total` 且 `playing=true` 的实时快照

#### Scenario: 回放完成后查询进度

- **WHEN** 所有轨迹点已应用后调用 `get_route_progress`
- **THEN** 返回 `current == total` 且 `playing=false`

#### Scenario: 中止后查询进度

- **WHEN** 回放被清除 / 取消后调用 `get_route_progress`
- **THEN** 返回 `playing=false`


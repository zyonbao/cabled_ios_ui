## ADDED Requirements

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

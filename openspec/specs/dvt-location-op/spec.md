# dvt-location-op Specification

## Purpose
TBD - created by archiving change add-developer-tools-tab-phase1. Update Purpose after archive.
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

- `play_route_gpx(path, disable_sleep, timing_randomness_range)`：解析 GPX 文件轨迹点；点带时间戳时按相邻时间差 `sleep` 还原真实速度，`disable_sleep` 为真时各点间不等待立即跑完，`timing_randomness_range`（毫秒）对等待时间加随机抖动；点缺时间戳时退化为固定间隔逐点设定。GPX 解析失败 / 无有效轨迹点 MUST 返回可读错误。
- `play_route_manual(waypoints, speed_mps, tick_s)`：对给定途经点序列，按 haversine 距离与给定速度（米/秒）自研插值，按固定 tick（秒）生成中间点并平滑逐点设定。途经点不足 2 个或速度非正 MUST 返回 `BAD_TARGET`。

#### Scenario: GPX 带时间戳真实回放

- **WHEN** 选择带时间戳的 GPX 文件回放
- **THEN** 按相邻点时间差还原速度逐点移动，第一个点生效后即返回，连接保持以维持模拟

#### Scenario: GPX 忽略时间立即跑完

- **WHEN** 选择 GPX 回放并启用 `disable_sleep`
- **THEN** 各点间不等待，快速跑完整条轨迹

#### Scenario: 手动多点按速度移动

- **WHEN** 提供 ≥2 个途经点与正速度
- **THEN** 平台层按距离与速度插值出中间点，平滑沿途逐点设定

#### Scenario: 中止轨迹

- **WHEN** 轨迹回放进行中用户请求清除
- **THEN** 中止回放会话并恢复真实 GPS

#### Scenario: 非法轨迹入参

- **WHEN** 轨迹为空 / 手动途经点不足 2 个 / 速度非正
- **THEN** 返回 `BAD_TARGET`

### Requirement: 清除虚拟定位

平台层 SHALL 提供 `clear_location(target)`，恢复设备真实 GPS：iOS<17 调用 `DtSimulateLocation.clear`；iOS 17+ 取消常驻定位会话（关闭连接即停止模拟），并尽力调用一次 `clear()`。该清除同样 MUST 中止正在进行的轨迹回放会话。无活动会话时 MUST 返回可读结果而非崩溃。平台层 MUST 提供 `shutdown` 路径在退出 / 换设备时取消常驻会话（含轨迹回放），避免悬挂连接。

#### Scenario: 清除生效

- **WHEN** 用户请求清除虚拟定位
- **THEN** 取消模拟、恢复真实 GPS，返回 `{ok}`

#### Scenario: 退出释放会话

- **WHEN** 应用退出或切换设备
- **THEN** 取消任何活动的常驻定位会话，不留悬挂连接


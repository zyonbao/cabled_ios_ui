## Why

当前 GPX 轨迹回放的「忽略时间戳」只能让各点间不等待、尽可能快地跑完，节奏不可控；而「时间抖动」没有独立开关，行为隐式（仅在按真实时间戳回放时才生效），用户难以理解何时生效。需要把两者拆成清晰的开关，并在忽略时间戳时给出可控的节奏方式（固定间隔 / 指定速度）。

## What Changes

- 为 GPX 回放新增「时间抖动」开关：仅在开关打开时才允许设置并应用抖动毫秒值；关闭时不施加任何抖动。
- 将「忽略时间戳」改为明确的开关；打开时 **时间抖动被禁用**（互斥）。
- 「忽略时间戳」打开时，新增两种二选一的节奏方式来放置坐标：
  1. **固定间隔**：每个点之间等待固定秒数；
  2. **指定速度（m/s）**：按相邻点的 haversine 距离 ÷ 速度计算每段等待时间。
- **BREAKING**（内部 API）：`play_route_gpx` 的入参由 `(path, disable_sleep, timing_randomness_range)` 调整为按时间戳/忽略时间戳两种语义的新参数集合（见 design.md）。该 API 仅供本仓库内部（`slide6_ui` UI 与 `toolkit_api`）调用，无外部消费者。
- UI（开发者工具 → 虚拟定位 → GPX 页签）联动启用/禁用：忽略时间戳关闭时禁用节奏方式选择与对应输入、启用抖动开关；忽略时间戳打开时禁用抖动、启用节奏方式选择与对应输入。

## Capabilities

### New Capabilities
<!-- 无新增能力 -->

### Modified Capabilities
- `dvt-location-op`: 「轨迹回放」需求中 `play_route_gpx` 的时间节奏语义变更——拆分独立的时间抖动开关，并在忽略时间戳时支持「固定间隔」与「指定速度（m/s）」两种节奏方式。
- `slide6-developer-tools`: 「虚拟定位界面」需求中 GPX 回放的交互变更——时间抖动开关、忽略时间戳开关、以及忽略时间戳时的节奏方式（固定间隔 / 速度）选择与联动启用规则。

## Impact

- 代码：
  - `ios_toolkit/device.py`（`_parse_gpx_steps`、`iOSDevice.play_route_gpx`）。
  - `ios_toolkit/toolkit_api.py`（`play_route_gpx` 包装与入参校验）。
  - `slide6_ui/developer_tools/location_dialog.py`（GPX 页签 UI 与联动逻辑）。
  - `slide6_ui/languages/zh-CN.json`、`slide6_ui/languages/en-US.json`（新增 i18n 文案）。
- API：`play_route_gpx` 入参变更（内部 API，无外部消费者）。
- 依赖：无新增第三方依赖（复用既有 `gpxpy` 与 `_haversine_m`）。

## 1. 后端：GPX 解析与节奏语义

- [x] 1.1 重构 `ios_toolkit/device.py` 的 `_parse_gpx_steps`：入参改为 `(path, ignore_timestamps, timing_randomness_range, ignore_mode, interval_s, speed_mps)`，按设计矩阵生成每个非首点 delay（按时间戳/固定间隔/速度三类），首点 delay=0，保留 `_MAX_ROUTE_STEPS` 上限
- [x] 1.2 speed 模式复用 `_haversine_m(prev, cur) / speed_mps` 计算每段等待；距离为 0 时 delay=0
- [x] 1.3 入参校验：`ignore_mode` 非法、speed 模式 `speed_mps<=0`、`interval_s<0` 抛 `ValueError`（由上层转 `BAD_TARGET`）；保留无有效轨迹点错误
- [x] 1.4 更新 `iOSDevice.play_route_gpx` 签名与对 `_parse_gpx_steps` 的调用，透传新参数
- [x] 1.5 更新 `ios_toolkit/toolkit_api.py` 的 `play_route_gpx` 签名、前置校验（path 必填/存在、`ignore_mode` 合法、speed/interval 取值）与透传，返回结构保持 `{ok, data:{playing, source:"gpx", points}}`

## 2. UI：GPX 页签控件与联动

- [x] 2.1 在 `slide6_ui/developer_tools/location_dialog.py` 的 GPX 页签新增「时间抖动」`QCheckBox`（默认关）并与既有抖动 `QSpinBox` 组合
- [x] 2.2 新增节奏方式互斥单选（固定间隔 / 速度）+ 间隔 `QDoubleSpinBox`（秒，默认 1.0，范围 0–3600）与速度 `QDoubleSpinBox`（m/s，默认 5.0，范围 0.1–1000）
- [x] 2.3 实现联动：忽略时间戳关→禁用节奏方式与其输入、启用抖动开关（抖动 SpinBox 仅抖动开关开时可用）；忽略时间戳开→禁用抖动开关与 SpinBox、启用节奏方式且仅选中方式输入可用
- [x] 2.4 更新 `_play_gpx`：按当前开关与所选方式组装入参调用 `api.play_route_gpx`（忽略时间戳关传抖动值或 0；忽略时间戳开传 `ignore_mode`/`interval_s`/`speed_mps` 且抖动置 0）

## 3. i18n 文案

- [x] 3.1 在 `slide6_ui/languages/zh-CN.json` 新增/调整键：时间抖动开关、忽略时间戳、节奏方式标题、固定间隔标签与单位（秒）、速度标签与单位（m/s）
- [x] 3.2 在 `slide6_ui/languages/en-US.json` 同步新增对应英文键，确保两文件键集合一致

## 4. 验证

- [x] 4.1 自测：带时间戳 GPX 在「按时间戳 / 按时间戳+抖动 / 忽略时间戳+固定间隔 / 忽略时间戳+速度」四种组合下回放节奏符合预期
- [x] 4.2 自测：无时间戳 GPX 在未忽略时间戳时退化为固定间隔兜底；非法入参（speed<=0、interval<0、ignore_mode 非法）返回 `BAD_TARGET`
- [x] 4.3 自测：UI 控件启用/禁用联动与互斥行为正确（忽略时间戳与时间抖动互斥）
- [x] 4.4 运行 `openspec validate "gpx-playback-timing-modes" --strict` 通过

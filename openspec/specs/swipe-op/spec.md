## Purpose

定义滑动手势能力：通过 W3C pointer actions 生成稳定的滑动动作序列（按下、停顿、移动、抬起），并明确持续时长、坐标语义及返回格式，保证跨设备行为一致。

## Requirements

### Requirement: 通过 W3C pointer actions 实现滑动
系统 SHALL 通过 WDA W3C Actions（`POST /session/<id>/actions`，pointer 事件序列：pointerDown → pause（`duration_ms`）→ pointerMove → pointerUp）执行滑动操作。坐标单位为逻辑点（pt）。`duration_ms` 默认值为 250。

#### Scenario: 滑动成功
- **WHEN** 以有效 UDID 和合法坐标调用 `swipe(target, x1, y1, x2, y2, duration_ms)`，WDA 正在运行
- **THEN** 返回 `{"ok": true, "data": {"exitCode": 0, "stdout": "", "stderr": "", "extra": {"fromX": x1, "fromY": y1, "toX": x2, "toY": y2, "durationMs": duration_ms}}}` 且设备上列表发生对应方向的滚动

#### Scenario: duration_ms 使用默认值 250
- **WHEN** 调用 `swipe(target, x1, y1, x2, y2)` 不传 `duration_ms`
- **THEN** 使用 250ms 作为滑动持续时间，返回结果中 `extra.durationMs` 为 250

#### Scenario: UDID 不存在时返回 BAD_TARGET
- **WHEN** 以不存在的 UDID 调用 `swipe`
- **THEN** 返回 `{"ok": false, "error": {"kind": "BAD_TARGET", ...}}`

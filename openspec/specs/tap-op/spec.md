## Purpose

点击手势能力——通过 W3C pointer actions 在指定逻辑坐标执行点击。

## Requirements

### Requirement: 通过 W3C pointer actions 实现点击
系统 SHALL 通过 WDA W3C Actions（`POST /session/<id>/actions`，pointer 类型，pointerDown + pointerUp 序列）在指定逻辑坐标执行点击操作。坐标单位为逻辑点（pt），不需要乘以 scale factor。

#### Scenario: 点击成功
- **WHEN** 以有效 UDID 和合法坐标调用 `tap(target, x, y)`，WDA 正在运行
- **THEN** 返回 `{"ok": true, "data": {"exitCode": 0, "stdout": "", "stderr": "", "extra": {"tapX": x, "tapY": y}}}` 且设备上对应坐标的按钮被触发

#### Scenario: UDID 不存在时返回 BAD_TARGET
- **WHEN** 以不存在的 UDID 调用 `tap(target, x, y)`
- **THEN** 返回 `{"ok": false, "error": {"kind": "BAD_TARGET", ...}}`

#### Scenario: WDA 请求失败时返回 SUBPROCESS
- **WHEN** 以有效 UDID 调用 `tap(target, x, y)` 但 WDA 不可访问
- **THEN** 返回 `{"ok": false, "error": {"kind": "SUBPROCESS", ...}}`

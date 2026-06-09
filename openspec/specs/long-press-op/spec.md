## Purpose

长按手势能力——通过 W3C pointer actions 实现长按，并经 JSON CLI 暴露 long_press op。

## Requirements

### Requirement: 通过 W3C pointer actions 实现长按

系统 SHALL 通过 WDA W3C Actions（`POST /session/<id>/actions`，pointer 事件序列：pointerMove(duration=0) → pointerDown → pause(`duration_ms`) → pointerUp）在同一坐标执行长按操作。坐标单位为逻辑点（pt）。`duration_ms` 默认值为 800。

#### Scenario: 长按成功

- **WHEN** 以有效 UDID 和合法坐标调用 `long_press(target, x, y, duration_ms)`，WDA 正在运行
- **THEN** 返回 `{"ok": true, "data": {"exitCode": 0, "stdout": "", "stderr": "", "extra": {"x": x, "y": y, "durationMs": duration_ms}}}` 且设备在该坐标触发长按（如弹出上下文菜单或进入编辑态）

#### Scenario: duration_ms 使用默认值 800

- **WHEN** 调用 `long_press(target, x, y)` 不传 `duration_ms`
- **THEN** 使用 800ms 作为按住时长，返回结果中 `extra.durationMs` 为 800

#### Scenario: UDID 不存在时返回 BAD_TARGET

- **WHEN** 以不存在的 UDID 调用 `long_press`
- **THEN** 返回 `{"ok": false, "error": {"kind": "BAD_TARGET", ...}}`

#### Scenario: WDA 调用异常归类 SUBPROCESS

- **WHEN** 设备已就绪但与 WDA 通信失败
- **THEN** 返回 `{"ok": false, "error": {"kind": "SUBPROCESS", ...}}` 且不抛出未捕获异常

### Requirement: JSON CLI 暴露 long_press op

一次性 JSON CLI（`toolkit_cli`）SHALL 在 op 路由表中提供 `long_press` op，从 `args` 读取 `target`/`x`/`y` 及可选 `durationMs`（camelCase，映射到 `duration_ms`），调用 `toolkit_api.long_press` 并返回统一信封。

#### Scenario: CLI 路由 long_press

- **WHEN** stdin 传入 `{"op": "long_press", "args": {"target": "<udid>", "x": 100, "y": 200, "durationMs": 1000}}`
- **THEN** CLI 调用 `toolkit_api.long_press(target, 100, 200, 1000)` 并把结果（附带 `requestId`）写到 stdout，退出码 0

#### Scenario: CLI 缺省 durationMs

- **WHEN** stdin 传入 `{"op": "long_press", "args": {"target": "<udid>", "x": 100, "y": 200}}`
- **THEN** 使用默认 800ms 执行长按

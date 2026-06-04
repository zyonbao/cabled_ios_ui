## Context

`executor_ios` 通过 WDA 的 W3C pointer actions（`POST /session/{sid}/actions`）实现触控。现有 `tap` 与 `swipe` 都复用 `device._pointer_gesture(actions)` 这一封装：

- `tap`：pointerMove(0) → pointerDown → pause(100) → pointerUp。
- `swipe`：pointerMove(0) → pointerDown → pause(dur) → pointerMove(dur) → pointerUp。

长按本质上就是"原地按下并保持一段较长时间再抬起"，即 `tap` 的 pause 时长拉长且不发生位移。因此可以完全复用 `_pointer_gesture`，无需新的 WDA 通道或依赖。

两个控制台（`slide6_console`、`web_console`）当前都依据"按下到抬起的位移阈值"区分点按与滑动：位移 < 8px 为点按，否则为滑动；滑动时长由按住时间映射并夹在 120~1500ms。长按需要作为"原地（位移小）但按住时间长"的第三类手势插入这套判定。

## Goals / Non-Goals

**Goals:**

- 在 `executor_ios` 暴露 `long_press(target, x, y, duration_ms=800)`，返回与 `tap`/`swipe` 一致的 `OpResult` 信封。
- 通过 JSON CLI（`long_press` op）与 `web_console` 的 `POST /api/long_press` 对外开放该能力。
- 两个控制台都能在画面上以"原地按住"触发长按，并与点按/滑动互斥，坐标映射沿用现有逻辑。

**Non-Goals:**

- 不实现多指/压力（force touch）手势。
- 不实现"长按后拖拽"（long-press-then-drag）组合手势——长按结束即抬起。
- 不改动既有 `tap`/`swipe` 的行为与默认值。

## Decisions

### 1. 复用 `_pointer_gesture` 实现长按

`device.long_press(x, y, duration_ms)` 发送：pointerMove(0,x,y) → pointerDown → pause(duration_ms) → pointerUp，并返回 `extra={"x": x, "y": y, "durationMs": duration_ms}`。

- 理由：与 `tap`/`swipe` 同源，行为可预测、维护成本最低；WDA 对长按没有专用 REST 接口，pointer actions 是既有且验证过的通道。
- 备选：调用 WDA `/wda/touchAndHold`（element/duration 接口）。否决：该接口面向元素或基于秒的浮点时长、与现有坐标驱动模型不一致，且我们已统一走 actions 通道。

### 2. `duration_ms` 默认 800ms

- 理由：iOS 触发上下文菜单/编辑态的长按阈值约 0.5s，800ms 留出余量更稳定。`tap` 的 100ms、`swipe` 的 120~1500ms 与之区隔清晰。
- CLI/HTTP 参数名用 camelCase `durationMs`（与 `swipe` 一致），内部转 `duration_ms`。

### 3. 控制台手势判定：先位移、再时长

把判定从"二选一（tap/swipe）"扩展为三类，统一规则：

- 位移 ≥ 点按阈值（8px）→ `swipe`（保持现状，优先级最高，避免长按时手抖被误判后又错判）。
- 位移 < 阈值且按住时长 ≥ 长按阈值（默认 600ms，高于 iOS `UILongPressGestureRecognizer` 默认 `minimumPressDuration` 约 0.5s）→ `long_press`。
- 否则 → `tap`。

- `web_console`（`app.js`）：在 `pointerup` 时按 `dist` 与 `hold` 时间分流；同时用一个 `setTimeout` 定时器在原地按住达到阈值时提供即时视觉/触发，但为避免与既有"抬起判定"产生重复发送，采用**抬起时一次性判定**为主（不在按住途中提前发送），保持与现有点按/滑动同样的"抬起即发"模型，复杂度最低。
- `slide6_console`（`mirror.py` + `gestures.py`）：在 `mouseReleaseEvent` 中先判位移，位移小则按 `event.timestamp() - press_ms` 的按住时长决定 `tap` 还是 `long_press`；`gestures.py` 增加 `is_long_press(hold_ms)` 与长按时长常量。新增 `long_press` 信号，`main_window` 连接到 `on_long_press` 走 `AsyncRunner`。

- 理由：抬起时一次性判定与现有两端实现完全同构，改动面最小，互斥天然成立。
- 备选：按住途中由定时器主动触发长按（按下即倒计时）。否决：需要处理"已触发后抬起不再发 tap/swipe"的额外状态机，且 web 与桌面两端都要维护，收益有限。

### 4. 长按时长上限钳制

控制台把测得的按住时长直接作为 `durationMs` 传给执行层时，钳制到合理上限（默认 ≤ 3000ms），避免误操作（长时间不抬手）产生超长按压。执行层对非法/缺省值用 800ms 兜底。

## Risks / Trade-offs

- [按住途中无即时反馈] → 采用抬起时判定，用户长按期间界面无"已识别长按"提示。可接受：与现有点按/滑动一致；后续如需可加视觉提示，不影响契约。
- [长按与慢速短滑的边界] → 位移阈值优先于时长，慢速但有位移仍判为 swipe，符合直觉。
- [WDA 会话过期] → 复用 `_pointer_gesture` → `_post_with_session_retry`，已有一次重建会话的重试，长按继承该健壮性。
- [超长按住] → 控制台侧钳制上限 + 执行层默认值兜底，避免异常时长。

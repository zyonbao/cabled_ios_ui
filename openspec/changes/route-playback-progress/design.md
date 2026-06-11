## Context

轨迹回放在后台事件循环（`_bg_loop`）上由 `_drive_route` 逐点 `loc.set` 驱动，`play_route_*` 在第一个点生效（`ready` 事件）后即同步返回，之后回放与 UI 完全解耦——没有从后台回传进度的通道。UI 仅在 `_on_play` 设置一次静态状态文案。

## Goals / Non-Goals

**Goals:**
- 让 UI 能展示实时「当前/总点数」与「已完成」。
- 跨线程安全、不阻塞 UI 线程、不改变既有回放时序与会话语义。

**Non-Goals:**
- 不改回放算法、版本分流、常驻会话与清除逻辑。
- 不为单点设定提供进度（仅轨迹回放）。

## Decisions

### 决策 1：轮询式进度（而非回调/信号）
后台运行在独立事件循环线程，回放与 UI 生命周期解耦。采用**轮询**最稳：平台层维护进度快照，UI 用 `QTimer` 定期查询。
- 备选：从后台线程向 Qt 发信号 → 需跨线程信号、生命周期管理复杂，弃用。

### 决策 2：进度状态存放与并发
在 `iOSDevice` 维护 `_route_progress = {current, total, playing}`，用既有 `_location_lock` 保护读写：
- `_start_route` 开播重置 `{0, len(steps), True}`；超时/失败置 `playing=False`。
- `_drive_route` 每次 `loc.set` 后递增 `current`；全部应用完置 `playing=False`（运动结束，iOS 17+ 连接仍保持以维持定位）。
- `_cancel_location_task` 置 `playing=False`。
- `get_route_progress()` 返回字典副本。

### 决策 3：UI 轮询与完成判定
`LocationDialog` 用 500ms `QTimer`，回放成功后启动并立即查询一次；查询经 `AsyncRunner` 提交（不阻塞 UI 线程）。
- `current < total` → 「正在回放轨迹（current/total 个点）…」。
- `current >= total`（且 total>0）→ 「已回放完成（total/total 个点）…」并停表。
- 查询返回不可用（设备丢失）→ 停表。
- 清除、`closeEvent` → 停表。

## Risks / Trade-offs

- [轮询频率与开销] → 500ms 间隔、查询为内存读取，开销可忽略。
- [完成态与常驻会话] → iOS 17+ 全部点应用后连接仍保持以维持定位；用 `playing=False` 表示「运动完成」而非「会话结束」，UI 以 `current>=total` 判完成，语义清晰。
- [关闭后回调晚到] → `closeEvent` 停表；偶发晚到的查询回调只更新隐藏控件，无副作用。

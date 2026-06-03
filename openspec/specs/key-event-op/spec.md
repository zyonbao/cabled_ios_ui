## ADDED Requirements

### Requirement: 按键路由表映射各按键到对应 WDA 实现
系统 SHALL 根据按键路由表将 `key` 参数路由到对应的 WDA 实现：`HOME`/`POWER` 通过 `POST /wda/pressButton`；`ENTER`/`DEL`/`TAB`/`SPACE`/`ESCAPE` 通过 `POST /session/<id>/actions`（W3C key event）；`BACK`/`MENU`/`RECENTS` 及其他未知 key 返回 `NOT_IMPLEMENTED`。

#### Scenario: HOME 键回到桌面
- **WHEN** 调用 `key_event(target, "HOME")`，WDA 正在运行
- **THEN** 返回成功响应且设备回到桌面

#### Scenario: BACK 键返回 NOT_IMPLEMENTED
- **WHEN** 调用 `key_event(target, "BACK")`
- **THEN** 返回 `{"ok": false, "error": {"kind": "NOT_IMPLEMENTED", ...}}`，不发起任何 WDA 请求

#### Scenario: 未知 key 返回 NOT_IMPLEMENTED
- **WHEN** 调用 `key_event(target, "UNKNOWN_KEY")`
- **THEN** 返回 `{"ok": false, "error": {"kind": "NOT_IMPLEMENTED", ...}}`

#### Scenario: ENTER 键通过 W3C key event 发送
- **WHEN** 调用 `key_event(target, "ENTER")`，WDA 正在运行
- **THEN** 通过 W3C key actions 发送 `"\uE007"`，返回成功响应

### Requirement: HOME/POWER 键无需 session
系统 SHALL 在执行 `HOME` 和 `POWER` 按键时直接调用 `POST /wda/pressButton`，无需先创建 WDA session。

#### Scenario: HOME 键不创建 session
- **WHEN** 调用 `key_event(target, "HOME")`
- **THEN** 不发起 `POST /session` 请求，直接调用 `POST /wda/pressButton`

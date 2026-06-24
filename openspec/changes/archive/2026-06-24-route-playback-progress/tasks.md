## 1. 后端进度维护

- [x] 1.1 `iOSDevice` 新增 `_route_progress = {current, total, playing}`（由 `_location_lock` 保护）
- [x] 1.2 `_drive_route` 每应用一个点递增 `current`，全部应用完置 `playing=False`
- [x] 1.3 `_start_route` 开播重置进度；超时/失败分支置 `playing=False`；`_cancel_location_task` 置 `playing=False`
- [x] 1.4 新增 `iOSDevice.get_route_progress()` 返回字典副本
- [x] 1.5 `ios_toolkit/toolkit_api.py` 新增 `get_route_progress(target)`

## 2. UI 轮询展示

- [x] 2.1 `LocationDialog` 新增 500ms `QTimer`，`_on_play` 成功后启动并立即查询一次
- [x] 2.2 `_poll_progress` 经 `AsyncRunner` 查询；`_on_progress` 按 current/total 刷新「进行中 / 已完成」并在完成或不可用时停表
- [x] 2.3 `_clear` 与新增 `closeEvent` 停止轮询

## 3. i18n

- [x] 3.1 `zh-CN.json` / `en-US.json` 新增 `playing_progress`、`play_done`

## 4. 验证

- [x] 4.1 `py_compile`、JSON 解析、ReadLints 通过
- [x] 4.2 `openspec validate "route-playback-progress" --strict` 通过

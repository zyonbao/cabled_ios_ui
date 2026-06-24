## Why

轨迹回放（GPX / 手动）在第一个点生效后立即返回，UI 仅设置一次「正在回放轨迹（N 个点）…」的静态文案，用户无法看到回放进度，长轨迹时不知道当前进展或是否已完成。需要把回放进度实时回传到 UI。

## What Changes

- 平台层在轨迹回放过程中维护实时进度（已应用点数 / 总点数 / 是否仍在运动），并提供 `get_route_progress(target)` 供 UI 轮询查询。
- UI（开发者工具 → 虚拟定位）在回放开始后以定时器轮询进度，将状态文案刷新为「正在回放轨迹（当前/总 个点）…」；全部点应用完成后显示「已回放完成（总/总 个点）…」并停止轮询。
- 清除定位、关闭窗口、设备不可用时停止轮询。

## Capabilities

### New Capabilities
<!-- 无新增能力 -->

### Modified Capabilities
- `dvt-location-op`: 轨迹回放新增「回放进度查询」能力（`get_route_progress`，回报 current/total/playing）。
- `slide6-developer-tools`: 虚拟定位界面新增「轨迹回放实时进度展示」（轮询刷新当前/总点数与完成态）。

## Impact

- 代码：
  - `ios_toolkit/device.py`（`iOSDevice._route_progress`、`_drive_route`、`_start_route`、`_cancel_location_task`、新增 `get_route_progress`）。
  - `ios_toolkit/toolkit_api.py`（新增 `get_route_progress`）。
  - `slide6_ui/developer_tools/location_dialog.py`（`QTimer` 轮询、`_poll_progress`/`_on_progress`、`closeEvent`）。
  - `slide6_ui/languages/zh-CN.json`、`en-US.json`（`playing_progress`、`play_done`）。
- API：新增只读查询 `get_route_progress`，不改既有回放入参与返回结构。
- 依赖：无新增。

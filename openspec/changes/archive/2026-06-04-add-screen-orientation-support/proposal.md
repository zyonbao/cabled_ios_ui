## Why

设备横屏时画面渲染会错乱：WDA 的 MJPEG broadcaster 默认按竖屏（设备原生方向）推送帧，而 `window_size` 按当前方向返回尺寸（横屏时宽>高），二者方向不一致，导致 `web_console` 与 `slide6_console` 在横屏下画面被拉伸/挤压、点按与滑动坐标错位。当前两端都没有"获取屏幕方向"的能力，无法据此正确渲染与映射坐标。

## What Changes

- `executor_ios.toolkit_api` 新增 `orientation(target)` 接口：返回设备当前屏幕方向（如 `PORTRAIT` / `LANDSCAPE_LEFT` / `LANDSCAPE_RIGHT` / `UPSIDE_DOWN`），底层走 WDA `GET /session/{sid}/orientation`，并附带可供 UI 使用的归一化字段（方向枚举 + 旋转角度）。
- `web_console` 与 `slide6_console` 在准备设备后获取方向，并**按方向渲染视频流**：使画面与设备实际朝向一致、宽高比正确，且点按/滑动坐标映射在横竖屏下都准确。
- 两端在"选中设备后"各新增一个**刷新按钮**，点击后执行与"重新选中当前设备"完全一致的逻辑（重新 `prepare` → 取 `window_size`/`orientation` → 重连视频流），用于在设备旋转后手动重新同步。

## Capabilities

### New Capabilities
- `orientation-op`: `executor_ios` 平台能力——查询设备当前屏幕方向，返回统一信封（方向枚举 + 旋转角度），错误语义与其他 `*-op` 一致。
- `web-console-orientation`: `web_console` 按屏幕方向渲染 MJPEG 视频流与坐标映射，并提供"选中设备后的刷新"动作（web_console 当前无既有 spec，故以新能力聚焦本特性）。

### Modified Capabilities
- `slide6-screen-mirror`: 实时画面渲染需按设备屏幕方向旋转/布局，并保证横竖屏下手势坐标映射正确。
- `slide6-desktop-shell`: 选中设备后新增"刷新"按钮，其动作等同于重新选中当前设备。

## Impact

- 代码：
  - `executor_ios/toolkit_api.py`（新增 `orientation`）、`executor_ios/device.py`（新增 WDA orientation 查询方法）。
  - `web_console/web_server.py`（新增 `/api/orientation`）、`web_console/web/app.js`（按方向渲染 + 刷新按钮）、`web_console/web/index.html`/`style.css`（刷新按钮 UI）。
  - `slide6_console/main_window.py`（获取方向、刷新按钮、生命周期）、`slide6_console/mirror.py`（按方向渲染与坐标映射）。
- 行为：横屏设备的画面与坐标恢复正确；新增一次方向查询（可与 `window_size` 同阶段）。
- 兼容：纯新增接口与 UI，不破坏既有调用；`executor_ios` 既有契约不变。
- 平台：与现状一致，聚焦 macOS USB 真机（`executor_ios` 当前仅支持该场景）。

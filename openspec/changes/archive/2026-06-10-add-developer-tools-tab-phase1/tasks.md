## 1. 平台能力层：DDI 挂载

- [x] 1.1 `ios_toolkit/device.py`：新增 `ddi_status()`（按版本选 image type，`is_image_mounted` + `query_developer_mode_status`，走 usbmux lockdown，免 tunnel）
- [x] 1.2 `ios_toolkit/device.py`：新增 `ddi_mount(method, **paths)`（auto / personalized / developer / manual；`AlreadyMountedError` 幂等成功；开发者模式未开启给可读错误）
- [x] 1.3 `ios_toolkit/device.py`：新增 `ddi_unmount()`（按版本选 mounter 调 `umount()`）

## 2. 平台能力层：DVT 进程

- [x] 2.1 `ios_toolkit/device.py`：新增内部 `_with_dvt(op)`（<17 usbmux lockdown / 17+ RSD，RSD 缺失抛可读错误；`async with DvtProvider(...)`）
- [x] 2.2 新增 `list_processes()`（`DeviceInfo.proclist` 规整为 `[{pid,name,realAppName,isApplication,startDate}]`）
- [x] 2.3 新增 `launch_app_dvt(bundle_id)`（`ProcessControl.launch` 返回 pid）与 `kill_process(pid)`（`ProcessControl.kill`）

## 3. 平台能力层：虚拟定位

- [x] 3.1 `ios_toolkit/device.py`：新增 `set_location(lat, lon)`：<17 走 `DtSimulateLocation`；17+ 起常驻定位会话（`Future` 持于 device，set 后置就绪事件再返回）
- [x] 3.2 新增 `clear_location()`（<17 `DtSimulateLocation.clear`；17+ 取消会话 + 尽力 `clear()`）与 `shutdown_location()`（退出/换设备取消会话）
- [x] 3.3 轨迹回放：抽出统一 `_run_route_async(steps)` 路线会话（替代单点 `_run_location_session_async`，set_location 复用单步路线）；新增 `_parse_gpx_steps(path, disable_sleep, timing_randomness_range)`（gpxpy）与 `_interpolate_route(waypoints, speed_mps, tick_s)`（haversine 插值）
- [x] 3.4 新增 `play_route_gpx(path, disable_sleep, timing_randomness_range)` 与 `play_route_manual(waypoints, speed_mps, tick_s)`（首点生效即返回，可被 clear/shutdown 中止；空轨迹/<2 点/速度非正返回 `BAD_TARGET`）

## 4. toolkit_api 包装

- [x] 4.1 `ios_toolkit/toolkit_api.py`：新增 `ddi_status` / `ddi_mount` / `ddi_unmount` / `list_processes` / `launch_app_dvt` / `kill_process` / `set_location` / `clear_location` 包装（参数校验 + `_prepare_device_basic`）
- [x] 4.2 `ios_toolkit/toolkit_api.py`：新增 `play_route_gpx` / `play_route_manual` 包装（参数校验：文件存在、途经点 ≥2、速度 > 0）

## 5. UI：开发者工具 Tab

- [x] 5.1 新建 `slide6_ui/developer_tools/` 包与 `DeveloperToolsTab(QWidget)`：构造 `(runner, get_target)`，实现 `set_target` / `shutdown`
- [x] 5.2 顶部 DDI 状态栏：状态标签 + 挂载/卸载按钮（挂载弹方式选择 + 手动文件选择）；iOS 17+ tunnel 提示与启动入口
- [x] 5.3 功能位 grid（进程管理、虚拟定位卡片）+ `_set_features_enabled` 按 DDI 状态门控
- [x] 5.4 进程管理面板/对话框：列表 + 按名筛选 + 刷新 + 按 bundle id 启动 + kill（二次确认）+ 明细（只读）
- [x] 5.5 虚拟定位面板/对话框：经纬度输入设定 + 清除 + 状态文案
- [x] 5.6 虚拟定位对话框扩展轨迹回放：GPX 文件选择 + 选项（忽略时间戳/抖动）；手动途经点表（增删 + 经纬度）+ 速度输入 + 开始回放；回放/中止状态文案

## 6. 接线

- [x] 6.1 `slide6_ui/main_window.py`：注册「开发者工具」Tab，`on_select_device` 分发 `set_target`，`closeEvent` 调用 `shutdown`

## 7. 验证

- [x] 7.1 lint 无误 + 导入冒烟（pyright 对新子包的陈旧索引误报以运行时导入为准）
- [ ] 7.2 真机验证：DDI 状态/挂载（≥1 种方式）/卸载；进程列表/启动/kill/明细；虚拟定位设定/清除（含 iOS 17+ 常驻会话与退出释放）；轨迹回放（GPX 带/不带时间戳、手动多点按速度移动、回放中清除中止）

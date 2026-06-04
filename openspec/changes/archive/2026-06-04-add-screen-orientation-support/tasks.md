## 1. executor_ios 方向接口

- [x] 1.1 `device.py`：新增 `orientation()` 方法，**优先**调用 WDA `GET /session/{sid}/rotation` 取 `z` 角（4 方向），失败回退 `GET /session/{sid}/orientation`
- [x] 1.2 `device.py`：`z` → 归一化枚举 + `degrees`（0/90/180/270），`z` 就近取整到 90 倍数；coarse 接口做旧值归一化；未知值/异常回退 `PORTRAIT`/0
- [x] 1.3 `toolkit_api.py`：新增 `orientation(target)`，走 `_prepare_device` 后调用 `device.orientation()`，返回统一信封；异常归类 `SUBPROCESS`
- [x] 1.4 真机自检：四方向均返回正确的 `orientation`/`degrees`（粗粒度 `/orientation` 只有 2 值，故改用 `/rotation` 的 `z`）

## 2. web_console 后端

- [x] 2.1 `web_server.py`：新增 `GET /api/orientation?target=` 端点，调用 `toolkit_api.orientation` 并透传信封/错误

## 3. web_console 前端渲染与坐标

- [x] 3.1 `app.js`：`onSelectDevice` 在取 `window_size` 后请求 `/api/orientation`，缓存到 `state.orientation`
- [x] 3.2 `app.js`：按"帧 vs `window_size` 宽高比"判断——不一致才旋转 90/270，倒置额外 +180；`style.css` 改 `object-fit: contain` 去拉伸；竖屏不旋转
- [x] 3.3 `app.js`：`toDevicePoint` 复用容器分数×`window_size`（当前方向）空间，旋转后画面正立即映射正确
- [x] 3.4 真机复核：旋转后触控区与显示画面对齐

## 4. web_console 刷新按钮

- [x] 4.1 `index.html`：在快捷操作区新增"刷新画面 / 方向"按钮（区别于顶部刷新设备列表）+ 方向信息行
- [x] 4.2 `app.js`：刷新按钮绑定 `onSelectDevice`（重新选中当前设备逻辑）；随连接态启用/禁用

## 5. slide6_console 渲染与坐标

- [x] 5.1 `mirror.py`：`ScreenView.set_orientation(orientation, degrees)`；`on_frame` 收帧时按"帧 vs window 宽高比"判断是否旋转（90° 倍数无损转置），倒置额外 +180
- [x] 5.2 `mirror.py`：旋转在收帧阶段完成，下游 `image_rect()`/绘制/坐标映射对"已正立 + 当前方向 window_size"均成立，无需额外逆变换；`SLIDE6_DEBUG` 打印帧/窗口几何便于真机调试
- [x] 5.3 `main_window.py`：选中设备流程在 `window_size` 后经后台线程调用 `toolkit_api.orientation`，结果回主线程 `set_orientation`

## 6. slide6_console 刷新按钮与重选逻辑

- [x] 6.1 `main_window.py`：`on_select_device` 读取当前选中项跑完整流程，本身即重选逻辑（刷新按钮直接复用）
- [x] 6.2 `main_window.py`：新增"刷新画面 / 方向"按钮，绑定 `on_select_device`，沿用 generation 计数；随连接态启用/禁用

## 7. 验证

- [x] 7.1 真机自测：竖屏 / 横屏（左/右）/ 倒置四方向下两端画面方向、宽高比、点按/滑动命中均正确
- [x] 7.2 真机自测：设备旋转后点刷新按钮，两端重新同步方向与尺寸并恢复正确渲染
- [x] 7.3 异常路径：`orientation` 失败时两端回退竖屏渲染、不崩溃
- [x] 7.4 `openspec validate add-screen-orientation-support --strict` 通过

## 8. 真机调试发现并修复的缺陷

- [x] 8.1 方向检测只有 2 值：WDA `/orientation` 仅返回粗粒度 PORTRAIT/LANDSCAPE → 改用 `/rotation` 的 `z` 角拿到完整 4 方向
- [x] 8.2 已是当前方向的帧被重复旋转：最初无条件按 `degrees` 旋转 → 改为"仅当帧方向与 `window_size` 不一致才旋转"
- [x] 8.3 倒置竖屏差 180°：宽高比判断无法识别 180° 翻转 → 对 `PORTRAIT_UPSIDE_DOWN` 在宽高比一致分支额外 +180°
- [x] 8.4 web 横屏画面被 `object-fit: fill` 拉伸 → 改为 `contain`

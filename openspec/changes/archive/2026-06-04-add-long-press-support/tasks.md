## 1. executor_ios 长按能力

- [x] 1.1 `device.py`：新增 `long_press(self, x, y, duration_ms)`，复用 `_pointer_gesture`（pointerMove(0) → pointerDown → pause(duration_ms) → pointerUp），返回 `_ok({"exitCode":0,"stdout":"","stderr":"","extra":{"x":x,"y":y,"durationMs":duration_ms}})`，异常归类 `SUBPROCESS`
- [x] 1.2 `toolkit_api.py`：新增 `long_press(target, x, y, duration_ms=800)`，走 `_prepare_device` 后调用 `device.long_press`，BAD_TARGET 透传
- [x] 1.3 `toolkit_cli.py`：新增 `_handle_long_press`（读取 `args["x"]`/`args["y"]` 与 `args.get("durationMs", 800)`）并注册到 `OP_TABLE`

## 2. web_console 后端

- [x] 2.1 `web_server.py`：新增 `LongPressBody(target, x, y, durationMs=800)` 与 `POST /api/long_press` 端点，调用 `toolkit_api.long_press` 并透传信封/错误

## 3. web_console 前端手势

- [x] 3.1 `app.js`：新增长按阈值常量（约 600ms）与时长上限（约 3000ms）
- [x] 3.2 `app.js`：`pointerup` 判定改为"位移≥阈值→swipe；位移<阈值且 hold≥长按阈值→long_press；否则→tap"，长按调用 `postJson("/api/long_press", {...})`，坐标用按下点映射，`durationMs` 取实测 hold 钳制后值
- [x] 3.3 `app.js`：长按后若键盘开启则保持 `els.kbd.focus()`

## 4. slide6_console 前端手势

- [x] 4.1 `gestures.py`：新增 `LONG_PRESS_MIN_MS`（600）与 `LONG_PRESS_MAX_MS`（3000）常量，新增 `is_long_press(hold_ms)` 与 `clamp_long_press_duration(hold_ms)`
- [x] 4.2 `mirror.py`：`ScreenView` 新增 `long_press = Signal(int, int, int)` 信号；`mouseReleaseEvent` 在位移小于阈值时按 hold 时长决定发 `tap` 还是 `long_press`
- [x] 4.3 `main_window.py`：连接 `screen.long_press` 到 `on_long_press`，经 `AsyncRunner` 调用 `api.long_press`，失败 `_flash`；沿用 `gesture_finished` 保持键盘焦点

## 5. 文档

- [x] 5.1 `docs/PYTHON-PLATFORM-EXECUTOR-CONTRACT.zh-CN.md`：在可用 op 列表与 6.x 小节补充 `long_press` 的请求/成功响应示例

## 6. 验证

- [x] 6.1 `openspec validate add-long-press-support --strict` 通过
- [ ] 6.2 真机自测：在可长按出菜单的位置（如主屏图标、消息气泡）原地长按，两端均能弹出上下文菜单/进入编辑态
- [ ] 6.3 互斥回归：原地短按仍为点按、带位移仍为滑动，长按不误触发
- [ ] 6.4 异常路径：错误 UDID 返回 BAD_TARGET；WDA 不可用时不崩溃

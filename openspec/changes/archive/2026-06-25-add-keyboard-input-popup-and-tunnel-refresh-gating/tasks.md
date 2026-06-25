# Tasks

## 1. tunnel 刷新联动门控（slide6-developer-tools）

- [x] 1.1 `_on_refresh_tunnel` 在 iOS 17+/已挂载/tunnel 运行时重新 `_probe_rsd` 重评估门控；tunnel 未运行时清除过期 `_dvt_ready` 再刷新功能位

## 2. 键盘输入浮动窗口（slide6-keyboard-input）

- [x] 2.1 入口按钮改为恒定文字按钮，点击切换「键盘输入：已关闭 / 已打开」，不改变侧栏高度（移除就地替换的 kbd_active_row 抬高逻辑）
- [x] 2.2 新增浮动「键盘输入」子窗口（keymouse Tab 内子 widget）：含 KeyboardCapture 输入框 + 退出叉；默认覆盖在入口按钮位置
- [x] 2.3 浮动窗口自身承载 Tab 内拖拽，move 钳制到 Tab rect，不可拖出
- [x] 2.4 打开聚焦输入框并启动 KeyboardSender；点叉 / 再次点按钮 / 断连 均关闭窗口、停止捕获、按钮回「已关闭」
- [x] 2.5 `zh-CN.json` / `en-US.json` 文案：入口「已关闭 / 已打开」

## 3. 验证

- [x] 3.0 `_on_refresh_tunnel` py_compile 通过
- [x] 3.1 离屏：浮动窗显示/隐藏、拖拽钳制不出 Tab（超界与负值均钳回）
- [x] 3.2 i18n.validate 无缺失、JSON 合法、py_compile
- [ ] 3.3 真机：开启/关闭键盘输入、拖拽浮窗、tunnel 起来后点刷新解锁功能位
- [x] 3.4 `openspec validate add-keyboard-input-popup-and-tunnel-refresh-gating --strict`

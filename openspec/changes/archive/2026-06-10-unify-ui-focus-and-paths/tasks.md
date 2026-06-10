# Tasks

## 1. 取消自动聚焦输入框（#2）

- [x] 1.1 封装一个小助手：在 tab `set_target` / 显示、子页面 / 对话框打开时，把焦点交给中性控件（不聚焦输入框）—— 新增 `common/focus.py:suppress_auto_focus`，将文本输入框 focusPolicy 降为 ClickFocus（显式 setFocus 仍有效）
- [x] 1.2 应用到含输入框的 tab / 子页面：设备信息 / App 列表 / Crash 报告 / 系统日志 / 文件系统 / 相册 / 描述文件 / 开发者工具（main_window 统一应用）；子页面 / 对话框：AfcBrowserDialog、ProcessDialog、LocationDialog、Settings
- [x] 1.3 保留键鼠键盘捕获的 `kbd_capture.setFocus()`（keymouse tab 不应用助手，行为不变）

## 2. 路径根统一为 /（#9）

- [x] 2.1 `common/afc_browser.py` `_display_path()`：所有 root 的上下文根显示为 `/`（去掉 documents 的 `Documents` 前缀）
- [x] 2.2 `common/afc_browser.py` `_parse_path()`：以 `/` 起的输入解析回对应 root 下逻辑路径（与 _display_path 互逆）
- [x] 2.3 `album/dcim_album.py`：路径框把 `/DCIM` 上下文根显示为 `/`，导航夹紧仍以真实 `/DCIM` 为根
- [x] 2.4 核对「上一级」在显示根禁用、非根启用对各浏览器一致（afc_browser/dcim/crash 均 root 禁用）

## 3. 收尾修复（手验中发现）

- [x] 3.1 `common/afc_browser.py`：用 `shiboken6.isValid(self)` 守卫所有后台回调（`_on_list` / `_refresh` / `_submit` / `_on_batch_done` 及各 on_error），修复 modal 浏览对话框关闭后 `afc_list` 回调晚到访问已删除 `_FileTable` 的崩溃

## 4. 验证

- [x] 4.1 lint 无误 + 导入冒烟
- [x] 4.2 真机 / 手验：切各 tab 与子页面均不自动聚焦输入框；键盘捕获仍自动聚焦
- [x] 4.3 手验：App Documents 根显示 `/`、相册根显示 `/`、文件系统 / Crash 仍 `/`；编辑路径回车跳转正确、越界夹紧（相册）正常；上一级启用/禁用正确

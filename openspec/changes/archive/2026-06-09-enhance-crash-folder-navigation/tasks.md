## 1. 平台能力层

- [x] 1.1 `ios_toolkit/device.py`：`iOSDevice.list_crashes(sub_path="/")` 透传 `CrashReportsManager.ls(sub_path, depth=1)`；每条目归一为 `{name(基名), path(相对根完整路径), isDir, size, mtime}`，stat 用绝对路径 `"/" + path`
- [x] 1.2 `ios_toolkit/toolkit_api.py`：`list_crashes(target, sub_path="/")` 透传，保持向后兼容

## 2. Crash 报告 Tab 导航

- [x] 2.1 维护 `cur_path`（相对根，根为 `""`）；新增可编辑路径输入框（回车经 `normpath` 归一跳转，杜绝 `..` 越界）与「上一级」按钮，工具栏按统一顺序 **上一级 - 路径编辑框 - 刷新**（其后过滤 / 导出 / 删除）；「上一级」按 `bool(cur_path)` 设置启用态（根禁用）
- [x] 2.2 `reload` 传 `sub_path=cur_path or "/"`；设备切换 / 刷新重置 `cur_path` 到根
- [x] 2.3 双击文件夹条目进入（用 `path`）；「上一级」用 `posixpath.dirname` 且夹在根不越界
- [x] 2.4 导出 / 删除 / 选择改用条目 `path`（替代 `name`），过滤 / 多选 / 右键在当前层继续生效

## 3. 验证

- [x] 3.1 lint 无误
- [x] 3.2 真机验证：根列举（3 目录 + 57 文件）、进入 `Assistant`→`Analytics/SpeechLogs`、路径与 `path` 字段正确（iPhone 15/iOS 17.6.1）
- [~] 3.3 真机验证：根级导出已验证（44KB .ips，保留原文件）；本机子目录暂无叶子文件可测嵌套导出，路径机制与根级一致；删除（破坏性）待 GUI 确认

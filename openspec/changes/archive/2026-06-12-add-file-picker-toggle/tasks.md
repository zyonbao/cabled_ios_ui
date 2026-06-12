## 1. 统一选择器模块

- [x] 1.1 泛化 `_PathBarFileDialog`，支持 `file_mode` / `accept_mode` / `show_dirs_only` / `default_name`
- [x] 1.2 提供 4 个 helper：`open_existing_file` / `open_existing_files` / `save_file` / `open_directory`，非原生分支统一走带路径栏对话框
- [x] 1.3 新增偏好 `settings/use_builtin_file_dialog`（默认关闭），`use_builtin_file_dialog()` 与取反的 `use_native_file_dialog()`，每次弹窗即时读取
- [x] 1.4 路径栏长路径显示头部（初始化与目录变化后 `setCursorPosition(0)`）

## 2. 调用点收口

- [x] 2.1 将 `crash`、`afc_browser`、`app_manager`、`keymouse`、`developer_tools`、`syslog`、`oslog`、`profiles`、`album` 的本地选取改为走 helper
- [x] 2.2 清理各文件不再使用的 `QFileDialog` 导入，确认模块外无 `QFileDialog` 直接调用
- [x] 2.3 同步 `location_dialog` 中引用旧常量的注释

## 3. Settings UI

- [x] 3.1 General 标签新增「文件选择器」分组与「使用应用内置的文件/文件夹选择器」开关，绑定持久化键
- [x] 3.2 Settings 窗口高度自适应到最高标签页；XPC tunnel 分组与日志文件输入行设最小高度
- [x] 3.3 i18n 文案 `settings.file_dialog.*`（中英文，不暴露框架名）

## 4. 校验

- [x] 4.1 lint 无错；两份语言 JSON 合法；相关模块编译通过
- [ ] 4.2 手动验证：默认走系统选择器；开启内置后各入口（打开/多选/保存/选目录）均为带路径栏对话框且体验一致
- [ ] 4.3 手动验证：长路径在路径栏显示头部；Settings 切换标签时 XPC tunnel 行不被挤压

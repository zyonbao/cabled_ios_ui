## 1. 平台能力层：导出

- [x] 1.1 `ios_toolkit/device.py`：新增 `export_profile(identifier, local_path)`，复用 `get_profile_list()` 取 `ProfileManifest[identifier]['Data']` 原始字节写入本地；缺失/无该 id 返回可读错误信封
- [x] 1.2 `ios_toolkit/toolkit_api.py`：新增 `export_profile(target, identifier, local_path)` 包装（空 identifier → `BAD_TARGET`）

## 2. 描述文件 Tab 化

- [x] 2.1 新建 `slide6_ui/profiles/profiles_tab.py`：`ProfilesTab(QWidget)`，迁移列表 / 安装 / 拖拽 / 多选移除，构造为 `(runner, get_target)` 并实现 `set_target`
- [x] 2.2 新增「导出选中…」按钮：单选另存、多选导目录、汇总成功/失败
- [x] 2.3 `slide6_ui/profiles/__init__.py` 导出 `ProfilesTab`；移除 `ProfilesDialog`（删除 `profiles_dialog.py`）

## 3. 接线与移除旧入口

- [x] 3.1 `slide6_ui/main_window.py`：注册「描述文件」Tab，并在 `on_select_device` 分发 `set_target`
- [x] 3.2 `slide6_ui/app_manager/app_manager.py`：移除「描述文件…」按钮、`on_profiles_clicked` 与 `ProfilesDialog` 导入

## 4. 验证

- [x] 4.1 lint 无误（`main_window` 三处 `.crash/.profiles/.syslog` 为 pyright 陈旧索引误报，运行时导入冒烟通过）
- [ ] 4.2 真机验证：列表 / 安装 / 移除照旧；导出单选与多选可落地，导出的 `.mobileconfig` 可被重新安装

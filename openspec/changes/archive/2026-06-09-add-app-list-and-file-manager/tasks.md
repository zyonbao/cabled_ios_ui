## 1. executor 层：App 清单能力（app-inventory-op）

- [x] 1.1 在 `executor_ios/device.py` 的 Nuitka 静态导入提示块中补充 `house_arrest` / `afc` 相关导入
- [x] 1.2 在 `iOSDevice` 增加异步方法 `_list_apps_async`，调用 `InstallationProxyService.get_apps(application_type="Any")`，映射出 `bundleId`/`name`/`appType`/`fileSharing`/`sandboxAccessible`
- [x] 1.3 在 `iOSDevice` 增加 `_install_app_async`（`install_from_local`）与 `_uninstall_app_async`（`uninstall`），均提交到 `_bg_loop`
- [x] 1.4 在 `executor_ios/toolkit_api.py` 新增 `list_apps(target)` / `install_app(target, ipa_path)` / `uninstall_app(target, bundle_id)`，含参数校验（ipa 扩展名、bundle_id 非空）与统一 `_ok`/`_err` 包络
- [x] 1.5 校验：通过 `executor_ios/toolkit_cli.py` 或临时脚本在真机验证三函数返回结构与错误路径

## 2. executor 层：文件传输能力（app-file-transfer-op）

- [x] 2.1 在 `iOSDevice` 增加 house-arrest 连接辅助：按 `root`（documents→`documents_only=True`/container→`False`）建立 `AfcService`，使用短连接（用后即关）
- [x] 2.2 实现 `root`+`sub_path` 的路径解析与越界校验（规范化、拒绝越过所选根的 `..`）
- [x] 2.3 增加 `afc_list` / `afc_pull` / `afc_push` / `afc_rm` / `afc_mkdir` 的异步实现，提交到 `_bg_loop`
- [x] 2.4 在 `executor_ios/toolkit_api.py` 暴露对应函数，统一包络；`container` 不可访问与远端/本地文件不存在均返回明确 `error`
- [x] 2.5 大文件优先用 AFC `pull`/`push` 分块路径（已用 `pull`/`push`）；真机校验导入导出正确性

## 3. UI 重构：主界面 Tab 化（slide6-desktop-shell）

- [x] 3.1 将 `main_window._build_ui` 拆分：顶部栏保留设备下拉 + 刷新；顶部不再展示系统/UDID/名称/型号（设备明细改由「设备信息」Tab 承载）
- [x] 3.2 引入左侧纵向 `SidebarTabs`，新建「键鼠操作」Tab，将现有画面区/手势/键盘/文本/剪贴板/HOME/Switcher/截图控件迁入
- [x] 3.3 将帧率下拉从顶部迁入「键鼠操作」Tab 右侧操作区，保持 `on_fps_changed` 行为不变
- [x] 3.4 更新 `_fill_info` 与相关引用，并回归现有键鼠功能（点按/滑动/键盘/剪贴板/截图）
- [x] 3.5 WDA/镜像延迟启动：仅在进入「键鼠操作」Tab（或已在该 Tab 时选中设备）启动，离开该 Tab 自动停流并停止 WDA

## 4. UI 新增：App 列表 Tab（slide6-app-manager）

- [x] 4.1 新建「App 列表」Tab 组件（建议 `slide6_console/app_manager.py`）：列表视图 + 搜索框 + 筛选开关（fileSharing / 沙盒可访问）+ 操作按钮
- [x] 4.2 接入 `AsyncRunner.submit(list_apps)` 加载与刷新列表，行内标识 fileSharing / sandboxAccessible
- [x] 4.3 实现搜索（名称/bundleId，不区分大小写）与两类筛选的内存过滤
- [x] 4.4 实现安装：按钮选择 `.ipa` + 列表区拖拽 `.ipa`（`dragEnterEvent`/`dropEvent`，校验扩展名），调用 `install_app` 后刷新；失败给出可读提示
- [x] 4.5 实现卸载：行内"卸载"按钮 → 确认 → `uninstall_app` → 刷新
- [x] 4.6 「操作」列合并：按能力在行内展示 `Documents`/`Sandbox`/`卸载`，去掉底部操作栏

## 5. UI 新增：App 文件浏览器（afc_browser.py）

- [x] 5.1 文件浏览器对话框：可编辑相对路径（回车跳转）+ 非根 `..` 行双击返回；调用 `afc_list` 渲染目录
- [x] 5.2 入口控制：仅 fileSharing 提供 `Documents`，仅 sandboxAccessible 提供 `Sandbox`
- [x] 5.3 实现导出：文件"另存为" / 文件夹"选择目录" / 拖出 Finder（临时落地）→ `afc_pull`（递归）
- [x] 5.4 实现导入：行内/拖入本地文件或文件夹 → `afc_push`（递归）→ 刷新
- [x] 5.5 实现删除（二次确认）/ 新建目录 / 重命名（`afc_rm`/`afc_mkdir`/`afc_rename`）并刷新
- [x] 5.6 行内文字按钮（导入↑/导出↓/重命名✎/删除✕）+ 等价右键菜单；提交逻辑收敛到 `_submit`

## 5b. UI 新增：设备信息 Tab（device-info-op + slide6-desktop-shell）

- [x] 5b.1 `executor_ios` 新增 `device_info(target)`：经 lockdown `get_value()` 读取全量属性，剔除字节类字段
- [x] 5b.2 新建 `device_info.py` 的 `DeviceInfoTab`：键/值表格，常用字段置顶、其余排序，支持筛选
- [x] 5b.3 设备信息 Tab 置于左侧首位并设为选中设备后默认 Tab；支持双击/右键复制字段名与值

## 6. 校验与收尾

- [x] 6.1 真机回归：iOS ≤16 与 iOS 17+（经 tunnel）各验证 App 列表/安装/卸载/文件浏览
- [ ] 6.2 验证打包：`packaging/build_macos_app.sh` 产出的 .app 中 App/文件功能可用（确认 pymobiledevice3 子服务已打包）— **未验证**：归档时打包验证尚未进行，后续打包时需确认 pymobiledevice3 子服务（house_arrest/afc/installation_proxy/lockdown）均已纳入 .app
- [x] 6.3 更新 `slide6_console/README.md`（如涉及）说明新 Tab 与限制（IPA 签名、沙盒可访问范围）
- [x] 6.4 运行 `openspec validate "add-app-list-and-file-manager"` 通过

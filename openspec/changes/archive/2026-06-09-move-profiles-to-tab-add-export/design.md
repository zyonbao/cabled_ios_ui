## Context

描述文件管理现为 `ProfilesDialog`（`slide6_ui/profiles/profiles_dialog.py`），由「App 列表」Tab 的「描述文件…」按钮 `on_profiles_clicked` 以模态对话框打开。底层经 `toolkit_api.list_profiles/install_profile/remove_profile` → `device.*` → lockdown `MobileConfigService`，免 WDA / tunnel。

## Goals / Non-Goals

**Goals:**

- 将描述文件管理提升为独立 sidebar Tab，保留全部既有能力（列表 / 安装 / 拖拽 / 多选移除）。
- 新增导出能力（单选另存、多选导出到目录）。
- 与其它 Tab 一致：实现 `set_target`，由主窗口分发。

**Non-Goals:**

- 不改动安装 / 移除的底层语义。
- 不处理描述文件签名校验 / 解密（导出原始字节，签名包按原样落地）。

## Decisions

### 决策 1：Tab 化复用对话框逻辑

新建 `ProfilesTab(QWidget)`，迁移 `ProfilesDialog` 的表格 / 安装 / 拖拽 / 移除逻辑，构造签名改为 `(runner, get_target)` 并实现 `set_target(target)`（重置列表并按设备重载，空设备显示「未选择设备」、不发请求）。删除 `ProfilesDialog` 与「App 列表」中的按钮入口，避免双入口与死代码。

### 决策 2：导出取 `ProfileManifest` 原始字节

`export_profile(identifier, local_path)` 调用 `MobileConfigService.get_profile_list()`，从返回的 `ProfileManifest[identifier]` 取原始 `Data`（描述文件原始字节，可能为 CMS 签名包），写入 `local_path`。字段按 iOS 版本差异**防御式查找**（`ProfileManifest` 缺失或无该 identifier 时返回 `NOT_FOUND`/`SUBPROCESS` 信封而非抛异常）。导出字节原样落地，不做签名处理。

- 备选：`get_stored_profile` 仅适用于 cloud/setup 描述文件，不能枚举任意已装描述文件，故不采用。

### 决策 3：导出 UI 与 Crash 导出一致

单选 → `QFileDialog.getSaveFileName` 预填 `<name>.mobileconfig`；多选 → `getExistingDirectory` 后逐项写 `<identifier>.mobileconfig`（identifier 唯一，避免重名覆盖），汇总成功 / 失败数量。所有阻塞调用经 `AsyncRunner`。

## Risks / Trade-offs

- [`ProfileManifest` 键名 / 结构随 iOS 版本变化] → 防御式取值（`ProfileManifest` → identifier → `Data`），缺失则返回可读错误；真机验证导出字节可被重新安装。
- [签名描述文件导出后内容为签名包] → 这是预期：导出即"取回设备上的原始描述文件"，按原样落地，文档/状态可提示。
- [双入口残留] → 一并移除「App 列表」按钮与 `ProfilesDialog`，避免行为分叉。

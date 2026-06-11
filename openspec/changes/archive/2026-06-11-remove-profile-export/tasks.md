# Tasks

## 1. UI 层移除导出入口
- [x] 1.1 `slide6_ui/profiles/profiles_tab.py`：移除「导出选中」按钮、`_on_export_clicked` / `_export_single` / `_on_single_exported` / `_export_many` / `_on_many_exported` / `_after_export` / `_safe_name`，保留 `_selected_profiles`（移除流程仍用）
- [x] 1.2 更新模块 docstring，说明 iOS 不暴露已安装描述文件原始字节、故不提供导出

## 2. 平台能力层移除 export_profile
- [x] 2.1 `ios_toolkit/device.py`：移除 `export_profile(identifier, local_path)`
- [x] 2.2 `ios_toolkit/toolkit_api.py`：移除 `export_profile(target, identifier, local_path)` 包装

## 3. i18n 清理
- [x] 3.1 `slide6_ui/languages/zh-CN.json`：移除 `profiles.export_selected` 及 `need_select_export` / `missing_identifier` / `export_title` / `export_to` / `exporting_one` / `exporting_many` / `export_failed` / `export_failed_short` / `export_failed_msg` / `exported_to` / `exported_partial` / `exported_ok`
- [x] 3.2 `slide6_ui/languages/en-US.json`：同步移除相同键

## 4. 验证
- [x] 4.1 JSON 解析通过；无残留 `export_profile` / `profiles.export*` 引用（归档历史除外）
- [x] 4.2 profiles_tab 导入与冒烟（lint 无错）
- [x] 4.3 `openspec validate remove-profile-export --strict` 通过

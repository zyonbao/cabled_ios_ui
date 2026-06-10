# Tasks

## 1. 错误信封扩展（逻辑层，零 i18n）

- [x] 1.1 扩展 `toolkit_api._err(kind, message, details=None, code=None)`：透传 `code` 进信封（`error.code`），未提供时省略该键；`message` 保持英文调试详情
- [x] 1.2 盘点 `ios_toolkit/`（`toolkit_api.py` / `device.py` / `ddi_provider.py`）中会上浮到 UI 的错误点，确定最终 `code` 枚举（以 design 错误码表初稿为基准，按实际微调）

## 2. 逐点改造 toolkit 错误（中文 message → code + details + 英文 message）

- [x] 2.1 DDI 相关：`DDI_NO_SOURCE` / `DDI_STATUS_TIMEOUT` / `DDI_MOUNT_TIMEOUT` / `DDI_UNMOUNT_TIMEOUT` / `DDI_IMAGE_MISSING` / `DDI_PERSONALIZED_ARGS_MISSING` / `DDI_DEVELOPER_ARGS_MISSING` / `DDI_UNKNOWN_FAMILY`(`details.family`) / `DEVELOPER_MODE_OFF`
- [x] 2.2 DVT / tunnel：`DVT_READY_TIMEOUT` / `RSD_QUERY_TIMEOUT` / `TUNNEL_REQUIRED`（经 `_TunnelRequiredError` + `_dvt_exc_to_err` 边界统一映射）
- [x] 2.3 虚拟定位 / GPX：`LOCATION_START_TIMEOUT` / `GPX_FILE_NOT_FOUND`(`details.path`) / `GPX_PARSE_FAILED`(`details.exc`) / `GPX_NO_TRACKPOINTS`
- [x] 2.4 logarchive：`LOG_ARCHIVE_FAILED`(`details.exc`)
- [x] 2.5 上浮异常：`device.py` 的 tunnel `RuntimeError` 改为 `_TunnelRequiredError`、no-trackpoints 改为 `_GpxNoTrackpointsError`；`ddi_provider.py` 的 `RuntimeError` 文案改英文（仅作调试详情）
- [x] 2.6 改造后所有相关 `_err` 的 `message` 为英文，可变量已移入 `details`；grep 确认 `ios_toolkit/` 无遗留面向用户的硬编码中文 `_err`（仅 `local_api_test.py` 的测试输入保留中文）

## 3. UI 本地化映射

- [x] 3.1 新增 `slide6_ui/common/errors.py: localize_error(error: dict) -> str`：`errors.<code>`(+details 插值) → `errors.kind.<kind>` → `error.message` → 通用未知错误，四级回退（新增 `i18n.has(key)` 辅助做存在性判断）
- [x] 3.2 在 `zh-CN.json` / `en-US.json` 新增 `errors` 命名空间：每个 `code` 一条 `errors.<CODE>`（占位符名与 `details` 字段一致）+ `errors.kind.<KIND>` 兜底 + `errors.unknown`
- [x] 3.3 将 UI 中展示 toolkit 错误的位置（`.get("error", {}).get("message")` 等读取点，共 29 处）改为经 `localize_error(...)` 渲染

## 4. 验证

- [x] 4.1 `i18n.validate()` 通过（占位符一致，问题列表为空）；模块字节编译与 `localize_error` 导入冒烟通过；grep 核对 toolkit `_err` 无残留面向用户中文、UI 无 `.get("message")` 直接展示点
- [x] 4.2 冒烟构造各 `code` 错误：zh-CN/en-US 分别显示中英文、`details`（family/path）插值正确；未映射 code → `errors.kind.<kind>` 回退、无 kind 映射 → 原始英文 `message`、无错误 → `errors.unknown`

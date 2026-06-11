# Tasks

## 1. 逻辑层（ios_toolkit，零 i18n）

- [x] 1.1 `device.py`：新增 `_run_diagnostics(target, fn)` 辅助——iOS<17 经 usbmux/lockdown、iOS17+ 经 `_get_rsd_from_tunneld` 打开 `DiagnosticsService`，tunnel 缺失复用 `_TunnelRequiredError`（→ `code=TUNNEL_REQUIRED`）
- [x] 1.2 `device.py`：实现 `device_restart` / `device_shutdown` / `device_sleep`（下发成功即返回，不轮询回执）
- [x] 1.3 `device.py`：实现 `diagnostics_battery` / `diagnostics_wifi` / `diagnostics_info` / `diagnostics_ioregistry`
- [x] 1.4 `device.py`：实现 `diagnostics_mobilegestalt`，将库 `DeprecationError` 兜底为 `code=MOBILEGESTALT_DEPRECATED`
- [x] 1.5 `toolkit_api.py`：为以上 8 个方法加薄包装（`_prepare_device_basic` + 统一 `_err`，含 `MOBILEGESTALT_DEPRECATED`）

## 2. UI 复用组件

- [x] 2.1 将 `developer_tools_tab._FeatureTile` 提升到 `slide6_ui/common/feature_tile.py`（签名/样式不变）
- [x] 2.2 `developer_tools_tab.py` 改为从 `common.feature_tile` 导入，回归冒烟

## 3. 诊断 Tab（slide6_ui/diagnostics）

- [x] 3.1 新增 `slide6_ui/diagnostics/diagnostics_tab.py`：`DiagnosticsTab`（`set_target`、未选设备禁用、`AsyncRunner`）
- [x] 3.2 两个 section（电源控制 / 诊断信息）各用一个 `FlowLayout` + `_FeatureTile` 卡片
- [x] 3.3 电源卡片：点击先 `QMessageBox.question`（本地化、默认否）二次确认，确认后下发
- [x] 3.4 信息卡片：查询后以只读弹窗（`QPlainTextEdit` + 格式化 JSON、可复制）呈现
- [x] 3.5 MobileGestalt 卡片：仅 iOS<17.4 创建（复用 `ddi_provider.parse_major_minor`）
- [x] 3.6 错误展示统一经 `localize_error`
- [x] 3.7 `slide6_ui/diagnostics/__init__.py` 导出 `DiagnosticsTab`

## 4. 主窗口集成

- [x] 4.1 `main_window.py`：导入并注册 `DiagnosticsTab`（`addTab` + `main_window.tab.diagnostics`）
- [x] 4.2 `main_window.py`：设备切换时 `diagnostics_tab.set_target(self.target)`

## 5. 国际化

- [x] 5.1 `zh-CN.json` / `en-US.json` 新增 `diagnostics.*`（tab 名、section 名、各卡片标题/描述、确认弹窗、结果弹窗标题、状态文案）
- [x] 5.2 新增诊断错误码文案：`errors.MOBILEGESTALT_DEPRECATED`（`TUNNEL_REQUIRED` 已存在则复用）
- [x] 5.3 `i18n.validate()` 通过（占位符一致、两语对齐）

## 6. 验证

- [x] 6.1 字节编译：`python -m py_compile` 覆盖新增/改动文件
- [x] 6.2 headless 冒烟：构造 `DiagnosticsTab`、模拟 <17.4 / ≥17.4 验证 MobileGestalt 卡片显隐、确认弹窗取消路径不发请求、信息弹窗可渲染
- [x] 6.3 `openspec validate add-diagnostics-tab --strict` 通过

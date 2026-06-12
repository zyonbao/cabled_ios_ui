## 1. 诊断 Tab：移除 tunnel 面板，改门控提示

- [x] 1.1 `diagnostics_tab.py`：删除顶部 tunnel 面板 UI（`tunnel_widget`/`tunnel_label`/`tunnel_btn`/`tunnel_stop_btn`/`tunnel_restart_btn`/`tunnel_refresh_btn`）及其在 `_build_ui` 中的创建
- [x] 1.2 删除 tunnel 相关 handler 与辅助方法（`_refresh_tunnel_panel`/`_set_tunnel_busy`/`_on_start_tunnel`/`_on_stop_tunnel`/`_on_restart_tunnel`/`_on_refresh_tunnel`/`_after_tunnel`）及 `_wire` 中对应连接
- [x] 1.3 调整 `set_target` / `on_tab_activated`：移除 `tunnel_widget` 可见性与 `_refresh_tunnel_panel` 调用，仅保留 `_refresh_features()` 的门控刷新
- [x] 1.4 `_refresh_features`：tunnel 缺失时除卡片置灰 + tooltip 外，底部状态栏给出“需先到开发者工具启动 XPC tunnel”的引导文案（新 i18n 键）
- [x] 1.5 清理 `diagnostics_tab.py` 中因移除而未使用的 import / 引用

## 2. 键鼠操作 Tab：移除模态与自动拉起，改非模态引导

- [x] 2.1 `keymouse_tab.py`：`select_device` 不再调用 `_gate_tunnel`；iOS 17+ tunnel 未启用时直接走非模态引导（overlay/状态），不自动拉起
- [x] 2.2 删除 `_gate_tunnel` 及其触发的 `tunnel.launch_tunneld` 自动拉起路径；按需精简/合并 `_after_tunnel`、`_tunnel_failed`
- [x] 2.3 统一经 `readiness.probe()` 输出引导：缺 tunnel → 提示去开发者工具启动 XPC tunnel 并挂载 DDI；缺 DDI → 提示去开发者工具挂载；RSD 不工作 → 提示重挂 DDI / 重启 tunnel（均非模态 overlay/状态）
- [x] 2.4 新增/调整对应 overlay/状态 i18n 文案（缺 tunnel 引导）
- [x] 2.5 清理 `keymouse_tab.py` 中因移除而未使用的 import / 引用

## 3. 主窗口：调整 sidebar Tab 顺序

- [x] 3.1 `main_window.py` `_build_ui`：将 `addTab` 顺序调整为 设备信息 / 相册 / 文件系统 / App 列表 / 描述文件 / Crash 报告 / 开发者工具 / 键鼠操作 / 诊断
- [x] 3.2 确认 `_on_tab_changed`/`_on_keymouse_tab`/`suppress_auto_focus` 等仍按对象引用工作（不依赖固定索引），重排后行为不变

## 4. i18n 文案

- [x] 4.1 `zh-CN.json`：新增诊断 tunnel 缺失引导键、键鼠缺 tunnel 引导键；移除/保留不再使用的键（如 `keymouse.tunnel_need.*` 等模态文案按需清理）
- [x] 4.2 `en-US.json`：与 zh-CN 同步增改，保持键集一致

## 5. 验证

- [x] 5.1 运行 lint（ReadLints）确认 diagnostics/keymouse/main_window 无未使用引用与报错
- [ ] 5.2 手动验证：iOS 17+ 设备 tunnel 未启用时，诊断卡片置灰并提示去开发者工具、键鼠 overlay 引导且无任何模态框；在开发者工具启动 tunnel 后，切回诊断/键鼠自动可用
- [ ] 5.3 手动验证：sidebar 顺序为 开发者工具 → 键鼠操作 → 诊断，且 tunnel 启停/重启仅在开发者工具出现
- [x] 5.4 `openspec validate unify-tunnel-entry-reorder-tabs --strict` 通过

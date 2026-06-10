# Tasks

## 1. 共享就绪前置检查

- [ ] 1.1 新增 `slide6_ui/common/readiness.py`：按 iOS 版本检查 tunnel/DDI/RSD，返回结构化结果（缺失项 + 引导文案 + 建议动作）；耗时探测经 `AsyncRunner`
- [ ] 1.2 RSD 服务可用性探测：复用 `ddi_wait_ready` 思路或轻量探测，必要时缓存最近结果避免频繁阻塞

## 2. tunnel 单次授权重启 + 控制入口

- [ ] 2.1 `tunnel.py` 重写 `restart_tunneld()`：单条 osascript（同一 `with administrator privileges`）内 `lsof+kill`（-9 兜底）+ `nohup <tunneld cmd> &` 后台重启；返回后普通权限轮询端口；命令仍由固定内部路径构成、校验入口、不插外部输入
- [ ] 2.2 验证后台子进程在 osascript 返回后存活；不存活则回退 stop+launch 两次授权并记日志

## 3. 开发者工具：tunnel 面板（6.1）

- [ ] 3.1 顶部 tunnel 区块仅 iOS 17+ 可见；按 `is_tunnel_running()` 动态显示「未启动/已启动」
- [ ] 3.2 未启动→「启动」；已启动→「停止」+「重启」；三者经 `AsyncRunner` 调 `tunnel.launch/stop/restart`，操作中禁用按钮 + 状态提示；完成后刷新面板状态

## 4. 开发者工具：就绪门控（7）

- [ ] 4.1 进程 / 定位功能位点击前调用 readiness；未通过则按缺失项给引导（状态栏 + 必要时 QMessageBox）
- [ ] 4.2 iOS 17- 缺 DDI 的引导提供 reload 按钮（重新检查 + 刷新状态）
- [ ] 4.3 `keymouse_tab.py` 接入 readiness：在 `select_device` / 进入流程中补 DDI / RSD 检查与引导（保留现有 `_gate_tunnel`）

## 5. 开发者工具：文案不撑宽（5）

- [ ] 5.1 底部 status label 水平 `QSizePolicy` 设为不向外推；超 3 行用 `QFontMetrics.elidedText` 尾部省略；完整文案进 tooltip
- [ ] 5.2 `resizeEvent` 时按当前宽度重算省略

## 6. 子功能弹窗非模态（8）

- [ ] 6.1 `ProcessDialog` / `LocationDialog` 由 `.exec()` 改 `.show()` + `setModal(False)` + `WA_DeleteOnClose`
- [ ] 6.2 tab 持有打开窗口引用列表，关闭时移除；`shutdown` 统一关闭所有子窗口

## 7. 验证

- [ ] 7.1 lint 无误 + 导入冒烟
- [ ] 7.2 真机手验（iOS 17+）：重启 tunnel 仅一次密码；tunnel 面板启动/停止/重启状态正确；缺 DDI/缺 tunnel/RSD 不工作分别给出正确引导；键鼠缺 DDI 有引导
- [ ] 7.3 真机手验（iOS 17-）：不显示 tunnel 面板；缺 DDI 引导带 reload
- [ ] 7.4 回归：底部长文案不撑宽窗口、窗口缩放重排；可同时打开进程管理与虚拟定位多个窗口、退出全部关闭

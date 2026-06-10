# Tasks

## 1. 共享就绪前置检查

- [x] 1.1 新增 `slide6_ui/common/readiness.py`：按 iOS 版本检查 tunnel/DDI/RSD，返回结构化结果（缺失项 + 引导文案 + 建议动作）；耗时探测经 `AsyncRunner`。提供纯逻辑 `evaluate()`（用已知状态判定，无 I/O）与阻塞 `probe()`（补查 DDI/RSD）两个入口
- [x] 1.2 RSD 服务可用性探测：新增平台 API `rsd_service_available`（device.py + toolkit_api.py），连 `RemoteServiceDiscoveryService` 读 `peer_info["Services"]` 查 `com.apple.dt.testmanagerd.remote` 是否存在（仅 XPC 握手、无 DVT，远轻于 `ddi_wait_ready`）

## 2. tunnel 单次授权重启 + 控制入口

- [x] 2.1 `tunnel.py` 重写 `restart_tunneld()`：单条 osascript（同一 `with administrator privileges`）内 `lsof+kill`（-9 兜底）+ **前台**运行 tunneld（**非** `nohup … &`，否则授权返回时后台子进程被特权 helper 回收→kill 成功但拉不起来）；launch/restart 共用 `_spawn_foreground_tunneld()`（Popen 不等待 + 轮询端口），restart 仅多带 `_kill_tunneld_shell()` 前缀；命令仍由固定内部路径构成、校验入口、不插外部输入
- [x] 2.2 端口超时/授权取消**仅记 WARNING 并返回 False**（UI 提示手动重试），不自动回退到两次授权

## 3. 开发者工具：tunnel 面板（6.1）

- [x] 3.1 顶部 tunnel 区块仅 iOS 17+ 可见（`tunnel_widget`）；`_refresh_tunnel_panel()` 按 `is_tunnel_running()` 动态显示「未启动/已启动」
- [x] 3.2 未启动→「启动」；已启动→「停止」+「重启」；三者经 `AsyncRunner` 调 `tunnel.launch/stop/restart`，`_set_tunnel_busy()` 操作中禁用按钮 + 状态提示；完成后 `_refresh_tunnel_panel()` 刷新

## 4. 开发者工具：就绪门控（7，禁用式）

- [x] 4.1 进程 / 定位功能位按 `readiness.evaluate()`（用 tab 已知的 `_mounted`/`_dvt_ready` + `is_tunnel_running()`）置 **enabled/disabled**；未就绪时 disabled + tooltip 说明缺失项；设备切换、tunnel 操作完成、DDI/DVT 状态变化（含 `_on_rsd_probe`）时调 `_refresh_features()` 重算
- [x] 4.2 iOS 17- 缺 DDI：功能位 disabled + tooltip 引导挂载；顶部「刷新状态」按钮始终可用充当 reload（重新检查 + 刷新状态/按钮态）
- [x] 4.3 `keymouse_tab.py` 接入 readiness：tunnel 确认（或无需）后经 `_check_readiness` → `readiness.probe` 补 DDI / RSD 检查；缺失时 overlay 引导（挂载 DDI / 重启 tunnel），保留现有 `_gate_tunnel`

## 5. 开发者工具：文案不撑宽（5）

- [x] 5.1 底部 status label 水平 `QSizePolicy(Ignored, Preferred)` 不向外推；`_set_status()` 存原文 + tooltip，`_elide_status()` 贪心折成 ≤3 行、第 3 行 `QFontMetrics.elidedText` 尾省略
- [x] 5.2 `resizeEvent` 调 `_elide_status()` 按当前宽度重算省略

## 6. 子功能弹窗非模态 + 每子功能单例（8）

- [x] 6.1 `_open_subwindow()` 统一以 `.show()` + `setModal(False)` + `WA_DeleteOnClose` 打开 `ProcessDialog` / `LocationDialog`
- [x] 6.2 tab 持有 `_subwindows{功能名: dialog}` 映射：已有窗口则 `raise_()`+`activateWindow()` 前置（不新开），`destroyed` 时移除；不同子功能可并存；`shutdown` 统一 `close()` 所有子窗口

## 7. 验证

- [x] 7.1 lint 无误 + 导入冒烟（6 个改动模块全部 import OK；仅 `..syslog` 为既有 basedpyright 路径告警，运行期正常）
- [x] 7.2 真机手验（iOS 17+）：重启 tunnel 仅一次密码（kill+前台重启同一授权，修正早先 nohup 后台被回收的问题）；tunnel 面板状态正确；RSD 探测不确定时不误报缺失（超时放宽 12s + 宽容判定）
- [x] 7.3 真机手验（iOS 17-）：不显示 tunnel 面板；缺 DDI 引导带 reload
- [x] 7.4 回归：底部长文案不撑宽窗口、窗口缩放重排；可同时打开进程管理与虚拟定位多个窗口、退出全部关闭

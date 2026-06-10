## Context

- 现有 `slide6_ui/common/tunnel.py`：`launch_tunneld()`（Popen 不等待、轮询端口）、`stop_tunneld()`（osascript 提权 `lsof+kill`）、`restart_tunneld()` = stop + launch = **两次授权**。`is_tunnel_running()` 探端口。
- `developer_tools_tab.py`：顶部 `tunnel_widget` 仅有「启动 XPC tunnel」单按钮，对 `needs_tunnel` 设备 `setVisible`；底部 `status` 是 `QLabel(wordWrap=True)`，长文案会撑宽窗口；进程 / 定位子功能用 `ProcessDialog(...).exec()` / `LocationDialog(...).exec()`（模态）。已有 `ddi_wait_ready` DVT 就绪探测。
- `keymouse_tab.py`：`select_device` 已对 iOS 17+ 做 `_gate_tunnel`（缺 tunnel 时弹窗启动），但未显式检查 DDI 挂载 / RSD 服务可用，缺 DDI 时直接 WDA 失败。
- iOS 17+ WDA 依赖 `com.apple.dt.testmanagerd.remote`（DDI 挂载后才暴露，且需 tunnel 重新枚举 RSD）；进程/定位依赖 `dtservicehub`（DVT）。

## Goals / Non-Goals

**Goals:**
- 抽出统一就绪前置检查助手，键鼠 / 开发者工具共用，条件不满足时给出**可操作引导**（去挂 DDI / 启用或重启 tunnel / reload）而非直接失败。
- tunnel 状态面板仅 iOS 17+ 展示，提供启动 / 停止 / 重启。
- 重启 tunnel 仅一次系统授权。
- 开发者工具底部文案不撑宽窗口（3 行省略）。
- 子功能弹窗非模态，可同时多开。

**Non-Goals:**
- 不改 DDI 挂载本身的流程（沿用现有）。
- 不改 tunnel 的安全约束（仍是固定路径 + 原生授权、绑定 127.0.0.1）。
- 不做 tab 切换聚焦 / 路径栏统一（Change C）；不做日志重构（Change A）。

## Decisions

1. **共享就绪助手 `slide6_ui/common/readiness.py`**：暴露纯逻辑的检查函数，返回结构化结果（哪一项缺失、对应引导文案与建议动作），不直接弹窗——由各调用方决定用 `QMessageBox` 还是状态栏呈现。检查矩阵：
   - iOS 17+：`tunnel_ready`（`is_tunnel_running`）、`ddi_mounted`（`api.ddi_status` 或乐观挂载态）、`rsd_service_ok`（目标 RSD 服务存在 / `ddi_wait_ready` 类探测）。
   - iOS 17-：`ddi_mounted`。
   - 缺失项 → 文案：缺 tunnel「请启用 XPC tunnel」；缺 DDI「请到开发者工具根 tab 挂载 DDI」；tunnel+DDI 均就绪但 RSD 服务不工作「请重新挂载 DDI 或重启 XPC tunnel」。
2. **就绪检查接入点**：开发者工具的进程 / 定位功能位点击前、键鼠操作 `select_device`/进入时各调用助手；不满足则呈现引导（开发者工具用状态栏 + 必要时弹窗；键鼠沿用现有 overlay/弹窗）。iOS 17- 的 DDI 引导附带「reload」按钮（重新检查并刷新状态）。
3. **tunnel 面板（6.1）**：把开发者工具顶部 `tunnel_widget` 改为仅 iOS 17+ 可见的状态行：动态显示「未启动 / 已启动」，按状态切换按钮组——未启动=「启动」；已启动=「停止」+「重启」。三者复用 `tunnel.launch/stop/restart`，经 `AsyncRunner` 执行，操作期间禁用按钮。
4. **单次授权重启（6.2）**：`tunnel.restart_tunneld()` 重写为构造**单条** osascript：在一个 `do shell script ... with administrator privileges` 内先 `lsof -ti tcp:PORT | kill`（含 -9 兜底），再以 `nohup <tunneld cmd> >log 2>&1 &` 后台重启，使 osascript 立即返回；随后在普通权限下轮询端口就绪（复用 `launch_tunneld` 的轮询逻辑）。命令仍只由固定内部路径构成、校验入口存在、不插入任何外部输入。
5. **文案不撑宽（5）**：开发者工具底部状态文案改为固定 / 受限宽度，水平 `QSizePolicy` 设为 `Ignored`/`Minimum` 使其不向外推；超 3 行按字符或 `QFontMetrics.elidedText` 对尾部省略；`resizeEvent` 时按当前宽度重算省略。保留完整文案于 tooltip。
6. **非模态弹窗（8）**：`ProcessDialog` / `LocationDialog` 由 `.exec()` 改 `.show()`，设 `setModal(False)` 与 `Qt.WA_DeleteOnClose`，由 tab 持有引用列表防止被 GC、并在关闭时移除；`shutdown` 时统一关闭。允许同设备开多个窗口（各自独立 runner 调用）。

## Risks / Trade-offs

- **单次授权重启的后台化**：`nohup ... &` 在 root shell 下后台运行 tunneld，需确认 osascript 返回后进程存活（与现 `launch_tunneld` 的 Popen 不等待行为等价）。若个别环境后台子进程随 shell 退出被回收，回退为 `launch_tunneld` 现状（两次授权）并记日志。
- **就绪检查的 RSD 探测成本**：`rsd_service_ok` 若每次点击都重探可能有延迟；用轻量探测（沿用 `ddi_wait_ready` 思路或缓存最近结果），避免阻塞 UI（仍走 AsyncRunner）。
- **非模态弹窗的并发**：多个窗口对同一设备并发 DVT 调用需各自经 AsyncRunner，不共享可变状态；定位会话等全局副作用需注意（清除定位是全局动作）——在文案上提示用户。
- 跨 Change 触及 `slide6-developer-tools`（与 Change A 同时修改不同 requirement，无冲突）。

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

1. **共享就绪助手 `slide6_ui/common/readiness.py`**：暴露纯逻辑的检查函数，返回结构化结果（哪一项缺失、对应引导文案与建议动作），不直接弹窗——由各调用方决定用按钮禁用 + tooltip、`QMessageBox` 还是状态栏呈现。检查矩阵：
   - iOS 17+：`tunnel_ready`（`is_tunnel_running`）、`ddi_mounted`（`api.ddi_status` 或乐观挂载态）、`rsd_service_ok`。
   - iOS 17-：`ddi_mounted`。
   - **`rsd_service_ok` 探测方式（已定）**：查 tunnel 的 RSD 服务列表里目标服务（`com.apple.dt.testmanagerd.remote` 等）是否存在——这是轻量、无副作用的探测，直接对应「键鼠失效=tunnel RSD 列表里 testmanagerd.remote 缺失」的真实症结；**不**做 `ddi_wait_ready` 那类偏重的 DVT 握手。
   - 缺失项 → 文案：缺 tunnel「请启用 XPC tunnel」；缺 DDI「请到开发者工具根 tab 挂载 DDI」；tunnel+DDI 均就绪但 RSD 服务不工作「请重新挂载 DDI 或重启 XPC tunnel」。
2. **就绪检查接入点（已定：禁用式门控）**：开发者工具的进程 / 定位功能位**默认按就绪结果置 enabled/disabled**；未就绪时按钮 disabled，tooltip 说明缺什么（缺 tunnel / 缺 DDI / RSD 不工作的具体文案），而非状态栏引导或点击弹窗。就绪状态在设备切换、tunnel 面板操作完成、DDI 状态变化时重算并刷新按钮态。键鼠操作 `select_device`/进入时调用助手，沿用现有 overlay/弹窗引导（缺 tunnel 仍走现有 `_gate_tunnel`，补 DDI/RSD 检查与引导）。iOS 17- 的 DDI 引导附带「reload」按钮（重新检查并刷新状态/按钮态）。
3. **tunnel 面板（6.1）**：把开发者工具顶部 `tunnel_widget` 改为仅 iOS 17+ 可见的状态行：动态显示「未启动 / 已启动」，按状态切换按钮组——未启动=「启动」；已启动=「停止」+「重启」。三者复用 `tunnel.launch/stop/restart`，经 `AsyncRunner` 执行，操作期间禁用按钮。
4. **单次授权重启（6.2）**：`tunnel.restart_tunneld()` 重写为构造**单条** osascript：在一个 `do shell script ... with administrator privileges` 内先 `lsof -ti tcp:PORT | kill`（含 -9 兜底），再在**前台**运行 `<tunneld cmd> >log 2>&1`（**不**用 `nohup … &` 后台化）；该 osascript 经 `subprocess.Popen` 启动且**不等待**（前台守护会持续占用 do-shell-script），随后在普通权限下轮询端口就绪。launch 与 restart 共用同一套「前台守护 + Popen 不等待 + 轮询端口」逻辑（`_spawn_foreground_tunneld`），restart 只是多带一个 kill 前缀。**关键修正**：早先尝试用 `nohup … &` 后台化失败——`do shell script ... with administrator privileges` 返回时，本次授权 fork 出的后台子进程会被特权 helper 回收，导致「kill 成功但新 tunnel 拉不起来」；改回前台运行即可存活（与 `launch_tunneld` 行为一致）。命令仍只由固定内部路径构成、校验入口存在、不插入任何外部输入。**回退策略（已定）**：若端口轮询超时/授权取消，**不自动回退到 stop+launch 两次授权**，仅记 WARNING 日志并在 UI 提示用户手动重试。
5. **文案不撑宽（5）**：开发者工具底部状态文案改为固定 / 受限宽度，水平 `QSizePolicy` 设为 `Ignored`/`Minimum` 使其不向外推；超 3 行按字符或 `QFontMetrics.elidedText` 对尾部省略；`resizeEvent` 时按当前宽度重算省略。保留完整文案于 tooltip。
6. **非模态弹窗 + 每子功能单例（8，已定）**：`ProcessDialog` / `LocationDialog` 由 `.exec()` 改 `.show()`，设 `setModal(False)` 与 `Qt.WA_DeleteOnClose`。**每个子功能同时只允许一个窗口**：tab 持有 `{功能名: dialog}` 映射，点击某子功能时若其窗口已存在则 `raise_()` + `activateWindow()` 把现有窗口前置（不新开）；窗口关闭时从映射移除。不同子功能（进程管理 / 虚拟定位）可各开一个、并存。`shutdown` 时统一关闭所有子窗口。该单例约束同时消解了虚拟定位「清除是全局动作」的并发副作用顾虑（不会有两个定位窗口互相干扰）。

## Risks / Trade-offs

- **单次授权重启需用前台守护**：`do shell script ... with administrator privileges` 返回时会回收本次授权 fork 出的后台子进程，因此 restart 的 relaunch **必须前台运行**（osascript 用 Popen 不等待托住它），与 `launch_tunneld` 一致；不可用 `nohup … &` 后台化（会被回收 → kill 成功但拉不起来）。端口轮询超时/取消时**仅记 WARNING + 提示手动重试**（不自动二次弹密码）。
- **就绪检查的 RSD 探测**：`rsd_service_ok` 改为查 tunnel RSD 服务列表（轻量、无副作用），避免 `ddi_wait_ready` 的握手开销；探测仍经 AsyncRunner，不阻塞 UI。
- **每子功能单例**：同子功能再次点击前置已有窗口而非新开，天然避免对同一设备的并发可变状态/全局副作用（如清除定位）；不同子功能可并存，各自经 AsyncRunner。
- 跨 Change 触及 `slide6-developer-tools`（与 Change A 同时修改不同 requirement，无冲突）。

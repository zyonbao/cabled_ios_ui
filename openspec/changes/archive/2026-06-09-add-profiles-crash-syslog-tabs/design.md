## Context

`slide6_ui` 是基于 PySide6 的桌面应用，所有阻塞型设备操作通过 `ios_toolkit.toolkit_api`（同步 `{ok, data}` 信封）调用，再经由 `AsyncRunner`（`QThreadPool` + generation 守卫）派发到工作线程，结果通过 Qt 信号回到主线程。`ios_toolkit/device.py` 内部维护一个常驻 daemon 线程上的 asyncio 事件循环 `_bg_loop`，所有 `pymobiledevice3` 协程通过 `asyncio.run_coroutine_threadsafe(coro, _bg_loop)` 执行，且普遍采用「每请求一条短连接 lockdown」的模式（见 `_with_afc` / `list_apps`）。

本变更新增三类能力，均不依赖 WDA / XPC tunnel：

- 描述文件：`pymobiledevice3.services.mobile_config.MobileConfigService`（`get_profile_list` / `install_profile(bytes)` / `remove_profile(identifier)`）。
- Crash：`pymobiledevice3.services.crash_reports.CrashReportsManager`（`ls(path, depth)` / `pull(...)` / `clear(path)`，基于 AFC2）。
- 系统日志流：`SyslogService.watch()`（传统 syslog，产出字符串行）与 `OsTraceService.syslog()`（结构化 `SyslogEntry`，含 pid/subsystem/category/level）。两者均为 `LockdownService`，免 tunnel。

已确认环境 `pymobiledevice3==9.16.0` 包含上述全部模块。

## Goals / Non-Goals

**Goals:**

- 在「App 列表」Tab 内提供描述文件管理对话框：列表 + 拖拽/点击安装 + 多选移除。
- 新增独立「Crash 报告」Tab：列表 + 多选/右键导出与删除 + 导出可选保留原文件。
- 新增独立「系统日志」Tab：syslog/oslog 下拉切换、实时流、关键字过滤、暂停/清空/另存。
- toolkit_api 新增请求/响应函数（描述文件、crash）与流式订阅接口（日志），沿用既有信封与线程模型。
- 流式日志采用后台线程采集 + 主线程限速渲染，避免高吞吐刷爆 UI。

**Non-Goals:**

- 不实现描述文件的静默安装 / 监管（escalate / supervise / keybag）能力。
- 不解析 crash 文件内容（只做列表 / 导出 / 删除；不做符号化）。
- 不实现 DVT/instruments 级别的 os_log 高级过滤（仅 `os_trace` 的基础结构化流 + 关键字过滤）。
- 不新增 JSON CLI 子命令（本变更面向桌面应用进程内调用；流式接口本就不适合一次性 CLI 信封）。
- 不改动现有 Tab、WDA/tunnel 生命周期与既有 toolkit_api 函数。

## Decisions

### 决策 1：描述文件入口放在「App 列表」Tab 的对话框，而非独立 Tab

`TODO.md` 将「描述文件 + App 管理」归并为同一定位，用户也明确要求「放在 App list 页面单独加一个按钮」。因此在 `AppManagerTab` 工具栏新增「描述文件…」按钮，弹出 `ProfilesDialog`（`QDialog`）。对话框内部复用 `AsyncRunner`（由 `AppManagerTab` 透传）与 `get_target`。

- **替代方案**：独立 Tab。被否决，因为描述文件管理低频，独立 Tab 会稀释导航；且与 App 管理同属「安装到设备的可信负载」语义，合并更自然。

### 决策 2：Crash 与 Syslog 各为独立 Tab，在 `MainWindow._build_ui` 注册

Crash 与日志是高频排障入口，且交互复杂（多选/右键/流控），适合独立 Tab。注册顺序建议置于「文件系统」之后、「键鼠操作」之前，保持「信息/管理在前、重 WDA 在后」的既有约定。两者均实现 `set_target(target)`，由 `MainWindow.on_select_device` 统一分发。

### 决策 3：toolkit_api 请求/响应函数沿用短连接模式

描述文件与 crash 操作天然是请求/响应，直接复用 `_prepare_device_basic` + `_bg_loop` + 短连接 lockdown：

- `list_profiles(target)` / `install_profile(target, path)` / `remove_profile(target, identifier)`
- `list_crashes(target)` / `pull_crash(target, remote, local)` / `clear_crash(target, remote)`

返回信封示例：
- `list_profiles` → `data = {"profiles": [{"identifier","name","type","organization","payloadCount"}, ...]}`
- `list_crashes` → `data = {"entries": [{"name","isDir","size","mtime"}, ...]}`（结构与 `afc_list` 对齐，便于 UI 复用多选/导出模式）。

crash 的删除使用 `CrashReportsManager.clear(path)`（按相对路径删除单项）；导出使用 `pull(out, entry, erase=...)`。`pull` 自带 `erase` 标志，可在导出成功后原子删除原文件，因此 UI 的「不保留原文件」= `pull_crash(erase=True)`（一步完成），无需「先 pull 再 clear」；`clear_crash` 仍保留用于纯删除场景。注意 `ls(path, depth)` 仅返回名称列表，大小 / 时间需对每项额外 `stat`（经其内部 AFC）。

### 决策 4：日志流采用「QThread 直连 + Qt 信号 + 限速渲染」，不经 AsyncRunner

`AsyncRunner` 面向一次性结果，不适合持续流。参考 `mirror.py` 的 `MjpegThread(QThread)` 模型，新增 `SyslogStreamThread(QThread)`：

- 线程内创建并运行自己的 asyncio 事件循环，`async for line in service.watch()`（syslog）或 `async for entry in OsTraceService(...).syslog()`（oslog）。
- 每行/条目通过 `line_ready = Signal(str)` 跨线程投递（Qt 自动队列化）。
- 主线程侧用「批量缓冲 + `QTimer` 周期 flush（如每 100ms）」做限速渲染，单次最多追加 N 行，超出上限的旧行从顶部裁剪（环形/上限行数，如 5000 行），防止内存与重绘失控。
- 「暂停」= 停止 flush（缓冲继续丢弃或保留可配，默认丢弃以免堆积）；「清空」= 清空缓冲与视图；「另存」= 将当前视图文本写入用户选择的 `.log` 文件。
- 切换 syslog/oslog 或设备 = 停止并 `wait()` 当前线程，重建新线程。

**最终实现（已落地）**：在 `device.py` 暴露 `iOSDevice.open_log_stream(source)` → `LogStreamHandle`。该 handle 通过 `asyncio.run_coroutine_threadsafe` 在共享 `_bg_loop` 上调度一个消费协程：协程 `async for` 迭代所选来源的异步生成器（syslog 走 `SyslogService.watch()`，oslog 走 `OsTraceService.syslog()` 经 `_format_oslog_entry` 格式化），把文本行推入一个有界的线程安全 `queue.Queue`；出错 / 自然结束时推入 `(ERROR, msg)` / `(EOF, None)` 哨兵。`close()` 经 `call_soon_threadsafe` 取消协程，连接随 `async with` 退出释放。

UI 侧 `SyslogStreamThread(QThread)` 仅阻塞读取该队列并以 `line_ready` / `stream_error` 信号上抛（参考 `mirror.py`），主线程做缓冲 + `QTimer` 限速 flush + 上限裁剪。

- **为什么用 `_bg_loop` + 队列而非 QThread 内独立事件循环**：所有设备 I/O 统一在唯一事件循环上（与 `device.py` 其余请求/响应一致），UI 层完全不直接接触 `pymobiledevice3`；有界队列天然提供背压（满则丢弃旧行而非阻塞采集）；`close()` 取消干净。
- **替代方案 A**：`SyslogStreamThread.run()` 内自建 asyncio 循环直连 pymobiledevice3（与 mirror 读 MJPEG 端口同构）。可行但会出现第二个事件循环触达 usbmux，且把设备依赖泄漏到 UI 层，故未采用。
- **替代方案 B**：轮询。被否决：syslog 本质是推流，轮询不可行。

### 决策 5：关键字过滤在渲染侧做，采集侧不丢数据

过滤为大小写不敏感子串匹配（首版），在主线程 flush 时对缓冲行应用。过滤条件变化时对「当前已缓冲的全量行」重新套用，不影响后台采集。后续可演进为正则。

### 决策 6：UI 复用既有多选 / 导出 / 二次确认范式

- Crash 列表用 `QTableWidget`（列：名称 / 大小 / 时间）+ `ExtendedSelection` + `setContextMenuPolicy(CustomContextMenu)` 右键菜单，多选导出沿用 `DcimAlbumTab._export_selected` 的「选目录 + 逐项 pull + 汇总」模式。
- 描述文件列表同样用 `QTableWidget` + 多选；安装拖拽复用 `AppManagerTab` 的 `dragEnterEvent/dropEvent` 校验（扩展名 `.mobileconfig`）。
- 删除 / 移除 / 不保留导出统一 `QMessageBox.question` 二次确认。

## Risks / Trade-offs

- [描述文件安装需设备端手动确认] → UI 在发起安装后明确提示「请在设备『设置』中确认安装」，并将 `install_profile` 的返回视为「已下发」而非「已安装」。
- [受监管/MDM 描述文件移除被拒] → 捕获服务异常并在状态栏回显原因，不视为崩溃。
- [Crash 列表可能为嵌套目录/海量条目] → `CrashReportsManager.ls(depth=1)` 仅列顶层；导出/删除按名称逐项处理；大列表通过表格虚拟化（Qt 默认）承载。
- [日志高吞吐刷爆 UI] → 后台采集 + `QTimer` 限速 flush + 上限行数裁剪 + 暂停开关多重防护（参考 mirror 线程模型）。
- [oslog 在低版本/特定设备行为差异] → 默认下拉为 `syslog`（最稳）；`oslog` 失败时通过 `stream_error` 信号在状态栏提示并停止，不影响应用其余功能。
- [流线程未干净退出导致 lockdown 连接泄漏] → 切换/关闭时 `requestInterruption()` + 停止内部 loop + `wait()`；`MainWindow.closeEvent` 主动停止日志线程。
- [敏感信息落盘] → 仅在用户显式「另存」时写文件；不自动持久化日志；不记录任何凭据（遵循安全基线第 4 条）。

## Migration Plan

- 纯增量：新增模块与两个 Tab、一个按钮、若干 toolkit_api 函数，不改动既有契约与数据。
- 回滚：移除新增 Tab 注册、按钮与新增模块即可，无数据迁移。
- 分阶段落地建议：先 toolkit_api 契约 + 描述文件（最简）→ Crash Tab（复用导出范式）→ 系统日志流（新增线程模型，最复杂）。

## Open Questions（已确认决策）

- 日志「暂停」语义：**已确认默认丢弃暂停期间新行**（恢复后仅显示新日志，内存零堆积）。
- Crash 列表列：**已确认展示 名称 / 大小 / 时间 三列**（逐项 `stat`），接受文件多时的额外加载耗时。
- 实施 / 提交方式：**已确认单一变更内按顺序全部实现**（契约层 → 描述文件 → Crash → 日志流）。
- 仍待真机校验（非阻塞）：oslog 是否需按 pid/subsystem 预过滤（首版仅关键字子串过滤）；描述文件列表展示字段以 `get_profile_list` 实际返回为准，安装 / 移除标识符字段在实现期对真机校验。

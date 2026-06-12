# 设计：主机配对（Pair / Unpair）

## 背景与约束

- 配对记录（pair record）是 lockdown 会话的信任凭据。macOS 上的**权威存储是 usbmuxd**；`pymobiledevice3` 读取顺序为 `usbmuxd → iTunes → 本地缓存目录`（见 `pair_records.get_preferred_pair_record`）。
- 本机的所有其它 lockdown 连接均以 `autopair=False` 打开，绝不在别处触发自动配对；配对/取消配对只能由本功能显式发起。
- 安全基线：配对走 usbmux + lockdown 标准流程，证书/私钥由 `pymobiledevice3` 生成；不记录、不打印任何密钥或证书原文。

## 坑位记录（重要 —— 避免后续重复踩坑）

### 坑 1：`create_using_usbmux(autopair=False)` 仍会校验配对，且陈旧记录会抛异常

- `create_using_usbmux` 内部总是调用 `_handle_autopair`，而 `_handle_autopair` **无论 `autopair` 真假都先 `validate_pairing()`**。
- 当设备上残留一条**已失效的主机配对记录**时，`validate_pairing()` 在 `StartSession` 后做 SSL 握手会被设备直接断开（SSL EOF）。
- **`pymobiledevice3` 的 bug**：`validate_pairing()` 只 `except SSLZeroReturnError`（本意是"记录已在设备端移除→视为未配对，返回 False"），但底层 `ServiceConnection.ssl_start` 已把 `SSLZeroReturnError` **重新包装成 `ConnectionTerminatedError`**，于是那个 `except` 捕获不到，异常直接抛穿 `create_using_usbmux`。
- 后果：连接创建阶段就崩溃，**根本到不了 `lockdown.pair()`**——用户点"配对"、手机点"信任"都没用，因为我们压根没发出 Pair 请求。
- **对策**：不走 `create_using_usbmux`，自己按它的步骤手搓 lockdown 客户端（`ServiceConnection.create_using_usbmux` + 选 `PlistUsbmuxLockdownClient` + `_initialize()`），**跳过 `_handle_autopair`**。这样可以由我们自己决定何时 validate、何时 pair。封装为 `_open_lockdown_no_autopair()`。

### 坑 2：写本地配对记录 `~/.pymobiledevice3/<udid>.plist` 报 Permission denied

- `pymobiledevice3` 默认把缓存记录写到 `~/.pymobiledevice3/`。该目录里常残留**早期 `sudo` 运行留下的、属主为 root** 的 plist；非 root 进程无法覆盖写它们，`pair()` 末尾 `save_pair_record()` 抛 `PermissionError`（设备端其实已配对成功，只是写本地缓存失败）。
- **对策（两层）**：
  1. 把缓存目录改到应用自己的数据目录 `~/Library/CablediOS/PairingRecords`（常量 `_PAIRING_RECORDS_DIR`，与日志、DDI 同级约定），从源头避开被污染的共享目录。
  2. 兜底：`pair()` 前调用 `_clear_unwritable_pair_cache()`——若当前设备的缓存文件存在且当前用户不可写就先删除（目录归用户所有，删 root 文件是允许的），让 `pair()` 能写出归当前用户所有的新记录。

### 坑 3：usbmuxd 优先级会"遮蔽"本地新记录

- 由于读取顺序 usbmuxd 优先，若只写本地缓存目录，陈旧的 usbmuxd 记录会继续被优先采用。
- **好在** `PlistUsbmuxLockdownClient.save_pair_record()` 在写本地缓存的同时也会 `SavePairRecord` 回 usbmuxd，因此用 `PlistUsbmuxLockdownClient` 配对成功后，会用新记录**覆盖** usbmuxd 里的旧记录，后续 validate 即可成功。手搓客户端时必须选到 `PlistUsbmuxLockdownClient`（usbmuxd 支持 Plist 协议时）。

### 坑 4：unpair 不需要 SSL，但 `create_using_usbmux` 同样会因坑 1 崩

- `unpair()` 只发一个 `Unpair` 请求（`verify_request=False`），不需要 SSL 握手，本可在未 validate 的情况下完成。
- **对策**：同样用 `_open_lockdown_no_autopair()`，再 `fetch_pair_record()` 手动取记录后 `unpair()`，绕开会崩的 validate。

### 坑 5：探测配对状态时把 SSL EOF 当作"未配对"

- 探测（`_probe_paired_async`）里自己调用 `validate_pairing()`，并捕获 `ConnectionTerminatedError` / `ssl.SSLError`，按 `pymobiledevice3` 的**本意**判定为"未配对"（而非报错），让用户可以重新发起配对。

### 坑 6：未配对设备触发依赖配对的请求 → 满屏 `NotPairedError`

- 选择设备后若立刻给所有 tab `set_target()`，会对 app/profiles/crash/afc/ddi/diagnostics 等依赖配对的服务发起请求，未配对时全部 `NotPairedError`，再被 asyncio 以 "Future exception was never retrieved" 打成 traceback。
- **对策**：依赖配对的 tab **只在确认配对后**才下发真实 target，未确认时一律清空（`""`）。由配对状态广播统一驱动（`_apply_gated_targets`）。`list_targets` 里也先判配对、未配对则跳过 WDA 探测。

### 坑 7：非活动 tab 劫持共享顶栏状态

- 键鼠 tab 的 `select_device(active=False)` 在设备 `state != online` 时会无条件往**共享顶栏状态**写「未安装WDA」，即使当前根本不在键鼠 tab，导致配对完成后顶栏仍误报。
- **对策**：键鼠 tab 仅在自己是活动 tab 时才写共享状态；非活动的延迟选择只更新自己 tab 内蒙版。

## toolkit 层接口

- `iOSDevice.pairing_state() -> {paired: bool}`：基于 `_probe_paired_async`（手搓客户端 + 自管 validate + SSL EOF 容错）。
- `iOSDevice.pair()`：`_clear_unwritable_pair_cache()` → 手搓客户端 `lockdown.pair()`（设备弹信任、阻塞至响应）→ 由 `PlistUsbmuxLockdownClient.save_pair_record` 写回 usbmuxd → 干净连接复核状态。给出足够超时（用户需在设备上物理确认）。
- `iOSDevice.unpair()`：手搓客户端 `fetch_pair_record()` → `unpair()`。
- `toolkit_api` 暴露同步包装 `pairing_state` / `pair_device` / `unpair_device`，沿用统一 `_ok` / `_err` 结果约定。
- 所有方法带 `logging` 便于排障（不打印密钥/证书）。

## UI 与门控

- 顶栏：设备下拉框右侧一个配对按钮，文案随 `_paired`（None/True/False）切换：检查中（禁用）/ 取消配对 / 配对。
- 选择设备 → `_refresh_pairing()` 异步探测 → `_set_pair_state()` 广播：更新按钮、应用蒙版、按配对态加载/清空依赖配对的 tab，并处理键鼠 tab 的 on_enter/on_leave。
- 共享蒙版：单个 `QWidget` 重父到当前依赖配对的 tab；未配对且当前 tab 受门控时覆盖并提示，否则隐藏。通过对受门控 tab 安装 `eventFilter` 跟随其尺寸变化重新定位。
- 「设备信息」读取公共 lockdown 值、无需会话，**不**受门控。
- 配对/取消配对完成后重跑一次设备选择流程（`on_select_device`），让各 tab 在新信任态下一致重载与门控。

## 不做的事

- 不做监督式配对（`pair_supervised`）/ 组织配对。
- 不在配对流程里自动安装 WDA 或挂载 DDI/启动 tunnel；配对只解决"信任"这一前置。
- 不改动已配对设备下各功能的既有逻辑。

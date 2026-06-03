# executor_ios 实现任务清单

> 本文档按实现阶段分解任务，供开发中逐项对照执行。
> 每个任务项均注明依赖文件、实现要点和验收标准。
>
> 参考文档：
> - `PYTHON-PLATFORM-EXECUTOR-CONTRACT.zh-CN.md`（协议规范，含 README 要求、交付标准、目录结构）

---

## 全局约束（所有 Phase 均适用）

| 约束 | 说明 |
|---|---|
| **仅支持 USB 连接设备** | Wi-Fi 配对设备（网络发现）全程不支持，在所有 Phase 中均不发现、不注册、不操作 |
| **仅支持物理设备** | iOS 模拟器 Not In Scope |
| **XPC tunnel 不由代码管理** | 始终由用户在外部独立运行，详见 Phase 3 §3.0 |

---

## Phase 1 — toolkit_api.py 基本功能

**目标：** 实现单设备场景下的完整平台能力层，所有 WDA 操作均已可用。

> **Phase 1 架构决策（已确定）：**
>
> | 事项 | 决策 |
> |---|---|
> | **端口转发** | **临时转发（ephemeral）**：每次操作调用内部用 `asyncio.run()` 同时跑端口转发 server 和 WDA 请求，操作完成后进程退出，server 自动关闭。不维护跨调用的持久转发，不需要全局端口表。 |
> | **WDA Session** | **Phase 1 不缓存**：每次需要 session 的操作都直接 `POST /session` 新建，不在进程内或跨进程缓存 session_id。Session 复用推迟到 Phase 3（`iOSDevice._session_id`）。 |
>
> 背景：`toolkit_cli.py` 每次被 broker 调用都是全新进程，全局状态无法跨调用持久化；同时 usbmux 建连耗时 < 10ms，WDA session 新建（WDA 已运行时）耗时 < 500ms，均在 15 秒超时预算内可接受。

### 1.1 基础设施

- [ ] **创建 `__init__.py`**
  - 空文件，将 `executor_ios` 标记为 Python 包
  - 验收：`python3 -c "import executor_ios"` 不报错

- [ ] **创建 `_ephemeral_forward(udid, device_port)` 异步上下文管理器**
  - 文件：`toolkit_api.py`（模块内私有）
  - 签名：`async def _ephemeral_forward(udid: str, device_port: int = 8100) -> AsyncIterator[int]`
  - 实现：
    1. 用 `socket` bind 探测从 8200 起找到第一个可用本地端口 `local_port`
    2. 调用 `pymobiledevice3` 的 `usbmux.list_devices()` 找到目标 UDID 的设备对象；UDID 不存在则 raise `ValueError`
    3. 用 `asyncio.start_server` 启动端口转发 server（`host="127.0.0.1"`, `port=local_port`），client 连接时通过 `device.create_connection(device_port)` 建 usbmux 通道并双向 relay（参考 `port_forward.py` 的 `_relay_via_usbmux` 逻辑）
    4. `yield local_port`（server 在 async with 块内持续运行）
    5. 退出 async with 时 server 自动关闭
  - 每个操作函数在 `asyncio.run()` 内用 `async with _ephemeral_forward(udid) as local_port` 使用
  - 验收：进入 context 后，`local_port` 可正常接受 TCP 连接并透传到设备 8100

- [ ] **创建 WDA HTTP 工具函数**
  - 文件：`toolkit_api.py`（模块内私有）
  - `_wda_get(local_port: int, path: str, timeout: float = 15.0) -> dict`：发起 `GET` 请求，返回解析后的 JSON；连接失败或 HTTP 错误统一 raise `WdaError`
  - `_wda_post(local_port: int, path: str, body: dict, timeout: float = 15.0) -> dict`：发起 `POST` 请求，同上
  - `WdaError(Exception)`：内部异常类，携带 `message: str`；调用方捕获后统一转换为 `_err("SUBPROCESS", ...)` 返回
  - 注意：这两个函数是同步的（内部用 `requests`），在 `asyncio.run()` 内调用时需通过 `loop.run_in_executor(None, ...)` 或直接调用（requests 是同步阻塞，在 async 函数内直接调用会阻塞事件循环，但单操作场景可接受）

- [ ] **统一返回值工具函数**
  - 文件：`toolkit_api.py`（模块内私有）
  - `_ok(data: dict) -> dict`：返回 `{"ok": True, "data": data}`
  - `_err(kind: str, message: str, details: dict = {}) -> dict`：返回 `{"ok": False, "error": {"kind": kind, "message": message, "details": details}}`
  - `_not_implemented(op: str) -> dict`：返回 `_err("NOT_IMPLEMENTED", f"{op} is not supported on iOS")`

- [ ] **创建 `_create_session(local_port: int) -> str` 函数**
  - 文件：`toolkit_api.py`（模块内私有）
  - 实现：`POST http://127.0.0.1:<local_port>/session`，body：`{"capabilities": {"alwaysMatch": {}}}`
  - 从响应取 `sessionId` 并返回；失败则 raise `WdaError`
  - **Phase 1 不做缓存**：每次调用都新建 session，不读写任何全局状态
  - 所有依赖 session 的操作（`tap`、`swipe`、`input_text`、`launch_app`、`kill_app`）在 `_ephemeral_forward` 内先调用此函数获取 `session_id`
  - Phase 3 迁移时，session 复用逻辑由 `iOSDevice._session_id` 属性承接，此函数保留为底层创建原语

---

### 1.2 `list_targets()`

- [ ] **实现 `list_targets() -> dict`**
  - 文件：`toolkit_api.py`
  - 实现步骤（全部在一次 `asyncio.run()` 内完成）：
    1. 调用 `pymobiledevice3` 的 `usbmux.list_devices()` 获取当前已连接设备列表；**仅保留 `connection_type == "USB"` 的条目**（过滤 Wi-Fi 配对设备）
    2. 对每个设备通过 lockdown 读取元数据（`DeviceName`、`ProductType`、`ProductVersion`），读取失败时降级为空字符串，不阻塞后续
    3. 每个设备构造一个 target dict：
       ```json
       {
         "id": "<UDID>",
         "platform": "ios",
         "name": "<DeviceName>",
         "state": "online",
         "metadata": {
           "model": "<ProductType>",
           "os_version": "<ProductVersion>"
         }
       }
       ```
    4. 返回 `_ok({"targets": [...]})`
  - `list_targets()` **不启动端口转发**，仅做设备发现和元数据读取
  - 无设备时返回 `_ok({"targets": []})`，不报错
  - 模拟器 Not In Scope，不处理
  - 整体耗时目标：< 1 秒
  - 验收：连接一台物理设备后，`list_targets()` 返回该设备信息（含正确的 UDID、name、model、os_version）

---

### 1.3 `screenshot(target: str) -> dict`

- [ ] **实现 `screenshot(target: str) -> dict`**
  - 文件：`toolkit_api.py`
  - 调用模式：`asyncio.run(_screenshot_async(target))`，内部用 `async with _ephemeral_forward(target) as local_port`
  - 实现：`GET /screenshot`（WDA REST API，此端点无需 session）
  - 响应中取 `value` 字段（base64 字符串）
  - 返回格式：
    ```json
    { "mimeType": "image/png", "base64": "<base64字符串>" }
    ```
  - UDID 不存在（`_ephemeral_forward` 内 `list_devices` 找不到目标）→ `BAD_TARGET`
  - WDA 请求失败（`WdaError`）→ `SUBPROCESS`
  - 验收：返回 PNG base64，用 base64 解码后可正常打开图片

---

### 1.4 `dump_ui(target: str) -> dict`

- [ ] **实现 `dump_ui(target: str) -> dict`**
  - 文件：`toolkit_api.py`
  - 实现：`GET /source?format=xml`（WDA REST API）
  - 将 WDA 返回的 XML 字符串存入 `raw` 字段，`rawMime` 固定为 `application/xml`
  - 解析 XML，将每个可见元素映射为统一 selector：
    - `resourceId`：取元素 `name` 属性，无则空字符串
    - `text`：取元素 `label` 属性，无则空字符串
    - `contentDesc`：取元素 `value` 属性，无则空字符串
    - `class`：取元素 `type` 属性，无则空字符串
    - `bounds`：将 `x`/`y`/`width`/`height` 属性转换为 `"[x1,y1][x2,y2]"` 格式
    - `clickable`：元素 `visible` 为 true 且有 bounds 时推断为 true，否则 false
    - `enabled`：取元素 `enabled` 属性
    - `visible`：取元素 `visible` 属性
  - 所有字段必须存在，缺失时用默认值（字符串字段用空字符串，布尔字段用 false）
  - selector 数量上限 200 条，超出时截断
  - 去重：相同 `resourceId` + `bounds` 组合只保留一条
  - 验收：返回包含 `raw` 和 `selectors` 的 dict，selectors 中每条都有全部 8 个字段

---

### 1.5 `tap(target: str, x: int, y: int) -> dict`

- [ ] **实现 `tap(target: str, x: int, y: int) -> dict`**
  - 文件：`toolkit_api.py`
  - 调用模式：`asyncio.run(_tap_async(target, x, y))`，内部用 `async with _ephemeral_forward(target) as local_port`
  - 实现：
    1. `session_id = await _create_session(local_port)`（每次新建，不缓存）
    2. `POST /session/<session_id>/actions`，pointer 类型，pointerDown + pointerUp 序列
  - 坐标使用逻辑点（pt），不需要乘以 scale factor
  - 返回格式：
    ```json
    { "ok": true, "exitCode": 0, "stdout": "", "stderr": "", "extra": { "tapX": x, "tapY": y } }
    ```
  - 验收：在已知按钮坐标调用 `tap()` 后，界面上该按钮被触发

---

### 1.6 `swipe(target: str, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 250) -> dict`

- [ ] **实现 `swipe(target: str, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 250) -> dict`**
  - 文件：`toolkit_api.py`
  - 调用模式：同 `tap`（`asyncio.run` + `_ephemeral_forward` + `_create_session`）
  - 实现：`POST /session/<session_id>/actions`，pointer 事件序列：pointerDown → pause（duration_ms）→ pointerMove → pointerUp
  - 坐标单位同 tap（逻辑点）
  - 返回格式：
    ```json
    { "ok": true, "exitCode": 0, "stdout": "", "stderr": "", "extra": { "fromX": x1, "fromY": y1, "toX": x2, "toY": y2, "durationMs": duration_ms } }
    ```
  - 验收：在列表页面调用 `swipe()` 后，列表发生滚动

---

### 1.7 `input_text(target: str, text: str) -> dict`

- [ ] **实现 `input_text(target: str, text: str) -> dict`**
  - 文件：`toolkit_api.py`
  - 输入校验（校验失败返回 `BAD_TARGET`）：
    - 拒绝包含换行符（`\n`、`\r`）的文本
    - 拒绝包含单引号（`'`）的文本
    - 拒绝包含反引号（`` ` ``）的文本
    - 拒绝超过 1024 字节的文本
  - 调用模式：同 `tap`（`asyncio.run` + `_ephemeral_forward` + `_create_session`）
  - 实现：
    - 主路径：`GET /session/<session_id>/element/active` 获取当前聚焦 element 的 id，使用 `POST /session/<session_id>/element/<id>/value` 写入
    - Fallback：若 `/element/active` 返回 404 或无元素，使用 WDA W3C key actions 逐字符发送（`POST /session/<session_id>/actions`，ActionType = key）
  - 返回格式：
    ```json
    { "ok": true, "exitCode": 0, "stdout": "", "stderr": "", "extra": { "length": <字符数> } }
    ```
  - 验收：在文本框聚焦状态下调用 `input_text()`，文本框内容与输入一致

---

### 1.8 `key_event(target: str, key: str) -> dict`

- [ ] **实现 `key_event(target: str, key: str) -> dict`**
  - 文件：`toolkit_api.py`
  - 调用模式：同 `tap`（`asyncio.run` + `_ephemeral_forward` + `_create_session`，`HOME`/`POWER` 无需 session 也可直接用 `POST /wda/pressButton`）
  - 按键路由表：

    | key | 实现方式 |
    |---|---|
    | `HOME` | WDA `POST /wda/pressButton`，button = "home" |
    | `POWER` | WDA `POST /wda/pressButton`，button = "power" |
    | `ENTER` | WDA W3C key event，key value = `"\uE007"` |
    | `DEL` | WDA W3C key event，key value = `"\uE017"` |
    | `TAB` | WDA W3C key event，key value = `"\uE004"` |
    | `SPACE` | WDA W3C key event，key value = `"\uE00D"` |
    | `ESCAPE` | WDA W3C key event，key value = `"\uE00C"` |
    | `BACK` | 返回 `NOT_IMPLEMENTED`（iOS 无 Android 导航键） |
    | `MENU` | 返回 `NOT_IMPLEMENTED` |
    | `RECENTS` | 返回 `NOT_IMPLEMENTED` |
    | 其他未知 key | 返回 `NOT_IMPLEMENTED` |

  - 验收：`key_event(target, "HOME")` 后设备回到桌面；`key_event(target, "BACK")` 返回 `NOT_IMPLEMENTED` 错误

---

### 1.9 `launch_app(target: str, package: str, activity: str | None = None) -> dict`

- [ ] **实现 `launch_app(target: str, package: str, activity: str | None = None) -> dict`**
  - 文件：`toolkit_api.py`
  - `activity` 参数对 iOS 无意义，忽略即可
  - `package` 对应 iOS bundleId（如 `us.zoom.videomeetings`）
  - 调用模式：同 `tap`（`asyncio.run` + `_ephemeral_forward` + `_create_session`）
  - 实现：
    - 主路径：`POST /session/<session_id>/wda/apps/launch`，body 为 `{"bundleId": package}`
    - Fallback：若 `WdaError`，使用 `pymobiledevice3` 的 `AppServiceClient` 启动应用（需在 `asyncio.run` 内 await，或通过 `loop.run_in_executor` 调用同步 API）
  - 返回格式：`OpResult` 风格（同 tap）
  - 验收：调用后 App 在前台启动

---

### 1.10 `kill_app(target: str, package: str) -> dict`

- [ ] **实现 `kill_app(target: str, package: str) -> dict`**
  - 文件：`toolkit_api.py`
  - 调用模式：同 `tap`（`asyncio.run` + `_ephemeral_forward` + `_create_session`）
  - 实现：
    - 主路径：`POST /session/<session_id>/wda/apps/terminate`，body 为 `{"bundleId": package}`
    - Fallback：若 `WdaError`，使用 `pymobiledevice3` 的 `AppServiceClient` 杀死应用
  - 返回格式：`OpResult` 风格（同 tap）
  - 验收：调用后 App 进程不再存在（可通过 `dump_ui` 或设备状态确认）

---

### 1.11 `switch_app_env(target: str, env: str) -> dict`（空实现）

- [ ] **实现 `switch_app_env()` 空桩**
  - 文件：`toolkit_api.py`
  - 直接返回：`_not_implemented("switch_app_env")`
  - 验收：返回 `{"ok": False, "error": {"kind": "NOT_IMPLEMENTED", ...}}`

---

### 1.12 `type_credential()` 及其他（空实现）

- [ ] **实现 `type_credential()` 空桩**
  - 文件：`toolkit_api.py`
  - 直接返回：`_not_implemented("type_credential")`
  - 说明：待后续实现 `secrets.py` 时再填充

- [ ] **（备忘）`secrets.py` 接口约定**（实现 `type_credential` 时参考）
  - 文件：`executor_ios/secrets.py`（可选，仅在实现 `type_credential` 时创建）
  - 接口：
    ```python
    def get_credential(env: str, role: str, field: str) -> str:
        """从本地安全存储（环境变量、keychain 等）读取凭据，返回明文字符串。"""
        ...
    ```
  - 安全约束（零容忍）：
    - 明文只允许在 Python 进程内存中短暂存在
    - 不得写入 `stdout` / `stderr` / 日志文件 / 命令行参数
    - 不得出现在任何响应体中（包括 `error.details`）
  - `type_credential` 的实现：调用 `get_credential(env, role, field)` 取得明文 → 调用 `input_text()` 写入，明文不经过任何中间层

- [ ] **确认所有协议规定的 op 均有对应函数**
  - 检查清单：`list_targets` / `screenshot` / `dump_ui` / `tap` / `swipe` / `input_text` / `key_event` / `launch_app` / `kill_app` / `switch_app_env` / `type_credential`
  - 未实现的均返回 `NOT_IMPLEMENTED`，无遗漏

---

### Phase 1 验收

- [ ] 单台物理设备连接后，以下调用全部正常返回（不抛 Python 异常）：
  - `list_targets()`
  - `screenshot("<udid>")`
  - `dump_ui("<udid>")`
  - `tap("<udid>", x, y)`
  - `swipe("<udid>", x1, y1, x2, y2)`
  - `input_text("<udid>", "hello")`
  - `key_event("<udid>", "HOME")`
  - `launch_app("<udid>", "us.zoom.videomeetings")`
  - `kill_app("<udid>", "us.zoom.videomeetings")`
- [ ] 不存在的 UDID 返回 `BAD_TARGET` 而非 Python 异常
- [ ] `switch_app_env` 和 `type_credential` 返回 `NOT_IMPLEMENTED`
- [ ] 每次调用独立完成（无需外部持久进程），多次连续调用均可正常执行

---

## Phase 2 — toolkit_cli.py

**目标：** 实现一次性 JSON CLI 入口，供 Studio broker 调用。自身不含平台逻辑，全部委托给 `toolkit_api.py`。

### 2.1 CLI 主流程

- [ ] **实现 stdin → stdout 一次性 JSON 协议**
  - 文件：`toolkit_cli.py`
  - 启动方式：`python3 -B -m executor_ios.toolkit_cli`
  - 流程：
    1. 从 `stdin` 读取完整 JSON（一个对象）
    2. 解析 `op`、`requestId`、`deadlineMs`、`args` 字段
    3. 根据 `op` 分发到 `toolkit_api.py` 中对应函数
    4. 将函数返回的 dict 包装为响应 JSON（附加 `requestId`）
    5. 写入 `stdout` 后退出
  - `stdout` 只输出一个完整 JSON，不混入其他内容
  - `stderr` 可写调试日志（绝不能包含明文凭据）

- [ ] **实现请求分发映射表**
  - 文件：`toolkit_cli.py`
  - 维护一个 `op` → `handler` 的映射，handler 接收 `args` dict，返回 `toolkit_api` 的 dict
  - 未知 `op` → 返回 `NOT_IMPLEMENTED` 错误响应

- [ ] **实现 `deadlineMs` 超时控制**
  - 若请求包含 `deadlineMs`，使用 `threading.Timer` 或 `signal` 在超时后强制退出（exit code 5）
  - 若未指定，默认 15000ms

- [ ] **实现标准退出码**

  | 退出码 | 触发条件 |
  |---|---|
  | `0` | 请求已处理（成功/失败看 JSON `ok`） |
  | `2` | stdin 不是合法 JSON，或缺少必填字段（`op` / `args`） |
  | `3` | pymobiledevice3 未安装 / 运行时环境不满足 |
  | `4` | 内部子进程失败 |
  | `5` | 执行器内部未捕获异常 |

---

### 2.2 各 op 参数提取

- [ ] **实现各 op 的参数提取逻辑**
  - `list_targets`：无需参数
  - `screenshot`：`args.target`（必填，否则返回 exit 2）
  - `dump_ui`：`args.target`
  - `tap`：`args.target`、`args.x`、`args.y`
  - `swipe`：`args.target`、`args.x1`、`args.y1`、`args.x2`、`args.y2`、`args.durationMs`（可选，默认 250）；注意 JSON 中为 `durationMs`，传入 Python 函数时需转换为 `duration_ms`
  - `input_text`：`args.target`、`args.text`
  - `key_event`：`args.target`、`args.key`
  - `launch_app`：`args.target`、`args.package`、`args.activity`（可选）
  - `kill_app`：`args.target`、`args.package`
  - `switch_app_env`：`args.target`、`args.env`
  - `type_credential`：`args.target`、`args.env`、`args.role`、`args.field`、`args.skipClear`（可选）

---

### Phase 2 验收

- [ ] 通过 shell 管道模拟 broker 调用，各 op 正常响应：
  ```bash
  echo '{"op":"list_targets","args":{}}' | python3 -B -m executor_ios.toolkit_cli
  echo '{"op":"screenshot","args":{"target":"<udid>"}}' | python3 -B -m executor_ios.toolkit_cli
  ```
- [ ] 非法 JSON 输入返回 exit code 2
- [ ] 未知 op 返回 `NOT_IMPLEMENTED` 响应，exit code 0
- [ ] `stdout` 只有一行 JSON，`stderr` 无敏感信息

---

## Phase 3 — 多设备支持与设备管理器

**目标：** 引入 `iOSDevicesManager` 和 `iOSDevice`，使设备发现、端口映射、WDA 状态管理、WDA 自动安装等逻辑面向对象化，支持多台设备并发使用。

> **范围约束（Not In Scope）：**
> - **仅支持 USB 连接设备**，Wi-Fi 配对设备不在支持范围内
> - XPC tunnel 不由代码管理，始终是外部前置条件（见下方说明）

---

### ⚠️ Phase 3 开始前必须确认的事项

在开始任何 Phase 3 任务前，以下三项必须由团队明确决策并写入文档：

- [x] **WDA 包配置来源**（已决策）
  - **不负责下载或安装 WDA**，WDA 需由用户提前手动安装到设备上
  - WDA Bundle ID 从 `~/.executor_ios.json` 读取，字段名为 `wda_bundle_id`；若未配置则默认为 `com.facebook.WebDriverAgentRunner.xctrunner`
  - `list_targets()` 通过 `AppServiceClient.list_installed_apps()` 检查 WDA 是否已安装：
    - 已安装 → `state: "online"`
    - 未安装 → `state: "offline"`（不报错，正常返回，不阻塞其他设备）
  - `is_prepared()` 只检查 WDA HTTP 进程是否活跃（`GET /status` 在 2 秒内返回 200），**不再检查安装状态**
  - `do_prepare()` **只负责启动 WDA 进程**，不下载、不安装：
    - 若 WDA 未安装（`state: "offline"` 的设备）调用 `do_prepare()` → 抛出明确错误，提示用户需先手动安装 WDA
    - 若 WDA 已安装但未运行 → 通过 pymobiledevice3 启动 WDA xctrunner 进程，等待 HTTP 端点就绪（最多 60 秒）

- [x] **`do_prepare()` 的触发时机**（已决策：方案 B）
  - 在每次操作（`screenshot`、`tap`、`dump_ui` 等所有非 `list_targets` 操作）执行前，先调用 `device.is_prepared()`
  - 若返回 False，则自动调用 `device.do_prepare()` 尝试启动 WDA，再继续执行原始操作
  - `list_targets` 不触发 `do_prepare()`（设备发现阶段不强制启动 WDA）
  - `toolkit_api.py` 中每个操作函数的模式：
    ```python
    device = manager.get_device(target)
    if device is None:
        return _err("BAD_TARGET", ...)
    if not device.is_prepared():
        device.do_prepare()   # 按需启动 WDA，失败则抛异常由上层转为 SUBPROCESS 错误
    return device.screenshot()   # 执行实际操作
    ```

- [x] **RSD 注入的具体接口**（已决策：环境变量）
  - 通过环境变量注入，变量名：`IOS_RSD_ADDRESS`（字符串）和 `IOS_RSD_PORT`（整数）
  - `iOSDevicesManager` 在注册设备时读取这两个环境变量，写入对应 `iOSDevice` 的 `rsd_address` / `rsd_port`
  - 每次 `toolkit_cli.py` 启动时均读取（进程级别），无需单独的注入调用
  - 未设置环境变量时 `rsd_address` / `rsd_port` 为 None；iOS 17+ 设备调用 `do_prepare()` 时若为 None 则抛出明确错误

---

### 3.0 XPC tunnel 与 RSD 配置约定

iOS 17+ 设备上，启动 WDA xctrunner 需要通过 CoreDevice/RemoteXPC 通道访问开发者服务，这要求 XPC tunnel 已在外部启动，并提供 RSD（Remote Service Discovery）地址和端口。

**约定：**

- XPC tunnel **始终由用户在外部独立运行**，不由本项目代码启动或管理：
  ```bash
  sudo pymobiledevice3 remote tunneld
  ```
- XPC tunnel 启动后，通过以下命令以 JSON 格式获取当前设备的 RSD 信息（`rsd_address`、`rsd_port`）：
  ```bash
  sudo python3 -m executor_ios.xpc_tunnel --json
  ```
- `iOSDevice` 对象需接收 RSD 配置，供 `do_prepare()` 在 iOS 17+ 上使用

**RSD 配置注入方式：**

- `iOSDevice` 增加可选属性：`rsd_address: str | None` 和 `rsd_port: int | None`
- 通过环境变量注入：`IOS_RSD_ADDRESS`（字符串）和 `IOS_RSD_PORT`（整数），由 `iOSDevicesManager` 在注册设备时读取，不由代码自动发现
- `do_prepare()` 中的行为：

  | 设备系统版本 | RSD 是否已配置 | 行为 |
  |---|---|---|
  | iOS 16 及以下 | 无需（忽略） | 通过 lockdown/usbmux 路径启动 WDA |
  | iOS 17+ | 已配置 | 使用 RSD 路径连接 CoreDevice，启动 WDA xctrunner |
  | iOS 17+ | 未配置 | 抛出明确错误，提示用户先启动 XPC tunnel 并提供 RSD 信息 |

---

### 3.1 `iOSDevice` 类

- [ ] **创建 `iOSDevice` 类**
  - 文件：建议新建 `executor_ios/device.py`
  - 属性：
    - `udid: str`：设备唯一标识，**仅 USB 连接设备**（Wi-Fi 设备不支持）
    - `local_port: int`：本机上与该设备 8100 端口对应的 usbmux 转发端口（持久分配，进程生命周期内不变）
    - `name: str`：设备名称
    - `model: str`：设备型号
    - `os_version: str`：系统版本
    - `rsd_address: str | None`：XPC tunnel 暴露的 RSD 地址（iOS 17+ `do_prepare` 时必填）
    - `rsd_port: int | None`：XPC tunnel 暴露的 RSD 端口（iOS 17+ `do_prepare` 时必填）
    - `_forward_task`：后台 usbmux 端口转发句柄（见下方持久转发说明）
    - `_session_id: str | None`：当前有效的 WDA session ID，初始为 `None`
    - `_session_lock: threading.Lock`：保护 `_session_id` 读写的锁（多线程并发调用时防止重复创建 session）

- [ ] **实现持久 usbmux 端口转发（替代 Phase 1 的 ephemeral 模式）**
  - Phase 3 中，`iOSDevice` 持有一个**持久运行**的端口转发，生命周期与 `iOSDevice` 对象相同
  - 实现方式：使用一个模块级后台事件循环线程
    ```python
    # device.py 模块级，仅初始化一次
    _bg_loop = asyncio.new_event_loop()
    _bg_thread = threading.Thread(target=_bg_loop.run_forever, daemon=True)
    _bg_thread.start()
    ```
  - 每台设备注册时，通过 `asyncio.run_coroutine_threadsafe(_start_forward(device, local_port), _bg_loop)` 提交转发协程，返回的 `Future` 存入 `_forward_task`
  - `_start_forward` 内部：`asyncio.start_server(...)` + 双向 relay（逻辑同 `port_forward.py`），协程永不主动退出，靠 `_forward_task.cancel()` 终止
  - 这样 `local_port` 在整个进程生命周期内持续可用，操作函数可直接用 `self.local_port` 发 HTTP 请求，无需 `asyncio.run()` 包装

- [ ] **实现 `iOSDevice.is_prepared() -> bool`**
  - 只检查 WDA HTTP 进程是否活跃：向 `http://127.0.0.1:<local_port>/status` 发送 GET 请求，在 2 秒内收到 200 响应则返回 True，否则返回 False
  - **不检查安装状态**（安装检查由 `list_targets` 承担，以 `state` 字段体现）

- [ ] **实现 `iOSDevice.is_wda_installed() -> bool`**（供 `list_targets` 使用）
  - 通过 `pymobiledevice3` 的 `AppServiceClient.list_installed_apps()` 检查 WDA bundleId 是否存在
  - bundleId 从 `~/.executor_ios.json` 的 `wda_bundle_id` 字段读取，未配置则默认 `com.facebook.WebDriverAgentRunner.xctrunner`

- [ ] **实现 `iOSDevice.do_prepare() -> None`**
  - 触发条件：`is_prepared()` 返回 False 时（即 WDA 进程未运行）
  - 实现步骤：
    1. **前置检查**：若 WDA 未安装（`is_wda_installed()` 返回 False），直接抛出 `RuntimeError`，提示用户需先手动安装 WDA
    2. **启动 WDA 进程**（WDA 已安装但未运行）：
       - iOS 16 及以下：通过 lockdown/usbmux 路径（`pymobiledevice3` 标准 API）启动 WDA xctrunner
       - iOS 17+：
         - 检查 `rsd_address` / `rsd_port` 是否已配置，未配置则抛出 `RuntimeError` 并附带提示信息（说明需先启动 XPC tunnel）
         - 已配置则使用 `pymobiledevice3` 的 RSD 路径（`RemoteServiceDiscoveryService`）连接 CoreDevice，再启动 WDA xctrunner
       - 等待 WDA HTTP 端点可用（轮询 `GET /status`，最多等待 60 秒）
    3. **重置 session 缓存**：`self._session_id = None`（WDA 重启后旧 session 必然失效）
    4. 启动完成后 `is_prepared()` 应返回 True
  - **不负责下载或安装 WDA**，安装失败/未安装时抛出带描述的异常

- [ ] **实现 `iOSDevice._ensure_session() -> str`（session 复用）**
  - 文件：`executor_ios/device.py`（`iOSDevice` 实例方法，私有）
  - 实现逻辑：
    ```
    with self._session_lock:
        if self._session_id is not None:
            return self._session_id           # 直接复用缓存
        session_id = _create_session(self.local_port)  # 复用 Phase 1 的原语函数
        self._session_id = session_id
        return session_id
    ```
  - session 失效自动重建：当 WDA 操作返回 HTTP 4xx 且响应体中 `value.error` 含 `"invalid session id"` 时：
    1. `with self._session_lock: self._session_id = None`（清除缓存）
    2. 调用 `self._ensure_session()` 重建
    3. 重试原请求一次；仍失败则返回 `SUBPROCESS` 错误，不再继续
  - heartbeat（可选，低优先级）：可在后台线程定期 `GET /session/<id>/timeouts` 检活，失效时清 `_session_id`；Phase 3 初期可不实现，等有实际需要再加

- [ ] **将 WDA 操作封装到 `iOSDevice`**
  - 为每个平台操作添加对应的实例方法（均为同步方法，直接用 `requests` + `self.local_port`）：
    - `screenshot() -> dict`
    - `dump_ui() -> dict`
    - `tap(x, y) -> dict`
    - `swipe(x1, y1, x2, y2, duration_ms) -> dict`
    - `input_text(text) -> dict`
    - `key_event(key) -> dict`
    - `launch_app(package, activity) -> dict`
    - `kill_app(package) -> dict`
  - 需要 session 的方法内部统一调用 `self._ensure_session()` 获取 `session_id`，不直接读 `self._session_id`
  - Phase 1 的 `asyncio.run()` + `_ephemeral_forward` 包装在 Phase 3 中**全部去掉**，因为 `local_port` 已由持久转发保证可用

---

### 3.2 `iOSDevicesManager` 类

- [ ] **创建 `iOSDevicesManager` 类（单例）**
  - 文件：`executor_ios/device.py`（与 `iOSDevice` 同文件）
  - 内部维护：`dict[str, iOSDevice]`，key 为 UDID

- [ ] **实现设备发现与注册**
  - 调用 `pymobiledevice3` 枚举当前连接的**USB 物理设备**（Wi-Fi 配对设备跳过，不注册）
  - 对每个新发现的 UDID：
    1. 分配一个本地可用端口（方法同 Phase 1）
    2. 启动 usbmux 端口转发（device:8100 → localhost:<local_port>）
    3. 创建 `iOSDevice` 对象并记录到内部 dict（`rsd_address` / `rsd_port` 初始为 None）
  - 已知设备（UDID 已在 dict 中）跳过，不重复分配端口

- [ ] **实现 `iOSDevicesManager.get_device(udid: str) -> iOSDevice | None`**
  - 按 UDID 查询已注册的设备，不存在返回 None

- [ ] **实现 `iOSDevicesManager.list_devices() -> list[iOSDevice]`**
  - 触发一次设备发现（更新内部表），返回所有已注册设备列表

- [ ] **更新 `toolkit_api.py` 使用 `iOSDevicesManager`**
  - **Phase 1 → Phase 3 迁移内容：**

    | Phase 1 | Phase 3 替代 |
    |---|---|
    | 每个操作用 `asyncio.run()` + `_ephemeral_forward` 包装 | 操作直接用 `device.local_port`（持久转发已保证） |
    | `_create_session()` 每次新建，不缓存 | `device._ensure_session()` 复用缓存，失效时自动重建 |
    | 无全局设备表 | `iOSDevicesManager` 单例管理所有 `iOSDevice` |

  - `list_targets()` 调用 `manager.list_devices()`，将每个 `iOSDevice` 转换为 target dict；其中 `state` 字段由 `device.is_wda_installed()` 决定：已安装 → `"online"`，未安装 → `"offline"`
  - 其他操作（`screenshot` 等）通过 `manager.get_device(target)` 取到 `iOSDevice` 对象，委托给对应实例方法
  - target 不存在（`get_device` 返回 None）→ 返回 `BAD_TARGET`
  - 迁移完成后，`toolkit_api.py` 中不再有任何 `asyncio.run()` 调用（全部移入 `device.py` 的后台事件循环）

---

### 3.3 `xpc_tunnel.py`（已删除，Not In Scope）

`device.py` 在 `do_prepare()` 中直接查询 tunneld HTTP API（`127.0.0.1:49151`）获取 RSD 信息，无需独立的查询辅助脚本。`xpc_tunnel.py` 已删除。

---

### Phase 3 验收

- [ ] 同时连接两台 **USB** 物理设备，`list_targets()` 返回两台设备，各有不同的本地端口
- [ ] Wi-Fi 配对设备不出现在 `list_targets()` 结果中
- [ ] 对两台设备分别调用 `screenshot()` 均正常返回
- [ ] `iOSDevice.is_prepared()` 在 WDA 运行时返回 True，WDA 未启动时返回 False
- [ ] iOS 17+ 设备上，`do_prepare()` 在未配置 RSD 时抛出明确错误信息
- [ ] iOS 17+ 设备上，`ios_tunneld` 已运行时，`do_prepare()` 能自动查询 tunneld 获取 RSD 并成功启动 WDA
- [ ] **Session 复用验收**：同一进程内对同一设备连续调用 `tap()` 两次，第二次调用的 `_ensure_session()` **不发起 `POST /session`**（可通过 WDA 访问日志或打桩确认）
- [ ] **Session 自动重建验收**：手动重启设备上的 WDA xctrunner，之后调用 `tap()` 仍能成功（`_ensure_session()` 检测到旧 session 失效后自动重建）
- [ ] `toolkit_api.py` 中不再有任何 `asyncio.run()` 调用，所有操作均为同步方法委托给 `iOSDevice`

---

## 附录：依赖与环境

| 依赖 | 用途 | 安装方式 |
|---|---|---|
| `pymobiledevice3` | 设备发现、usbmux 端口转发、App 安装与启动 | `pip install pymobiledevice3` |
| `requests` | WDA HTTP 通信 | `pip install requests` |
| `aioquic`（Python < 3.13） | XPC tunnel（`ios_tunneld` 二进制内部使用） | `pip install aioquic` |

> **设备连接方式限制：** 本项目仅支持 **USB 连接**的物理 iOS 设备，Wi-Fi 配对设备（网络发现）不在支持范围内。
>
> **WDA 包：** 需由用户提前手动安装到设备上，本项目不负责下载或安装。WDA Bundle ID 通过 `~/.executor_ios.json` 的 `wda_bundle_id` 字段配置，未配置时默认 `com.facebook.WebDriverAgentRunner.xctrunner`。
>
> **XPC tunnel（外部前置条件）：** iOS 17+ 设备使用 `do_prepare()` 启动 WDA 前，需以 root 权限运行 `ios_tunneld`（由 `tunneld_main.py` 打包而来，建议配置为 LaunchDaemon 自动启动）。`do_prepare()` 会自动查询本地 tunneld HTTP API（`http://127.0.0.1:49151`）获取 RSD 信息，无需手动设置环境变量。tunneld 未运行时 `do_prepare()` 会抛出明确错误提示。本项目代码**不负责**启动或管理 tunneld 进程。

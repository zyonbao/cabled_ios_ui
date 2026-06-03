## Context

`executor_ios` 是 iOS UI 自动化链路的平台能力层，运行在 macOS Host 上，负责通过 USB 连接与 iOS 物理设备通信。Broker 每次调用时通过 `toolkit_cli.py` 启动一个全新 Python 进程，传入 JSON 请求，读取 JSON 响应后进程退出。

当前状态：`toolkit_api.py` 和 `toolkit_cli.py` 均为空文件，Phase 1 目标是交付完整可用的 `toolkit_api.py`。

核心约束：
- **进程无状态**：Broker 每次调用都是全新进程，Python 进程内的任何全局状态不跨调用持久化
- **仅 USB 设备**：Wi-Fi 配对设备（网络发现）全程不支持
- **仅物理设备**：iOS 模拟器 Not In Scope
- **XPC tunnel 外部管理**：Phase 1 不涉及 iOS 17+ 的 WDA 安装/启动，XPC tunnel 相关逻辑推迟到 Phase 3

## Goals / Non-Goals

**Goals:**
- 实现所有协议规定的 11 个操作函数（`list_targets`、`screenshot`、`dump_ui`、`tap`、`swipe`、`input_text`、`key_event`、`launch_app`、`kill_app`、`switch_app_env`、`type_credential`）
- 每次操作在独立的 `asyncio.run()` 生命周期内完成（临时端口转发模式）
- 统一返回值格式（`_ok` / `_err` / `_not_implemented`）
- 错误分类正确（`BAD_TARGET`、`SUBPROCESS`、`NOT_IMPLEMENTED`）

**Non-Goals:**
- Phase 2 CLI 入口（`toolkit_cli.py`）
- Phase 3 持久端口转发、session 复用、多设备管理器（`device.py`）
- WDA 的安装和启动（`do_prepare`）
- iOS 17+ RSD 注入逻辑
- `secrets.py` 和 `type_credential` 实际实现

## Decisions

### 决策 1：临时端口转发（Ephemeral）模式

**选择：** 每次操作用 `asyncio.run()` 同时驱动端口转发 server 和 WDA 请求，操作完成后进程退出，server 自动关闭。

**理由：** Broker 每次调用是全新进程，无法复用进程间的持久连接。usbmux 建连耗时 < 10ms，WDA session 新建（WDA 已运行时）耗时 < 500ms，均在 15 秒超时预算内可接受。临时模式比维护全局端口表更简单、更安全（不存在端口泄漏问题）。

**替代方案：** 持久端口转发（Phase 3 采用）需要跨调用持久进程，与当前的"每次全新进程"调用模式不兼容。

### 决策 2：每次新建 WDA Session（不缓存）

**选择：** 每次需要 session 的操作都直接 `POST /session` 新建，不在进程内或跨进程缓存 session_id。

**理由：** 进程无状态约束使跨调用 session 缓存不可行。新建 session 耗时在预算内。Session 复用（`iOSDevice._ensure_session`）推迟到 Phase 3，届时进程生命周期足够长。

### 决策 3：WDA HTTP 工具使用同步 requests

**选择：** `_wda_get` / `_wda_post` 使用同步 `requests` 库，在 `asyncio.run()` 内直接调用（不通过 `run_in_executor`）。

**理由：** 单操作场景下事件循环只跑一个请求，同步阻塞可接受。引入 `run_in_executor` 会增加代码复杂度，收益微弱。后续 Phase 3 切换到纯同步模式后这层包装也无需保留。

### 决策 4：dump_ui 字段映射与去重策略

**选择：** WDA XML 字段映射为统一 selector（`resourceId`←`name`、`text`←`label`、`contentDesc`←`value`、`class`←`type`、`bounds`←坐标计算），上限 200 条，按 `resourceId + bounds` 去重。

**理由：** 统一 selector 格式与 Android 平台对齐，方便 broker 层跨平台处理。200 条上限防止超大 UI 树导致响应体过大。`resourceId + bounds` 组合去重覆盖最常见的重复场景（同名同位元素）。

### 决策 5：input_text 输入校验

**选择：** 拒绝含换行符、单引号、反引号或超过 1024 字节的文本，返回 `BAD_TARGET` 错误。

**理由：** WDA W3C key actions 对特殊字符的处理存在平台差异性，早期拒绝比运行时报错更清晰。1024 字节上限防止超长输入影响 WDA 稳定性。

## Risks / Trade-offs

- **[风险] 每次新建 session 的累积耗时** → 在批量操作场景下（如连续 10 次 tap），每次调用额外 < 500ms 的 session 新建开销会叠加。缓解：15 秒超时预算通常足够；Phase 3 的 session 复用会彻底解决。

- **[风险] asyncio + requests 混用的阻塞风险** → `_wda_post` 在 async 协程内同步调用会阻塞事件循环，若端口转发 relay 在同一事件循环内，理论上可能死锁。缓解：relay 是纯 I/O 转发，WDA 请求期间 relay 通道空闲，实际不会死锁；若将来出现问题可切换 `run_in_executor`。

- **[风险] dump_ui 200 条上限截断有效元素** → 对复杂 UI 页面可能截断靠后的可操作元素。缓解：broker 层应优先使用截图 + AI 定位，dump_ui 作为辅助手段；Phase 3 可根据实际使用反馈调整上限。

- **[Trade-off] 临时端口转发每次重建开销** → 相比持久转发，每次操作多出 usbmux 建连开销（< 10ms）。接受：处于预算内，Phase 3 升级后消除。

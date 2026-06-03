## Context

Phase 1 交付了 `toolkit_api.py`，暴露 11 个 Python 函数。Studio broker 需以子进程方式驱动 iOS executor，通过 stdin 写入 JSON 请求、从 stdout 读取 JSON 响应，进程处理完后退出。目前缺少这一 CLI 层，以及 `type_credential` 所需的凭据读取模块 `secrets.py`。

## Goals / Non-Goals

**Goals:**
- 实现 `toolkit_cli.py`：读 stdin → 路由到 `toolkit_api.py` → 写 stdout，一次请求一次退出
- 实现 `secrets.py`：从环境变量安全读取凭据，供 `type_credential` 使用
- 将 `type_credential` 从 NOT_IMPLEMENTED 桩升级为真实实现
- stdout 只输出一个完整 JSON 对象，任何内部日志只走 stderr

**Non-Goals:**
- NDJSON 长驻进程模式（Contract 第 3 层，WillNotDo）
- HTTP proxy server 或 REST API 暴露
- 凭据加密持久化（仅支持环境变量，不做 Keychain 集成）
- 模拟器支持

## Decisions

**决策 1：CLI 入口使用 `asyncio.run` 包装整个请求处理**

- 方案 A：同步包装（每个 op 内部各自 `asyncio.run`）→ 已是 Phase 1 现状，CLI 层无需额外异步
- 方案 B：CLI 层统一 `asyncio.run` → 引入不必要的嵌套复杂度
- **选择方案 A**：`toolkit_cli.py` 完全同步，直接调用 `toolkit_api.py` 公共函数，简洁无嵌套

**决策 2：op → 函数的路由表**

用字典 `OP_TABLE = {"list_targets": api.list_targets, ...}` 静态映射，避免 `getattr` 动态反射带来的安全隐患和可读性问题。未知 op 返回 `NOT_IMPLEMENTED` 错误而非 exit 2。

**决策 3：凭据来源——仅环境变量**

- 方案 A：Keychain 集成 → 需要 macOS 权限，测试环境复杂
- 方案 B：加密本地文件 → 需要密钥管理
- **方案 C：环境变量**（选择）→ 对 CI/CD 友好，与 Studio broker 的注入方式一致；`secrets.py` 按约定的 `IOS_CRED_<ROLE>_<FIELD>` 格式读取

**决策 4：type_credential 不清除再输入**

默认行为：直接调用 `input_text` 写入，不先清除 field。`skip_clear` 参数保留接口兼容，暂不实现清除逻辑（field 清除依赖 UI 状态，需先 tap 再 select-all，复杂度超出本 phase）。

**决策 5：退出码约定**

| 退出码 | 触发条件 |
|--------|---------|
| 0 | 请求已处理（ok true 或 false 看 JSON） |
| 2 | stdin 解析失败或必填字段（op/args）缺失 |
| 5 | 未捕获的内部异常 |

## Risks / Trade-offs

- **环境变量凭据泄露** → 凭据仅在内存中存活，不写入 stdout/stderr；调用方负责注入前清理 shell history
- **type_credential 不清除 field** → 若 field 已有内容，会拼接而非覆盖；本 phase 记录为已知限制，下一 phase 可实现 tap-select-all-delete 前置步骤
- **stdout 污染** → `toolkit_api.py` 内部若有 print 语句会破坏 JSON 输出；需在 review 中确认无残留 print

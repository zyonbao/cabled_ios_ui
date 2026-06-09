## Purpose

executor 的 JSON CLI 协议——定义可执行模块入口、请求/响应格式、退出码约定与支持的 op 列表。

## Requirements

### Requirement: CLI 入口作为可执行模块运行

`toolkit_cli.py` SHALL 可通过 `python3 -B -m executor_ios.toolkit_cli` 启动，以 stdin/stdout 一次性 JSON 协议处理单条请求后退出。

#### Scenario: 正常启动并处理请求
- **WHEN** 调用方通过子进程启动 `python3 -B -m executor_ios.toolkit_cli` 并向 stdin 写入合法 JSON
- **THEN** CLI 处理请求，向 stdout 输出一个完整 JSON 响应，进程以退出码 0 结束

---

### Requirement: 请求格式

CLI SHALL 从 stdin 读取一个完整 JSON 对象，包含以下字段：

| 字段 | 必填 | 说明 |
|---|---|---|
| `op` | 是 | 操作名（见支持的 op 列表） |
| `requestId` | 否 | 原样回传，供上层排障 |
| `deadlineMs` | 否 | 超时上限（毫秒），默认 15000 |
| `args` | 是 | 操作参数对象，各 op 字段由对应 spec 定义 |

#### Scenario: 合法请求被解析
- **WHEN** stdin 包含 `{"op":"list_targets","args":{}}` 格式的 JSON
- **THEN** CLI 成功解析并路由到对应操作

#### Scenario: `op` 字段缺失
- **WHEN** stdin JSON 中不包含 `op` 字段
- **THEN** CLI 向 stdout 输出 `{"ok":false,"error":{"kind":"INTERNAL",...}}` 并以退出码 2 退出

#### Scenario: stdin 为非法 JSON
- **WHEN** stdin 内容无法被解析为合法 JSON
- **THEN** CLI 以退出码 2 退出，stdout 不输出任何内容

---

### Requirement: 响应格式

CLI SHALL 向 stdout 输出且仅输出一个完整 JSON 对象。

成功响应：
```json
{
  "ok": true,
  "requestId": "<same-as-request>",
  "data": { ... }
}
```

失败响应：
```json
{
  "ok": false,
  "requestId": "<same-as-request>",
  "error": {
    "kind": "BAD_TARGET | SUBPROCESS | NOT_IMPLEMENTED | INTERNAL",
    "message": "<human-readable>",
    "details": {}
  }
}
```

#### Scenario: requestId 原样回传
- **WHEN** 请求中包含 `"requestId": "req-42"`
- **THEN** 响应中包含 `"requestId": "req-42"`

#### Scenario: stdout 不混入日志
- **WHEN** 操作执行期间有调试信息需要输出
- **THEN** 调试信息 SHALL 写入 stderr，stdout 只包含一个 JSON 对象

---

### Requirement: 退出码约定

CLI SHALL 按下表约定的语义设置进程退出码：

| 退出码 | 含义 |
|---|---|
| 0 | 请求已处理，成功/失败看 `ok` 字段 |
| 2 | stdin JSON 解析失败或必填字段缺失 |
| 3 | 平台运行时未安装（pymobiledevice3 / WDA 不可达） |
| 4 | 内部子进程失败 |
| 5 | 执行器内部未捕获异常 |

#### Scenario: 操作成功时退出码为 0
- **WHEN** 操作正常完成（`ok: true`）
- **THEN** 进程以退出码 0 退出

#### Scenario: 操作返回业务错误时退出码为 0
- **WHEN** 操作返回 `ok: false`（如 BAD_TARGET）
- **THEN** 进程仍以退出码 0 退出（业务错误不视为 CLI 错误）

---

### Requirement: 支持的 op 列表

CLI SHALL 路由以下所有 op 到 `toolkit_api.py` 对应函数：

| op | 函数 | 必填 args | 备注 |
|---|---|---|---|
| `list_targets` | `api.list_targets()` | 无 | |
| `screenshot` | `api.screenshot(target)` | `target` | |
| `dump_ui` | `api.dump_ui(target)` | `target` | |
| `tap` | `api.tap(target, x, y)` | `target`, `x`, `y` | |
| `swipe` | `api.swipe(target, x1, y1, x2, y2)` | `target`, `x1`, `y1`, `x2`, `y2` | args 中字段名为 `durationMs`，映射到函数的 `duration_ms` |
| `input_text` | `api.input_text(target, text)` | `target`, `text` | |
| `key_event` | `api.key_event(target, key)` | `target`, `key` | |
| `launch_app` | `api.launch_app(target, package)` | `target`, `package` | `activity` 可选，iOS 忽略 |
| `kill_app` | `api.kill_app(target, package)` | `target`, `package` | |
| `switch_app_env` | `api.switch_app_env(target, env)` | `target`, `env` | 当前返回 `NOT_IMPLEMENTED` |
| `type_credential` | `api.type_credential(...)` | `target`, `env`, `role`, `field` | args 中为 `skipClear`（camelCase），映射到函数的 `skip_clear` |

#### Scenario: 未知 op 返回 NOT_IMPLEMENTED
- **WHEN** 请求 op 不在支持列表中
- **THEN** CLI 返回 `{"ok":false,"error":{"kind":"NOT_IMPLEMENTED",...}}` 并以退出码 0 退出

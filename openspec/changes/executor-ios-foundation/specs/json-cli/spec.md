# json-cli

`toolkit_cli.py` 实现的 stdin/stdout 一次性 JSON 协议，是 Studio broker 调用 iOS 平台能力的唯一入口。

## 启动方式

```bash
python3 -B -m executor_ios.toolkit_cli
```

## 请求格式（stdin）

每次调用传入一个完整 JSON 对象：

```json
{
  "op": "<operation-name>",
  "requestId": "<optional-id>",
  "deadlineMs": 15000,
  "args": { ... }
}
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `op` | 是 | 操作名，见下方支持列表 |
| `requestId` | 否 | 原样回传，方便上层排障 |
| `deadlineMs` | 否 | 超时上限（毫秒），默认 15000 |
| `args` | 是 | 操作参数，具体字段由各 op spec 定义 |

## 响应格式（stdout）

成功：
```json
{
  "ok": true,
  "requestId": "<same-as-request>",
  "data": { ... }
}
```

失败：
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

## 退出码

| 退出码 | 含义 |
|---|---|
| `0` | 请求已处理，成功/失败看 JSON `ok` 字段 |
| `2` | stdin JSON 解析失败或必填字段缺失 |
| `3` | 平台运行时未安装（pymobiledevice3 / WDA 不可达）|
| `4` | 内部子进程失败 |
| `5` | 执行器内部未捕获异常 |

## 约束

- `stdout` 只输出一个完整 JSON 对象，不混入任何额外日志
- `stderr` 可写调试日志，但绝不能包含明文凭据
- 进程处理完请求后退出，不保持常驻

## 本阶段支持的 op

| op | 对应 spec |
|---|---|
| `list_targets` | device-discovery |
| `screenshot` | screenshot |

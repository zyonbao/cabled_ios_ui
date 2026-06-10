# json-cli Specification

## MODIFIED Requirements

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
    "kind": "BAD_TARGET | SUBPROCESS | NOT_IMPLEMENTED | INTERNAL | TIMEOUT | ...",
    "code": "<stable-fine-grained-error-code>",
    "message": "<english-debug-detail>",
    "details": {}
  }
}
```

错误信封字段约定：
- `kind` SHALL 为粗粒度错误大类（向后兼容，保留既有取值）。
- `code` SHALL 为稳定、全局唯一、细粒度的错误码（大写蛇形，如 `DDI_MOUNT_TIMEOUT`），用于消费方按错误身份做本地化或分支处理；同一 `kind` 下可有多个 `code`。当某错误尚未分配专属 `code` 时，`code` MAY 省略，消费方按 `kind` 兜底。
- `message` SHALL 为英文人类可读的调试详情，仅用于日志 / 兜底展示，消费方 SHALL NOT 将其作为面向最终用户的本地化文案来源，也 SHALL NOT 对其文本做相等匹配以判定错误类型。
- 错误相关的可变量（路径、底层异常文本、类型名等）SHALL 以结构化键值放入 `details`，而非拼接进 `message`。
- 逻辑层（`ios_toolkit`）SHALL NOT 依赖任何 UI / i18n 模块来产生错误文案；本地化由消费方（UI）依据 `code` / `details` 完成。

#### Scenario: requestId 原样回传
- **WHEN** 请求中包含 `"requestId": "req-42"`
- **THEN** 响应中包含 `"requestId": "req-42"`

#### Scenario: stdout 不混入日志
- **WHEN** 操作执行期间有调试信息需要输出
- **THEN** 调试信息 SHALL 写入 stderr，stdout 只包含一个 JSON 对象

#### Scenario: 失败响应携带稳定错误码与结构化详情
- **WHEN** 某操作因可识别原因失败且已分配专属错误码
- **THEN** `error.code` 为该稳定细粒度码，`error.kind` 为其所属大类
- **AND** 相关可变量出现在 `error.details` 中，`error.message` 为英文调试详情

#### Scenario: 未分配专属码时按大类兜底
- **WHEN** 某失败尚未分配专属 `code`
- **THEN** `error.kind` 仍给出正确大类，消费方据 `kind` 兜底处理，响应不因缺 `code` 而非法

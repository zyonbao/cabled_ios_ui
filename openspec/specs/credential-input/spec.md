## ADDED Requirements

### Requirement: 凭据从环境变量读取

`secrets.py` SHALL 按约定格式 `IOS_CRED_<ROLE>_<FIELD>` 从环境变量中读取凭据，`<ROLE>` 和 `<FIELD>` 均大写。明文凭据 SHALL NOT 出现在任何日志、响应体或 stderr 输出中。

#### Scenario: 环境变量存在时读取成功
- **WHEN** 环境变量 `IOS_CRED_USER_PASSWORD` 已设置
- **THEN** `secrets.get_credential("user", "password")` 返回对应值

#### Scenario: 环境变量缺失时返回错误
- **WHEN** 对应环境变量未设置
- **THEN** `secrets.get_credential()` 返回 `None`，调用方 SHALL 返回 `BAD_TARGET` 错误

---

### Requirement: type_credential 完成真实写入

`type_credential(target, env, role, field, skip_clear=False)` SHALL 通过 `secrets.py` 读取凭据后调用 `input_text` 将其写入目标设备当前聚焦的 element。

CLI 层 SHALL 将 JSON args 中的 `skipClear`（camelCase，Contract 约定）映射为函数参数 `skip_clear`（snake_case）。`skipClear` 缺省时视为 `false`。

#### Scenario: 凭据存在时写入成功
- **WHEN** 对应环境变量已设置，且目标设备有聚焦的 text field
- **THEN** 函数返回 `{"ok":true,...}`，凭据已写入 element，明文不出现在返回值中

#### Scenario: 凭据不存在时返回 BAD_TARGET
- **WHEN** 对应环境变量未设置
- **THEN** 函数返回 `{"ok":false,"error":{"kind":"BAD_TARGET","message":"credential not found: IOS_CRED_<ROLE>_<FIELD>"}}`

#### Scenario: stderr 不输出明文凭据
- **WHEN** type_credential 执行期间发生任何错误
- **THEN** stderr 日志 SHALL NOT 包含凭据的实际值

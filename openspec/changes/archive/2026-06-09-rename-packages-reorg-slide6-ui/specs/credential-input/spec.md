## MODIFIED Requirements

### Requirement: 凭据从环境变量读取

`secrets.py` SHALL 按约定格式 `IOS_CRED_<ROLE>_<FIELD>` 从环境变量中读取凭据，`<ROLE>` 和 `<FIELD>` 均大写。明文凭据 SHALL NOT 出现在任何日志、响应体或 stderr 输出中。公开函数名（`get_credential`、`credential_env_key`）保持不变。

该模块名恢复为 `secrets.py`（先前为规避遮蔽曾改名为 `credentials.py`）之所以安全，是因为 Nuitka multidist 的 tunneld `--main` 已移至仓库根目录 `cabled_ios_tunnel.py`，`ios_toolkit/` 不再成为顶层导入根，`secrets.py` 仅以 `ios_toolkit.secrets` 被导入，不再遮蔽 stdlib 的 `secrets` 模块。

#### Scenario: 环境变量存在时读取成功
- **WHEN** 环境变量 `IOS_CRED_USER_PASSWORD` 已设置
- **THEN** `secrets.get_credential("user", "password")` 返回对应值

#### Scenario: 环境变量缺失时返回错误
- **WHEN** 对应环境变量未设置
- **THEN** `secrets.get_credential()` 返回 `None`，调用方 SHALL 返回 `BAD_TARGET` 错误

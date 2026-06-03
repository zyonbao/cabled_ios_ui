## Why

Phase 1 交付了 `toolkit_api.py`，提供了 11 项 iOS 平台操作的 Python 函数接口。Studio broker 需要通过子进程调用这些能力，而非直接导入 Python 模块。本 change 实现 `toolkit_cli.py`——一个 stdin/stdout 一次性 JSON CLI 入口，以及 `secrets.py`——凭据读取模块，从而完成 PYTHON-PLATFORM-EXECUTOR-CONTRACT 第 1-2 层规范的全部交付。

## What Changes

- 新增 `executor_ios/toolkit_cli.py`：读取 stdin JSON 请求 → 调用 `toolkit_api.py` 对应函数 → 将结果写入 stdout JSON 响应，处理完毕后退出
- 新增 `executor_ios/secrets.py`：从环境变量或本地加密存储中读取凭据，供 `type_credential` 调用；明文凭据不出现在任何日志或响应中
- `toolkit_api.py` 中的 `type_credential` 升级为真实实现（当前为 `NOT_IMPLEMENTED` 桩），调用 `secrets.py` 读取凭据后执行 `input_text`

## Capabilities

### New Capabilities

- `json-cli`：`toolkit_cli.py` 实现的 stdin/stdout 一次性 JSON 协议，支持 Phase 1 全部 9 项 op（list_targets / screenshot / dump_ui / tap / swipe / input_text / key_event / launch_app / kill_app）及 type_credential
- `credential-input`：`secrets.py` + `type_credential` 实现，从安全存储读取凭据并通过 `input_text` 写入目标 element，明文凭据不落磁盘不进日志

### Modified Capabilities

<!-- 无已有 spec 的 requirement 变更 -->

## Impact

- 新增文件：`executor_ios/toolkit_cli.py`、`executor_ios/secrets.py`
- 修改文件：`executor_ios/toolkit_api.py`（type_credential 从 NOT_IMPLEMENTED 桩升为真实实现）
- 调用方式：`python3 -B -m executor_ios.toolkit_cli`，stdin 传入 JSON，stdout 输出 JSON，一次请求一次退出
- 新增依赖：无（凭据存储方案仅依赖 Python 标准库 + 环境变量）
- 安全约束：stderr 可写调试日志，但绝不包含明文凭据；stdout 只输出一个 JSON 对象

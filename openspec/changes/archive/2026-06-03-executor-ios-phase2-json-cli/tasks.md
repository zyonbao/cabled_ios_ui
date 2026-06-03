## 1. secrets.py — 凭据读取模块

- [x] 1.1 创建 `executor_ios/secrets.py`，实现 `get_credential(role: str, field: str) -> str | None`，按 `IOS_CRED_<ROLE>_<FIELD>` 格式从环境变量读取，`role`/`field` 自动转大写
- [x] 1.2 确认 `secrets.py` 中不存在任何将凭据值写入日志或异常消息的路径

## 2. type_credential 真实实现

- [x] 2.1 在 `toolkit_api.py` 中将 `type_credential` 从 `_not_implemented` 桩升级为真实实现：调用 `secrets.get_credential(role, field)`，若返回 `None` 则返回 `BAD_TARGET`，否则调用 `input_text(target, credential_value)` 并返回其结果
- [x] 2.2 确认返回值中不包含凭据明文（`data` / `extra` 字段均不含凭据值）

## 3. toolkit_cli.py — JSON CLI 入口

- [x] 3.1 创建 `executor_ios/toolkit_cli.py`，实现 `main()` 函数：从 `sys.stdin` 读取全部内容并解析 JSON，解析失败时以退出码 2 退出
- [x] 3.2 校验必填字段 `op` 和 `args` 存在，缺失时向 stdout 写入 `{"ok":false,...}` 并以退出码 2 退出
- [x] 3.3 构建 `OP_TABLE` 字典静态映射 **11 个 op** 到 `toolkit_api` 对应函数（list_targets / screenshot / dump_ui / tap / swipe / input_text / key_event / launch_app / kill_app / switch_app_env / type_credential）
- [x] 3.4 实现 op 路由：查 `OP_TABLE`，未知 op 返回 `NOT_IMPLEMENTED`；已知 op 从 `args` 中提取参数后调用对应函数；处理以下 camelCase→snake_case 映射：`durationMs`→`duration_ms`（swipe）、`skipClear`→`skip_clear`（type_credential）
- [x] 3.5 将 `toolkit_api` 返回的 `dict` 附加 `requestId` 字段后以 `json.dumps` 写入 stdout，再以退出码 0 退出
- [x] 3.6 用 `try/except Exception` 包裹整个 `main()`，未捕获异常时向 stderr 写入错误信息并以退出码 5 退出
- [x] 3.7 在文件末尾添加 `if __name__ == "__main__": main()`，确保 `-m executor_ios.toolkit_cli` 可直接启动

## 4. 验收检查

- [x] 4.1 `echo '{"op":"list_targets","args":{}}' | python3 -m executor_ios.toolkit_cli` 返回含设备信息的 JSON，退出码 0
- [x] 4.2 `echo '{"op":"screenshot","args":{"target":"<udid>"}}' | python3 -m executor_ios.toolkit_cli` 返回含 base64 PNG 的 JSON
- [x] 4.3 `echo '{"op":"unknown_op","args":{}}' | python3 -m executor_ios.toolkit_cli` 返回 `NOT_IMPLEMENTED` JSON，退出码 0
- [x] 4.4 `echo 'not json' | python3 -m executor_ios.toolkit_cli` 退出码为 2
- [x] 4.5 `echo '{"op":"type_credential","args":{"target":"<udid>","env":"staging","role":"user","field":"password"}}' | python3 -m executor_ios.toolkit_cli` 在未设置环境变量时返回 `BAD_TARGET`
- [x] 4.6 设置 `IOS_CRED_USER_PASSWORD=test123` 后重复 4.5，在设备有聚焦 text field 时返回 `ok: true`，返回值中不含 `test123`
- [x] 4.7 验证 stdout 只输出一个 JSON 对象，无额外换行或日志混入

## MODIFIED Requirements

### Requirement: CLI 入口作为可执行模块运行

`toolkit_cli.py` SHALL 可通过 `python3 -B -m ios_toolkit.toolkit_cli` 启动，以 stdin/stdout 一次性 JSON 协议处理单条请求后退出。

#### Scenario: 正常启动并处理请求
- **WHEN** 调用方通过子进程启动 `python3 -B -m ios_toolkit.toolkit_cli` 并向 stdin 写入合法 JSON
- **THEN** CLI 处理请求，向 stdout 输出一个完整 JSON 响应，进程以退出码 0 结束

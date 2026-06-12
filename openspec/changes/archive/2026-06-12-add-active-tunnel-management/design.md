# 设计：活动 XPC tunnel 管理

## 背景与约束

- tunneld 进程有两种启动形态（见 `tunnel.py._tunneld_command`）：
  - 开发：`<venv>/bin/python -m ios_toolkit.tunneld_main --port <n>`
  - 冻结：`<bundle>/Contents/MacOS/cabled_ios_tunnel --port <n>`
- tunneld 以 **root** 运行（经 `osascript ... with administrator privileges` 拉起）。
- 现有 `is_tunnel_running` / `stop_tunneld` 只看**当前配置端口**（`get_tunnel_port()`），无法覆盖其它端口残留进程。
- 安全基线：提权命令字符串只能由内部固定推导路径 + 校验过的整数 PID 组成，绝不拼接界面/外部自由文本。

## 进程发现（无需提权）

- 用 `ps -axww -o pid=,user=,command=` 列出全部进程的完整命令行。macOS 上非 root 即可读取其它用户（含 root）的进程命令行，因此**发现阶段不需要管理员权限**。
- 逐行用稳定标记匹配 tunneld：
  - Python 模式：命令行同时（或分别）包含 `ios_toolkit.tunneld_main` 或 `tunneld_main.py`。
  - MachO 模式：命令行包含 `cabled_ios_tunnel`（作为可执行名/路径出现）。
- 解析字段：`pid`（int）、`user`、`port`（从 `--port <n>` 正则解析，缺省/解析失败标记为未知）、`mode`（python / macho）、`command`（完整命令行，仅用于展示）。
- 排除自身进程与明显误匹配（如该管理对话框自身命令行中出现关键词时不计入；通过精确匹配 argv 形态降低误报）。

**决策**：发现用 `ps` 文本解析而非依赖端口探测，因为要覆盖"任意端口"的残留进程，端口探测只能验证单个已知端口。

## 批量结束（单次授权）

- UI 允许多选若干 PID，点击「批量结束」。
- 仅校验每个 PID 为正整数后，构造**单条** shell：
  - `kill <pids>; sleep 1; kill -9 <仍存活的 pids>`（TERM 优先、KILL 兜底），全部 PID 以空格拼接。
  - 整条命令放入一个 `do shell script "..." with administrator privileges`，因此**只弹一次**授权框、只输入一次密码。
- 非 root 的 tunneld（理论上少见，但 Python 模式若由普通用户直接启动则可能）一并在同一特权上下文 kill，简化逻辑。
- 结束后回到 UI 线程刷新列表。

**决策**：复用现有 `osascript do shell script` 单提权模式（与 `restart_tunneld` 的"单次授权 kill+relaunch"一致），保证多选只输一次密码。

**安全**：PID 来自 `ps` 解析并经 `str.isdigit()` / `int()` 校验后再拼接，命令中不含任何用户可编辑文本；`command` 字段只用于界面展示，绝不回写进 shell。

## UI

- 入口：「开发者工具」tab 新增按钮「管理活动 tunnel」（与统一 tunnel 入口同区域）。
- 弹出对话框（模态）：表格列出 PID / 用户 / 端口 / 形态 / 命令行，每行可勾选；底部「刷新」「批量结束（n）」按钮（无选中时禁用）。
- 列表为空时显示「未发现活动 tunnel 进程」。
- 批量结束进行中禁用按钮，完成或失败后刷新并提示结果；授权取消/失败不崩溃。

## 不做的事

- 不在「诊断」「键鼠操作」tab 暴露该入口（保持 tunnel 管理统一在「开发者工具」）。
- 不自动清理残留进程；一切由用户显式选择并确认授权。
- 不改动当前端口 tunnel 的启动/停止/重启既有逻辑。

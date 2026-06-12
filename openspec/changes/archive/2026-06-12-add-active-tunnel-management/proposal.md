# 新增「活动 XPC tunnel 管理」功能

## Why

- 现在 XPC tunnel 端口可在「偏好设置」中配置，用户改端口后再启动，会在系统中遗留**多个端口号不同**的 tunneld 进程。
- 现有 tunnel 控制（启动 / 停止 / 重启）只针对**当前配置端口**这一个 tunnel，无法发现或清理其它端口残留的 tunneld 进程。
- 残留的 tunneld 进程以 root 运行、占用端口与资源，用户难以察觉与管理，容易造成端口冲突或行为异常。

需要一个集中查看并批量清理所有活动 tunneld 进程的入口。

## What Changes

- 在「开发者工具」tab（tunnel 统一入口）新增「管理活动 tunnel」入口，弹出列表展示当前系统中**所有** tunneld 进程（不限于当前配置端口）。
- 进程发现按启动形态匹配：
  - **Python 模式**：命令行匹配 tunneld 的 Python 入口（`ios_toolkit.tunneld_main` 模块 / `tunneld_main.py` 文件路径）。
  - **MachO 模式**：命令行匹配随包分发的 `cabled_ios_tunnel` 二进制文件 / 路径。
- 列表展示每个进程的 PID、运行用户、监听端口（从 `--port` 解析）、启动形态（Python / MachO）、完整命令行。
- 支持**多选批量结束**进程；批量结束时只触发**一次**系统授权（管理员密码只输入一次），在同一提权上下文内 kill 选中的全部 PID。
- 结束后刷新列表；支持手动刷新。

## Impact

- Affected specs: `slide6-tunnel-bootstrap`（新增「活动 tunnel 发现与批量清理」相关 Requirement）
- Affected code:
  - `slide6_ui/common/tunnel.py`：新增进程发现（list_tunnel_processes）与批量结束（kill_tunnel_processes，单次授权）能力。
  - `slide6_ui/developer_tools/developer_tools_tab.py`：新增「管理活动 tunnel」入口与弹出管理对话框。
  - `slide6_ui/languages/zh-CN.json` / `en-US.json`：新增相关文案键。
- 不改变现有"当前端口" tunnel 的启动 / 停止 / 重启行为；本功能是其补充。

## 1. 进程发现能力（tunnel.py）

- [x] 1.1 新增 `list_tunnel_processes() -> list[dict]`：用 `ps -axww -o pid=,user=,command=` 列举进程并按形态匹配（Python：`ios_toolkit.tunneld_main` / `tunneld_main.py`；MachO：`cabled_ios_tunnel`）
- [x] 1.2 为每个匹配项解析 `pid`(int) / `user` / `port`(从 `--port <n>` 正则，失败为 None) / `mode`('python'|'macho') / `command`(完整命令行)
- [x] 1.3 排除自身/误匹配；对解析异常做容错（单行失败不影响整体）
- [x] 1.4 发现路径不触发任何 osascript / 提权

## 2. 批量结束能力（tunnel.py）

- [x] 2.1 新增 `kill_tunnel_processes(pids: list[int]) -> bool`：校验每个 pid 为正整数，构造单条 `kill <pids>; sleep 1; kill -9 <存活者>` 并经**单次** `do shell script ... with administrator privileges` 执行
- [x] 2.2 命令仅由固定字符串 + 校验后的整数 PID 组成，不拼接任何外部文本；空列表直接返回
- [x] 2.3 授权取消 / 超时 / 失败返回 False 且不抛出

## 3. 管理对话框 UI（developer_tools_tab.py）

- [x] 3.1 新增「管理活动 tunnel」按钮（与统一 tunnel 控制同区域）
- [x] 3.2 实现弹出对话框：表格列 PID / 用户 / 端口 / 形态 / 命令行，每行可勾选（多选）
- [x] 3.3 底部「刷新」「批量结束（n）」按钮；无选中时禁用批量结束；列表为空显示空态文案
- [x] 3.4 发现/结束均经 AsyncRunner 在后台线程执行，回 UI 线程刷新；结束进行中禁用按钮
- [x] 3.5 结束完成/失败后刷新列表并给出结果提示（非崩溃）

## 4. i18n 文案

- [x] 4.1 `zh-CN.json`：新增管理入口、对话框标题、列头、空态、批量结束、结果提示等文案键
- [x] 4.2 `en-US.json`：与 zh-CN 同步，保持键集一致

## 5. 验证

- [x] 5.1 运行 lint（ReadLints）确认 tunnel.py / developer_tools_tab.py 无报错
- [ ] 5.2 手动验证：改不同端口启动多个 tunnel 后，管理列表能列全；Python / MachO 形态标记正确；端口解析正确
- [ ] 5.3 手动验证：多选批量结束只输入一次密码；结束后列表刷新；取消授权不崩溃
- [ ] 5.4 手动验证：入口仅在「开发者工具」出现
- [x] 5.5 `openspec validate add-active-tunnel-management --strict` 通过

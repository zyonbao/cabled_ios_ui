## MODIFIED Requirements

### Requirement: 用 multidist 合并 GUI 与 tunneld 入口共享依赖

打包脚本 SHALL 使用 Nuitka multidist（一次构建传入多个 `--main`：`CablediOS.py` 与 `cabled_ios_tunnel.py`，两者均位于仓库根目录并使用绝对导入以兼容 multidist 顶层 `__main__`，从而避免任何包内目录成为顶层导入根），产出共享同一份依赖的单一依赖树，使 GUI 与 tunneld 两个入口的公共依赖（如 `pymobiledevice3`）只打包一份。打包脚本 SHALL 在 `CablediOS.app/Contents/MacOS/` 内提供名为 `cabled_ios_tunnel` 的可执行入口（指向 multidist 主二进制的副本或符号链接），使应用在冻结环境下无需 Python 解释器即可以管理员权限拉起 tunneld。

#### Scenario: 公共依赖只分发一份

- **WHEN** 打包脚本成功完成
- **THEN** GUI 与 tunneld 共享同一份依赖目录，`pymobiledevice3` 等公共依赖不被重复分发两份

#### Scenario: 打包后 App bundle 内含 cabled_ios_tunnel 入口

- **WHEN** 打包脚本成功完成
- **THEN** `CablediOS.app/Contents/MacOS/cabled_ios_tunnel` 存在且具有可执行权限

#### Scenario: 以 cabled_ios_tunnel 名称调用时分发到 tunneld 入口

- **WHEN** 以 root 通过 `CablediOS.app/Contents/MacOS/cabled_ios_tunnel` 路径运行（`sys.argv[0]` basename 为 `cabled_ios_tunnel`）
- **THEN** multidist 二进制分发到 tunneld 入口，进程在 `127.0.0.1:49151` 监听并提供 tunneld REST API

#### Scenario: 默认启动分发到 GUI 入口

- **WHEN** 用户正常启动 `CablediOS.app`
- **THEN** multidist 二进制分发到 GUI 入口，显示设备控制台窗口

# nuitka-macos-packaging Specification

## Purpose
TBD - created by archiving change add-nuitka-macos-packaging. Update Purpose after archive.
## Requirements
### Requirement: 提供 Nuitka 打包脚本产出 CablediOS.app

仓库 SHALL 提供一个可重复执行的 Nuitka 打包脚本，用于在 macOS 上将 `executor_ios` 与 `slide6_console` 编译为非 onefile 的独立应用 `CablediOS.app`。脚本 SHALL 启用 PySide6 插件并显式包含 `pymobiledevice3` 包，使产物在未安装 Python 与依赖的 macOS 上可运行。

#### Scenario: 执行打包脚本生成主 App

- **WHEN** 在已安装 Nuitka 与项目依赖的 macOS 上执行打包脚本
- **THEN** 在输出目录生成 `CablediOS.app`
- **AND** 该 App 以 `slide6_console.app:main` 为入口，启动后显示设备控制台窗口

#### Scenario: 缺少构建依赖时给出明确报错

- **WHEN** 执行打包脚本但环境缺少 Nuitka 或必要依赖
- **THEN** 脚本以非零状态退出并打印缺失项与修复提示，不产出半成品 App

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

### Requirement: 为 CablediOS.app 设置应用图标

打包脚本 SHALL 由 `slide6_console/AppIcon.png` 生成多分辨率 `.icns`，并经 Nuitka `--macos-app-icon` 设为 `CablediOS.app` 的应用图标，使其在 Finder 与 Dock 中显示自定义图标。

#### Scenario: 打包后 App 显示自定义图标

- **WHEN** 打包脚本成功完成
- **THEN** `CablediOS.app` 在 Finder 与 Dock 中显示由 `AppIcon.png` 生成的图标，而非默认通用图标

#### Scenario: 源图标缺失时的处理

- **WHEN** 执行打包脚本但 `AppIcon.png` 不存在
- **THEN** 脚本跳过图标设置并打印警告，仍产出可运行的 `CablediOS.app`（使用默认图标）

### Requirement: 冻结环境下 pymobiledevice3 依赖完整可用

打包产物 SHALL 包含 `executor_ios` 运行所需的 `pymobiledevice3` 子模块（含 `usbmux`、`lockdown`、`installation_proxy`、`remote_service_discovery`、`dvt.testmanaged.xcuitest` 等懒加载引用），使设备发现与 WDA 生命周期在 iOS≤16 与 iOS17+ 两条路径下均可运行。

#### Scenario: 冻结 App 中列出设备

- **WHEN** 在冻结的 `CablediOS.app` 中连接 USB iOS 设备并刷新设备列表
- **THEN** 应用成功调用 `pymobiledevice3` 完成设备发现，不因模块缺失而失败

#### Scenario: 冻结 App 中启动 iOS 17+ 设备的 WDA

- **WHEN** 在冻结 App 中选中一台 iOS 17+ 设备并启动 WDA
- **THEN** 应用经 tunneld RSD 与 `pymobiledevice3` 的 XCUITest 服务成功拉起 WDA，不因子模块被裁剪而失败


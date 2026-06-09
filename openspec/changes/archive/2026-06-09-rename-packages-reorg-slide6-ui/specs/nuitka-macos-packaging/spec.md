## MODIFIED Requirements

### Requirement: 提供 Nuitka 打包脚本产出 CablediOS.app

仓库 SHALL 提供一个可重复执行的 Nuitka 打包脚本，用于在 macOS 上将 `ios_toolkit` 与 `slide6_ui` 编译为非 onefile 的独立应用 `CablediOS.app`。脚本 SHALL 启用 PySide6 插件并显式包含 `pymobiledevice3` 包，使产物在未安装 Python 与依赖的 macOS 上可运行。

#### Scenario: 执行打包脚本生成主 App

- **WHEN** 在已安装 Nuitka 与项目依赖的 macOS 上执行打包脚本
- **THEN** 在输出目录生成 `CablediOS.app`
- **AND** 该 App 以 `slide6_ui.app:main` 为入口，启动后显示设备控制台窗口

#### Scenario: 缺少构建依赖时给出明确报错

- **WHEN** 执行打包脚本但环境缺少 Nuitka 或必要依赖
- **THEN** 脚本以非零状态退出并打印缺失项与修复提示，不产出半成品 App

### Requirement: 为 CablediOS.app 设置应用图标

打包脚本 SHALL 由 `slide6_ui/AppIcon.png` 生成多分辨率 `.icns`，并经 Nuitka `--macos-app-icon` 设为 `CablediOS.app` 的应用图标，使其在 Finder 与 Dock 中显示自定义图标。

#### Scenario: 打包后 App 显示自定义图标

- **WHEN** 打包脚本成功完成
- **THEN** `CablediOS.app` 在 Finder 与 Dock 中显示由 `AppIcon.png` 生成的图标，而非默认通用图标

#### Scenario: 源图标缺失时的处理

- **WHEN** 执行打包脚本但 `AppIcon.png` 不存在
- **THEN** 脚本跳过图标设置并打印警告，仍产出可运行的 `CablediOS.app`（使用默认图标）

### Requirement: 冻结环境下 pymobiledevice3 依赖完整可用

打包产物 SHALL 包含 `ios_toolkit` 运行所需的 `pymobiledevice3` 子模块（含 `usbmux`、`lockdown`、`installation_proxy`、`remote_service_discovery`、`dvt.testmanaged.xcuitest` 等懒加载引用），使设备发现与 WDA 生命周期在 iOS≤16 与 iOS17+ 两条路径下均可运行。

#### Scenario: 冻结 App 中列出设备

- **WHEN** 在冻结的 `CablediOS.app` 中连接 USB iOS 设备并刷新设备列表
- **THEN** 应用成功调用 `pymobiledevice3` 完成设备发现，不因模块缺失而失败

#### Scenario: 冻结 App 中启动 iOS 17+ 设备的 WDA

- **WHEN** 在冻结 App 中选中一台 iOS 17+ 设备并启动 WDA
- **THEN** 应用经 tunneld RSD 与 `pymobiledevice3` 的 XCUITest 服务成功拉起 WDA，不因子模块被裁剪而失败

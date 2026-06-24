# Phase 3 — 多设备支持与设备管理器

## 背景

Phase 1/2 已实现单设备场景下的完整平台能力层（`toolkit_api.py` + `toolkit_cli.py`），每次操作通过 ephemeral 端口转发 + 每次新建 WDA session 完成。

Phase 3 目标：引入 `iOSDevicesManager` 和 `iOSDevice` 类，将设备发现、持久端口转发、WDA 进程生命周期管理、session 复用等逻辑面向对象化，支持多台 USB 设备并发使用。

## 变更范围

- **新增** `executor_ios/device.py`：包含 `iOSDevice` 和 `iOSDevicesManager`
- **新增** `executor_ios/tunneld_main.py`：tunneld 守护进程入口，打包为独立的 `ios_tunneld` 二进制
- **更新** `executor_ios/toolkit_api.py`：从 ephemeral 模式迁移到 `iOSDevicesManager` 驱动

## 核心设计原则

1. **持久端口转发**：`iOSDevice` 持有后台事件循环中运行的 usbmux 转发，生命周期与对象相同，操作函数直接使用 `self.local_port` 发 HTTP 请求，无需 `asyncio.run()` 包装
2. **WDA 按需启动**：不负责安装 WDA；WDA 未安装时设备标记为 `offline`；WDA 已安装但未运行时，操作前自动调用 `do_prepare()` 启动
3. **Session 复用**：同一进程内对同一设备复用 WDA session ID，失效时自动重建，避免重复 `POST /session`
4. **RSD 自动查询**：iOS 17+ 设备的 XPC tunnel RSD 信息由 `do_prepare()` 自动查询本地 tunneld（`http://127.0.0.1:49151`）获取，无需手动配置环境变量；tunneld 以独立守护进程（`ios_tunneld`）root 运行

## 不在范围内

- Wi-Fi 配对设备（全程不发现、不注册、不操作）
- WDA 安装（用户手动安装，代码不介入）
- XPC tunnel 进程管理（始终由用户在外部独立运行）
- iOS 模拟器

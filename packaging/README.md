# 打包 CablediOS.app（Nuitka）

用 Nuitka 把 `executor_ios` + `slide6_console` 打包成独立的 macOS 应用 `CablediOS.app`，
分发给没有 Python / pymobiledevice3 环境的使用者。

## 前置条件

- macOS（脚本仅支持 Darwin），且已安装 Xcode 命令行工具（提供 `sips`、`iconutil`）。
- 一个装好运行期依赖的 Python 环境（优先使用仓库的 `.venv`）。

安装依赖（建议都装进同一个 `.venv`）：

```bash
.venv/bin/python -m pip install -r executor_ios/requirements.txt
.venv/bin/python -m pip install -r slide6_console/requirements.txt
.venv/bin/python -m pip install -r packaging/requirements-build.txt
```

## 构建

```bash
packaging/build_macos_app.sh
```

产物：`build/nuitka/CablediOS.app`（非 onefile，已在 `.gitignore` 的 `build/` 内）。

脚本是幂等的：每次运行会先清空 `build/nuitka/` 再构建。

## 架构：multidist 共享依赖

GUI 与 tunneld 守护进程都依赖 `pymobiledevice3`。为避免公共依赖被打包两份，脚本用
Nuitka 的 **multidist**（一次构建传入两个 `--main`）生成单一依赖树：

- GUI 入口：`slide6_console/app.py` → 分发名 basename `app`
- tunneld 入口：`executor_ios/ios_tunneld.py` → 分发名 basename `ios_tunneld`

运行时 Nuitka 按 `sys.argv[0]` 的 basename 选择执行哪个入口。构建后脚本在
`CablediOS.app/Contents/MacOS/` 内创建名为 `ios_tunneld` 的入口（指向 GUI 主二进制的
符号链接）；`slide6_console/tunnel.py` 以管理员权限拉起 iOS 17+ 的 XPC tunnel 时即调用它。

> multidist + `--macos-create-app-bundle` 在 Nuitka 中标记为 experimental。若未能产出
> app bundle，脚本会自动回退到“两次 standalone 构建 + 合并 dist”（见脚本 `build_fallback`）。

## 应用图标

脚本由 `slide6_console/AppIcon.png` 生成多分辨率 `.icns`（`sips` + `iconutil`），经
`--macos-app-icon` 设为 App 图标。源图标缺失时跳过并告警，仍产出可运行的 App（默认图标）。

## 已知限制

- **未签名 / 未公证**：首次启动会被 Gatekeeper 拦截。放行方式：
  - 右键 `CablediOS.app` → 打开，确认；或
  - 系统设置 → 隐私与安全性 → “仍要打开”；或
  - 去除隔离属性：`xattr -dr com.apple.quarantine build/nuitka/CablediOS.app`
- 仅支持 USB 连接的 iOS 设备（沿用 executor_ios 现状）。
- iOS 17+ 设备每次启动 XPC tunnel 需一次系统管理员授权（按需拉起，不做持久化免授权）。

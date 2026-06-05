## Why

当前 `slide6_console` 桌面应用只能在已配置好 Python 环境与 `.venv` 的开发机上以 `python -m slide6_console.app` 方式运行，无法直接分发给没有 Python / pymobiledevice3 的使用者。需要用 Nuitka 将 `executor_ios` + `slide6_console` 打包成一个独立的 macOS 应用（`CablediOS.app`）。但现有代码在运行期依赖源码树布局与解释器路径（尤其是 `tunnel.py` 对 tunneld 的拉起方式），在冻结打包后会失效，必须先做兼容性处理。

## What Changes

- 重构 `slide6_console/tunnel.py` 的 tunneld 拉起逻辑：不再依赖 `.venv/bin/python` 或 `sys.executable` 运行 `python -m executor_ios.tunneld_main`，改为在冻结环境下定位并执行随包分发的独立 `ios_tunneld` 可执行文件；开发环境保持原有解释器方式作为回退。
- 修正 tunneld 入口存在性校验：从校验 `executor_ios/tunneld_main.py` 源文件改为校验实际可执行入口（冻结环境校验 bundled 二进制，开发环境校验源文件）。
- 为 `executor_ios/device.py` 中对 `pymobiledevice3` 子模块的函数内懒加载补充 Nuitka 静态分析可见的导入提示，确保被打包进产物。
- 将 `executor_ios/secrets.py` 重命名为 `executor_ios/credentials.py`：在冻结产物中，包内同级模块会成为顶层可导入名，`secrets.py` 会遮蔽 stdlib 的 `secrets`（pymobiledevice3 依赖其 `token_hex`），导致 tunneld 启动失败。公开函数名（`get_credential`/`credential_env_key`）保持不变。
- 新增极薄入口包装（均使用绝对导入，避免 multidist 顶层 `__main__` 下相对导入失败）：`CablediOS.py`（GUI，basename 即 `CablediOS`，成为 `CFBundleExecutable`）与 `executor_ios/ios_tunneld.py`（tunneld，basename `ios_tunneld`）。
- 采用 Nuitka multidist（多个 `--main`）一次构建出 GUI 与 tunneld 两个入口，**共享同一份依赖**（pymobiledevice3 等只打包一份），避免公共依赖被分发两份。
- 新增 Nuitka 打包脚本，产出非 onefile 的 `CablediOS.app`（含 PySide6 插件、`pymobiledevice3` 等依赖），并在 bundle 内创建 `ios_tunneld` 入口（指向 multidist 主二进制的副本/符号链接）。
- 使用 `slide6_console/AppIcon.png` 生成 `.icns` 并设为 `CablediOS.app` 的应用图标（`--macos-app-icon`）。

## Capabilities

### New Capabilities
- `nuitka-macos-packaging`: 用 Nuitka 把 `executor_ios` + `slide6_console` 打包为独立的 macOS 应用 `CablediOS.app`，包含主 App 与随包分发的 `ios_tunneld` 二进制及其构建脚本。

### Modified Capabilities
- `slide6-tunnel-bootstrap`: tunneld 的拉起方式从“用 Python 解释器运行 `-m executor_ios.tunneld_main`”改为“在冻结环境下运行随包分发的 `ios_tunneld` 二进制，开发环境回退到解释器方式”，入口存在性校验目标随之调整。
- `credential-input`: 凭据读取模块由 `secrets.py` 重命名为 `credentials.py`（避免在冻结产物中遮蔽 stdlib `secrets`）；公开函数行为不变。

## Impact

- 代码：`slide6_console/tunnel.py`（tunneld 定位/拉起/校验）、`executor_ios/device.py`（懒加载导入提示）、`executor_ios/secrets.py`→`credentials.py`（重命名）、`executor_ios/toolkit_api.py`（更新 import）。
- 新增：`CablediOS.py`（multidist GUI 入口包装）、`executor_ios/ios_tunneld.py`（multidist tunneld 入口包装）、Nuitka 打包脚本（`packaging/build_macos_app.sh`）。
- 依赖：构建期新增 `nuitka`、`ordered-set`、`zstandard`（Nuitka 推荐）；运行期依赖不变（PySide6、requests、pymobiledevice3）。
- 资源：`slide6_console/AppIcon.png`（1254×1254）转 `.icns` 用作 App 图标。
- 分发：产物从“源码 + venv”变为 `CablediOS.app`（内嵌 `ios_tunneld`，带应用图标）。
- 不改变运行期行为与用户交互流程（仅改变 tunneld 的定位与启动机制）。

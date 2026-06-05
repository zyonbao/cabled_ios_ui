## Context

`slide6_console` 是基于 PySide6 的桌面应用，进程内调用 `executor_ios.toolkit_api` 控制 USB 连接的 iOS 设备。iOS 17+ 设备需要一个以 root 运行、监听 `127.0.0.1:49151` 的 XPC tunnel 守护进程（`executor_ios.tunneld_main`），由 `tunnel.py` 通过 `osascript ... with administrator privileges` 按需拉起。

当前运行期对“源码树 + Python 解释器”有三处硬依赖，冻结打包后均会失效：

1. `tunnel._repo_root()` 用 `Path(__file__).resolve().parent.parent` 定位仓库根，冻结后指向不可用路径。
2. `tunnel._interpreter()` 取 `.venv/bin/python` 或 `sys.executable`；冻结后 `sys.executable` 指向 App 主二进制而非 Python，`python -m executor_ios.tunneld_main` 无法运行。
3. `launch_tunneld()` 校验 `executor_ios/tunneld_main.py` 源文件是否存在；冻结后无 `.py` 源文件，校验恒为 False。

此外 `device.py` 中对 `pymobiledevice3` 各子模块全部为函数体内懒加载，Nuitka 静态分析难以追踪，存在被裁掉的风险。

约束：不改变运行期交互行为；tunneld 必须仍以 root 启动；命令路径固定、不拼接外部输入（沿用现有安全约束）。

## Goals / Non-Goals

**Goals:**
- 使 `executor_ios` + `slide6_console` 能被 Nuitka 冻结为独立的 `CablediOS.app`，在无 Python/pymobiledevice3 的 macOS 上运行。
- tunneld 在冻结环境下以随包分发的独立 `ios_tunneld` 二进制启动，开发环境保持解释器方式回退。
- 提供一键 Nuitka 打包脚本，产出 `CablediOS.app` 并内嵌 `ios_tunneld`。

**Non-Goals:**
- 不做代码签名 / 公证（notarization）/ DMG 制作（留作后续）。
- 不引入自动更新机制。
- 不改变 WDA 生命周期、镜像、手势、键盘等业务逻辑。
- 不支持 Wi-Fi 设备（沿用仅 USB 的现状）。

## Decisions

### 决策 1：GUI 与 tunneld 用 Nuitka multidist 合并为单一依赖树

主 App 冻结后 `sys.executable` 即 App 自身，无法当作 `python -m ...` 来跑子模块，因此 tunneld 必须有独立可执行入口。GUI 与 tunneld 都重度依赖 `pymobiledevice3`，若各自 standalone 打包会让公共依赖（libpython、pymobiledevice3、cryptography 等）被分发两份。

采用 Nuitka 的 **multidist** 特性（官方 Use Case 6，2.4+ 稳定）：一次构建传入多个 `--main`，生成单一二进制，多个入口**共享同一份依赖**，公共依赖只打包一份。运行时按 `sys.argv[0]` 的 basename 选择执行哪个入口。

multidist 的每个 `--main` 都被编译为顶层 `__main__`（无父包），因此入口脚本**不能使用相对导入**，否则运行时报 `attempted relative import with no known parent package`。`slide6_console/app.py` 使用了包内相对导入，不能直接作为入口；故为两个入口都新增「绝对导入」的极薄包装，且其 basename 即为期望的分发名/可执行名：
- `CablediOS.py`（GUI）：`from slide6_console.app import main; main()` → basename `CablediOS`，成为 `CFBundleExecutable`。
- `executor_ios/ios_tunneld.py`（tunneld）：`from executor_ios.tunneld_main import main; main()` → basename `ios_tunneld`。

构建命令形如：

```
nuitka --standalone --macos-create-app-bundle --enable-plugin=pyside6 \
       --include-package=pymobiledevice3 \
       --main=CablediOS.py --main=executor_ios/ios_tunneld.py
```

在产出的 `CablediOS.app/Contents/MacOS/` 内放置名为 `ios_tunneld` 的副本/符号链接指向 multidist 主二进制；`tunnel.py` 以该路径经 osascript 提权执行时，argv[0] basename 为 `ios_tunneld`，正确分发到 tunneld 入口。GUI 入口（basename `app`）由 .app 的 `CFBundleExecutable` 启动。

- 备选 A（回退）：GUI 与 tunneld 各自 `--standalone` 打包，再把两份 dist 覆盖合并到同一目录共享依赖。被列为回退：要求两份依赖完全一致才能安全覆盖，且 multidist + app bundle 属 experimental，若组合出问题则启用此回退。
- 备选 B：让主 App 接收特殊参数（如 `--run-tunneld`）后转身扮演 tunneld。被否决：会把整套 PySide6/GUI 依赖也以 root 拉起，攻击面更大。multidist 已能共享依赖，无需让 GUI 二进制以 root 运行。

### 决策 2：用 `frozen` 检测区分运行环境，集中在 tunnel.py 的两个 helper 中

新增一个判定函数（基于 `getattr(sys, "frozen", False)` 与 Nuitka 的 `__compiled__`），并改造：
- `_tunneld_command()`：冻结环境返回 `[<bundled ios_tunneld 路径>]`；开发环境返回 `[<interpreter>, "-m", "executor_ios.tunneld_main"]`。
- 入口存在性校验：冻结环境校验 bundled 二进制存在；开发环境校验 `tunneld_main.py` 源文件存在。

冻结环境下 bundled 二进制定位为 `Path(sys.executable).parent / "ios_tunneld"`（即 `Contents/MacOS/` 下与主二进制同级）。

- 备选：用环境变量显式声明产物路径。被否决：增加分发配置负担，且 `Contents/MacOS/` 同级是 .app 的稳定约定。

### 决策 3：device.py 懒加载保留，新增 Nuitka 可见的静态导入提示

保留函数体内懒加载（避免循环导入与启动开销），但在模块顶部加入 `TYPE_CHECKING` 之外的静态分析提示块（`if False:` 守卫的 import），让 Nuitka 能发现这些子模块。同时在打包脚本中显式 `--include-package=pymobiledevice3`，双保险。

- 备选：把所有懒加载改成模块级导入。被否决：会重新引入循环导入风险并拖慢启动。

### 决策 4：打包脚本用 standalone multidist + macOS app bundle，单次构建

打包脚本以一次 `nuitka --standalone --macos-create-app-bundle --enable-plugin=pyside6 --include-package=pymobiledevice3 --main=CablediOS.py --main=executor_ios/ios_tunneld.py` 完成构建（非 onefile），产物为 `CablediOS.app`；构建后在 `Contents/MacOS/` 内创建名为 `ios_tunneld` 的副本/符号链接指向 multidist 主二进制并赋可执行权限。脚本幂等、可重复执行。若 multidist + app bundle 组合失败，脚本回退到“两次 standalone 构建 + dist 覆盖合并”（决策 1 备选 A）。

## Risks / Trade-offs

- [pymobiledevice3 动态导入/插件被裁剪] → 显式 `--include-package=pymobiledevice3`，并在 device.py 加静态导入提示；构建后做一次真机冒烟测试覆盖 iOS≤16 与 iOS17+ 两条路径。
- [公共依赖（pymobiledevice3 等）被分发两份导致体积翻倍] → 用 multidist 单次构建共享依赖只打一份；不采用各自独立 standalone。
- [multidist + `--macos-create-app-bundle` 属 experimental，组合行为不确定（如哪个入口成为 .app 默认启动项）] → 保留“两次 standalone + dist 覆盖合并”作为回退；构建后校验 .app 默认启动 GUI、`ios_tunneld` 可独立执行，必要时调整 product name / `CFBundleExecutable`。
- [osascript 以管理员权限执行 bundle 内二进制，路径含空格] → 沿用现有 `_applescript_quote` 转义并对路径加引号；二进制路径来自内部固定推导，不含外部输入。
- [未签名/未公证导致 Gatekeeper 拦截] → 本次 Non-Goal，README/脚本输出中提示使用者首次需手动放行；后续单独处理签名。
- [Nuitka 与 PySide6 版本兼容] → 脚本中固定 Nuitka 版本范围并在失败时给出明确报错；不在本变更内锁死具体版本号。

## Context

当前 Nuitka multidist 打包传入两个 `--main`：

- GUI：仓库根目录 `CablediOS.py`（绝对导入，basename `CablediOS`）。
- tunneld：包内 `executor_ios/ios_tunneld.py`（绝对导入，basename `ios_tunneld`）。

Nuitka/CPython 对 `--main`（即 `__main__` 脚本）的处理是：脚本所在目录成为顶层导入根（等价于 `sys.path[0]`）。因此当 tunneld 的 `--main` 位于 `executor_ios/` 内时，`executor_ios/` 目录成为顶层根，目录里的 `secrets.py` 可被以顶层名 `secrets` 导入，从而遮蔽 stdlib 的 `secrets`（`pymobiledevice3` 在 tunneld 进程内 `import secrets`）。为规避此问题，先前把文件改名为 `credentials.py`。

GUI 入口 `CablediOS.py` 位于仓库根目录，根目录没有 `secrets.py`，故从不触发遮蔽——这也正是它放在外层的额外好处。

## Goals / Non-Goals

**Goals:**
- 把 tunneld 的 multidist `--main` 移到仓库根目录，使 `executor_ios/` 不再成为顶层导入根，从根本上消除 `secrets` 遮蔽。
- 将 `executor_ios/credentials.py` 恢复为 `executor_ios/secrets.py`，保持公开 API（`get_credential`、`credential_env_key`）不变。
- 保留 `executor_ios/ios_tunneld.py` 以支持非打包（开发）模式下手动启动 tunneld。

**Non-Goals:**
- 不改变 tunneld 的运行端口、REST 行为或授权拉起流程。
- 不改变凭据读取的环境变量约定（`IOS_CRED_<ROLE>_<FIELD>`）与脱敏要求。
- 不改变 GUI 入口 `CablediOS.py`。

## Decisions

### 决策 1：新增根目录入口 `cabled_ios_tunnel.py` 作为 tunneld 的 `--main`

新增仓库根目录文件 `cabled_ios_tunnel.py`，内容为薄包装器，绝对导入并委托：

```
from executor_ios.tunneld_main import main
```

打包脚本的 `TUNNELD_MAIN` 指向它。该入口位于根目录，因此其所在目录（仓库根）成为顶层根，`executor_ios` 仅以包形式 `executor_ios.*` 被导入，`secrets.py` 只能是 `executor_ios.secrets`，不再遮蔽 stdlib。

**备选方案**：把根入口直接命名为 `ios_tunneld.py` 以保留分发 basename `ios_tunneld`，从而免改 `tunnel.py` 与符号链接名。否决原因：会与 `executor_ios/ios_tunneld.py` 同名造成混淆，且与 GUI 入口的命名风格不一致。采用与功能语义匹配的独立名 `cabled_ios_tunnel`。

### 决策 2：分发 basename 由 `ios_tunneld` 改为 `cabled_ios_tunnel`

multidist 按 `--main` 的 basename 分发，新入口 basename 为 `cabled_ios_tunnel`，因此：

- `packaging/build_macos_app.sh`：bundle 内与主二进制同级的 tunneld 分发可执行（符号链接）名由 `ios_tunneld` 改为 `cabled_ios_tunnel`。
- `slide6_console/tunnel.py`：冻结环境下 `_bundled_tunneld_binary()` 返回的名字由 `ios_tunneld` 改为 `cabled_ios_tunnel`。

开发环境的拉起方式不变，仍为 `python -m executor_ios.tunneld_main`。

### 决策 3：保留 `executor_ios/ios_tunneld.py`，但限定启动方式

保留该文件供非打包模式使用。约束：必须以**模块形式**启动（`python -m executor_ios.ios_tunneld` 或 `-m executor_ios.tunneld_main`），此时 `sys.path[0]` 为仓库根目录，`secrets` 不被遮蔽。**严禁**以文件路径 `python executor_ios/ios_tunneld.py` 启动——那会让 `executor_ios/` 重新成为顶层根，dev 模式下重现遮蔽。

## Risks / Trade-offs

- [以文件路径直接运行 `executor_ios/ios_tunneld.py` 会重现 dev 模式遮蔽] → 在文件 docstring 与 README 中明确要求以 `-m` 模块形式启动；GUI dev 路径已使用 `-m executor_ios.tunneld_main`，不受影响。
- [分发 basename 改名后遗漏同步点导致冻结环境拉起失败] → 集中改动两处（打包脚本符号链接名、`tunnel.py` 的 `_bundled_tunneld_binary`），并在 tasks 中逐项核对；规格场景同步更新为 `cabled_ios_tunnel`。
- [改名遗漏 import 导致运行时 ImportError] → 全仓搜索 `credentials` / `from . import credentials` 引用并逐一更新（`toolkit_api.py`）。

## Migration Plan

1. 新增 `cabled_ios_tunnel.py`；改名 `credentials.py` → `secrets.py` 并更新 `toolkit_api.py` 导入。
2. 更新 `packaging/build_macos_app.sh`（`TUNNELD_MAIN` 与符号链接名）与 `slide6_console/tunnel.py`（bundled 二进制名）。
3. 更新文档与受影响规格。
4. 回滚策略：还原上述文件即可恢复 `credentials.py` + 包内 `ios_tunneld` `--main` 方案。

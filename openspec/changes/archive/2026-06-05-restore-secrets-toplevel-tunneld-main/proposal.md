## Why

`executor_ios/secrets.py` 当初被改名为 `credentials.py`，是为了规避 Nuitka multidist 打包时的模块遮蔽问题：tunneld 的 `--main` 是包内文件 `executor_ios/ios_tunneld.py`，导致 `executor_ios/` 目录成为顶层导入根，其中的 `secrets.py` 会以顶层名 `secrets` 遮蔽 stdlib 的 `secrets`（`pymobiledevice3` 依赖它）。只要把 tunneld 的 `--main` 移到仓库根目录（与 GUI 入口 `CablediOS.py` 一致），`executor_ios/` 就不再是顶层根，遮蔽问题从根上消失，文件名即可恢复为更习惯的 `secrets.py`。

## What Changes

- 新增仓库根目录的 tunneld 启动入口 `cabled_ios_tunnel.py`（绝对导入 `from executor_ios.tunneld_main import main`），取代 `executor_ios/ios_tunneld.py` 作为 Nuitka multidist 的 tunneld `--main`。
- 打包脚本 `packaging/build_macos_app.sh` 的 `TUNNELD_MAIN` 指向新的根入口；bundle 内分发可执行名由 `ios_tunneld` 改为 `cabled_ios_tunnel`（multidist 按 `--main` basename 分发）。
- `slide6_console/tunnel.py` 中冻结环境下解析的 bundled 二进制名由 `ios_tunneld` 改为 `cabled_ios_tunnel`。
- 将 `executor_ios/credentials.py` 改回 `executor_ios/secrets.py`；同步更新 `executor_ios/toolkit_api.py` 的导入与相关文档；公开函数名（`get_credential`、`credential_env_key`）保持不变。
- 保留 `executor_ios/ios_tunneld.py` 供非打包模式使用；但其只能以模块形式 `python -m executor_ios.ios_tunneld`（或 `-m executor_ios.tunneld_main`）启动，**不可**以文件路径 `python executor_ios/ios_tunneld.py` 启动，否则 dev 模式下会再次触发 `secrets` 遮蔽。

## Capabilities

### New Capabilities
<!-- 无新增能力 -->

### Modified Capabilities
- `credential-input`: 凭据读取模块文件名由 `credentials.py` 恢复为 `secrets.py`（公开 API 不变）。
- `nuitka-macos-packaging`: tunneld 的 multidist `--main` 由包内 `executor_ios/ios_tunneld.py` 改为仓库根目录 `cabled_ios_tunnel.py`，bundle 内 tunneld 分发可执行名由 `ios_tunneld` 改为 `cabled_ios_tunnel`。
- `slide6-tunnel-bootstrap`: 冻结环境下随包分发并被授权拉起的 tunneld 二进制名由 `ios_tunneld` 改为 `cabled_ios_tunnel`。

## Impact

- 代码：新增 `cabled_ios_tunnel.py`；改名 `executor_ios/credentials.py` → `executor_ios/secrets.py`；修改 `executor_ios/toolkit_api.py`、`packaging/build_macos_app.sh`、`slide6_console/tunnel.py`。
- 文档：`executor_ios/README.md`、`docs/TODO.md` 中涉及 `credentials.py` / `ios_tunneld` 命名的描述。
- 运行约束：非打包模式启动 tunneld 必须使用模块形式（`-m`），不可用文件路径直接运行 `executor_ios/ios_tunneld.py`。
- 无外部 API/契约变更；`get_credential` / `credential_env_key` 函数签名不变。

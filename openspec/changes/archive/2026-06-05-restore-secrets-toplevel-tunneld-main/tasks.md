## 1. 恢复 secrets.py

- [x] 1.1 将 `executor_ios/credentials.py` 改名为 `executor_ios/secrets.py`，更新文件 docstring（说明现在安全：tunneld `--main` 已移到根目录，`executor_ios/` 不再是顶层导入根）
- [x] 1.2 更新 `executor_ios/toolkit_api.py` 中 `from . import credentials` 及 `credentials.get_credential` / `credentials.credential_env_key` 的引用为 `secrets`
- [x] 1.3 全仓搜索其余 `credentials`（代码层）引用并修正，确认无遗漏的 import

## 2. 新增根目录 tunneld 入口

- [x] 2.1 在仓库根目录新增 `cabled_ios_tunnel.py`：薄包装器，`from executor_ios.tunneld_main import main`，`if __name__ == "__main__": main()`，docstring 说明它是 multidist tunneld `--main`、basename 决定分发名
- [x] 2.2 更新 `executor_ios/ios_tunneld.py` 的 docstring：保留供非打包模式使用，但必须以 `-m` 模块形式启动，不可用文件路径直接运行

## 3. 更新打包脚本

- [x] 3.1 `packaging/build_macos_app.sh`：`TUNNELD_MAIN` 指向根目录 `cabled_ios_tunnel.py`
- [x] 3.2 `packaging/build_macos_app.sh`：`add_tunneld_entry()` 创建的符号链接名由 `ios_tunneld` 改为 `cabled_ios_tunnel`；同步更新 fallback 路径中的对应命名
- [x] 3.3 更新脚本顶部注释中关于 secrets/ios_tunneld 命名与 two-pass 历史的描述

## 4. 更新 tunnel.py 启动逻辑

- [x] 4.1 `slide6_console/tunnel.py`：`_bundled_tunneld_binary()` 返回的 basename 由 `ios_tunneld` 改为 `cabled_ios_tunnel`
- [x] 4.2 核对 `tunnel.py` 中冻结/开发环境拉起与入口校验逻辑（`_tunneld_command`、`_tunneld_entry_exists`）与新命名一致；开发路径仍为 `-m executor_ios.tunneld_main`

## 5. 文档与验证

- [x] 5.1 更新 `executor_ios/README.md`、`packaging/README.md`、`slide6_console/README.md` 中涉及 `credentials.py` / `ios_tunneld` 命名的描述
- [x] 5.2 dev 模式验证：确认 `from executor_ios import secrets` 不再遮蔽 stdlib `secrets`（`token_hex` 可用），`get_credential` / `credential_env_key` 正常
- [x] 5.3 执行 `packaging/build_macos_app.sh` 验证：bundle 内存在可执行 `cabled_ios_tunnel`，GUI 默认启动正常，以 `cabled_ios_tunnel` 名调用分发到 tunneld 入口

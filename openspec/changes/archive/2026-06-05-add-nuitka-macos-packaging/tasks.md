## 1. tunnel.py 冻结兼容性改造

- [x] 1.1 在 `slide6_console/tunnel.py` 新增 `_is_frozen()` 判定（基于 `sys.frozen` 与 Nuitka `__compiled__`）
- [x] 1.2 新增 `_bundled_tunneld_binary()`：冻结环境返回 `Path(sys.executable).parent / "ios_tunneld"`
- [x] 1.3 改造 `_interpreter()` / 新增 `_tunneld_command()`：冻结环境返回 `[<ios_tunneld 路径>]`，开发环境返回 `[<interpreter>, "-m", "executor_ios.tunneld_main"]`
- [x] 1.4 修正 `launch_tunneld()` 的入口存在性校验：冻结环境校验 bundled 二进制存在，开发环境校验 `tunneld_main.py` 源文件存在；入口不存在时直接返回失败、不弹授权框
- [x] 1.5 用 `_tunneld_command()` 重建 osascript shell 命令字符串，保留对路径的引用与 `_applescript_quote` 转义，确保不拼接任何外部输入

## 2. device.py 依赖可见性

- [x] 2.1 在 `executor_ios/device.py` 顶部新增 `if False:` 守卫的静态导入提示块，列出所有懒加载的 `pymobiledevice3` 子模块（usbmux / lockdown / installation_proxy / remote_service_discovery / dvt.testmanaged.xcuitest）供 Nuitka 发现
- [x] 2.2 确认改动不影响现有懒加载行为与循环导入规避（仅作静态提示，不在运行期执行）
- [x] 2.3 将 `executor_ios/secrets.py` 重命名为 `credentials.py`（避免冻结产物中遮蔽 stdlib `secrets`），更新 `toolkit_api.py` 的 import 与 `executor_ios/README.md`；公开函数名不变

## 3. multidist 入口包装（绝对导入）

- [x] 3.1 新增 `executor_ios/ios_tunneld.py`：仅 `from executor_ios.tunneld_main import main; main()`，使 multidist 入口 basename 为 `ios_tunneld`
- [x] 3.2 新增 `CablediOS.py`（仓库根）：`from slide6_console.app import main; main()`，绝对导入避免 multidist 顶层 `__main__` 相对导入失败；basename `CablediOS` 即 `CFBundleExecutable`

## 4. Nuitka 打包脚本

- [x] 4.1 在仓库根新增 `packaging/build_macos_app.sh`（可执行、幂等）
- [x] 4.2 脚本前置检查：校验 `nuitka` 可用、`PySide6`/`pymobiledevice3` 已安装，缺失时非零退出并打印修复提示
- [x] 4.3 脚本由 `slide6_console/AppIcon.png` 生成 `packaging/AppIcon.icns`（sips 缩放各档尺寸 + iconutil 合成 iconset）；源图标缺失时跳过并告警
- [x] 4.4 脚本以 multidist 单次构建：`nuitka --standalone --macos-create-app-bundle --macos-app-icon=packaging/AppIcon.icns --enable-plugin=pyside6 --include-package=pymobiledevice3 --main=CablediOS.py --main=executor_ios/ios_tunneld.py`，产物为 `CablediOS.app`（非 onefile）
- [x] 4.5 脚本在 `CablediOS.app/Contents/MacOS/` 内创建 `ios_tunneld`（副本或符号链接指向 multidist 主二进制）并 `chmod +x`
- [x] 4.6 脚本校验产物：`.app` 默认启动分发到 GUI、`ios_tunneld` 可独立执行、图标已生效；若 multidist+app bundle 失败则回退到“两次 standalone + dist 覆盖合并”
- [x] 4.7 脚本结尾打印产物路径与首次运行 Gatekeeper 放行提示

## 5. 构建期依赖与文档

- [x] 5.1 新增打包依赖清单（如 `packaging/requirements-build.txt`：nuitka、ordered-set、zstandard）
- [x] 5.2 在打包脚本头部注释或 `packaging/README.md` 中说明用法、产物位置、multidist 入口分发约定与已知限制（未签名/未公证）

## 6. 验证

- [x] 6.1 开发环境下运行 `python -m slide6_console.app` 确认 tunnel 改造未破坏原有解释器拉起路径（已冒烟验证 `_is_frozen`/`_tunneld_command`/入口校验与各模块导入）
- [x] 6.2 执行 `packaging/build_macos_app.sh` 成功产出 `CablediOS.app`（multidist 单依赖树，299M），`Contents/MacOS/ios_tunneld -> app` 存在、图标已嵌入；`ios_tunneld` 入口分发已验证（修复 stdlib `secrets` 遮蔽后重建确认）
- [x] 6.3 冻结 App 真机冒烟测试：iOS 18.6 设备拉起 XPC tunnel、启动 WDA、镜像串流、方向旋转(90/180)、键盘捕获、多次重选设备均正常，日志无报错
- [x] 6.4 运行 `openspec validate add-nuitka-macos-packaging --strict` 通过

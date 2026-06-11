# slide6_ui 移植到 Windows —— 调研与工作量评估

> 本文档汇总了关于「将 `slide6_ui` 桌面控制台移植到 Windows」的调研结论，包括工作量评估、底层依赖原理、以及部署组件的体积/取舍。

## 一、整体结论

- **核心 UI 几乎零改动**，真正的工作量集中在 **「iOS 17+ 隧道」** 和 **「打包」** 两块。
- 工作量估计：
  - 仅支持 **iOS ≤ 16**：约 **2–3 天**。
  - 完整支持 **iOS 17+**（含真机联调）：约 **1.5 ～ 2.5 周**。
- 有两个**无法靠代码消除的部署前提**（见第四节）。

## 二、分模块工作量评估

| 模块 | 工作量 | 说明 |
|---|---|---|
| UI 层（PySide6 / Qt） | 极小（基本免改） | 天然跨平台；`file_dialogs.py` 现强制非原生对话框，Windows 上正好可用；拖拽、`QSettings`/`QStandardPaths` 均跨平台 |
| `ios_toolkit` iOS ≤16 链路 | 小（以回归测试为主） | pymobiledevice3 官方支持 Windows；usbmux/lockdown/AFC/安装卸载/截图等可用。需回归测试自建 asyncio 事件循环在 Windows 的行为 |
| 键盘修饰键平台分支 | 小（~0.5 天） | `keymouse/keyboard.py` 的 `_collect_modifiers` 按 macOS 的 Ctrl/Meta 交换语义硬编码，Windows 需按平台分支（Ctrl→control，Win 键忽略/映射） |
| **iOS 17+ XPC 隧道重写 + 提权** | **大（含联调 1～1.5 周，风险最高）** | `common/tunnel.py` 全是 macOS 专有，需为 Windows 重写（见第三节） |
| **Windows 打包脚本** | 中（2–3 天） | `packaging/build_macos_app.sh` 完全 macOS 专有，需新写 Nuitka/PyInstaller 脚本产出 `.exe`、双入口、`.ico`、UAC manifest、可选签名 |
| 整体回归测试 | 中（2–3 天） | |

## 三、最大工作量：iOS 17+ XPC Tunnel 重写

`slide6_ui/common/tunnel.py` 是整个移植里改动最大、风险最高的部分，必须为 Windows 重写：

| 现状（macOS） | Windows 需替换为 |
|---|---|
| `osascript ... with administrator privileges` 提权 | UAC 提权（`ShellExecute "runas"` / 带 manifest 的提权 helper） |
| `lsof -ti tcp:PORT` + `kill` 管理进程 | `Get-NetTCPConnection`/`netstat` + `taskkill`，或直接记录 PID |
| 前台 daemon 阻塞 `do shell script` 维持存活 | Windows 进程模型重做（不能照搬前台阻塞那套） |
| 冻结二进制路径 `Contents/MacOS/cabled_ios_tunnel` | Windows exe 同目录解析 |
| `/tmp/ios_tunneld.log` 硬编码 | 用 `tempfile` / `%TEMP%` |

隧道本身（pymobiledevice3 `TunneldRunner`）在 Windows 的额外约束（已查证官方文档）：

- 需要 **`pytun-pmd3`**（基于 Wintun 的自研 TUN/TAP），隧道进程**必须以管理员运行**。
- 已知坑：网卡需启用 **IPv6**，否则报 `error code: 1168`（社区 issue #1275）；稳定性不如 macOS，需实测各 iOS 小版本。

> 建议：投入 UI 集成前，先用一台 iOS 17+ 设备在 Windows 上跑通 `pymobiledevice3 remote tunneld` 验证可行性。

## 四、两个无法回避的部署前提及其原理

pymobiledevice3 逆向的是 **Apple 设备的应用层协议**，但它依赖两样**操作系统级的底座**，无法靠逆向消除。

### 前提 ①：用户机必须有 usbmuxd（USB 接入层）

- pymobiledevice3 **不直接操作 USB 总线**，而是连接 **usbmuxd**（USB multiplexing daemon）的本地 socket / 命名管道，用 usbmux 协议跟它对话。
- usbmuxd 负责：枚举/监听 USB 上的 iOS 设备、把多条逻辑连接复用到一条 USB 通道、存取**配对记录（pairing record）**。
- 来源：
  - **macOS**：系统自带（原生），开箱即用。
  - **Windows**：系统没有，Apple 把它打包进 iTunes / Apple Devices，称 **Apple Mobile Device Service (AMDS)**，附带 iOS USB 驱动。
  - **Linux**：装开源 `usbmuxd`。

### 前提 ②：iOS 17+ 隧道需要虚拟网卡（Wintun）+ 管理员权限

- iOS 17 起 Apple 把开发者服务改为 **RemoteXPC over 隧道**：设备暴露成一个虚拟网络端点（IPv6 + RSD 服务发现），主机要用「网络」方式访问它。
- 落地这条隧道必须在 OS 里**创建一个虚拟网络接口（TUN 设备）**并配 IP/路由——这是**内核能力**，应用层无法模拟。
  - **macOS / Linux**：内核自带 `utun` / `tun`（macOS 还需临时挂起系统 `remoted`）。
  - **Windows**：无内置用户态 TUN，借用 **Wintun** 驱动（经 `pytun-pmd3` 封装）创建虚拟网卡。
- 创建虚拟网卡 + 改路由是特权操作，因此**隧道进程必须以管理员运行**（对应 UAC 提权）。

链路示意：

```
你的程序(pmd3)  ─不依赖AAS→  连接命名管道
                                  │
                            AMDS(usbmuxd服务)  ─依赖AAS的CoreFoundation→  AAS
                                  │
                              USB驱动 → iPhone
```

## 五、关于 Wintun

- **开发者**：WireGuard 项目，作者 **Jason A. Donenfeld（zx2c4）**——即 WireGuard VPN 作者。
- 第三方、开源的 Windows 用户态 TUN 网卡驱动，与 Apple/iOS 无关；pymobiledevice3 只是「借用」。
- 形态是 `wintun.dll` + 签名内核驱动，体积很小（几百 KB 级）。`pytun-pmd3` 包会带上它，**通常不用单独安装**，运行时以管理员权限加载即可。

## 六、usbmuxd 组件体积与取舍（避免装完整 iTunes）

真正需要的只是 iTunes 安装包里的少数组件，而非整个 iTunes。解包 `iTunes64Setup.exe`（7-Zip / lessmsi）后可单独安装。

以 iTunes 12.9 64 位离线包为典型样本（不同版本浮动几 MB）：

| MSI 组件 | 安装包大小 | 作用 | 是否需要 |
|---|---|---|---|
| `AppleMobileDeviceSupport64.msi` | **~15 MB** | usbmuxd 服务 + iOS USB 驱动 | **必需（核心）** |
| `AppleApplicationSupport64.msi` | **~52–55 MB** | Apple 通用运行库（CoreFoundation 等） | 大概率必需（AMDS 间接依赖） |
| `iTunes64.msi` | ~159 MB | 播放器本体 | **不需要** |
| `Bonjour64.msi` | ~2.6 MB | Wi-Fi 同步 | 不需要（USB 不用） |
| 整个 `iTunes64Setup.exe` | ~200–260 MB | — | 不需要 |

### 关于 AppleApplicationSupport (AAS) 是否可省

- **对 pymobiledevice3 本身**：用不到 AAS（纯 Python，不调用 Apple DLL）。
- **对你间接依赖的 AMDS 服务**：大概率要——AMDS 常驻进程用 Apple CoreFoundation 写成，运行时链接 AAS 里的 DLL；iTunes 安装顺序也强制「先 AAS 后 AMDS」。
- **务实结论**：把 **AAS + AMDS 都算必需**（合计 ~70MB），不要为省 52MB 去赌。仍远小于完整 iTunes。

### 产品分发建议

在自己的安装器里静默安装：

```bat
msiexec /i AppleApplicationSupport64.msi /qn /norestart
msiexec /i AppleMobileDeviceSupport64.msi /qn /norestart
```

用户侧约多 ~70MB，无感知，不会看到 iTunes。

## 七、待验证 / 下一步

1. **隧道可行性验证**：iOS 17+ 真机 + Windows，跑通 `pymobiledevice3 remote tunneld`（注意 IPv6、管理员权限、error 1168）。
2. **能否只装 AMDS（省掉 AAS）**：解包具体 iTunes 版本，用 Orca 看 `AppleMobileDeviceSupport64.msi` 的 LaunchCondition；在干净 Windows 上只装 AMDS，实测服务能否启动、`pymobiledevice3 usbmux list` 能否列出设备。
3. **`tunnel.py` 跨平台抽象设计**：macOS / Windows 两套实现。
4. **Windows 打包脚本**：Nuitka/PyInstaller、双入口、UAC manifest。
5. **键盘修饰键平台分支** 与 **asyncio 事件循环** 在 Windows 的回归测试。

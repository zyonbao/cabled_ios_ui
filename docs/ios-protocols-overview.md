# iOS 设备通信协议总览

> 本文档整理了 iOS UI 自动化相关的各层协议，涵盖设备连接、管理服务、开发者服务、屏幕镜像和 WDA 接口。

---

## 一、设备连接层

| 协议 / 工具 | 层级 | 作用 | iOS 17+ |
|-------------|------|------|:-------:|
| **USB MUX（usbmuxd）** | 物理层 | USB 设备检测、TCP-over-USB 隧道基础设施 | ✅ 仍在用 |
| **lockdownd**（端口 62078）| 服务层 | iOS 主管理守护进程，通过 SSL + plist 启动各子服务 | ✅ 基础功能保留 |
| **RemoteXPC / CoreDevice tunnel** | 服务层 | iOS 17+ 新协议，替代 lockdownd 的开发者服务入口，通过 `tunneld` 建立 IPv6 网络隧道 | ✅ 新路 |

---

## 二、设备管理服务（lockdownd 子服务）

| 服务名 | 协议格式 | 功能 | iOS 17+ |
|--------|----------|------|:-------:|
| `installation_proxy` | plist | App 列表、安装、卸载 | ✅ |
| `com.apple.mobile.screenshotr` | plist（DLMessage）| 截图（一问一答，PNG 直返）| ❌ iOS 13+ 逐步失效，iOS 17 废弃 |
| `springboardservices` | plist | SpringBoard 控制、App 启动 | ⚠️ 受限 |
| `afc`（Apple File Conduit）| 二进制协议 | 沙盒文件读写 | ✅ |
| `house_arrest` | plist | App Documents 目录访问 | ✅ |
| `syslog_relay` | 文本流 | 系统日志 | ✅ |
| `mobile_image_mounter` | plist | 挂载开发者镜像（DDI）| ❌ iOS 17 改为 Personalized Package |

---

## 三、开发者服务（DTX / RemoteXPC）

| 服务名 | 协议格式 | 功能 | iOS 17+ |
|--------|----------|------|:-------:|
| `com.apple.instruments.remoteserver` | **DTX**（二进制，NSKeyedArchiver）| 进程 ps / launch / kill、性能采样 | ❌ iOS 14 已改 |
| `com.apple.instruments.remoteserver.DVTSecureSocketProxy` | **DTX over SSL** | 同上，iOS 14–16 | ⚠️ iOS 17 迁移到 XPC tunnel |
| `com.apple.coredevice.feature.processcontrol` | **RemoteXPC** | iOS 17+ 进程 launch / kill / ps | ✅ 新路 |
| `com.apple.testmanagerd` | DTX / XPC | XCTest 运行（WDA 启动依赖）| ✅ |
| `com.apple.debugserver` | **GDB RSP**（文本协议）| LLDB 调试、断点、内存读写 | ✅ |

### DTX 协议结构（简要）

```
Header (16 bytes)
  magic:           0x1F3D5B79
  message_length:  uint32
  fragment_index:  uint16
  fragment_count:  uint16
  payload_length:  uint32
  identifier:      uint32
  flags:           uint32

Payload
  NSKeyedArchiver 序列化的 ObjC 对象
  （方法名、参数列表等）
```

---

## 四、屏幕镜像协议

| 协议 | 传输层 | 格式 | FPS | iOS 17+ | 开源实现 |
|------|--------|------|:---:|:-------:|---------|
| **QuickTime USB 镜像**（hidden config `0x2A`）| libusb 直连 4 个 Bulk endpoint | H.264 + AAC | 30–60 | ✅ | [`quicktime_video_hack`](https://github.com/danielpaulus/quicktime_video_hack)（Go）|
| **IOSurface 帧读取** | `CoreSimulator.framework` 私有 API | JPEG | ~30 | ✅（仅模拟器）| [`tapflow`](https://github.com/jo-duchan/tapflow)（Swift）|
| `screenshotr`（DLMessage）| lockdownd | PNG | 5–15 | ❌ | tidevice（已走废弃路径）|

### QuickTime 隐藏 USB 配置激活流程

```
正常状态：
  iOS 只暴露 1 个 USB 配置（SubClass 0xFE，2 个 Bulk endpoint，usbmuxd 使用）

激活后（QuickTime 录制时 Mac 自动触发）：
  iOS 多出 1 个隐藏配置（SubClass 0x2A，4 个 Bulk endpoint）
    ├── Endpoint 1/2：usbmuxd 复用
    └── Endpoint 3/4：AV 数据流（H.264 视频 + AAC 音频）

激活方式：
  Mac 向设备发送 USB vendor-specific 控制命令
  （quicktime_video_hack 已完整逆向，有技术文档）
```

---

## 五、WDA（WebDriverAgent）REST API

WDA 是运行在 iOS 设备 / 模拟器上的 XCTest 进程，暴露标准 WebDriver REST API（默认端口 8100）。  
所有通信为 HTTP + JSON，与底层 USB 协议完全解耦，不受 iOS 17 协议变化影响。

### 无需 Session 的接口

| 端点 | 方法 | 功能 |
|------|------|------|
| `/status` | GET | 健康检查、设备信息（OS 版本等）|
| `/wda/device/info` | GET | 设备名、型号、UDID、是否模拟器 |
| `/wda/screen` | GET | 屏幕逻辑分辨率、scale |
| `/screenshot` | GET | 截图，返回 base64 PNG，2–5 FPS |
| `/source` | GET | UI 层级树（XML / JSON），`?format=json` 切换 |
| `/wda/accessibleSource` | GET | 仅包含可访问性元素的 UI 树 |
| `/wda/pressButton` | POST | 硬件键（`home` / `power` / `volumeUp`）|

### 需要 Session 的接口

| 端点 | 方法 | 功能 |
|------|------|------|
| `/session` | POST | 建立 session，可指定 `bundleId` 启动 App |
| `/session/:id` | DELETE | 删除 session |
| `/session/:id` | GET | 心跳检查 |
| `/session/:id/actions` | POST | **W3C Actions**：tap / swipe / 键盘输入 |
| `/session/:id/element/active` | GET | 获取当前焦点元素 UUID |
| `/session/:id/element/:uuid/value` | POST | 向元素输入文本 |
| `/session/:id/wda/apps/launch` | POST | 启动 App（bundleId）|
| `/session/:id/wda/apps/terminate` | POST | 终止 App（bundleId）|
| `/session/:id/wda/apps/list` | GET | 列出运行中的 App |

### W3C Actions 示例（tap）

```json
{
  "actions": [{
    "type": "pointer",
    "id": "finger1",
    "parameters": {"pointerType": "touch"},
    "actions": [
      {"type": "pointerMove", "duration": 0, "x": 200, "y": 400},
      {"type": "pointerDown", "button": 0},
      {"type": "pause", "duration": 100},
      {"type": "pointerUp", "button": 0}
    ]
  }]
}
```

---

## 六、协议层级全景图

```
┌─────────────────────────────────────────────────────────────────┐
│  应用层   WDA REST API（HTTP + JSON，基于 WebDriver 协议）         │
│           端口 8100，由 XCTest runner 提供                        │
└──────────────────────────┬──────────────────────────────────────┘
                           │ WDA 进程由 XCTest 框架驱动
┌──────────────────────────▼──────────────────────────────────────┐
│  开发者层  DTX（iOS ≤ 16）/ RemoteXPC（iOS 17+）                  │
│           com.apple.testmanagerd → 启动 XCTest runner            │
│           com.apple.coredevice.feature.processcontrol → 进程控制  │
└──────────────────────────┬──────────────────────────────────────┘
                           │
        ┌──────────────────┴──────────────────┐
        │                                     │
┌───────▼────────┐                  ┌─────────▼──────────────────┐
│  lockdownd     │                  │  RemoteXPC tunnel（iOS 17+）│
│  SSL + plist   │                  │  tunneld → IPv6 link-local  │
│  端口 62078    │                  │  + XPC over 网络隧道         │
└───────┬────────┘                  └─────────────────────────────┘
        │
┌───────▼────────────────────────────────────────────────────────┐
│  usbmuxd（TCP-over-USB）                                        │
│  设备发现 + 隧道基础设施，iOS 17+ 仍然存在                         │
└───────┬────────────────────────────────────────────────────────┘
        │ USB
┌───────▼────────────────────────────────────────────────────────┐
│  USB 物理层                                                      │
│  ├── 标准 config（SubClass 0xFE）：usbmuxd 数据通道              │
│  └── 隐藏 config（SubClass 0x2A）：QuickTime 镜像 H.264 流        │
└────────────────────────────────────────────────────────────────┘
```

---

## 七、各工具的协议使用情况

| 工具 | 底层协议 | iOS 17+ | 备注 |
|------|----------|:-------:|------|
| **tidevice**（截图）| screenshotr（lockdownd）| ❌ | iOS 17 失效，作者已放弃维护 |
| **tidevice**（launch/kill）| DTX Instruments | ❌ | iOS 17 无法使用 |
| **pymobiledevice3** | lockdownd + RemoteXPC | ✅ | 全面实现，纯 Python，5 万行+ |
| **xcrun simctl** | CoreSimulator 内部 | ✅（仅模拟器）| 需完整 Xcode |
| **xcrun devicectl** | CoreDevice（RemoteXPC）| ✅ | 需 Xcode 15+ |
| **quicktime_video_hack** | USB hidden config 0x2A | ✅ | Go 实现，30–60fps 镜像 |
| **tapflow** | IOSurface + CoreSimulator | ✅（仅模拟器）| Swift，~30fps |
| **本项目（executor_ios）** | WDA REST API（HTTP）| ✅ | 纯 Python + requests |

---

## 八、iOS 17+ 各功能可用路径速查

| 功能 | 可用方案 |
|------|---------|
| 设备发现 | usbmuxd ✅ / `xcrun devicectl list devices` ✅ |
| App 列表 | `installation_proxy`（lockdownd）✅ |
| App 安装 / 卸载 | `installation_proxy` ✅ |
| **App 启动 / 终止** | WDA REST API ✅ / `xcrun devicectl` ✅ / RemoteXPC（pymobiledevice3）✅ |
| **进程 ps / kill** | RemoteXPC（CoreDevice）✅ / `xcrun devicectl` ✅ |
| **截图（静态）** | WDA `/screenshot` ✅ / `xcrun devicectl` ✅ / pymobiledevice3 DVT ✅ |
| **截图（30fps+ 流）** | QuickTime hidden config（quicktime_video_hack）✅ |
| **UI 树导出** | WDA `/source` ✅ |
| **tap / swipe** | WDA W3C Actions ✅ |
| **文本输入** | WDA `/element/:id/value` ✅ |
| 系统日志 | `syslog_relay` ✅ |
| 调试 / 断点 | `debugserver`（GDB RSP）✅ |

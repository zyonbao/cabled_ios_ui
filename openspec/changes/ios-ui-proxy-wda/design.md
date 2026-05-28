## Context

iOS TA 框架需要在 Mac 上对 iOS 设备/模拟器执行 UI 操作（截图、UI 树导出、手势）。WebDriverAgent（WDA）是运行在 iOS 设备上的 XCTest 服务，暴露标准 WebDriver REST API。现有方案通常通过 Appium Server 间接调用 WDA，引入 Java/Node.js 进程、额外端口和启动延迟。本项目直接与 WDA REST API 通信，在 Mac 端构建一个轻量 Python proxy 服务。

**当前依赖现状：**
- WDA 已部署到目标设备（通过 `xcodebuild test-without-building` 或 `idb`）
- 模拟器：WDA 监听 `http://localhost:8100`
- 真机：需通过 `iproxy <local-port> 8100` 做 USB 端口转发

## Goals / Non-Goals

**Goals:**
- 封装 WDA 的 screenshot / source / W3C actions 接口，提供稳定的 Python HTTP 服务
- 管理 WDA session 生命周期（建立、心跳、超时重建）
- 支持模拟器和真机（通过端口参数区分）
- 对外暴露统一 REST API，供 TA 脚本调用

**Non-Goals:**
- 不管理 WDA 自身的部署/签名（由外部 `idb` 或 `xcodebuild` 负责）
- 不支持 Windows/Linux（依赖 Mac Xcode 工具链）
- 不实现 App 安装/卸载等 session 级操作（超出 UI proxy 范围）
- 不封装完整 Appium 协议

## Decisions

### D1：直接调用 WDA REST API，不走 Appium Server

**选择**：`requests` 直接 HTTP 调用 WDA 的 `/screenshot`、`/source`、`/actions` 等端点。

**原因**：
- Appium Server 引入 Node.js 进程和额外端口 4723，启动慢（2–5s）
- WDA 的 REST API 是标准 WebDriver 协议，文档清晰，稳定
- 去掉 Appium 中间层后，延迟降低约 50ms/请求

**备选**：`appium-python-client` → 功能全但依赖重，且对 TA 框架来说 90% 功能用不到

---

### D2：用 FastAPI + uvicorn 构建 proxy HTTP 层

**选择**：`fastapi` 作为对外服务框架，`uvicorn` 异步运行。

**原因**：
- 异步支持并发请求（多设备同时操作）
- Pydantic 模型自动校验入参，减少防御性代码
- 自动生成 OpenAPI 文档，便于 TA 团队集成

**备选**：Flask → 同步阻塞，多设备场景有性能瓶颈

---

### D3：手势操作使用 W3C Actions 协议

**选择**：`POST /actions` 发送 W3C pointer actions（`pointerDown` / `pause` / `pointerMove` / `pointerUp`）实现 swipe；`pointerDown` + `pointerUp` 实现 click。

**原因**：
- WDA 原生支持 W3C Actions（`FBTouchActionCommands.m` 中 `POST /actions`）
- W3C 协议语义明确，支持多指、持续时间参数
- 与 Selenium/Appium 生态兼容，未来可平滑切换

**备选**：`POST /wda/dragfromcoordtocoord` → WDA 私有端点，可能在版本间变动

---

### D4：Session 管理策略——懒建立 + 心跳维持

**选择**：
1. Proxy 启动时不立即建立 WDA session
2. 第一次操作请求时建立 session（`POST /session`）
3. 后台线程每 30s 发一次 `GET /session/:id` 保活
4. 连续 3 次心跳失败后自动重建 session

**原因**：
- WDA session 有超时（默认 60s），必须主动维护
- 懒建立避免 proxy 启动时 WDA 未就绪导致启动失败
- 重建逻辑透明，TA 脚本无需感知 session 状态

---

### D5：多设备通过端口参数区分

**选择**：每个设备实例对应一个 proxy 进程，通过 `--wda-port` 和 `--proxy-port` 启动参数区分。

**原因**：
- 简单：每个 proxy 进程状态独立，无共享状态
- TA runner 可通过不同端口并行操作多台设备
- 避免多设备 session 互相干扰

## Risks / Trade-offs

| 风险 | 缓解策略 |
|------|----------|
| WDA 进程崩溃 | 心跳检测 + 自动重建 session；崩溃时返回 503 让上层重试 |
| 真机端口转发断开（iproxy 退出） | 请求超时检测（3s）；日志明确提示 iproxy 状态 |
| WDA 版本升级导致 API 变更 | 封装 WDA 调用到单独 `wda_client.py`，隔离变更面 |
| iOS 版本兼容性（XCTest 行为差异） | `GET /source` 和 `/screenshot` 在 iOS 14+ 稳定；记录已验证版本 |
| 坐标系差异（逻辑点 vs 像素） | WDA 使用逻辑点坐标；proxy 层做分辨率归一化（可选传入 scale） |

## Migration Plan

1. 在 TA 环境验证 WDA 部署（simulator 优先）
2. 启动 proxy：`python -m ios_ui_ta_proxy --wda-port 8100 --proxy-port 9000`
3. 通过 proxy 的 `/docs`（FastAPI OpenAPI）验证各接口可用性
4. 真机场景：先执行 `iproxy 8100 8100`，再启动 proxy

**回滚**：直接停止 proxy 进程，TA 脚本切回原 Appium 方案，无 schema 变更。

## Open Questions

- WDA session 的 `bundleId` 参数：是否需要 attach 到特定 App，还是使用无 App session（`"bundleId": "com.apple.springboard"`）？
- `ui_dump` 返回格式：XML（WDA 默认）还是 JSON（`?format=json`）？TA 框架解析偏好？
- proxy 是否需要鉴权（token）以防 TA 环境中误操作设备？

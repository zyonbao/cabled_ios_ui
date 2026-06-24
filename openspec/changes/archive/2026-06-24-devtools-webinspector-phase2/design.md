## Context

WebInspector 是 lockdown 服务，iOS 17+ 经 tunnel 的 `com.apple.webinspector.shim.remote` 访问，**不需要 DDI**（区别于 sysmontap/网络监控/条件诱导等 DVT 工具）。门控更像系统日志：仅需 tunnel（17+）。设备须开启「Web 检查器」开关。

## 真机实测（iOS 26 + tunnel）

- WebInspector shim 经 tunnel `connect()` 成功；`get_open_application_pages()` 返回真实页面：`Safari浏览器 / com.apple.mobilesafari / page_id=1 / title / url`。
- 未开「Web 检查器」开关 → `WebInspectorNotEnabledError`（连接阶段即抛）。
- CDP 依赖 `uvicorn 0.48 / fastapi 0.136 / wsproto` 均已随 pymobiledevice3 安装。

## Goals / Non-Goals

**Goals**
- 子面板内列出可调试页面并可刷新。
- 一键起本地 CDP 桥接，用 Chrome DevTools 连上获得完整调试。
- 桥接与窗口生命周期绑定，关窗自动回收。
- 未开开关 / 无页面时给出明确降级提示。

**Non-Goals**
- 不自造 DevTools UI（完整体验交给 Chrome DevTools）。
- 不实现 WebDriver 自动化（automation_session，需 Remote Automation 开关）——后续可选。
- 不内嵌浏览器。

## Decisions

### 决策 1：完整调试走 CDP 桥接（复用 pymobiledevice3），不自造 UI

pymobiledevice3 已能把 WIP 桥成 CDP（`webinspector cdp` 命令，uvicorn ASGI server）。我们只做「列页面 + 起桥接 + 显示连接入口 + 回收」，把完整 DevTools 交给 Chrome。

### 决策 2：CDP server 嵌入式运行（uvicorn.Server in 线程），不起子进程

`pymobiledevice3` 的 `cdp` 命令用阻塞式 `uvicorn.run`。集成进 GUI 用 `uvicorn.Server(Config(...))` 在**后台线程**跑（自带 loop），桥接用独立的 `WebinspectorService(RSD)`；句柄持有 server，`close()` 时触发 server should-exit 并 join。原因：打包后无独立 python，**子进程方案不可靠**，嵌入式无外部依赖。
- **主要实现风险**：`cli/webinspector.py` 的 CDP app 用模块级全局（`cdp_inspector`/`app`/`create_app`），嵌入式运行需复刻其 ASGI app 构造（不复用其 `uvicorn.run`），并管好 server 的优雅关闭。实现首步先验证「嵌入式 server 起停 + Chrome 连上」最小闭环。

### 决策 3：前置/降级语义

- 未开「Web 检查器」开关（`WebInspectorNotEnabledError`）→ UI 显示引导文案，不报错弹窗。
- 枚举到 0 页面 → 提示「设备上打开一个 Safari 标签或含 WebView 的 App」。

## Risks / Trade-offs

- 嵌入式 uvicorn 的生命周期/优雅关闭需处理好，避免端口占用残留（close 未净化会导致下次起桥接 9222 被占）。
- CDP 桥接依赖用户本机装 Chromium 系浏览器（Chrome/Edge）；UI 文案需说明。
- 端口冲突（9222 被占）需可改端口并给出可读错误。

## Migration Plan

1. ✅ 真机确认（已完成）：shim 可起、枚举到真实页面、未开开关报 NotEnabled、CDP 依赖在位。
2. 平台层：`list_web_pages` + CDP 桥接句柄（嵌入式 uvicorn.Server，生命周期绑定）；先打通「起桥接 + Chrome 连上」最小闭环。
3. UI 子面板：页面列表 + 刷新 + 起停桥接 + 连接入口 + 开关引导。
4. i18n、校验、真机验收（开关开/关、有页面/无页面、关窗回收无端口残留）。

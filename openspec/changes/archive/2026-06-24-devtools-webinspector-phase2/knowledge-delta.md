## 变更摘要

新增开发者工具「Web 检查器」子面板：枚举可调试页面 + 一键 CDP 桥接到 Chrome DevTools。

## 目标模块

slide6-developer-tools / webinspector-op

## 知识写入目标

`openspec/specs/webinspector-op/spec.md`、`openspec/specs/slide6-developer-tools/spec.md`

## 架构变更

- WebInspector 为 lockdown 服务，iOS 17+ 经 tunnel 的 `com.apple.webinspector.shim.remote` 访问，**不需要 DDI**（门控仅 tunnel）。
- 平台层提供页面枚举 + CDP 桥接句柄（嵌入式 uvicorn.Server，生命周期绑定）。

## 接口变更

- 新增 `list_web_pages(target)`（页面列表 / 错误信封）。
- 新增 `open_cdp_bridge(target, host=127.0.0.1, port=9222)`（返回桥接句柄）。
- 降级：未开「Web 检查器」开关 → `WEBINSPECTOR_DISABLED` 可读错误 + UI 引导。

## 代码路径变更

- `ios_toolkit/device.py`、`ios_toolkit/toolkit_api.py`
- `slide6_ui/developer_tools/developer_tools_tab.py`、`slide6_ui/developer_tools/`（新增 dialog）

## 平台支持

- 真机已验证：iOS 26 + tunnel，shim 可起、枚举到真实页面；未开开关报 NotEnabled。
- 完整 DevTools 交给 Chrome（CDP 桥接），不自造 UI。

## 设计决策（WHY）

- 复用 pymobiledevice3 的 CDP 桥接、嵌入式运行：打包后无独立 python，子进程方案不可靠。
- 不自造 DevTools：Chrome DevTools 体验上限远高于自造 JS 控制台。

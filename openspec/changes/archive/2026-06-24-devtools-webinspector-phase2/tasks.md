# Tasks

## 0. 真机字段确认（实现前）

- [x] 0.1 已完成：webinspector shim 经 tunnel 可 `connect`；开启「Web 检查器」后枚举到真实页面（app/bundle/page_id/title/url）；未开开关报 `WebInspectorNotEnabledError`；CDP 依赖 uvicorn/fastapi/wsproto 在位

## 1. 平台层 WebInspector 能力

- [x] 1.1 `ios_toolkit/device.py`：WebInspector 枚举（RSD/lockdown，17+ 经 tunnel，无需 DDI），归一化页面为 `{app, bundle, page_id, title, url}`
- [x] 1.2 `ios_toolkit/toolkit_api.py`：`list_web_pages(target)`（返回页面列表 / 错误信封，未开开关返回可读 `WEBINSPECTOR_DISABLED`）
- [x] 1.3 CDP 桥接句柄：嵌入式 `uvicorn.Server` 后台线程运行（独立 `WebinspectorService(RSD)`），`open_cdp_bridge(target, host, port)` → 句柄；`close()` 优雅关闭并释放端口；端口占用返回可读错误
- [x] 1.4 句柄与窗口生命周期绑定：起桥接创建、Stop/关窗回收，无端口残留

## 2. Web 检查器子面板 UI

- [x] 2.1 `developer_tools_tab.py`：新增「Web 检查器」入口与单例窗口（沿用 `_open_subwindow`）
- [x] 2.2 页面列表（app / 标题 / url）+ 刷新；未开开关 / 0 页面给出引导文案
- [x] 2.3 「启动/停止 CDP 桥接」+ 显示连接入口（`chrome://inspect` 或 `localhost:<port>`），端口可改

## 3. 校验

- [x] 3.1 py_compile / openspec validate / `i18n.validate()` 通过
- [x] 3.2 真机验收：开关开/关、有页面/无页面、起停桥接、关窗回收（端口释放、无残留），Chrome DevTools 可连上调试

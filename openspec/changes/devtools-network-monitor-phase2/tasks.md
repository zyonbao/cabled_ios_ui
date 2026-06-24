# Tasks

## 1. 平台层网络采样

- [ ] 1.1 `ios_toolkit/device.py` 新增网络采样句柄（open/close/queue），输出趋势与连接流基础字段
- [ ] 1.2 `ios_toolkit/toolkit_api.py` 暴露 `open_network_stream(target, interval_ms)` 与参数校验（200~2000ms）
- [ ] 1.3 采样线程与窗口生命周期约束：Start 创建，Stop 回收，窗口关闭自动停止

## 2. Network Monitor 子面板 UI

- [ ] 2.1 `developer_tools_tab.py` 增加网络监控子面板入口与单例窗口管理
- [ ] 2.2 新增 Network Monitor 对话框：顶部状态条 + 三栏布局 + 控制栏（Start/Stop/Pause/Clear/Auto-scroll/Export）
- [ ] 2.3 实现趋势图（Rx/Tx/连接数/错误数）与连接流表格联动

## 3. 过滤器与导出

- [ ] 3.1 实现进程、协议、方向、host/port、关键词、仅活跃连接过滤
- [ ] 3.2 实现 CSV/JSON 导出，导出边界固定为当前过滤条件 + 当前 10 分钟窗口
- [ ] 3.3 字段缺失统一显示 `unsupported/unknown`

## 4. 稳定性与验证

- [ ] 4.1 落地 10 分钟滚动窗口与 ring buffer 淘汰策略
- [ ] 4.2 完成 py_compile / ReadLints / openspec validate 严格校验
- [ ] 4.3 真机验收：高吞吐场景无明显卡顿，无孤儿采样任务


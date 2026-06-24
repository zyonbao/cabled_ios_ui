## ADDED Requirements

### Requirement: Web 检查器界面

「开发者工具」Tab SHALL 提供「Web 检查器」功能卡片并打开子面板（非独立 sidebar Tab）。该能力为 lockdown 服务，**门控仅需 tunnel（iOS 17+），不需要 DDI**（区别于性能/网络/条件诱导等 DVT 卡片）。子面板 MUST 提供：可刷新的可调试页面列表（App / 标题 / URL）、启动/停止 CDP 桥接、以及连接入口提示（`chrome://inspect` 或 `localhost:<port>`，端口默认 9222 可改）。

设备未开启「Web 检查器」开关时 MUST 显示明确引导（设置 → Safari → 高级 → Web 检查器），不报错弹窗；枚举到 0 页面时 MUST 提示打开 Safari 标签 / 含 WebView 的 App。CDP 桥接 MUST 与子面板窗口生命周期绑定，关闭窗口自动停止并释放端口。

#### Scenario: 进入子面板列出页面

- **WHEN** 设备已开启 Web 检查器且有可调试页面，用户点击「Web 检查器」卡片
- **THEN** 子面板列出可调试页面（App / 标题 / URL）并可刷新

#### Scenario: 启动 CDP 桥接

- **WHEN** 用户启动 CDP 桥接
- **THEN** 显示连接入口（`chrome://inspect` 或 `localhost:<port>`），用户可用 Chrome DevTools 连上调试

#### Scenario: 未开启开关时引导

- **WHEN** 设备未开启「Web 检查器」开关
- **THEN** 子面板显示开启引导，不弹错误框

#### Scenario: 关闭窗口回收桥接

- **WHEN** 子面板窗口被关闭
- **THEN** CDP 桥接自动停止、端口释放，无残留

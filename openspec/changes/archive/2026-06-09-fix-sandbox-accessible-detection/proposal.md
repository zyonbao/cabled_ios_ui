## Why

「App 列表」对 App Store 应用（如 Chrome）误判为「沙盒可访问」，点进去实际无法访问容器。

根因：`list_apps` 的 `sandboxAccessible` 判定有两处问题：

1. **键名错误**：检查的是 `Entitlements["com.apple.security.get-task-allow"]`（macOS 命名），而 iOS 上 installation_proxy 返回的真实键是 **`get-task-allow`**（无前缀）。实测该键确实存在且对可调试应用为 `True`，此前因键名不符**永远取不到值**，于是恒走兜底。
2. **兜底过宽**：兜底用「存在 `SignerIdentity`」，但 **App Store 应用同样带 `SignerIdentity`**（`Apple iPhone OS Application Signing`），导致被误判为可访问。

house-arrest `VendContainer` 仅对**可调试应用**（`get-task-allow=true`）有效；App Store / 企业分发 / 系统应用的容器不可 vend。因此正确信号是 `get-task-allow`，应去掉 `SignerIdentity` 兜底。

真机实测（iPhone，iOS 17.x）：所有 `Apple Development` 签名应用 `Entitlements['get-task-allow']==True`；App Store 应用无此键。

## What Changes

- 修正 `sandboxAccessible` 判定：以 `Entitlements` 的 `get-task-allow` 为真为准（兼容带 `com.apple.security.` 前缀的写法作为次要回退），**移除 `SignerIdentity` 兜底**。
- 同步修订 `app-inventory-op` 规格中关于 `sandboxAccessible` 判定的描述（删除"通常不含 get-task-allow"与 SignerIdentity 兜底的错误表述）。

## Capabilities

### Modified Capabilities

- `app-inventory-op`: 修正 `sandboxAccessible` 的判定规则。

## Impact

- `ios_toolkit/device.py`：`_list_apps_async` 的 `sandbox_accessible` 计算。
- 不改 `toolkit_api` 接口与返回结构；UI 无需改动（仅判定结果更准确）。

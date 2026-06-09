## 1. 修复判定

- [x] 1.1 `ios_toolkit/device.py` `_list_apps_async`：`sandbox_accessible` 改为以 `Entitlements['get-task-allow']` 为真为准（兼容 `com.apple.security.get-task-allow` 次要回退），移除 `SignerIdentity` 兜底

## 2. 验证

- [~] 2.1 真机：`Apple Development` 签名应用 `sandboxAccessible=true`、无系统应用被误标（已验证）；App Store 应用（Chrome）`=false` 待用户在装有 Chrome 的设备复验
- [x] 2.2 lint 无误；经 `list_apps` 实跑验证判定

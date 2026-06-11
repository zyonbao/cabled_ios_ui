## REMOVED Requirements

### Requirement: 导出配置描述文件

**Reason**: 该能力依赖从 `get_profile_list()` 的 `ProfileManifest` 取回原始字节，但 iOS 实际只返回元数据（`Data` 恒为空），平台层无法实现，故移除 `export_profile`。

平台能力层 SHALL 提供 `export_profile(target, identifier, local_path)`，将设备上指定标识符的配置描述文件原始内容导出到本地文件，使用统一 `{ok, data}` 信封。该操作 MUST 基于 lockdown `MobileConfigService`，且 MUST NOT 依赖 WDA 或 XPC tunnel。

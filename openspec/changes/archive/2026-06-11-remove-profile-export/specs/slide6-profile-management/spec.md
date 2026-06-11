## REMOVED Requirements

### Requirement: 导出描述文件

**Reason**: iOS 的 MCInstall（`get_profile_list()`）只返回描述文件元数据，不暴露已安装描述文件的原始字节，导出能力在平台层无法兑现，因此从 UI 移除导出入口。

「描述文件」Tab SHALL 支持导出选中的描述文件到本地 `.mobileconfig`，经 `export_profile` 取回设备上的原始字节。单选时 SHALL 弹出「另存为」（预填 `<名称>.mobileconfig`）；多选时 SHALL 弹出目录选择并逐项导出（以 `<标识符>.mobileconfig` 命名避免重名），完成后汇总成功 / 失败数量。所有阻塞调用 MUST 经由 `AsyncRunner` 执行。未选中任何条目时 MUST 给出提示而非报错。

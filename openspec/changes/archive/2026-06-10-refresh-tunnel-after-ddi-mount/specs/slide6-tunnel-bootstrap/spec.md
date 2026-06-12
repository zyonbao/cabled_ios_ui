## ADDED Requirements

### Requirement: （已被后续实现替代）挂载成功后不再弹立即重启 tunnel 提示

> Note: 本 archive change 原始目标是“挂载后按需提示并重启 tunnel”。后续实现已调整为“挂载成功后不弹立即重启提示，直接进入就绪探测；保留手动重启入口”。本条按当前实现口径更新，避免历史文本与现网行为冲突。

应用在 DDI 挂载成功后 MUST NOT 弹出“是否现在重启 XPC tunnel”的模态确认提示。iOS 17+ 下若 tunnel 已在运行，SHALL 直接继续开发者服务就绪探测；若 tunnel 未运行，SHALL 提示用户按需从「开发者工具」启动 tunnel。应用保留手动「重启 tunnel」入口，但该动作不再作为挂载成功后的强制或默认后续步骤。

#### Scenario: iOS 17+ 挂载成功且 tunnel 已在运行

- **WHEN** iOS 17+ 设备挂载 DDI 成功，且 XPC tunnel 端口已在监听
- **THEN** 不弹出重启提示
- **AND** 直接继续就绪探测流程

#### Scenario: iOS 17+ 挂载成功但 tunnel 未运行

- **WHEN** iOS 17+ 设备挂载 DDI 成功，但 XPC tunnel 端口无人监听
- **THEN** 不弹出重启提示、不触发授权
- **AND** 提示用户按需启动 tunnel

#### Scenario: iOS<17 挂载成功

- **WHEN** iOS 主版本低于 17 的设备挂载 DDI 成功
- **THEN** 不进行任何 tunnel 重启相关提示

#### Scenario: 用户需手动重启时可后续触发

- **WHEN** 开发者服务未就绪且用户选择手动重启 tunnel
- **THEN** 应用允许从开发者工具入口手动重启，不在挂载成功时强制弹框

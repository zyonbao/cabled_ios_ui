## ADDED Requirements

### Requirement: 探测主机配对状态

工具层 SHALL 提供 `pairing_state(target)`，报告指定设备是否存在有效的主机配对记录，返回 `{"ok": true, "data": {"paired": bool}}`。探测 MUST NOT 在别处触发自动配对。探测过程中遇到 SSL EOF / 连接被终止类异常（即陈旧配对记录导致的握手失败）SHALL 判定为"未配对"（`paired=false`），而非报错。

#### Scenario: 已配对返回 true

- **WHEN** 设备存在有效配对记录
- **THEN** 返回 `{"ok": true, "data": {"paired": true}}`

#### Scenario: 未配对返回 false

- **WHEN** 设备没有配对记录
- **THEN** 返回 `{"ok": true, "data": {"paired": false}}`

#### Scenario: 陈旧记录导致握手失败按未配对处理

- **WHEN** 设备上残留一条已失效的配对记录，校验握手被设备断开（SSL EOF / 连接终止）
- **THEN** 判定为未配对（`paired=false`），不抛错，使调用方可重新发起配对

### Requirement: 发起主机配对

工具层 SHALL 提供 `pair_device(target)`，发起主机配对并触发设备端「信任此电脑」对话框，阻塞至用户响应或失败。配对 MUST 在不被陈旧配对记录阻断的前提下进行：实现 MUST NOT 依赖会先校验陈旧记录而崩溃的连接路径，而是在一条全新连接上直接发起配对。配对成功后，新的配对记录 MUST 被持久化到 usbmuxd（系统权威存储），以覆盖任何陈旧记录、保证后续校验成功。

#### Scenario: 用户信任后配对成功

- **WHEN** 调用 `pair_device`，用户在设备上点「信任」并完成
- **THEN** 返回成功，且后续 `pairing_state` 报告已配对

#### Scenario: 存在陈旧记录时仍能弹出信任并配对

- **WHEN** 设备上残留已失效配对记录
- **THEN** 仍能正常弹出「信任此电脑」并在信任后完成配对（不因校验陈旧记录而提前失败）

### Requirement: 取消主机配对

工具层 SHALL 提供 `unpair_device(target)`，撤销本机在该设备上的配对记录，返回 `{"ok": true, "data": {"paired": false}}`。实现 MUST NOT 依赖会因陈旧记录而崩溃的校验路径（取消配对仅需发送 Unpair 请求、无需 SSL 握手）。

#### Scenario: 取消配对成功

- **WHEN** 对已配对设备调用 `unpair_device`
- **THEN** 返回 `paired=false`，后续 `pairing_state` 报告未配对

#### Scenario: 无记录时安全返回

- **WHEN** 设备本就没有本机配对记录
- **THEN** 不抛错，安全返回未配对

### Requirement: 配对记录存储位置与权限健壮性

工具层 SHALL 将 `pymobiledevice3` 的本地配对记录缓存目录指向应用自有数据目录 `~/Library/CablediOS/PairingRecords`，而非默认的 `~/.pymobiledevice3`（后者常残留早期 sudo 运行留下的 root 属主文件，导致写入失败）。发起配对前，若目标设备对应的本地缓存文件存在且当前用户不可写，工具层 SHALL 先删除该文件，使配对得以写出归当前用户所有的新记录。该清理 MUST 为尽力而为，失败时记录日志但不阻断配对。

#### Scenario: 缓存写入不再因 root 残留文件失败

- **WHEN** 应用数据目录或共享目录中存在不可写的旧缓存记录，用户发起配对
- **THEN** 不可写的旧文件被清理，配对成功并写出可用的新记录，不再出现 PermissionError

#### Scenario: 清理失败不阻断配对

- **WHEN** 清理旧缓存文件时发生异常
- **THEN** 记录日志并继续发起配对，不抛错中断

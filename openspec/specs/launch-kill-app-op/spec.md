## ADDED Requirements

### Requirement: 通过 WDA apps API 启动 App
系统 SHALL 通过 `POST /session/<id>/wda/apps/launch`（body：`{"bundleId": package}`）启动 App。`activity` 参数对 iOS 无意义，忽略。WDA 请求失败时 fallback 到 `pymobiledevice3` 的 `AppServiceClient` 启动。

#### Scenario: launch_app 通过 WDA 成功启动
- **WHEN** 以有效 UDID 和合法 bundleId 调用 `launch_app(target, package)`，WDA 正在运行
- **THEN** 返回 OpResult 成功格式且 App 在前台启动

#### Scenario: WDA 失败时 fallback 到 pymobiledevice3
- **WHEN** 调用 `launch_app(target, package)` 但 WDA 请求返回错误
- **THEN** 通过 `pymobiledevice3` `AppServiceClient` 启动 App，返回成功响应

#### Scenario: UDID 不存在时返回 BAD_TARGET
- **WHEN** 以不存在的 UDID 调用 `launch_app`
- **THEN** 返回 `{"ok": false, "error": {"kind": "BAD_TARGET", ...}}`

#### Scenario: activity 参数被忽略
- **WHEN** 调用 `launch_app(target, package, activity="MainActivity")`
- **THEN** 忽略 `activity` 参数，正常执行 App 启动

### Requirement: 通过 WDA apps API 终止 App
系统 SHALL 通过 `POST /session/<id>/wda/apps/terminate`（body：`{"bundleId": package}`）终止 App。WDA 请求失败时 fallback 到 `pymobiledevice3` 的 `AppServiceClient` 终止。

#### Scenario: kill_app 通过 WDA 成功终止
- **WHEN** 以有效 UDID 和合法 bundleId 调用 `kill_app(target, package)`，WDA 正在运行且 App 在前台
- **THEN** 返回 OpResult 成功格式且 App 进程不再存在

#### Scenario: WDA 失败时 fallback 到 pymobiledevice3
- **WHEN** 调用 `kill_app(target, package)` 但 WDA 请求返回错误
- **THEN** 通过 `pymobiledevice3` `AppServiceClient` 终止 App，返回成功响应

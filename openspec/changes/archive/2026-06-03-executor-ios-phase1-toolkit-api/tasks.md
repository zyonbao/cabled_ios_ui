## 1. 基础设施

- [x] 1.1 创建 `executor_ios/__init__.py`（空文件，将目录标记为 Python 包）
- [x] 1.2 在 `toolkit_api.py` 中实现 `WdaError(Exception)` 异常类（携带 `message: str`）
- [x] 1.3 在 `toolkit_api.py` 中实现统一返回值工具函数：`_ok(data)`、`_err(kind, message, details)`、`_not_implemented(op)`
- [x] 1.4 在 `toolkit_api.py` 中实现 `_wda_get(local_port, path, timeout)` 同步函数（requests GET，失败抛 `WdaError`）
- [x] 1.5 在 `toolkit_api.py` 中实现 `_wda_post(local_port, path, body, timeout)` 同步函数（requests POST，失败抛 `WdaError`）
- [x] 1.6 在 `toolkit_api.py` 中实现 `_ephemeral_forward(udid, device_port=8100)` 异步上下文管理器（动态探测本地端口，usbmux relay，UDID 不存在抛 `ValueError`）
- [x] 1.7 在 `toolkit_api.py` 中实现 `_create_session(local_port)` 函数（`POST /session`，返回 `sessionId`，失败抛 `WdaError`）

## 2. 设备发现

- [x] 2.1 实现 `list_targets() -> dict`（枚举 USB 物理设备，过滤 Wi-Fi，读取元数据，降级处理失败，不启动端口转发，无设备时返回空列表）

## 3. 截图与 UI 树

- [x] 3.1 实现 `screenshot(target) -> dict`（`asyncio.run` + `_ephemeral_forward`，`GET /screenshot`，返回 `mimeType + base64`，UDID 不存在→`BAD_TARGET`，WDA 失败→`SUBPROCESS`）
- [x] 3.2 实现 `dump_ui(target) -> dict`（`GET /source?format=xml`，解析 XML 为 selector 列表，8 字段映射，bounds 格式转换，去重，200 条上限截断，返回 `raw + rawMime + selectors`）

## 4. 交互操作

- [x] 4.1 实现 `tap(target, x, y) -> dict`（`asyncio.run` + `_ephemeral_forward` + `_create_session`，W3C pointer actions pointerDown+pointerUp，返回含 `extra.tapX/tapY` 的 OpResult）
- [x] 4.2 实现 `swipe(target, x1, y1, x2, y2, duration_ms=250) -> dict`（W3C pointer 序列 pointerDown→pause→pointerMove→pointerUp，返回含 `extra.fromX/fromY/toX/toY/durationMs` 的 OpResult）
- [x] 4.3 实现 `input_text(target, text) -> dict`（输入校验，主路径 `/element/active` + `/element/<id>/value`，fallback W3C key actions，返回含 `extra.length` 的 OpResult）
- [x] 4.4 实现 `key_event(target, key) -> dict`（按键路由表：`HOME`/`POWER`→`pressButton` 无需 session；`ENTER`/`DEL`/`TAB`/`SPACE`/`ESCAPE`→W3C key event；其余→`NOT_IMPLEMENTED`）

## 5. App 管理

- [x] 5.1 实现 `launch_app(target, package, activity=None) -> dict`（忽略 `activity`，主路径 `wda/apps/launch`，WDA 失败→pymobiledevice3 `AppServiceClient` fallback）
- [x] 5.2 实现 `kill_app(target, package) -> dict`（主路径 `wda/apps/terminate`，WDA 失败→pymobiledevice3 `AppServiceClient` fallback）

## 6. 空桩

- [x] 6.1 实现 `switch_app_env(target, env) -> dict`（直接返回 `_not_implemented("switch_app_env")`）
- [x] 6.2 实现 `type_credential(target, env, role, field, skip_clear=False) -> dict`（直接返回 `_not_implemented("type_credential")`）

## 7. 验收检查

- [x] 7.1 连接一台 USB 物理设备，验证 `list_targets()` 返回含正确 UDID/name/model/os_version 的设备信息
- [x] 7.2 验证 `screenshot("<udid>")` 返回可正常解码的 PNG base64
- [x] 7.3 验证 `dump_ui("<udid>")` 返回含 `raw` 和 `selectors` 的响应，每条 selector 有全部 8 个字段
- [x] 7.4 验证 `tap`、`swipe`、`input_text`、`key_event("HOME")`、`launch_app`、`kill_app` 均正常返回且不抛 Python 异常
- [x] 7.5 验证不存在的 UDID 返回 `BAD_TARGET` 而非 Python 异常
- [x] 7.6 验证 `switch_app_env` 和 `type_credential` 返回 `NOT_IMPLEMENTED`
- [x] 7.7 验证 `python3 -c "import executor_ios"` 不报错
- [x] 7.8 验证多次连续调用（无需外部持久进程）均可正常执行

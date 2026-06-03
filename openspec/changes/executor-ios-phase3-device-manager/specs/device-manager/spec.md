# device-manager

`iOSDevice` 和 `iOSDevicesManager` 类，实现多设备注册、端口分配与生命周期管理。

## 文件

`executor_ios/device.py`

## `iOSDevice` 属性

| 属性 | 类型 | 说明 |
|---|---|---|
| `udid` | `str` | 设备 UDID（仅 USB 设备） |
| `local_port` | `int` | 持久分配的本机转发端口 |
| `name` | `str` | 设备名称（来自 lockdown） |
| `model` | `str` | 设备型号（来自 lockdown） |
| `os_version` | `str` | 系统版本（来自 lockdown） |
| ~~`rsd_address`~~ | — | 已移除，RSD 信息在 `do_prepare()` 时按需查询 tunneld，不作为属性存储 |
| `_forward_task` | `Future` | 后台转发协程句柄 |
| `_session_id` | `str \| None` | WDA session 缓存 |
| `_session_lock` | `threading.Lock` | 保护 `_session_id` 读写 |
| `_wda_bundle_id` | `str` | WDA bundle ID（来自配置或默认值） |

## `iOSDevicesManager` 接口

```python
class iOSDevicesManager:
    def list_devices(self) -> list[iOSDevice]
    def get_device(self, udid: str) -> iOSDevice | None
```

单例，通过模块级变量 `_manager` 访问。

## 设备发现行为

- 调用 `usbmux.list_devices()`，**仅保留 `connection_type == "USB"` 的条目**
- 新 UDID：分配本地端口（从 8200 起探测可用端口）→ 启动持久转发 → 读取配置文件 → 创建 `iOSDevice`（RSD 信息不在发现阶段读取，`do_prepare()` 时按需查询 tunneld）
- 已知 UDID：跳过，不重新分配端口
- lockdown 元数据读取失败时降级为空字符串，不阻塞

## 配置文件

`~/.executor_ios.json`（可选）：

```json
{
  "wda_bundle_id": "com.facebook.WebDriverAgentRunner.xctrunner"
}
```

文件不存在或字段缺失时使用默认值 `com.facebook.WebDriverAgentRunner.xctrunner`。

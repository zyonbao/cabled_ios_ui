# device-discovery

通过 pymobiledevice3 发现已连接的 iOS 物理设备，并结合 WDA liveness 探测返回标准 target 列表。

## Interface

```
op: list_targets
args: {}
```

## Response

```json
{
  "ok": true,
  "data": {
    "targets": [
      {
        "id": "<UDID>",
        "platform": "ios",
        "name": "<DeviceName>",
        "state": "online",
        "metadata": {
          "model": "<ProductType>",
          "os_version": "<ProductVersion>"
        }
      }
    ]
  }
}
```

## Behavior

- 通过 `pymobiledevice3.usbmux.list_devices()` 获取已连接物理设备列表（async，用 `asyncio.run()` 包装为同步调用）
- 对每个发现的设备，尝试通过 lockdown 获取 DeviceName、ProductType、ProductVersion；失败时降级为 `"unknown"`，不阻塞整体返回
- 对每个设备调用 `wda_client.probe()`：成功则 `state = "online"`，失败则 `state = "offline"`
- 未安装 pymobiledevice3 或 usbmuxd 不可达时，返回空列表，不报错
- 响应时间要求：≤ 1 秒

## Error Cases

- `state: offline`：设备已发现但 WDA 未运行或端口不通（不是错误，正常返回）
- `BAD_TARGET`：不在此 op 使用，list_targets 不接受 target 参数
- `INTERNAL`：未预期的内部异常

## Notes

- `id` 字段为设备 UDID，作为后续所有操作的 `target` 参数值
- 仅支持物理设备（USB / WiFi），模拟器 Not In Scope
- iOS 17+ 设备需提前运行 `sudo pymobiledevice3 remote tunneld` 才能完整获取 lockdown 元数据；未运行时降级返回 unknown，不影响 state 判断

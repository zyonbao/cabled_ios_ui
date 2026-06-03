# screenshot

截取当前 iOS 设备屏幕，返回 base64 编码的 PNG 图像。

## Interface

```
op: screenshot
args:
  target: <UDID>   # 必填，由 list_targets 返回
```

## Response

```json
{
  "ok": true,
  "data": {
    "mimeType": "image/png",
    "base64": "<base64-encoded PNG>"
  }
}
```

## Behavior

- 调用 WDA `GET /screenshot`，WDA 返回 base64 PNG 字符串
- 返回的图像为**逻辑点分辨率**（pt）而非物理像素（px）
  - 例：iPhone 15 Pro 物理 2556×1179px，逻辑 852×393pt（scale=3）
  - WDA screenshot 返回的是逻辑点尺寸的图像
- 坐标体系与 tap / swipe 操作保持一致，上层可直接用图像坐标点击
- 响应时间要求：≤ 15 秒

## Error Cases

- `BAD_TARGET`：target UDID 不存在或 WDA 不可达
- `SUBPROCESS`：WDA 返回空数据或 HTTP 错误
- `INTERNAL`：未预期的内部异常

## Notes

- 图像格式固定为 PNG，不支持其他格式
- 不支持视频流 / 高帧率镜像（Not In Scope，需另行使用 QuickTime hidden config 方案）

# persistent-forward

持久 usbmux 端口转发，替代 Phase 1 的 ephemeral 模式。

## 动机

Phase 1 中每次操作都在 `asyncio.run()` 内临时启动端口转发，操作完成后关闭。Phase 3 引入持久转发：转发在设备注册时启动，生命周期与 `iOSDevice` 对象相同，操作函数直接使用 `self.local_port` 发 HTTP 请求，无需 `asyncio.run()` 包装。

## 后台事件循环

`device.py` 模块加载时初始化，仅初始化一次：

```python
_bg_loop = asyncio.new_event_loop()
_bg_thread = threading.Thread(target=_bg_loop.run_forever, daemon=True)
_bg_thread.start()
```

## 启动方式

设备注册时，通过 `asyncio.run_coroutine_threadsafe` 提交转发协程：

```python
future = asyncio.run_coroutine_threadsafe(
    _start_forward(udid, local_port), _bg_loop
)
device._forward_task = future
```

## `_start_forward` 实现

- `asyncio.start_server(handle_client, "127.0.0.1", local_port)`
- `handle_client`：接受连接后，通过 `usbmux.list_devices()` 找到目标 UDID，调用 `device.create_connection(8100)` 建立 usbmux 通道，双向 relay（复用 `port_forward.py` 中的 `_relay_via_usbmux` 逻辑）
- 协程永不主动退出；终止方式：`future.cancel()`

## 保证

- `local_port` 在整个进程生命周期内持续可用
- 多台设备各自独立的 `local_port`，互不干扰
- `toolkit_api.py` 中不再有任何 `asyncio.run()` 调用

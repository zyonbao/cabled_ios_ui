# session-reuse

WDA session 复用与自动重建，替代 Phase 1 的每次新建模式。

## `_ensure_session() -> str`

私有实例方法，所有需要 session 的操作（`tap`、`swipe`、`input_text`、`key_event`、`launch_app`、`kill_app`）统一调用此方法。

```python
def _ensure_session(self) -> str:
    with self._session_lock:
        if self._session_id is not None:
            return self._session_id
        session_id = _create_session(self.local_port)  # 复用 Phase 1 原语
        self._session_id = session_id
        return session_id
```

## Session 失效自动重建

当 WDA 操作返回 HTTP 4xx 且响应体中 `value.error` 含 `"invalid session id"` 时：

1. `with self._session_lock: self._session_id = None`
2. 调用 `self._ensure_session()` 重建
3. 重试原请求一次
4. 仍失败 → 返回 `SUBPROCESS` 错误，不再重试

## 线程安全

`_session_lock` 保证多线程并发调用时不重复创建 session。

## 与 Phase 1 的差异

| Phase 1 | Phase 3 |
|---|---|
| `_create_session()` 每次调用都新建 | `_ensure_session()` 复用缓存，仅在首次或失效后新建 |
| WDA 重启后自动工作（每次都新建 session） | WDA 重启后第一次操作因 session 失效触发自动重建 |

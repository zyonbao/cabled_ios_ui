"""workers.py — run blocking toolkit_api calls off the Qt main thread.

`ios_toolkit.toolkit_api` is fully synchronous and blocking (WDA HTTP calls,
WDA startup that can take tens of seconds). Calling it on the GUI thread would
freeze the UI, so every call is dispatched to a QThreadPool and its result is
delivered back to the main thread via Qt signals (auto-queued cross-thread).

A monotonically increasing "generation" guards against stale results: when the
user switches devices the generation is bumped, and callbacks tagged with an
older generation are dropped instead of mutating the current UI state.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

import shiboken6
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

logger = logging.getLogger(__name__)


class _CallSignals(QObject):
    done = Signal(object)
    failed = Signal(str)


class _Call(QRunnable):
    """Run a callable in the thread pool, emitting its result or error."""

    def __init__(self, fn: Callable[[], Any]) -> None:
        super().__init__()
        self.fn = fn
        self.signals = _CallSignals()

    def _emit(self, signal: Signal, payload: Any) -> None:
        """Emit only if the signal's C++ object is still alive.

        On app exit a task may still be running in the pool when QApplication
        tears down and deletes the ``_CallSignals`` C++ object; emitting then
        raises ``RuntimeError: Signal source has been deleted``. Skip quietly.
        """
        if not shiboken6.isValid(self.signals):
            return
        try:
            signal.emit(payload)
        except RuntimeError:
            pass  # signal source deleted between the check and the emit

    def run(self) -> None:  # noqa: D401 - QRunnable entry point
        try:
            result = self.fn()
        except Exception as exc:  # surface any failure to the UI thread
            # Background exceptions are otherwise swallowed (only the string
            # reaches the UI); log the full traceback for diagnosis.
            logger.exception("background task failed: %s", exc)
            self._emit(self.signals.failed, str(exc))
            return
        self._emit(self.signals.done, result)


class AsyncRunner:
    """Dispatches blocking work to a shared QThreadPool with generation guards."""

    def __init__(self) -> None:
        self._pool = QThreadPool.globalInstance()
        self._generation = 0
        # Keep references to in-flight calls so their signal objects are not
        # garbage-collected while the pool thread is still running them.
        self._active: set[_Call] = set()

    def bump_generation(self) -> int:
        """Invalidate in-flight callbacks and return the new generation token."""
        self._generation += 1
        return self._generation

    @property
    def generation(self) -> int:
        return self._generation

    def submit(
        self,
        fn: Callable[[], Any],
        on_done: Callable[[Any], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        generation: int | None = None,
    ) -> None:
        """Run ``fn`` in the pool; deliver result/error on the main thread.

        If ``generation`` is provided, the callbacks fire only when it still
        matches the current generation (i.e. the user has not switched away).
        """
        call = _Call(fn)

        def _guarded(cb: Callable[[Any], None] | None) -> Callable[[Any], None]:
            def _inner(payload: Any) -> None:
                if generation is not None and generation != self._generation:
                    return
                if cb is not None:
                    cb(payload)
            return _inner

        if on_done is not None:
            call.signals.done.connect(_guarded(on_done))
        if on_error is not None:
            call.signals.failed.connect(_guarded(on_error))

        # Retain the call until it finishes, then release it (on the main thread).
        self._active.add(call)
        call.signals.done.connect(lambda *_: self._active.discard(call))
        call.signals.failed.connect(lambda *_: self._active.discard(call))
        self._pool.start(call)

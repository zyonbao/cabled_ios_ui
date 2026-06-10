"""log_panel.py — shared live-log stream plumbing for syslog / oslog panels.

`LogStreamThread` drains a toolkit ``LogStreamHandle`` queue (which carries raw
syslog strings or structured oslog dicts) and emits them in batches to keep the
GUI thread responsive. `LogPanelBase` owns the start/stop/pause lifecycle and a
bounded raw buffer; concrete syslog/oslog panels supply the control widgets, the
view widget and the per-payload rendering.

Streaming uses lockdown services only — no WDA / XPC tunnel required.
"""

from __future__ import annotations

import collections
import logging
from typing import Callable

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ios_toolkit import toolkit_api as api

from ..common.workers import AsyncRunner

logger = logging.getLogger(__name__)

# Bound the buffered payloads by *bytes* (not line count) so a high-throughput
# stream cannot grow memory without limit; the oldest entries are evicted first
# once the running estimate exceeds the budget. Full history is served by the
# text / .logarchive export, not by unbounded in-memory retention.
_MAX_BYTES = 10 * 1024 * 1024  # ~10 MB in-memory log budget
# Display-only safety cap for the syslog text widget's block count (the byte
# budget above governs real memory; this just bounds the text widget itself).
_VIEW_BLOCK_LIMIT = 50000
# How often the worker thread flushes accumulated payloads to the GUI thread.
_FLUSH_MS = 100


class LogStreamThread(QThread):
    """Drains a toolkit LogStreamHandle queue and emits batched payloads.

    Payloads are raw syslog strings (``str``) or structured oslog dicts; the
    consuming panel decides how to render them. Batching (rather than one signal
    per line) keeps the GUI responsive under high log throughput.
    """

    batch_ready = Signal(list)
    stream_error = Signal(str)
    stream_eof = Signal()

    def __init__(self, handle) -> None:
        super().__init__()
        self._handle = handle

    def run(self) -> None:  # noqa: D401 - QThread entry point
        import queue as _queue
        import time

        logger.debug("LogStreamThread.run: started")
        total = 0
        pending: list = []
        last_flush = time.monotonic()
        while not self.isInterruptionRequested():
            try:
                kind, payload = self._handle.queue.get(timeout=0.1)
            except _queue.Empty:
                kind = None
            if kind == self._handle.LINE:
                pending.append(payload)
                total += 1
            elif kind == self._handle.ERROR:
                if pending:
                    self.batch_ready.emit(pending)
                logger.warning("LogStreamThread.run: stream ERROR after %s lines", total)
                self.stream_error.emit(str(payload))
                return
            elif kind == self._handle.EOF:
                if pending:
                    self.batch_ready.emit(pending)
                logger.debug("LogStreamThread.run: EOF after %s lines", total)
                self.stream_eof.emit()
                return
            now = time.monotonic()
            if pending and (now - last_flush) * 1000 >= _FLUSH_MS:
                self.batch_ready.emit(pending)
                pending = []
                last_flush = now
        # Interrupted: flush whatever remains.
        if pending:
            self.batch_ready.emit(pending)
        logger.debug("LogStreamThread.run: exiting (interrupted, total=%s)", total)

    def stop(self) -> None:
        """Cancel the toolkit stream and stop this thread (idempotent)."""
        logger.debug("LogStreamThread.stop: requesting interruption + closing handle")
        self.requestInterruption()
        if self._handle is not None:
            self._handle.close()
        finished = self.wait(3000)
        logger.debug("LogStreamThread.stop: wait finished=%s", finished)


class LogPanelBase(QWidget):
    """Shared start/stop/pause lifecycle + bounded buffer for a log view.

    Subclasses implement: ``SOURCE``; ``_build_controls`` (extra toolbar
    widgets); ``_build_view`` (the view widget); ``_stream_kwargs`` (oslog
    source-side filter params); ``_append_payload`` (render one payload honoring
    the current filter); ``_clear_view``; ``_rebuild_view`` (re-render the buffer
    with the current filter).
    """

    SOURCE = "syslog"

    def __init__(
        self,
        runner: AsyncRunner,
        get_target: Callable[[], str],
        get_os_version: Callable[[], str],
    ) -> None:
        super().__init__()
        self.runner = runner
        self._get_target = get_target
        self._get_os_version = get_os_version
        self._thread: LogStreamThread | None = None
        self._paused = False
        # Raw (unfiltered) payload buffer; the view shows the filtered subset.
        # Bounded by bytes (see _MAX_BYTES): a parallel _sizes deque tracks each
        # payload's estimated size so the running total stays cheap to maintain.
        self._buffer: collections.deque = collections.deque()
        self._sizes: collections.deque = collections.deque()
        self._buffer_bytes = 0
        self._byte_budget = _MAX_BYTES
        self._build_ui()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        bar = QHBoxLayout()
        self.start_btn = QPushButton("开始")
        self.pause_btn = QPushButton("暂停")
        self.pause_btn.setCheckable(True)
        # Pause is only meaningful while a stream is running; disabled (and reset
        # to "暂停") whenever the start button is in its "开始" (idle) state.
        self.pause_btn.setEnabled(False)
        self.clear_btn = QPushButton("清空")
        bar.addWidget(self.start_btn)
        bar.addWidget(self.pause_btn)
        bar.addWidget(self.clear_btn)
        self._build_controls(bar)
        root.addLayout(bar)

        self.view = self._build_view()
        root.addWidget(self.view, 1)

        self.status = QLabel("请选择设备后点击「开始」")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        self.start_btn.clicked.connect(self._toggle_start)
        self.pause_btn.toggled.connect(self._on_pause_toggled)
        self.clear_btn.clicked.connect(self._clear)

    # ------------------------------------------------------- subclass hooks

    def _build_controls(self, bar: QHBoxLayout) -> None:  # pragma: no cover - override
        """Append source-specific controls to the toolbar."""

    def _build_view(self) -> QWidget:  # pragma: no cover - override
        raise NotImplementedError

    def _stream_kwargs(self) -> dict:
        """Source-side stream filter kwargs (oslog: pid/message_filter/...)."""
        return {}

    def _render_appended(self, payloads: list) -> None:  # pragma: no cover - override
        """Render a batch of newly-arrived payloads, honoring the current filter.

        Called once per flushed batch (not per line) so views can insert in bulk
        and keep the GUI responsive under high log throughput.
        """
        raise NotImplementedError

    def _render_evicted(self, payloads: list) -> None:
        """Drop the given oldest payloads from the view (default: no-op).

        The byte-budget eviction calls this with the payloads removed from the
        front of the buffer so views holding strong references (e.g. a table
        model) can release them and actually free memory.
        """

    @staticmethod
    def _payload_bytes(payload) -> int:
        """Estimate a payload's retained size for the byte budget (conservative)."""
        if isinstance(payload, dict):
            return sum(len(str(v)) for v in payload.values()) + 64
        return len(str(payload)) + 16

    def _clear_view(self) -> None:  # pragma: no cover - override
        raise NotImplementedError

    def _rebuild_view(self) -> None:  # pragma: no cover - override
        """Re-render the whole buffer with the current filter applied."""
        raise NotImplementedError

    # -------------------------------------------------------- device switch

    def set_target(self, target: str) -> None:
        """Called when the selected device changes."""
        self._stop_stream()
        # Drop the previous device's logs (memory + view) on switch.
        self._clear()
        if target:
            self.status.setText("点击「开始」以查看实时日志")
        else:
            self.status.setText("未选择设备")

    # ---------------------------------------------------------- start/stop

    def _is_running(self) -> bool:
        return self._thread is not None

    def _toggle_start(self) -> None:
        if self._is_running():
            self._stop_stream()
            self.status.setText("已停止")
            return
        self._start_stream()

    def _start_stream(self) -> None:
        target = self._get_target()
        if not target:
            self.status.setText("未选择设备")
            return
        logger.debug("_start_stream: source=%s target=%s kwargs=%s",
                     self.SOURCE, target, self._stream_kwargs())
        handle = api.open_log_stream(target, self.SOURCE, **self._stream_kwargs())
        # open_log_stream returns a handle on success or an error envelope.
        if isinstance(handle, dict):
            logger.warning("_start_stream: open_log_stream returned error envelope: %s", handle)
            self.status.setText(
                "无法开始: " + handle.get("error", {}).get("message", "")
            )
            return
        self._thread = LogStreamThread(handle)
        self._thread.batch_ready.connect(self._on_batch)
        self._thread.stream_error.connect(self._on_stream_error)
        self._thread.stream_eof.connect(self._on_stream_eof)
        self._thread.start()
        self.start_btn.setText("停止")
        # Running: pause toggling becomes available (starts in "暂停"/unchecked).
        self.pause_btn.setEnabled(True)
        self.status.setText(f"正在实时流：{self.SOURCE}")

    def _stop_stream(self) -> None:
        if self._thread is not None:
            logger.debug("_stop_stream: source=%s", self.SOURCE)
            thread, self._thread = self._thread, None
            for sig, slot in (
                (thread.batch_ready, self._on_batch),
                (thread.stream_error, self._on_stream_error),
                (thread.stream_eof, self._on_stream_eof),
            ):
                try:
                    sig.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
            thread.stop()
            thread.deleteLater()
        self.start_btn.setText("开始")
        # Idle: pause resets to "暂停"/unchecked and is disabled (linkage rule).
        if self._paused or self.pause_btn.isChecked():
            self.pause_btn.setChecked(False)  # toggled handler resets _paused/text
        self._paused = False
        self.pause_btn.setEnabled(False)

    # ------------------------------------------------------------ rendering

    def _on_batch(self, payloads: list) -> None:
        if not self._buffer:
            logger.debug("_on_batch: first batch arrived (n=%s, source=%s)",
                         len(payloads), self.SOURCE)
        if self._paused:
            # Decision: drop new payloads while paused (no memory build-up).
            return
        for payload in payloads:
            size = self._payload_bytes(payload)
            self._buffer.append(payload)
            self._sizes.append(size)
            self._buffer_bytes += size
        # Evict the oldest payloads until back within the byte budget, then tell
        # the view which ones left (so a model holding references can free them).
        evicted: list = []
        while self._buffer_bytes > self._byte_budget and len(self._buffer) > 1:
            self._buffer_bytes -= self._sizes.popleft()
            evicted.append(self._buffer.popleft())
        if evicted:
            self._render_evicted(evicted)
        self._render_appended(payloads)

    def _on_pause_toggled(self, checked: bool) -> None:
        self._paused = checked
        self.pause_btn.setText("继续" if checked else "暂停")

    def _clear(self) -> None:
        self._buffer.clear()
        self._sizes.clear()
        self._buffer_bytes = 0
        self._clear_view()

    # -------------------------------------------------------------- errors

    def _on_stream_error(self, message: str) -> None:
        self._stop_stream()
        self.status.setText(f"流中断: {message}")

    def _on_stream_eof(self) -> None:
        self._stop_stream()
        self.status.setText("流已结束")

    # ------------------------------------------------------------- shutdown

    def shutdown(self) -> None:
        """Stop the stream thread (called when the host dialog closes)."""
        self._stop_stream()

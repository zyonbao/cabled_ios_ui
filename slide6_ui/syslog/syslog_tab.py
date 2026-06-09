"""syslog_tab.py — the "系统日志" tab (live syslog / oslog stream).

A drop-down selects the source (syslog = raw syslog_relay, oslog = structured
os_trace). A background QThread drains the toolkit LogStreamHandle's thread-safe
queue and emits batched lines; the GUI thread renders them with a bounded line
buffer (rate-limited, top-trimmed). Supports case-insensitive keyword filtering,
pause (drops new lines while paused), clear, and save-to-file.

Streaming uses lockdown services only — no WDA / tunnel required. The toolkit
runs the actual device I/O on its shared background event loop; this tab never
touches pymobiledevice3 directly.
"""

from __future__ import annotations

import collections
from typing import Callable

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ios_toolkit import toolkit_api as api

from ..common.workers import AsyncRunner

# Bound the on-screen / buffered line count so a high-throughput stream cannot
# grow memory or the text widget without limit; oldest lines are trimmed first.
_MAX_LINES = 5000
# How often the worker thread flushes accumulated lines to the GUI thread.
_FLUSH_MS = 100


class SyslogStreamThread(QThread):
    """Drains a toolkit LogStreamHandle queue and emits batched lines.

    Batching (rather than one signal per line) keeps the GUI thread responsive
    under high log throughput.
    """

    lines_ready = Signal(list)
    stream_error = Signal(str)
    stream_eof = Signal()

    def __init__(self, handle) -> None:
        super().__init__()
        self._handle = handle

    def run(self) -> None:  # noqa: D401 - QThread entry point
        import queue as _queue
        import time

        pending: list[str] = []
        last_flush = time.monotonic()
        while not self.isInterruptionRequested():
            try:
                kind, payload = self._handle.queue.get(timeout=0.1)
            except _queue.Empty:
                kind = None
            if kind == self._handle.LINE:
                pending.append(payload)
            elif kind == self._handle.ERROR:
                if pending:
                    self.lines_ready.emit(pending)
                self.stream_error.emit(str(payload))
                return
            elif kind == self._handle.EOF:
                if pending:
                    self.lines_ready.emit(pending)
                self.stream_eof.emit()
                return
            now = time.monotonic()
            if pending and (now - last_flush) * 1000 >= _FLUSH_MS:
                self.lines_ready.emit(pending)
                pending = []
                last_flush = now
        # Interrupted: flush whatever remains.
        if pending:
            self.lines_ready.emit(pending)

    def stop(self) -> None:
        """Cancel the toolkit stream and stop this thread (idempotent)."""
        self.requestInterruption()
        if self._handle is not None:
            self._handle.close()
        self.wait(3000)


class SyslogTab(QWidget):
    """The "系统日志" tab: live syslog/oslog with filter / pause / clear / save."""

    def __init__(self, runner: AsyncRunner, get_target: Callable[[], str]) -> None:
        super().__init__()
        self.runner = runner
        self._get_target = get_target
        self._thread: SyslogStreamThread | None = None
        self._paused = False
        # Raw (unfiltered) line buffer; the view shows the filtered subset.
        self._lines: collections.deque[str] = collections.deque(maxlen=_MAX_LINES)
        self._build_ui()
        self._wire()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        bar = QHBoxLayout()
        self.source_combo = QComboBox()
        self.source_combo.addItem("syslog（传统）", "syslog")
        self.source_combo.addItem("oslog（结构化）", "oslog")
        self.start_btn = QPushButton("开始")
        self.pause_btn = QPushButton("暂停")
        self.pause_btn.setCheckable(True)
        self.clear_btn = QPushButton("清空")
        self.save_btn = QPushButton("另存…")
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("关键字过滤（大小写不敏感）")
        bar.addWidget(QLabel("来源"))
        bar.addWidget(self.source_combo)
        bar.addWidget(self.start_btn)
        bar.addWidget(self.pause_btn)
        bar.addWidget(self.clear_btn)
        bar.addWidget(self.save_btn)
        bar.addWidget(self.filter_input, 1)
        root.addLayout(bar)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(_MAX_LINES)
        self.view.setLineWrapMode(QPlainTextEdit.NoWrap)
        root.addWidget(self.view, 1)

        self.status = QLabel("请选择设备后点击「开始」")
        root.addWidget(self.status)

    def _wire(self) -> None:
        self.start_btn.clicked.connect(self._toggle_start)
        self.pause_btn.toggled.connect(self._on_pause_toggled)
        self.clear_btn.clicked.connect(self._clear)
        self.save_btn.clicked.connect(self._save)
        self.filter_input.textChanged.connect(self._apply_filter)
        self.source_combo.currentIndexChanged.connect(self._on_source_changed)

    # -------------------------------------------------------- device switch

    def set_target(self, target: str) -> None:
        """Called by the main window when the selected device changes."""
        self._stop_stream()
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
        source = self.source_combo.currentData()
        handle = api.open_log_stream(target, source)
        # open_log_stream returns a handle on success or an error envelope.
        if isinstance(handle, dict):
            self.status.setText(
                "无法开始: " + handle.get("error", {}).get("message", "")
            )
            return
        self._thread = SyslogStreamThread(handle)
        self._thread.lines_ready.connect(self._on_lines)
        self._thread.stream_error.connect(self._on_stream_error)
        self._thread.stream_eof.connect(self._on_stream_eof)
        self._thread.start()
        self.start_btn.setText("停止")
        self.source_combo.setEnabled(False)
        self.status.setText(f"正在实时流：{source}")

    def _stop_stream(self) -> None:
        if self._thread is not None:
            thread, self._thread = self._thread, None
            try:
                thread.lines_ready.disconnect(self._on_lines)
            except (RuntimeError, TypeError):
                pass
            thread.stop()
            thread.deleteLater()
        self.start_btn.setText("开始")
        self.source_combo.setEnabled(True)

    def _on_source_changed(self, _index: int) -> None:
        # Switching source while running rebuilds the stream cleanly.
        if self._is_running():
            self._stop_stream()
            self._start_stream()

    # ------------------------------------------------------------ rendering

    def _on_lines(self, lines: list) -> None:
        if self._paused:
            # Decision: drop new lines while paused (no memory build-up).
            return
        kw = self.filter_input.text().strip().lower()
        for line in lines:
            self._lines.append(line)
            if not kw or kw in line.lower():
                self.view.appendPlainText(line)

    def _apply_filter(self) -> None:
        kw = self.filter_input.text().strip().lower()
        self.view.clear()
        if kw:
            matched = [ln for ln in self._lines if kw in ln.lower()]
        else:
            matched = list(self._lines)
        if matched:
            self.view.setPlainText("\n".join(matched))

    def _on_pause_toggled(self, checked: bool) -> None:
        self._paused = checked
        self.pause_btn.setText("继续" if checked else "暂停")

    def _clear(self) -> None:
        self._lines.clear()
        self.view.clear()

    def _save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "另存日志", "device.log", "日志文件 (*.log *.txt)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.view.toPlainText())
            self.status.setText(f"已保存到 {path}")
        except OSError as exc:
            self.status.setText(f"保存失败: {exc}")

    # -------------------------------------------------------------- errors

    def _on_stream_error(self, message: str) -> None:
        self._stop_stream()
        self.status.setText(f"流中断: {message}")

    def _on_stream_eof(self) -> None:
        self._stop_stream()
        self.status.setText("流已结束")

    # ------------------------------------------------------------- shutdown

    def shutdown(self) -> None:
        """Stop the stream thread (called from the main window on close)."""
        self._stop_stream()

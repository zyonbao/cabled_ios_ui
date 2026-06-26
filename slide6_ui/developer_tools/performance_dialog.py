"""performance_dialog.py — DVT performance monitor dialog.

Shows live sysmontap-based charts (CPU, memory, process, and net/disk IO) with a
10-minute rolling window. Sampling runs on a background DVT stream handle
created on Start and torn down on Stop / window close.
"""

from __future__ import annotations

import queue
import time
from collections import deque

from PySide6.QtCore import QRect, QTimer, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ios_toolkit import toolkit_api as api

from .. import i18n
from ..common.errors import localize_error
from ..common.workers import AsyncRunner, fire_and_forget


class _MultiMetricChart(QWidget):
    """Tiny multi-series line chart over a rolling 10-minute window."""

    AXIS_AUTO = "auto"
    AXIS_PERCENT = "percent"
    _PADDING = 12
    _HEADER_H = 22
    _LEGEND_ROW_H = 16

    def __init__(
        self,
        title: str,
        unit: str,
        series: list[tuple[str, QColor]],
        axis_mode: str = AXIS_AUTO,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._title = title
        self._unit = unit
        self._series = series
        self._axis_mode = axis_mode
        self._points: dict[str, deque[tuple[float, float]]] = {
            name: deque() for name, _ in series
        }
        self._visible: dict[str, bool] = {name: True for name, _ in series}
        self._legend_hitboxes: list[tuple[str, QRect]] = []
        self._fixed_max: float | None = None
        self.setMinimumHeight(130)
        # Multi-series charts let the user click the legend to toggle lines.
        if len(series) > 1:
            self.setCursor(Qt.PointingHandCursor)

    def clear(self) -> None:
        for points in self._points.values():
            points.clear()
        self.update()

    def set_fixed_max(self, value: float | None) -> None:
        self._fixed_max = value if (value is not None and value > 0) else None
        self.update()

    def append(self, name: str, ts: float, value: float) -> None:
        points = self._points.get(name)
        if points is None:
            return
        points.append((ts, value))
        self._drop_expired(points, ts)
        self.update()

    def _drop_expired(self, points: deque[tuple[float, float]], now_ts: float) -> None:
        cutoff = now_ts - 600.0
        while points and points[0][0] < cutoff:
            points.popleft()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(20, 20, 20))
        margin = self._PADDING
        left = margin
        right = self.width() - margin
        bottom = self.height() - margin

        legend_rows = self._estimate_legend_rows(max(120, right - left))
        top = margin + self._HEADER_H + legend_rows * self._LEGEND_ROW_H + 6
        chart_w = max(1, right - left)
        chart_h = max(1, bottom - top)

        painter.setPen(QPen(QColor(90, 90, 90), 1))
        painter.drawRect(left, top, chart_w, chart_h)

        core_value = self._core_value_text()
        painter.setPen(QPen(QColor(220, 220, 220), 1))
        painter.drawText(left, margin + 14, f"{self._title} {core_value}".rstrip())
        self._draw_legend_multiline(painter, left, margin + self._HEADER_H, right)

        all_points = [
            p
            for name, _ in self._series
            if self._visible.get(name, True)
            for p in self._points[name]
        ]
        if len(all_points) < 2:
            self._draw_axis_labels(painter, left, top, bottom, 0.0, 0.0)
            self._update_tooltip()
            return

        min_v, max_v = self._axis_range(all_points)
        if max_v <= min_v:
            max_v = min_v + 1.0
        if abs(max_v - min_v) < 1e-9:
            max_v = min_v + 1.0
        now_ts = max(ts for ts, _ in all_points)
        start_ts = now_ts - 600.0

        for name, color in self._series:
            if not self._visible.get(name, True):
                continue
            points = self._points[name]
            if len(points) < 2:
                continue
            painter.setPen(QPen(color, 2))
            prev = None
            for ts, value in points:
                x = left + int(((ts - start_ts) / 600.0) * chart_w)
                y = top + int((1.0 - (value - min_v) / (max_v - min_v)) * chart_h)
                if prev is not None:
                    painter.drawLine(prev[0], prev[1], x, y)
                prev = (x, y)
        self._draw_grid(painter, left, top, chart_w, chart_h)
        self._draw_axis_labels(painter, left, top, bottom, min_v, max_v)
        self._update_tooltip()

    def _axis_range(self, all_points: list[tuple[float, float]]) -> tuple[float, float]:
        if self._axis_mode == self.AXIS_PERCENT:
            return (0.0, 100.0)
        min_v = 0.0
        if self._fixed_max is not None and self._fixed_max > 0:
            return (min_v, float(self._fixed_max))
        max_v = max(v for _, v in all_points)
        return (min_v, max(1.0, max_v))

    def _draw_grid(self, painter: QPainter, left: int, top: int, chart_w: int, chart_h: int) -> None:
        painter.setPen(QPen(QColor(55, 55, 55), 1))
        for i in range(1, 4):
            y = top + int(chart_h * i / 4)
            painter.drawLine(left, y, left + chart_w, y)
        for i in range(1, 6):
            x = left + int(chart_w * i / 6)
            painter.drawLine(x, top, x, top + chart_h)

    def _draw_axis_labels(
        self,
        painter: QPainter,
        left: int,
        top: int,
        bottom: int,
        min_v: float,
        max_v: float,
    ) -> None:
        painter.setPen(QPen(QColor(170, 170, 170), 1))
        top_text = f"{max_v:.0f} {self._unit}".strip() if self._unit else f"{max_v:.0f}"
        bottom_text = f"{min_v:.0f} {self._unit}".strip() if self._unit else f"{min_v:.0f}"
        painter.drawText(left + 4, top + 12, top_text)
        painter.drawText(left + 4, bottom - 2, bottom_text)

    def _estimate_legend_rows(self, width: int) -> int:
        rows = 1
        used = 0
        for name, _color in self._series:
            item_w = 26 + max(48, len(name) * 7)
            if used > 0 and used + item_w > width:
                rows += 1
                used = 0
            used += item_w
        return rows

    def _draw_legend_multiline(self, painter: QPainter, left: int, base_y: int, right: int) -> None:
        self._legend_hitboxes = []
        x = left
        y = base_y + 10
        for name, color in self._series:
            item_w = 26 + max(48, len(name) * 7)
            if x > left and x + item_w > right:
                x = left
                y += self._LEGEND_ROW_H
            visible = self._visible.get(name, True)
            line_color = color if visible else QColor(90, 90, 90)
            text_color = QColor(220, 220, 220) if visible else QColor(120, 120, 120)
            painter.setPen(QPen(line_color, 2))
            painter.drawLine(x, y, x + 14, y)
            painter.setPen(QPen(text_color, 1))
            painter.drawText(x + 18, y + 4, name)
            self._legend_hitboxes.append((name, QRect(x, y - 8, item_w, self._LEGEND_ROW_H)))
            x += item_w

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        # Click a legend entry to toggle its line; at least one stays visible.
        if len(self._series) > 1:
            pos = event.position().toPoint()
            for name, rect in self._legend_hitboxes:
                if not rect.contains(pos):
                    continue
                currently_visible = self._visible.get(name, True)
                visible_count = sum(1 for v in self._visible.values() if v)
                if currently_visible and visible_count <= 1:
                    return  # keep the last visible line on
                self._visible[name] = not currently_visible
                self.update()
                return
        super().mousePressEvent(event)

    def _core_value_text(self) -> str:
        for name, _ in self._series:
            if not self._visible.get(name, True):
                continue
            points = self._points[name]
            if points:
                value = points[-1][1]
                if self._unit:
                    return f"{value:.1f} {self._unit}"
                return f"{value:.1f}"
        return "--"

    def _update_tooltip(self) -> None:
        lines = [self._title]
        for name, _ in self._series:
            points = self._points[name]
            if points:
                value = points[-1][1]
                label = f"{name}: {value:.2f} {self._unit}".rstrip()
            else:
                label = f"{name}: --"
            if not self._visible.get(name, True):
                label += "  (hidden)"
            lines.append(label)
        if len(self._series) > 1:
            lines.append("— click legend to toggle —")
        self.setToolTip("\n".join(lines))


class PerformanceDialog(QDialog):
    """Live performance monitor with 4 sysmontap charts."""

    def __init__(self, runner: AsyncRunner, target: str, parent=None) -> None:
        super().__init__(parent)
        self.runner = runner
        self._target = target
        self._stream = None
        self._running = False
        self._paused = False
        self._sample_count = 0
        self._cache: deque[dict] = deque()
        self._physical_mem_mb: float | None = None
        self._counter_state: dict[str, tuple[float, float]] = {}

        self.setWindowTitle(i18n.t("performance.title"))
        self.resize(880, 560)
        self._build_ui()
        self._wire()

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(250)
        self._poll_timer.timeout.connect(self._drain_stream)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        top = QGridLayout()
        top.addWidget(QLabel(i18n.t("performance.status_label")), 0, 0)
        self.state_label = QLabel(i18n.t("performance.state.idle"))
        top.addWidget(self.state_label, 0, 1)
        top.addWidget(QLabel(i18n.t("performance.cache_label")), 0, 2)
        self.cache_label = QLabel("0")
        top.addWidget(self.cache_label, 0, 3)
        top.addWidget(QLabel(i18n.t("performance.updated_label")), 0, 4)
        self.updated_label = QLabel(i18n.t("performance.updated_never"))
        top.addWidget(self.updated_label, 0, 5)
        top.addWidget(QLabel(i18n.t("performance.interval_label")), 0, 6)
        self.interval_combo = QComboBox()
        for ms in (200, 500, 1000, 2000):
            self.interval_combo.addItem(f"{ms} ms", ms)
        self.interval_combo.setCurrentIndex(1)
        top.addWidget(self.interval_combo, 0, 7)
        root.addLayout(top)

        controls = QHBoxLayout()
        self.start_btn = QPushButton(i18n.t("performance.start"))
        self.stop_btn = QPushButton(i18n.t("performance.stop"))
        self.pause_btn = QPushButton(i18n.t("performance.pause"))
        self.clear_btn = QPushButton(i18n.t("performance.clear"))
        controls.addWidget(self.start_btn)
        controls.addWidget(self.stop_btn)
        controls.addWidget(self.pause_btn)
        controls.addWidget(self.clear_btn)
        controls.addStretch(1)
        root.addLayout(controls)

        self.cpu_chart = _MultiMetricChart(
            "CPU",
            "%",
            [("CPU Usage", QColor(112, 214, 255))],
            axis_mode=_MultiMetricChart.AXIS_PERCENT,
        )
        self.mem_chart = _MultiMetricChart(
            "Memory Used",
            "MB",
            [("Used (active+wired+compressed)", QColor(161, 236, 124))],
        )
        self.io_chart = _MultiMetricChart(
            "Net/Disk IO",
            "KB/s",
            [
                ("Network RX", QColor(97, 218, 251)),
                ("Network TX", QColor(255, 167, 38)),
                ("Disk Read", QColor(129, 199, 132)),
                ("Disk Write", QColor(239, 83, 80)),
            ],
        )
        root.addWidget(self.cpu_chart)
        root.addWidget(self.mem_chart)
        root.addWidget(self.io_chart)

        self.status = QLabel(i18n.t("performance.hint"))
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self._sync_buttons()

    def _wire(self) -> None:
        self.start_btn.clicked.connect(self._start)
        self.stop_btn.clicked.connect(self._stop)
        self.pause_btn.clicked.connect(self._toggle_pause)
        self.clear_btn.clicked.connect(self._clear)

    def _start(self) -> None:
        if self._running:
            return
        self._counter_state.clear()
        interval_ms = int(self.interval_combo.currentData() or 500)
        opened = api.open_performance_stream(self._target, interval_ms=interval_ms)
        if isinstance(opened, dict):
            self.status.setText(localize_error(opened.get("error")))
            return
        self._stream = opened
        self._running = True
        self._paused = False
        self._poll_timer.start()
        self.state_label.setText(i18n.t("performance.state.running"))
        self.status.setText(i18n.t("performance.started", interval=interval_ms))
        self._sync_buttons()

    def _stop(self) -> None:
        self._poll_timer.stop()
        stream, self._stream = self._stream, None
        if stream is not None:
            # close() blocks up to 3s waiting for stream cleanup; closeEvent calls
            # _stop on exit, so run it on a daemon thread to keep the UI thread (and
            # app exit) from blocking on it.
            fire_and_forget(stream.close, name="performance-stream-close")
        self._running = False
        self._paused = False
        self.state_label.setText(i18n.t("performance.state.idle"))
        self.status.setText(i18n.t("performance.stopped"))
        self._sync_buttons()

    def _toggle_pause(self) -> None:
        if not self._running:
            return
        self._paused = not self._paused
        if self._paused:
            self.state_label.setText(i18n.t("performance.state.paused"))
            self.pause_btn.setText(i18n.t("performance.resume"))
        else:
            self.state_label.setText(i18n.t("performance.state.running"))
            self.pause_btn.setText(i18n.t("performance.pause"))
            self._render_from_cache()
        self.status.setText(i18n.t("performance.paused" if self._paused else "performance.resumed"))

    def _clear(self) -> None:
        self._cache.clear()
        self._sample_count = 0
        self._counter_state.clear()
        self.cache_label.setText("0")
        self.updated_label.setText(i18n.t("performance.updated_never"))
        self.cpu_chart.clear()
        self.mem_chart.clear()
        self.io_chart.clear()
        self.status.setText(i18n.t("performance.cleared"))

    def _drain_stream(self) -> None:
        if self._stream is None:
            return
        now = time.time()
        drained = 0
        while True:
            try:
                kind, payload = self._stream.queue.get_nowait()
            except queue.Empty:
                break
            drained += 1
            if kind == self._stream.ERROR:
                self.status.setText(i18n.t("performance.stream_error", error=payload))
                self._stop()
                return
            if kind == self._stream.EOF:
                self.status.setText(i18n.t("performance.stream_end"))
                self._stop()
                return
            if kind != self._stream.LINE or not isinstance(payload, dict):
                continue
            payload = self._decorate_rates(payload)
            self._cache.append(payload)
            self._sample_count += 1
            ts = float(payload.get("timestamp", now))
            self.updated_label.setText(time.strftime("%H:%M:%S", time.localtime(ts)))
            pm = payload.get("physical_mem_mb")
            if isinstance(pm, (int, float)) and pm > 0:
                self._physical_mem_mb = float(pm)
                self.mem_chart.set_fixed_max(self._physical_mem_mb)
        cutoff = now - 600.0
        while self._cache and float(self._cache[0].get("timestamp", 0.0)) < cutoff:
            self._cache.popleft()
        self.cache_label.setText(str(len(self._cache)))
        if drained and not self._paused:
            self._render_from_cache()

    def _render_from_cache(self) -> None:
        self.cpu_chart.clear()
        self.mem_chart.clear()
        self.io_chart.clear()
        for sample in self._cache:
            ts = float(sample.get("timestamp", 0.0))
            cpu_v = sample.get("cpu_percent")
            if isinstance(cpu_v, (int, float)):
                self.cpu_chart.append("CPU Usage", ts, float(cpu_v))
            mem_v = sample.get("memory_used_mb")
            if isinstance(mem_v, (int, float)):
                self.mem_chart.append("Used (active+wired+compressed)", ts, float(mem_v))
            rx_v = sample.get("net_rx_kbps")
            if isinstance(rx_v, (int, float)):
                self.io_chart.append("Network RX", ts, float(rx_v))
            tx_v = sample.get("net_tx_kbps")
            if isinstance(tx_v, (int, float)):
                self.io_chart.append("Network TX", ts, float(tx_v))
            dr_v = sample.get("disk_read_kbps")
            if isinstance(dr_v, (int, float)):
                self.io_chart.append("Disk Read", ts, float(dr_v))
            dw_v = sample.get("disk_write_kbps")
            if isinstance(dw_v, (int, float)):
                self.io_chart.append("Disk Write", ts, float(dw_v))

    def _decorate_rates(self, sample: dict) -> dict:
        ts = float(sample.get("timestamp", 0.0))
        sample["net_rx_kbps"] = self._counter_rate("net_bytes_in", sample, ts)
        sample["net_tx_kbps"] = self._counter_rate("net_bytes_out", sample, ts)
        sample["disk_read_kbps"] = self._counter_rate("disk_bytes_read", sample, ts)
        sample["disk_write_kbps"] = self._counter_rate("disk_bytes_written", sample, ts)
        return sample

    def _counter_rate(self, key: str, sample: dict, ts: float) -> float | None:
        cur = sample.get(key)
        if not isinstance(cur, (int, float)) or cur < 0:
            return None
        current = float(cur)
        last = self._counter_state.get(key)
        if last is None:
            self._counter_state[key] = (ts, current)
            return None
        last_ts, last_value = last
        if current < last_value:
            self._counter_state[key] = (ts, current)
            return None
        delta = current - last_value
        if delta == 0:
            return 0.0
        elapsed = ts - last_ts
        if elapsed <= 0:
            return None
        self._counter_state[key] = (ts, current)
        return delta / elapsed / 1024.0

    def _sync_buttons(self) -> None:
        self.start_btn.setEnabled(not self._running)
        self.stop_btn.setEnabled(self._running)
        self.pause_btn.setEnabled(self._running)
        if not self._running:
            self.pause_btn.setText(i18n.t("performance.pause"))
        self.interval_combo.setEnabled(not self._running)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        self._stop()
        super().closeEvent(event)


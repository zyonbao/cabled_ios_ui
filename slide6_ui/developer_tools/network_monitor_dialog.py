"""network_monitor_dialog.py — DVT Network Monitor sub-panel.

Live connection flows + throughput from the DVT NetworkMonitor instrument
(event-driven, no device sample interval). Three columns: left = TopN grouped by
remote IP / interface, middle = connection list, right = throughput trend +
detail. Per-flow process attribution is unavailable on modern iOS (pid=-2), so
there is no process column. The handle is created on Start and torn down on
Stop / window close.
"""

from __future__ import annotations

import json
import time
from collections import deque

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ios_toolkit import toolkit_api as api

from .. import i18n
from ..common.errors import localize_error
from ..common.file_dialogs import save_file
from ..common.focus import suppress_auto_focus
from ..common.workers import AsyncRunner
from .performance_dialog import _MultiMetricChart

_MAX_ROWS = 500  # cap rendered connection rows for UI responsiveness


class NetworkMonitorDialog(QDialog):
    """Live network monitor with grouped TopN, connection list and throughput trend."""

    def __init__(self, runner: AsyncRunner, target: str, parent=None) -> None:
        super().__init__(parent)
        self.runner = runner
        self._target = target
        self._handle = None
        self._running = False
        self._paused = False
        self._auto_scroll = True
        self._rate_state = None  # (ts, cum_rx, cum_tx)
        self._snapshot: dict | None = None
        self._group_filter: tuple[str, str] | None = None  # (mode, key)
        self._rx_series: deque = deque()
        self._tx_series: deque = deque()

        self.setWindowTitle(i18n.t("network.title"))
        self.resize(1040, 600)
        self._build_ui()
        self._wire()
        suppress_auto_focus(self)

        self._poll = QTimer(self)
        self._poll.setInterval(400)  # render/aggregation throttle (not a device rate)
        self._poll.timeout.connect(self._tick)

    # -- UI ----------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # Status + control bar
        bar = QHBoxLayout()
        bar.addWidget(QLabel(i18n.t("network.status_label")))
        self.state_label = QLabel(i18n.t("network.state.idle"))
        bar.addWidget(self.state_label)
        self.stats_label = QLabel("")
        bar.addWidget(self.stats_label)
        bar.addStretch(1)
        self.start_btn = QPushButton(i18n.t("network.start"))
        self.stop_btn = QPushButton(i18n.t("network.stop"))
        self.pause_btn = QPushButton(i18n.t("network.pause"))
        self.clear_btn = QPushButton(i18n.t("network.clear"))
        self.autoscroll_chk = QCheckBox(i18n.t("network.autoscroll"))
        self.autoscroll_chk.setChecked(True)
        self.export_btn = QPushButton(i18n.t("network.export"))
        for w in (self.start_btn, self.stop_btn, self.pause_btn, self.clear_btn,
                  self.autoscroll_chk, self.export_btn):
            bar.addWidget(w)
        root.addLayout(bar)

        # Filter bar
        flt = QHBoxLayout()
        flt.addWidget(QLabel(i18n.t("network.group_by")))
        self.group_combo = QComboBox()
        self.group_combo.addItem(i18n.t("network.group_remote"), "remote_ip")
        self.group_combo.addItem(i18n.t("network.group_iface"), "iface")
        flt.addWidget(self.group_combo)
        flt.addWidget(QLabel(i18n.t("network.protocol")))
        self.proto_combo = QComboBox()
        self.proto_combo.addItem(i18n.t("network.group_all"), "")
        for proto in ("TCP", "UDP", "unknown"):
            self.proto_combo.addItem(proto, proto)
        flt.addWidget(self.proto_combo)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(i18n.t("network.search_placeholder"))
        flt.addWidget(self.search_input, 1)
        self.active_chk = QCheckBox(i18n.t("network.active_only"))
        flt.addWidget(self.active_chk)
        root.addLayout(flt)

        # Three-column splitter
        split = QSplitter(Qt.Orientation.Horizontal)

        self.group_table = QTableWidget(0, 3)
        self.group_table.setHorizontalHeaderLabels([
            i18n.t("network.col_group"), i18n.t("network.col_conns"), i18n.t("network.col_bytes"),
        ])
        self._tune_table(self.group_table)
        split.addWidget(self.group_table)

        self.conn_table = QTableWidget(0, 6)
        self.conn_table.setHorizontalHeaderLabels([
            i18n.t("network.col_time"), i18n.t("network.col_proto"), i18n.t("network.col_dir"),
            i18n.t("network.col_local"), i18n.t("network.col_remote"), i18n.t("network.col_bytes"),
        ])
        self._tune_table(self.conn_table)
        split.addWidget(self.conn_table)

        right = QWidget()
        rlay = QVBoxLayout(right)
        rlay.setContentsMargins(0, 0, 0, 0)
        self.trend = _MultiMetricChart(
            "Throughput", "KB/s",
            [("Rx", QColor(97, 218, 251)), ("Tx", QColor(255, 167, 38))],
        )
        rlay.addWidget(self.trend, 1)
        self.detail_label = QLabel(i18n.t("network.no_selection"))
        self.detail_label.setWordWrap(True)
        self.detail_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        rlay.addWidget(self.detail_label)
        split.addWidget(right)

        split.setSizes([260, 520, 260])
        root.addWidget(split, 1)

        self.status = QLabel(i18n.t("network.hint"))
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self._sync_buttons()

    @staticmethod
    def _tune_table(table: QTableWidget) -> None:
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

    def _wire(self) -> None:
        self.start_btn.clicked.connect(self._start)
        self.stop_btn.clicked.connect(self._stop)
        self.pause_btn.clicked.connect(self._toggle_pause)
        self.clear_btn.clicked.connect(self._clear)
        self.export_btn.clicked.connect(self._export)
        self.autoscroll_chk.toggled.connect(self._on_autoscroll)
        self.group_table.itemSelectionChanged.connect(self._on_group_selected)
        self.group_combo.currentIndexChanged.connect(self._on_group_mode_changed)
        self.conn_table.itemSelectionChanged.connect(self._on_conn_selected)

    def _sync_buttons(self) -> None:
        self.start_btn.setEnabled(not self._running)
        self.stop_btn.setEnabled(self._running)
        self.pause_btn.setEnabled(self._running)
        if not self._running:
            self.pause_btn.setText(i18n.t("network.pause"))

    # -- Session control ---------------------------------------------------

    def _start(self) -> None:
        if self._running:
            return
        self.status.setText(i18n.t("network.connecting"))
        self.start_btn.setEnabled(False)
        self.runner.submit(
            lambda: api.open_network_stream(self._target),
            on_done=self._on_open,
            on_error=lambda e: self._fail(i18n.t("network.open_failed", error=e)),
        )

    def _on_open(self, result) -> None:
        if isinstance(result, dict):
            self._fail(localize_error(result.get("error")))
            return
        self._handle = result
        self._running = True
        self._paused = False
        self._rate_state = None
        self._poll.start()
        self.state_label.setText(i18n.t("network.state.running"))
        self.status.setText(i18n.t("network.started"))
        self._sync_buttons()

    def _fail(self, message: str) -> None:
        self.status.setText(message)
        self._sync_buttons()

    def _stop(self) -> None:
        self._poll.stop()
        handle, self._handle = self._handle, None
        if handle is not None:
            self.runner.submit(lambda: handle.close(), on_error=lambda e: None)
        self._running = False
        self._paused = False
        self.state_label.setText(i18n.t("network.state.idle"))
        self.status.setText(i18n.t("network.stopped"))
        self._sync_buttons()

    def _toggle_pause(self) -> None:
        if not self._running:
            return
        self._paused = not self._paused
        if self._paused:
            self.state_label.setText(i18n.t("network.state.paused"))
            self.pause_btn.setText(i18n.t("network.resume"))
            self.status.setText(i18n.t("network.paused"))
        else:
            self.state_label.setText(i18n.t("network.state.running"))
            self.pause_btn.setText(i18n.t("network.pause"))
            self.status.setText(i18n.t("network.resumed"))

    def _clear(self) -> None:
        self._rx_series.clear()
        self._tx_series.clear()
        self.trend.clear()
        self.group_table.setRowCount(0)
        self.conn_table.setRowCount(0)
        self.detail_label.setText(i18n.t("network.no_selection"))
        self.status.setText(i18n.t("network.cleared"))

    def _on_autoscroll(self, checked: bool) -> None:
        self._auto_scroll = checked

    # -- Poll / render -----------------------------------------------------

    def _tick(self) -> None:
        if self._handle is None:
            return
        snap = self._handle.snapshot()
        self._snapshot = snap
        if not snap.get("running", False):
            self.status.setText(i18n.t("network.stream_end"))
            self._stop()
            return
        now = float(snap["timestamp"])
        rx_rate, tx_rate = self._compute_rates(snap, now)
        self._rate_state = (now, snap["cum_rx"], snap["cum_tx"])
        self._rx_series.append((now, rx_rate))
        self._tx_series.append((now, tx_rate))
        self._drop_expired(self._rx_series, now)
        self._drop_expired(self._tx_series, now)

        conns = snap["connections"]
        err = sum(c["retx"] + c["dups"] for c in conns)
        self.stats_label.setText(i18n.t(
            "network.stats", conns=len(conns), err=err,
            rx=f"{rx_rate:.1f}", tx=f"{tx_rate:.1f}", dropped=snap["dropped"],
        ))
        if self._paused:
            return
        self.trend.clear()
        for ts, v in self._rx_series:
            self.trend.append("Rx", ts, v)
        for ts, v in self._tx_series:
            self.trend.append("Tx", ts, v)
        self._render_groups(conns)
        self._render_conns(conns)

    def _compute_rates(self, snap: dict, now: float) -> tuple[float, float]:
        if self._rate_state is None:
            return 0.0, 0.0
        last_ts, last_rx, last_tx = self._rate_state
        dt = now - last_ts
        if dt <= 0:
            return 0.0, 0.0
        rx = max(0.0, snap["cum_rx"] - last_rx) / dt / 1024.0
        tx = max(0.0, snap["cum_tx"] - last_tx) / dt / 1024.0
        return rx, tx

    @staticmethod
    def _drop_expired(series: deque, now: float) -> None:
        cutoff = now - 600.0
        while series and series[0][0] < cutoff:
            series.popleft()

    def _filtered(self, conns: list[dict], apply_group: bool = True) -> list[dict]:
        proto = self.proto_combo.currentData()
        text = self.search_input.text().strip().lower()
        active = self.active_chk.isChecked()
        gf = self._group_filter if apply_group else None
        out = []
        for c in conns:
            if proto and c["proto"] != proto:
                continue
            if active and (c["rx_bytes"] + c["tx_bytes"]) <= 0:
                continue
            if gf and c.get(gf[0]) != gf[1]:
                continue
            if text:
                hay = f"{c['local']} {c['remote']} {c['proto']} {c['iface']}".lower()
                if text not in hay:
                    continue
            out.append(c)
        return out

    def _render_groups(self, conns: list[dict]) -> None:
        mode = self.group_combo.currentData()
        # Group over the top-level filtered set (protocol / search / active) but
        # NOT the group filter itself, so "All" = all of the current protocol type.
        base = self._filtered(conns, apply_group=False)
        agg: dict[str, list[float]] = {}
        for c in base:
            key = str(c.get(mode) or "unknown")
            slot = agg.setdefault(key, [0.0, 0.0])
            slot[0] += 1
            slot[1] += c["rx_bytes"] + c["tx_bytes"]
        ranked = sorted(agg.items(), key=lambda kv: -kv[1][1])[:_MAX_ROWS]
        # Row 0 is always an "All" entry so the user can clear the group filter
        # and return to showing every connection.
        all_label = i18n.t("network.group_all")
        total_n = sum(int(v[0]) for v in agg.values())
        total_b = sum(v[1] for v in agg.values())
        table_rows = [(all_label, str(total_n), self._fmt_bytes(total_b))]
        table_rows += [(k, str(int(n)), self._fmt_bytes(b)) for k, (n, b) in ranked]
        select_key = all_label if self._group_filter is None else self._group_filter[1]
        # Block signals so re-selecting the active row doesn't re-trigger a
        # cascade render during the periodic rebuild.
        self.group_table.blockSignals(True)
        self._fill_table(self.group_table, table_rows, select_key=select_key)
        self.group_table.blockSignals(False)

    def _render_conns(self, conns: list[dict]) -> None:
        rows = self._filtered(conns)
        rows.sort(key=lambda c: -c["last_ts"])
        rows = rows[:_MAX_ROWS]
        keys = [(c["local"], c["remote"]) for c in rows]
        data = [
            (
                time.strftime("%H:%M:%S", time.localtime(c["last_ts"])),
                c["proto"], c["direction"], c["local"], c["remote"],
                f"↓{self._fmt_bytes(c['rx_bytes'])} ↑{self._fmt_bytes(c['tx_bytes'])}",
            )
            for c in rows
        ]
        # Preserve the user's selection + scroll position across the rebuild;
        # only follow the newest rows when auto-scroll is on.
        sel_key = self._selected_conn_key()
        vbar = self.conn_table.verticalScrollBar()
        scroll_pos = vbar.value()
        self.conn_table.blockSignals(True)
        self._fill_table(self.conn_table, data)
        restored = False
        if sel_key is not None and sel_key in keys:
            self.conn_table.selectRow(keys.index(sel_key))
            restored = True
        self.conn_table.blockSignals(False)
        if self._auto_scroll:
            self.conn_table.scrollToTop()
        else:
            vbar.setValue(min(scroll_pos, vbar.maximum()))
        if restored:
            self._on_conn_selected()  # refresh detail with latest bytes

    def _selected_conn_key(self) -> tuple[str, str] | None:
        items = self.conn_table.selectedItems()
        if not items:
            return None
        row = items[0].row()
        local = self.conn_table.item(row, 3)
        remote = self.conn_table.item(row, 4)
        if local is None or remote is None:
            return None
        return (local.text(), remote.text())

    def _fill_table(self, table: QTableWidget, rows: list[tuple], select_key=None) -> None:
        table.setRowCount(len(rows))
        for r, cols in enumerate(rows):
            for col, val in enumerate(cols):
                item = QTableWidgetItem(str(val))
                table.setItem(r, col, item)
            if select_key is not None and cols and cols[0] == select_key:
                table.selectRow(r)

    @staticmethod
    def _fmt_bytes(value: float) -> str:
        v = float(value)
        for unit in ("B", "KB", "MB", "GB"):
            if v < 1024 or unit == "GB":
                return f"{v:.0f}{unit}" if unit == "B" else f"{v:.1f}{unit}"
            v /= 1024
        return f"{v:.1f}GB"

    # -- Selection ---------------------------------------------------------

    def _on_group_selected(self) -> None:
        items = self.group_table.selectedItems()
        if not items:
            return
        row = items[0].row()
        if row == 0:  # the "All" row clears the group filter
            self._group_filter = None
        else:
            key = self.group_table.item(row, 0).text()
            self._group_filter = (self.group_combo.currentData(), key)
        if self._snapshot:
            self._render_conns(self._snapshot["connections"])

    def _on_group_mode_changed(self) -> None:
        # Switching remote/interface grouping invalidates the current key.
        self._group_filter = None
        if self._snapshot:
            self._render_groups(self._snapshot["connections"])
            self._render_conns(self._snapshot["connections"])

    def _on_conn_selected(self) -> None:
        key = self._selected_conn_key()
        if key is None or not self._snapshot:
            return
        local, remote = key
        for c in self._snapshot["connections"]:
            if c["local"] == local and c["remote"] == remote:
                self.detail_label.setText(i18n.t(
                    "network.detail",
                    proto=c["proto"], direction=c["direction"], iface=c["iface"],
                    local=c["local"], remote=c["remote"],
                    rx=self._fmt_bytes(c["rx_bytes"]), tx=self._fmt_bytes(c["tx_bytes"]),
                    retx=c["retx"], dups=c["dups"], rtt=c["avg_rtt"],
                ))
                return

    # -- Export ------------------------------------------------------------

    def _export(self) -> None:
        if not self._snapshot:
            self.status.setText(i18n.t("network.export_empty"))
            return
        rows = self._filtered(self._snapshot["connections"])
        path = save_file(
            self, i18n.t("network.export"), "network_connections.csv",
            [i18n.t("network.export_csv"), i18n.t("network.export_json")],
        )
        if not path:
            return
        try:
            if path.lower().endswith(".json"):
                self._export_json(path, rows)
            else:
                self._export_csv(path, rows)
        except Exception as exc:
            self.status.setText(i18n.t("network.export_failed", error=exc))
            return
        self.status.setText(i18n.t("network.export_done", count=len(rows), path=path))

    @staticmethod
    def _export_csv(path: str, rows: list[dict]) -> None:
        import csv
        cols = ["last_ts", "proto", "direction", "local", "remote", "iface",
                "rx_bytes", "tx_bytes", "retx", "dups", "avg_rtt"]
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(cols)
            for c in rows:
                writer.writerow([c.get(k) for k in cols])

    @staticmethod
    def _export_json(path: str, rows: list[dict]) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, ensure_ascii=False, indent=2)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        self._stop()
        super().closeEvent(event)

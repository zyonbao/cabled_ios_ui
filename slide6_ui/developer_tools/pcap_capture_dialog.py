"""pcap_capture_dialog.py — DVT PCAP capture sub-panel.

Captures device traffic via pcapd (over usbmux — no tunnel/DDI) straight to a
`.pcap` file (Wireshark-readable) and shows a rolling summary of recent packets.
Capture auto-stops on any limit (packets / size / duration). No per-layer parsing
— that is left to Wireshark. The handle is bound to the window lifecycle.
"""

from __future__ import annotations

import os
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ios_toolkit import toolkit_api as api

from .. import i18n
from ..common.errors import localize_error
from ..common.file_dialogs import save_file
from ..common.focus import suppress_auto_focus
from ..common.workers import AsyncRunner

_MAX_ROWS = 500


class PcapCaptureDialog(QDialog):
    """Capture device packets to a .pcap and show a rolling summary."""

    def __init__(self, runner: AsyncRunner, target: str, parent=None) -> None:
        super().__init__(parent)
        self.runner = runner
        self._target = target
        self._handle = None
        self._running = False

        self.setWindowTitle(i18n.t("pcap.title"))
        self.resize(820, 520)
        self._build_ui()
        self._wire()
        suppress_auto_focus(self)

        self._poll = QTimer(self)
        self._poll.setInterval(400)
        self._poll.timeout.connect(self._tick)

    # -- UI ----------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # --- Capture settings (editable while idle) ---
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel(i18n.t("pcap.output_label")))
        self.path_input = QLineEdit(self._default_out_path())
        out_row.addWidget(self.path_input, 1)
        self.browse_btn = QPushButton(i18n.t("common.browse"))
        out_row.addWidget(self.browse_btn)
        root.addLayout(out_row)

        cfg = QHBoxLayout()
        cfg.addWidget(QLabel(i18n.t("pcap.process_label")))
        self.process_input = QLineEdit()
        self.process_input.setPlaceholderText(i18n.t("pcap.process_placeholder"))
        self.process_input.setMaximumWidth(160)
        cfg.addWidget(self.process_input)
        cfg.addWidget(QLabel(i18n.t("pcap.interface_label")))
        self.interface_input = QLineEdit()
        self.interface_input.setPlaceholderText(i18n.t("pcap.interface_placeholder"))
        self.interface_input.setMaximumWidth(120)
        cfg.addWidget(self.interface_input)
        cfg.addStretch(1)
        cfg.addWidget(QLabel(i18n.t("pcap.limit_packets")))
        self.lim_packets = self._spin(1000, 5_000_000, 100000, 1000)
        cfg.addWidget(self.lim_packets)
        cfg.addWidget(QLabel(i18n.t("pcap.limit_mb")))
        self.lim_mb = self._spin(1, 4096, 50, 10)
        cfg.addWidget(self.lim_mb)
        cfg.addWidget(QLabel(i18n.t("pcap.limit_seconds")))
        self.lim_seconds = self._spin(5, 86400, 600, 30)
        cfg.addWidget(self.lim_seconds)
        root.addLayout(cfg)

        # --- Control bar ---
        bar = QHBoxLayout()
        self.start_btn = QPushButton(i18n.t("pcap.start"))
        self.stop_btn = QPushButton(i18n.t("pcap.stop"))
        bar.addWidget(self.start_btn)
        bar.addWidget(self.stop_btn)
        bar.addSpacing(12)
        self.state_label = QLabel(i18n.t("pcap.state.idle"))
        bar.addWidget(self.state_label)
        self.stats_label = QLabel("")
        bar.addWidget(self.stats_label)
        bar.addStretch(1)
        root.addLayout(bar)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            i18n.t("pcap.col_time"), i18n.t("pcap.col_proc"), i18n.t("pcap.col_pid"),
            i18n.t("pcap.col_iface"), i18n.t("pcap.col_proto"), i18n.t("pcap.col_len"),
        ])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)

        self.status = QLabel(i18n.t("pcap.compliance"))
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self.status)
        self._sync_buttons()

    @staticmethod
    def _spin(lo: int, hi: int, val: int, step: int) -> QSpinBox:
        s = QSpinBox()
        s.setRange(lo, hi)
        s.setValue(val)
        s.setSingleStep(step)
        return s

    @staticmethod
    def _default_out_path() -> str:
        out_dir = os.path.expanduser("~/Downloads")
        if not os.path.isdir(out_dir):
            out_dir = os.path.expanduser("~")
        return os.path.join(out_dir, "capture_" + time.strftime("%Y%m%d_%H%M%S") + ".pcap")

    def _wire(self) -> None:
        self.start_btn.clicked.connect(self._start)
        self.stop_btn.clicked.connect(self._stop)
        self.browse_btn.clicked.connect(self._browse)

    def _browse(self) -> None:
        path = save_file(self, i18n.t("pcap.choose_path"),
                         self.path_input.text().strip() or self._default_out_path(),
                         [i18n.t("pcap.pcap_filter")])
        if path:
            self.path_input.setText(path)

    def _sync_buttons(self) -> None:
        self.start_btn.setEnabled(not self._running)
        self.stop_btn.setEnabled(self._running)
        for w in (self.path_input, self.browse_btn, self.process_input,
                  self.interface_input, self.lim_packets, self.lim_mb, self.lim_seconds):
            w.setEnabled(not self._running)

    # -- Capture control ---------------------------------------------------

    def _start(self) -> None:
        if self._running:
            return
        path = self.path_input.text().strip()
        if not path:
            self.status.setText(i18n.t("pcap.need_path"))
            return
        process = self.process_input.text().strip() or None
        interface = self.interface_input.text().strip() or None
        kwargs = dict(
            process=process, interface=interface,
            max_packets=int(self.lim_packets.value()),
            max_bytes=int(self.lim_mb.value()) * 1024 * 1024,
            max_seconds=int(self.lim_seconds.value()),
        )
        self.status.setText(i18n.t("pcap.starting"))
        self.start_btn.setEnabled(False)
        self.runner.submit(
            lambda: api.open_pcap_stream(self._target, path, **kwargs),
            on_done=self._on_open,
            on_error=lambda e: self._fail(i18n.t("pcap.open_failed", error=e)),
        )

    def _on_open(self, result) -> None:
        if isinstance(result, dict):
            self._fail(localize_error(result.get("error")))
            return
        self._handle = result
        self._running = True
        self._poll.start()
        self.state_label.setText(i18n.t("pcap.state.running"))
        self.status.setText(i18n.t("pcap.started"))
        self._sync_buttons()

    def _fail(self, message: str) -> None:
        self.status.setText(message)
        self._sync_buttons()

    def _stop(self, *, reason: str = "stopped") -> None:
        self._poll.stop()
        handle, self._handle = self._handle, None
        if handle is not None:
            self.runner.submit(lambda: handle.close(), on_error=lambda e: None)
        self._running = False
        self.state_label.setText(i18n.t("pcap.state.idle"))
        self.status.setText(i18n.t("pcap.stopped_limit") if reason == "limit"
                            else i18n.t("pcap.stopped"))
        self._sync_buttons()

    # -- Poll / render -----------------------------------------------------

    def _tick(self) -> None:
        if self._handle is None:
            return
        snap = self._handle.snapshot()
        self.stats_label.setText(i18n.t(
            "pcap.stats", packets=snap["packets"], size=self._fmt_bytes(snap["bytes"]),
            elapsed=int(snap["elapsed"]),
        ))
        self._render(snap["summary"])
        if not snap["running"]:
            self._stop(reason=snap.get("stopped_reason") or "stopped")

    def _render(self, summary: list[dict]) -> None:
        rows = summary[-_MAX_ROWS:]
        rows = list(reversed(rows))
        self.table.setRowCount(len(rows))
        for r, p in enumerate(rows):
            vals = (
                time.strftime("%H:%M:%S", time.localtime(p["ts"])),
                p["comm"], "" if p["pid"] is None else str(p["pid"]),
                p["iface"], p["proto"], str(p["length"]),
            )
            for c, v in enumerate(vals):
                self.table.setItem(r, c, QTableWidgetItem(v))
        # Newest packet is row 0; keep it in view as the summary refreshes.
        self.table.scrollToTop()

    @staticmethod
    def _fmt_bytes(value: float) -> str:
        v = float(value)
        for unit in ("B", "KB", "MB", "GB"):
            if v < 1024 or unit == "GB":
                return f"{v:.0f}{unit}" if unit == "B" else f"{v:.1f}{unit}"
            v /= 1024
        return f"{v:.1f}GB"

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        self._poll.stop()
        handle, self._handle = self._handle, None
        if handle is not None:
            self.runner.submit(lambda: handle.close(), on_error=lambda e: None)
        super().closeEvent(event)

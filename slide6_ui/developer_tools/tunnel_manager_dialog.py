"""tunnel_manager_dialog.py — manage all active XPC tunnel (tunneld) processes.

The configurable tunnel port means a user can leave several tunneld processes
running on different ports. This dialog discovers every tunneld process started
by this app (any port, via `ps` — no elevation) and lets the user select one or
more rows and batch-kill them under a SINGLE administrator authorization (one
password for the whole batch). Discovery and the privileged kill both run off
the GUI thread through the shared AsyncRunner.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .. import i18n
from ..common.context_copy import install_plaintext_copy_menu, install_table_copy_menu
from ..common.focus import suppress_auto_focus
from ..common import tunnel
from ..common.table_perf import batch_table_fill
from ..common.workers import AsyncRunner

# Column indices for the process table.
_COL_PID = 0
_COL_USER = 1
_COL_PORT = 2
_COL_MODE = 3
_COL_COMMAND = 4


class TunnelManagerDialog(QDialog):
    """List active tunneld processes; row-select + batch kill (single auth)."""

    def __init__(self, runner: AsyncRunner, parent=None) -> None:
        super().__init__(parent)
        self.runner = runner
        self._procs: list[dict] = []
        self._busy = False
        self.setWindowTitle(i18n.t("tunnel_manager.title"))
        self.resize(760, 460)
        self._build_ui()
        self._wire()
        suppress_auto_focus(self)
        self.reload()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # Scope hint: discovery only sees tunnels this app launched.
        self.hint = QLabel(i18n.t("tunnel_manager.hint"))
        self.hint.setWordWrap(True)
        root.addWidget(self.hint)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            [
                i18n.t("tunnel_manager.col.pid"),
                i18n.t("tunnel_manager.col.user"),
                i18n.t("tunnel_manager.col.port"),
                i18n.t("tunnel_manager.col.mode"),
                i18n.t("tunnel_manager.col.command"),
            ]
        )
        # Standard list selection (multi-select via shift/cmd-click), consistent
        # with the other tables in the app — no per-row checkboxes.
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(_COL_PID, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(_COL_USER, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(_COL_PORT, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(_COL_MODE, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(_COL_COMMAND, QHeaderView.Stretch)
        root.addWidget(self.table, 1)

        bar = QHBoxLayout()
        self.status = QLabel(i18n.t("tunnel_manager.loading"))
        self.refresh_btn = QPushButton(i18n.t("common.refresh"))
        self.kill_btn = QPushButton(i18n.t("tunnel_manager.kill_selected", count=0))
        self.kill_btn.setEnabled(False)
        self.close_btn = QPushButton(i18n.t("common.close"))
        bar.addWidget(self.status, 1)
        bar.addWidget(self.refresh_btn)
        bar.addWidget(self.kill_btn)
        bar.addWidget(self.close_btn)
        root.addLayout(bar)

    def _wire(self) -> None:
        self.refresh_btn.clicked.connect(self.reload)
        self.kill_btn.clicked.connect(self._kill_selected)
        self.close_btn.clicked.connect(self.reject)
        self.table.itemSelectionChanged.connect(self._update_kill_button)
        # Double-click any row to inspect the full process detail (copyable).
        self.table.itemDoubleClicked.connect(self._show_detail)
        install_table_copy_menu(self.table)

    # ------------------------------------------------------------- loading

    def reload(self) -> None:
        if self._busy:
            return
        self.status.setText(i18n.t("tunnel_manager.loading"))
        self.refresh_btn.setEnabled(False)
        self.runner.submit(
            tunnel.list_tunnel_processes,
            on_done=self._on_listed,
            on_error=lambda e: self._on_listed([]),
        )

    def _on_listed(self, procs: list) -> None:
        self.refresh_btn.setEnabled(True)
        self._procs = list(procs or [])
        self._render()
        if self._procs:
            self.status.setText(i18n.t("tunnel_manager.count", count=len(self._procs)))
        else:
            self.status.setText(i18n.t("tunnel_manager.empty"))

    def _render(self) -> None:
        with batch_table_fill(self.table, auto_cols=(_COL_PID, _COL_USER, _COL_PORT, _COL_MODE)):
            self.table.setRowCount(len(self._procs))
            for row, proc in enumerate(self._procs):
                self.table.setItem(row, _COL_PID, QTableWidgetItem(str(proc.get("pid", ""))))
                self.table.setItem(row, _COL_USER, QTableWidgetItem(str(proc.get("user", ""))))
                port = proc.get("port")
                port_text = str(port) if port is not None else i18n.t("tunnel_manager.port_unknown")
                self.table.setItem(row, _COL_PORT, QTableWidgetItem(port_text))
                mode = proc.get("mode")
                mode_text = (
                    i18n.t("tunnel_manager.mode_macho")
                    if mode == tunnel.TUNNEL_MODE_MACHO
                    else i18n.t("tunnel_manager.mode_python")
                )
                self.table.setItem(row, _COL_MODE, QTableWidgetItem(mode_text))
                self.table.setItem(row, _COL_COMMAND, QTableWidgetItem(str(proc.get("command", ""))))
        self._update_kill_button()

    # ----------------------------------------------------------- selection

    def _selected_pids(self) -> list[int]:
        pids: list[int] = []
        for row in sorted({idx.row() for idx in self.table.selectionModel().selectedRows()}):
            if 0 <= row < len(self._procs):
                pid = self._procs[row].get("pid")
                if isinstance(pid, int) and pid > 0:
                    pids.append(pid)
        return pids

    def _update_kill_button(self) -> None:
        count = len(self._selected_pids())
        self.kill_btn.setText(i18n.t("tunnel_manager.kill_selected", count=count))
        self.kill_btn.setEnabled(count > 0 and not self._busy)

    # ---------------------------------------------------------------- kill

    def _kill_selected(self) -> None:
        pids = self._selected_pids()
        if not pids:
            return
        self._set_busy(True)
        self.status.setText(i18n.t("tunnel_manager.killing", count=len(pids)))
        self.runner.submit(
            lambda: tunnel.kill_tunnel_processes(pids),
            on_done=self._on_killed,
            on_error=lambda e: self._on_killed(False),
        )

    def _on_killed(self, ok: bool) -> None:
        self._set_busy(False)
        if ok:
            self.status.setText(i18n.t("tunnel_manager.kill_done"))
        else:
            self.status.setText(i18n.t("tunnel_manager.kill_failed"))
        # Refresh so terminated processes drop off the list (and survivors stay).
        self.reload()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.refresh_btn.setEnabled(not busy)
        self.kill_btn.setEnabled(not busy and len(self._selected_pids()) > 0)
        self.table.setEnabled(not busy)

    # -------------------------------------------------------------- detail

    def _show_detail(self, item) -> None:
        """Open a read-only, copyable detail view for the double-clicked row."""
        row = item.row()
        if not (0 <= row < len(self._procs)):
            return
        proc = self._procs[row]
        dlg = QDialog(self)
        dlg.setWindowTitle(i18n.t("tunnel_manager.detail_title", pid=proc.get("pid", "")))
        dlg.resize(560, 320)
        layout = QVBoxLayout(dlg)
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setPlainText("\n".join(f"{key}: {value}" for key, value in proc.items()))
        install_plaintext_copy_menu(view)
        layout.addWidget(view)
        close_btn = QPushButton(i18n.t("common.close"))
        close_btn.clicked.connect(dlg.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignRight)
        dlg.exec()

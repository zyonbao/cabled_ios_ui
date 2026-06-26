"""web_inspector_dialog.py — WebInspector sub-panel.

Lists debuggable pages (Safari tabs / app WebViews) and starts a local CDP bridge
so Chrome DevTools can attach for full debugging. WebInspector is a lockdown
service (tunnel on iOS 17+, no DDI). The device must have Settings → Safari →
Advanced → Web Inspector enabled. The CDP bridge is bound to the window.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ios_toolkit import toolkit_api as api

from .. import i18n
from ..common.errors import localize_error
from ..common.focus import suppress_auto_focus
from ..common.table_perf import batch_table_fill
from ..common.workers import AsyncRunner


class WebInspectorDialog(QDialog):
    """List debuggable web pages and bridge them to Chrome DevTools via CDP."""

    def __init__(self, runner: AsyncRunner, target: str, parent=None) -> None:
        super().__init__(parent)
        self.runner = runner
        self._target = target
        self._bridge = None

        self.setWindowTitle(i18n.t("webinspector.title"))
        self.resize(720, 460)
        self._build_ui()
        self._wire()
        suppress_auto_focus(self)
        self._refresh()

    # -- UI ----------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        top = QHBoxLayout()
        self.refresh_btn = QPushButton(i18n.t("webinspector.refresh"))
        top.addWidget(self.refresh_btn)
        top.addStretch(1)
        root.addLayout(top)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([
            i18n.t("webinspector.col_app"),
            i18n.t("webinspector.col_title"),
            i18n.t("webinspector.col_url"),
        ])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)

        bridge = QHBoxLayout()
        bridge.addWidget(QLabel(i18n.t("webinspector.port_label")))
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setValue(9222)
        bridge.addWidget(self.port_spin)
        self.bridge_btn = QPushButton(i18n.t("webinspector.start_bridge"))
        bridge.addWidget(self.bridge_btn)
        bridge.addStretch(1)
        root.addLayout(bridge)

        self.status = QLabel(i18n.t("webinspector.hint"))
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self.status)

    def _wire(self) -> None:
        self.refresh_btn.clicked.connect(self._refresh)
        self.bridge_btn.clicked.connect(self._toggle_bridge)

    # -- Page enumeration --------------------------------------------------

    def _refresh(self) -> None:
        self.refresh_btn.setEnabled(False)
        self.status.setText(i18n.t("webinspector.refreshing"))
        self.runner.submit(
            lambda: api.list_web_pages(self._target),
            on_done=self._on_pages,
            on_error=lambda e: self._after_refresh(i18n.t("webinspector.open_failed", error=e)),
        )

    def _on_pages(self, result: dict) -> None:
        if not result.get("ok"):
            error = result.get("error") or {}
            if error.get("code") == "WEBINSPECTOR_DISABLED":
                self._after_refresh(i18n.t("webinspector.disabled_guide"))
            else:
                self._after_refresh(localize_error(error))
            return
        pages = result["data"].get("pages", [])
        with batch_table_fill(self.table, auto_cols=(0,)):
            self.table.setRowCount(len(pages))
            for r, p in enumerate(pages):
                self.table.setItem(r, 0, QTableWidgetItem(str(p.get("app", ""))))
                self.table.setItem(r, 1, QTableWidgetItem(str(p.get("title", ""))))
                self.table.setItem(r, 2, QTableWidgetItem(str(p.get("url", ""))))
        msg = i18n.t("webinspector.no_pages") if not pages else i18n.t("webinspector.pages_count", count=len(pages))
        self._after_refresh(msg)

    def _after_refresh(self, message: str) -> None:
        self.refresh_btn.setEnabled(True)
        self.status.setText(message)

    # -- CDP bridge --------------------------------------------------------

    def _toggle_bridge(self) -> None:
        if self._bridge is not None:
            self._stop_bridge()
        else:
            self._start_bridge()

    def _start_bridge(self) -> None:
        port = int(self.port_spin.value())
        self.bridge_btn.setEnabled(False)
        self.port_spin.setEnabled(False)
        self.status.setText(i18n.t("webinspector.bridge_starting"))
        self.runner.submit(
            lambda: api.open_cdp_bridge(self._target, port=port),
            on_done=self._on_bridge,
            on_error=lambda e: self._bridge_failed(i18n.t("webinspector.bridge_failed", error=e)),
        )

    def _on_bridge(self, result) -> None:
        if isinstance(result, dict):  # error envelope
            self._bridge_failed(localize_error(result.get("error")))
            return
        self._bridge = result
        self.bridge_btn.setText(i18n.t("webinspector.stop_bridge"))
        self.bridge_btn.setEnabled(True)
        self.status.setText(i18n.t("webinspector.bridge_running", url=self._bridge.url))

    def _bridge_failed(self, message: str) -> None:
        self._bridge = None
        self.bridge_btn.setText(i18n.t("webinspector.start_bridge"))
        self.bridge_btn.setEnabled(True)
        self.port_spin.setEnabled(True)
        self.status.setText(message)

    def _stop_bridge(self) -> None:
        bridge, self._bridge = self._bridge, None
        if bridge is not None:
            self.runner.submit(lambda: bridge.close(), on_error=lambda e: None)
        self.bridge_btn.setText(i18n.t("webinspector.start_bridge"))
        self.port_spin.setEnabled(True)
        self.status.setText(i18n.t("webinspector.bridge_stopped"))

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        bridge, self._bridge = self._bridge, None
        if bridge is not None:
            self.runner.submit(lambda: bridge.close(), on_error=lambda e: None)
        super().closeEvent(event)

"""app_manager.py — the "App 列表" tab.

AppManagerTab lists / searches / filters installed apps and supports install
(click or drag .ipa) / uninstall, plus per-row entry points into the file
browser (see afc_browser.AfcBrowserDialog) for file-sharing or sandbox-capable
apps.

All blocking ios_toolkit calls go through the shared AsyncRunner so the Qt GUI
thread never blocks. App management talks to lockdown services directly and
needs neither WDA nor the XPC tunnel.
"""

from __future__ import annotations

import os
from typing import Callable

from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ios_toolkit import toolkit_api as api

from .. import i18n
from ..common.afc_browser import AfcBrowserDialog
from ..common.context_copy import install_table_copy_menu
from ..common.errors import localize_error
from ..common.workers import AsyncRunner


def _is_system_app(app: dict) -> bool:
    """Return True for built-in system apps (which cannot be uninstalled)."""
    return (app.get("appType") or "").lower() == "system"


class AppManagerTab(QWidget):
    """The "App 列表" tab: app inventory with install / uninstall / browse."""

    def __init__(self, runner: AsyncRunner, get_target: Callable[[], str]) -> None:
        super().__init__()
        self.runner = runner
        self._get_target = get_target
        self._apps: list[dict] = []
        self.setAcceptDrops(True)
        self._build_ui()
        self._wire()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # Toolbar: search + filters + actions.
        bar = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(i18n.t("app_manager.search_placeholder"))
        self.share_filter = QCheckBox(i18n.t("app_manager.filter_shared"))
        self.sandbox_filter = QCheckBox(i18n.t("app_manager.filter_sandbox"))
        self.refresh_btn = QPushButton(i18n.t("app_manager.refresh_list"))
        self.install_btn = QPushButton(i18n.t("app_manager.install_ipa"))
        bar.addWidget(self.search_input, 1)
        bar.addWidget(self.share_filter)
        bar.addWidget(self.sandbox_filter)
        bar.addWidget(self.refresh_btn)
        bar.addWidget(self.install_btn)
        root.addLayout(bar)

        # App table: name / bundle id / version / capability-driven action buttons.
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([
            i18n.t("afc.col.name"), "Bundle ID",
            i18n.t("afc.col.version"), i18n.t("afc.col.actions"),
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        root.addWidget(self.table, 1)

        self.status = QLabel(i18n.t("app_manager.drop_hint"))
        root.addWidget(self.status)

    def _wire(self) -> None:
        self.refresh_btn.clicked.connect(self.reload_apps)
        self.install_btn.clicked.connect(self.on_install_clicked)
        self.search_input.textChanged.connect(self._render)
        self.share_filter.toggled.connect(self._render)
        self.sandbox_filter.toggled.connect(self._render)
        install_table_copy_menu(
            self.table,
            on_copied=lambda t: self.status.setText(i18n.t("common.copied", text=t[:60])),
        )

    # ------------------------------------------------------------- loading

    def set_target(self, target: str) -> None:
        """Called by the main window when the selected device changes."""
        self._apps = []
        self._render()
        if target:
            self.reload_apps()
        else:
            self.status.setText(i18n.t("dev_tools.no_device"))

    def reload_apps(self) -> None:
        target = self._get_target()
        if not target:
            self.status.setText(i18n.t("dev_tools.no_device"))
            return
        self.status.setText(i18n.t("app_manager.loading"))
        self.refresh_btn.setEnabled(False)
        self.runner.submit(
            lambda: api.list_apps(target),
            on_done=self._on_apps,
            on_error=lambda e: self._fail(i18n.t("afc.load_failed_detail", error=e)),
        )

    def _on_apps(self, result: dict) -> None:
        self.refresh_btn.setEnabled(True)
        if not result.get("ok"):
            self._fail(localize_error(result.get("error")))
            return
        self._apps = result["data"].get("apps", [])
        self._render()
        self.status.setText(i18n.t("app_manager.count", count=len(self._apps)))

    def _fail(self, message: str) -> None:
        self.refresh_btn.setEnabled(True)
        self.status.setText(message)

    # ----------------------------------------------------------- rendering

    def _filtered(self) -> list[dict]:
        kw = self.search_input.text().strip().lower()
        only_share = self.share_filter.isChecked()
        only_sandbox = self.sandbox_filter.isChecked()
        out = []
        for app in self._apps:
            if only_share and not app.get("fileSharing"):
                continue
            if only_sandbox and not app.get("sandboxAccessible"):
                continue
            if kw and kw not in app.get("name", "").lower() and kw not in app.get("bundleId", "").lower():
                continue
            out.append(app)
        return out

    def _render(self) -> None:
        apps = self._filtered()
        self.table.setRowCount(len(apps))
        for row, app in enumerate(apps):
            self.table.setItem(row, 0, QTableWidgetItem(app.get("name", "")))
            self.table.setItem(row, 1, QTableWidgetItem(app.get("bundleId", "")))
            self.table.setItem(row, 2, QTableWidgetItem(app.get("version", "")))
            self.table.setCellWidget(row, 3, self._action_cell(app))

    def _action_cell(self, app: dict) -> QWidget:
        """Build the per-row action column: Documents / Sandbox / 卸载,
        shown only when the app advertises the matching capability."""
        cell = QWidget()
        lay = QHBoxLayout(cell)
        lay.setContentsMargins(4, 0, 4, 0)
        lay.setSpacing(6)
        if app.get("fileSharing"):
            docs = QPushButton("Documents")
            docs.clicked.connect(lambda _=False, a=app: self._open_browser(a, "documents"))
            lay.addWidget(docs)
        if app.get("sandboxAccessible"):
            sandbox = QPushButton("Sandbox")
            sandbox.clicked.connect(lambda _=False, a=app: self._open_browser(a, "container"))
            lay.addWidget(sandbox)
        # System apps cannot be uninstalled (the device rejects it), so the
        # uninstall action is offered for non-system apps only.
        if not _is_system_app(app):
            uninstall = QPushButton(i18n.t("app_manager.uninstall"))
            uninstall.clicked.connect(lambda _=False, a=app: self.on_uninstall(a))
            lay.addWidget(uninstall)
        lay.addStretch(1)
        return cell

    # -------------------------------------------------------- install/uninstall

    def on_install_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, i18n.t("app_manager.select_ipa"), "", "iOS App (*.ipa)")
        if path:
            self._install(path)

    def _install(self, ipa_path: str) -> None:
        target = self._get_target()
        if not target:
            self.status.setText(i18n.t("dev_tools.no_device"))
            return
        if not ipa_path.lower().endswith(".ipa"):
            self.status.setText(i18n.t("app_manager.only_ipa"))
            return
        self.status.setText(i18n.t("app_manager.installing", name=os.path.basename(ipa_path)))
        self.install_btn.setEnabled(False)
        self.runner.submit(
            lambda: api.install_app(target, ipa_path),
            on_done=self._on_installed,
            on_error=lambda e: self._after_install(i18n.t("app_manager.install_failed", error=e)),
        )

    def _on_installed(self, result: dict) -> None:
        if result.get("ok"):
            self._after_install(i18n.t("app_manager.install_ok"))
            self.reload_apps()
        else:
            msg = localize_error(result.get("error"))
            self._after_install(i18n.t("app_manager.install_failed_signed", msg=msg))

    def _after_install(self, message: str) -> None:
        self.install_btn.setEnabled(True)
        self.status.setText(message)

    def on_uninstall(self, app: dict) -> None:
        target = self._get_target()
        if not app or not target:
            return
        # Guard: system apps are not uninstallable (defensive — the UI already
        # hides the button for them).
        if _is_system_app(app):
            self.status.setText(i18n.t("app_manager.system_no_uninstall"))
            return
        bundle_id = app.get("bundleId", "")
        reply = QMessageBox.question(
            self, i18n.t("app_manager.uninstall_title"),
            i18n.t("app_manager.uninstall_confirm", name=app.get('name', bundle_id), bundle_id=bundle_id),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self.status.setText(i18n.t("app_manager.uninstalling", bundle_id=bundle_id))
        self.runner.submit(
            lambda: api.uninstall_app(target, bundle_id),
            on_done=lambda r: (self.status.setText(i18n.t("app_manager.uninstall_ok")), self.reload_apps())
            if r.get("ok") else self.status.setText(
                i18n.t("app_manager.uninstall_failed") + ": " + localize_error(r.get("error"))),
            on_error=lambda e: self.status.setText(i18n.t("app_manager.uninstall_failed_detail", error=e)),
        )

    # -------------------------------------------------------------- browse

    def _open_browser(self, app: dict, root: str) -> None:
        target = self._get_target()
        if not app or not target:
            return
        dlg = AfcBrowserDialog(
            self, self.runner, target,
            bundle_id=app.get("bundleId", ""), root=root,
            app_name=app.get("name", ""),
        )
        dlg.exec()

    # ----------------------------------------------------------- drag & drop

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._first_ipa(event) is not None:
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt override
        path = self._first_ipa(event)
        if path is None:
            self.status.setText(i18n.t("app_manager.only_ipa_drop"))
            return
        event.acceptProposedAction()
        self._install(path)

    @staticmethod
    def _first_ipa(event) -> str | None:
        mime = event.mimeData()
        if not mime.hasUrls():
            return None
        for url in mime.urls():
            if url.isLocalFile() and url.toLocalFile().lower().endswith(".ipa"):
                return url.toLocalFile()
        return None

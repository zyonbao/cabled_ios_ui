"""profiles_tab.py — the "描述文件" sidebar tab.

Lists the configuration profiles installed on the selected device and supports
install (click or drag a .mobileconfig), multi-select removal, and export
(single → save-as, multi → choose a directory). Profiles talk to the lockdown
MCInstall service directly and need neither WDA nor the XPC tunnel.

Installing a profile usually still requires the user to confirm it in the device
Settings app (system behaviour), so the UI surfaces that hint after delivery.
"""

from __future__ import annotations

import os
from typing import Callable

from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ios_toolkit import toolkit_api as api

from .. import i18n
from ..common.errors import localize_error
from ..common.workers import AsyncRunner


class ProfilesTab(QWidget):
    """The "描述文件" tab: list / install / multi-remove / export profiles."""

    def __init__(self, runner: AsyncRunner, get_target: Callable[[], str]) -> None:
        super().__init__()
        self.runner = runner
        self._get_target = get_target
        self._profiles: list[dict] = []
        self.setAcceptDrops(True)
        self._build_ui()
        self._wire()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        bar = QHBoxLayout()
        self.refresh_btn = QPushButton(i18n.t("common.refresh"))
        self.install_btn = QPushButton(i18n.t("profiles.install"))
        self.export_btn = QPushButton(i18n.t("profiles.export_selected"))
        self.remove_btn = QPushButton(i18n.t("profiles.remove_selected"))
        bar.addWidget(self.refresh_btn)
        bar.addWidget(self.install_btn)
        bar.addWidget(self.export_btn)
        bar.addStretch(1)
        bar.addWidget(self.remove_btn)
        root.addLayout(bar)

        # Columns: name / identifier / type / organization.
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([
            i18n.t("afc.col.name"), i18n.t("profiles.col.identifier"),
            i18n.t("profiles.col.type"), i18n.t("profiles.col.organization"),
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        root.addWidget(self.table, 1)

        self.status = QLabel(i18n.t("common.select_device_first"))
        self.status.setWordWrap(True)
        root.addWidget(self.status)

    def _wire(self) -> None:
        self.refresh_btn.clicked.connect(self.reload)
        self.install_btn.clicked.connect(self._on_install_clicked)
        self.export_btn.clicked.connect(self._on_export_clicked)
        self.remove_btn.clicked.connect(self._on_remove_clicked)

    # ------------------------------------------------------------- loading

    def set_target(self, target: str) -> None:
        """Called by the main window when the selected device changes."""
        self._profiles = []
        self.table.setRowCount(0)
        if target:
            self.reload()
        else:
            self.status.setText(i18n.t("dev_tools.no_device"))

    def reload(self) -> None:
        target = self._get_target()
        if not target:
            self.status.setText(i18n.t("dev_tools.no_device"))
            return
        self.status.setText(i18n.t("profiles.loading"))
        self.refresh_btn.setEnabled(False)
        self.runner.submit(
            lambda: api.list_profiles(target),
            on_done=self._on_profiles,
            on_error=lambda e: self._fail(i18n.t("afc.load_failed_detail", error=e)),
        )

    def _on_profiles(self, result: dict) -> None:
        self.refresh_btn.setEnabled(True)
        if not result.get("ok"):
            self._fail(localize_error(result.get("error")))
            return
        self._profiles = result["data"].get("profiles", [])
        self._render()
        self.status.setText(i18n.t("profiles.count", count=len(self._profiles)))

    def _fail(self, message: str) -> None:
        self.refresh_btn.setEnabled(True)
        self.status.setText(message)

    def _render(self) -> None:
        self.table.setRowCount(len(self._profiles))
        for row, p in enumerate(self._profiles):
            self.table.setItem(row, 0, QTableWidgetItem(p.get("name", "")))
            self.table.setItem(row, 1, QTableWidgetItem(p.get("identifier", "")))
            self.table.setItem(row, 2, QTableWidgetItem(p.get("type", "")))
            self.table.setItem(row, 3, QTableWidgetItem(p.get("organization", "")))

    # --------------------------------------------------------------- install

    def _on_install_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, i18n.t("profiles.select_file"), "", i18n.t("profiles.file_filter")
        )
        if path:
            self._install(path)

    def _install(self, path: str) -> None:
        target = self._get_target()
        if not target:
            self.status.setText(i18n.t("dev_tools.no_device"))
            return
        if not path.lower().endswith(".mobileconfig"):
            self.status.setText(i18n.t("profiles.only_mobileconfig"))
            return
        self.status.setText(i18n.t("profiles.delivering", name=os.path.basename(path)))
        self.install_btn.setEnabled(False)
        self.runner.submit(
            lambda: api.install_profile(target, path),
            on_done=self._on_installed,
            on_error=lambda e: self._after_install(i18n.t("profiles.install_failed", error=e)),
        )

    def _on_installed(self, result: dict) -> None:
        if result.get("ok"):
            self._after_install(i18n.t("profiles.delivered_confirm"))
            self.reload()
        else:
            msg = localize_error(result.get("error"))
            self._after_install(i18n.t("profiles.install_failed_msg", msg=msg))

    def _after_install(self, message: str) -> None:
        self.install_btn.setEnabled(True)
        self.status.setText(message)

    # --------------------------------------------------------------- export

    def _selected_profiles(self) -> list[dict]:
        rows = sorted({idx.row() for idx in self.table.selectedIndexes()})
        return [self._profiles[r] for r in rows if 0 <= r < len(self._profiles)]

    def _on_export_clicked(self) -> None:
        target = self._get_target()
        if not target:
            self.status.setText(i18n.t("dev_tools.no_device"))
            return
        profiles = self._selected_profiles()
        if not profiles:
            self.status.setText(i18n.t("profiles.need_select_export"))
            return
        if len(profiles) == 1:
            self._export_single(target, profiles[0])
        else:
            self._export_many(target, profiles)

    @staticmethod
    def _safe_name(text: str) -> str:
        """A filesystem-safe base name for an exported .mobileconfig."""
        keep = "".join(c if c.isalnum() or c in " ._-" else "_" for c in text)
        return keep.strip() or "profile"

    def _export_single(self, target: str, profile: dict) -> None:
        identifier = profile.get("identifier", "")
        if not identifier:
            self.status.setText(i18n.t("profiles.missing_identifier"))
            return
        default_name = self._safe_name(profile.get("name") or identifier) + ".mobileconfig"
        download_dir = os.path.expanduser("~/Downloads")
        if not os.path.isdir(download_dir):
            download_dir = os.path.expanduser("~")
        local_path, _ = QFileDialog.getSaveFileName(
            self, i18n.t("profiles.export_title"), os.path.join(download_dir, default_name),
            i18n.t("profiles.file_filter"),
        )
        if not local_path:
            return
        self.status.setText(i18n.t("profiles.exporting_one", name=profile.get('name') or identifier))
        self.export_btn.setEnabled(False)
        self.runner.submit(
            lambda: api.export_profile(target, identifier, local_path),
            on_done=lambda r: self._on_single_exported(r, local_path),
            on_error=lambda e: self._after_export(i18n.t("profiles.export_failed", error=e)),
        )

    def _on_single_exported(self, result: dict, local_path: str) -> None:
        if result.get("ok"):
            self._after_export(i18n.t("profiles.exported_to", path=local_path))
        else:
            msg = localize_error(result.get("error"))
            self._after_export(i18n.t("profiles.export_failed_msg", msg=msg))

    def _export_many(self, target: str, profiles: list[dict]) -> None:
        out_dir = QFileDialog.getExistingDirectory(self, i18n.t("profiles.export_to"))
        if not out_dir:
            return
        # Name by identifier (unique) to avoid same-name overwrites.
        items = [
            (p.get("identifier", ""), self._safe_name(p.get("identifier", "")) + ".mobileconfig")
            for p in profiles
            if p.get("identifier")
        ]
        self.status.setText(i18n.t("profiles.exporting_many", count=len(items)))
        self.export_btn.setEnabled(False)

        def _do_export() -> dict:
            ok, failed = 0, []
            for identifier, filename in items:
                res = api.export_profile(target, identifier, os.path.join(out_dir, filename))
                if res.get("ok"):
                    ok += 1
                else:
                    failed.append(identifier)
            return {"ok": ok, "failed": failed}

        self.runner.submit(
            _do_export,
            on_done=self._on_many_exported,
            on_error=lambda e: self._after_export(i18n.t("profiles.export_failed", error=e)),
        )

    def _on_many_exported(self, result: dict) -> None:
        failed = result.get("failed", [])
        if failed:
            self._after_export(i18n.t("profiles.exported_partial", ok=result['ok'], failed=len(failed)))
        else:
            self._after_export(i18n.t("profiles.exported_ok", ok=result['ok']))

    def _after_export(self, message: str) -> None:
        self.export_btn.setEnabled(True)
        self.status.setText(message)

    # ---------------------------------------------------------------- remove

    def _on_remove_clicked(self) -> None:
        target = self._get_target()
        if not target:
            self.status.setText(i18n.t("dev_tools.no_device"))
            return
        profiles = self._selected_profiles()
        if not profiles:
            self.status.setText(i18n.t("profiles.need_select_remove"))
            return
        reply = QMessageBox.question(
            self, i18n.t("profiles.remove_title"),
            i18n.t("profiles.remove_confirm", count=len(profiles)),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        identifiers = [p.get("identifier", "") for p in profiles if p.get("identifier")]
        self.status.setText(i18n.t("profiles.removing", count=len(identifiers)))
        self.remove_btn.setEnabled(False)

        def _do_remove() -> dict:
            ok, failed = 0, []
            for identifier in identifiers:
                res = api.remove_profile(target, identifier)
                if res.get("ok"):
                    ok += 1
                else:
                    failed.append(identifier)
            return {"ok": ok, "failed": failed}

        self.runner.submit(
            _do_remove,
            on_done=self._on_removed,
            on_error=lambda e: self._after_remove(i18n.t("profiles.remove_failed", error=e)),
        )

    def _on_removed(self, result: dict) -> None:
        failed = result.get("failed", [])
        if failed:
            self._after_remove(i18n.t("profiles.removed_partial", ok=result['ok'], failed=len(failed)))
        else:
            self._after_remove(i18n.t("profiles.removed_ok", ok=result['ok']))
        self.reload()

    def _after_remove(self, message: str) -> None:
        self.remove_btn.setEnabled(True)
        self.status.setText(message)

    # ----------------------------------------------------------- drag & drop

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._first_profile(event) is not None:
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt override
        path = self._first_profile(event)
        if path is None:
            self.status.setText(i18n.t("profiles.only_mobileconfig_drop"))
            return
        event.acceptProposedAction()
        self._install(path)

    @staticmethod
    def _first_profile(event) -> str | None:
        mime = event.mimeData()
        if not mime.hasUrls():
            return None
        for url in mime.urls():
            if url.isLocalFile() and url.toLocalFile().lower().endswith(".mobileconfig"):
                return url.toLocalFile()
        return None

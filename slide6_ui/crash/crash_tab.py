"""crash_tab.py — the "Crash 报告" tab.

Lists the device's crash logs and supports multi-select / right-click export and
delete. Export offers a "keep original on device" choice; when unchecked, each
crash log is removed from the device after a successful export (handled
atomically by the toolkit via CrashReportsManager.pull(erase=True)).

Crash logs are read over lockdown + AFC2 and need neither WDA nor the XPC tunnel.
All blocking calls go through the shared AsyncRunner.
"""

from __future__ import annotations

import os
import posixpath
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
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


def _human_size(num: int) -> str:
    size = float(num)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


class CrashReportsTab(QWidget):
    """The "Crash 报告" tab: list / export / delete device crash logs."""

    def __init__(self, runner: AsyncRunner, get_target: Callable[[], str]) -> None:
        super().__init__()
        self.runner = runner
        self._get_target = get_target
        self._entries: list[dict] = []
        # The rows currently shown (the filtered subset); selection maps to this.
        self._view: list[dict] = []
        # Current crash-root-relative directory ("" = root).
        self._cur_path = ""
        self._build_ui()
        self._wire()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        bar = QHBoxLayout()
        # Unified toolbar order across all file browsers: 上一级 - 路径编辑框 - 刷新,
        # followed by crash-specific filter / export / delete. The editable path
        # shows the crash root as "/" and jumps on Enter.
        self.up_btn = QPushButton(i18n.t("common.up"))
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText(i18n.t("afc.path_placeholder"))
        self.refresh_btn = QPushButton(i18n.t("common.refresh"))
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText(i18n.t("crash.filter_placeholder"))
        self.export_btn = QPushButton(i18n.t("crash.export_selected"))
        self.delete_btn = QPushButton(i18n.t("crash.delete_selected"))
        bar.addWidget(self.up_btn)
        bar.addWidget(self.path_edit, 1)
        bar.addWidget(self.refresh_btn)
        bar.addWidget(self.filter_input, 1)
        bar.addWidget(self.export_btn)
        bar.addWidget(self.delete_btn)
        root.addLayout(bar)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([
            i18n.t("afc.col.name"), i18n.t("afc.col.size"), i18n.t("crash.col.time"),
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        root.addWidget(self.table, 1)

        self.status = QLabel(i18n.t("common.select_device_first"))
        root.addWidget(self.status)

    def _wire(self) -> None:
        self.up_btn.clicked.connect(self._go_up)
        self.path_edit.returnPressed.connect(self._on_path_entered)
        self.refresh_btn.clicked.connect(self.reload)
        self.filter_input.textChanged.connect(self._render)
        self.export_btn.clicked.connect(self._export_selected)
        self.delete_btn.clicked.connect(self._delete_selected)
        self.table.itemDoubleClicked.connect(self._on_double_click)
        self.table.customContextMenuRequested.connect(self._on_context_menu)

    # ------------------------------------------------------------- loading

    def set_target(self, target: str) -> None:
        """Called by the main window when the selected device changes."""
        self._entries = []
        self._cur_path = ""  # reset to the crash root on device switch
        self._update_path()
        self.table.setRowCount(0)
        if target:
            self.reload()
        else:
            self.status.setText(i18n.t("dev_tools.no_device"))

    def _update_path(self) -> None:
        self.path_edit.setText("/" + self._cur_path)
        self.up_btn.setEnabled(bool(self._cur_path))

    def reload(self) -> None:
        target = self._get_target()
        if not target:
            self.status.setText(i18n.t("dev_tools.no_device"))
            return
        self.status.setText(i18n.t("crash.loading"))
        self.refresh_btn.setEnabled(False)
        sub_path = self._cur_path or "/"
        self.runner.submit(
            lambda: api.list_crashes(target, sub_path),
            on_done=self._on_entries,
            on_error=lambda e: self._fail(i18n.t("afc.load_failed_detail", error=e)),
        )

    # ------------------------------------------------------------ navigation

    def _go_up(self) -> None:
        if not self._cur_path:
            return
        self._cur_path = posixpath.dirname(self._cur_path)
        self.filter_input.clear()
        self._update_path()
        self.reload()

    def _on_path_entered(self) -> None:
        # Normalize the edited text into a crash-root-relative path. Resolving as
        # an absolute path first collapses any ".." so the input can never escape
        # the crash-reports root; "" means the root.
        norm = posixpath.normpath("/" + self.path_edit.text().strip()).lstrip("/")
        self._cur_path = "" if norm == "." else norm
        self.filter_input.clear()
        self._update_path()
        self.reload()

    def _on_double_click(self, item) -> None:
        row = item.row()
        if not (0 <= row < len(self._view)):
            return
        entry = self._view[row]
        if not entry.get("isDir"):
            return
        self._cur_path = entry.get("path", "")
        self.filter_input.clear()
        self._update_path()
        self.reload()

    def _on_entries(self, result: dict) -> None:
        self.refresh_btn.setEnabled(True)
        if not result.get("ok"):
            self._fail(localize_error(result.get("error")))
            return
        self._entries = result["data"].get("entries", [])
        self._render()
        self.status.setText(i18n.t("afc.item_count", count=len(self._entries)))

    def _fail(self, message: str) -> None:
        self.refresh_btn.setEnabled(True)
        self.status.setText(message)

    def _filtered(self) -> list[dict]:
        kw = self.filter_input.text().strip().lower()
        if not kw:
            return list(self._entries)
        return [e for e in self._entries if kw in e.get("name", "").lower()]

    def _render(self) -> None:
        self._view = self._filtered()
        self.table.setRowCount(len(self._view))
        for row, e in enumerate(self._view):
            name_item = QTableWidgetItem(e.get("name", ""))
            self.table.setItem(row, 0, name_item)
            size_item = QTableWidgetItem(
                "" if e.get("isDir") else _human_size(int(e.get("size", 0)))
            )
            self.table.setItem(row, 1, size_item)
            self.table.setItem(row, 2, QTableWidgetItem(e.get("mtime", "")))

    # ----------------------------------------------------------- selection

    def _selected_entries(self) -> list[dict]:
        rows = sorted({idx.row() for idx in self.table.selectedIndexes()})
        return [self._view[r] for r in rows if 0 <= r < len(self._view)]

    def _on_context_menu(self, pos) -> None:
        if not self._selected_entries():
            return
        menu = QMenu(self)
        export_action = menu.addAction(i18n.t("crash.export"))
        delete_action = menu.addAction(i18n.t("crash.delete"))
        action = menu.exec(self.table.viewport().mapToGlobal(pos))
        if action is export_action:
            self._export_selected()
        elif action is delete_action:
            self._delete_selected()

    # -------------------------------------------------------------- export

    def _export_selected(self) -> None:
        target = self._get_target()
        if not target:
            self.status.setText(i18n.t("dev_tools.no_device"))
            return
        entries = self._selected_entries()
        if not entries:
            self.status.setText(i18n.t("crash.need_select_export"))
            return
        out_dir = QFileDialog.getExistingDirectory(self, i18n.t("crash.export_to"))
        if not out_dir:
            return
        keep = self._ask_keep_original()
        if keep is None:
            return  # cancelled
        paths = [e.get("path", "") for e in entries]
        self.status.setText(i18n.t("crash.exporting", count=len(paths)))
        self.export_btn.setEnabled(False)
        erase = not keep

        def _do_export() -> dict:
            ok, failed = 0, []
            for path in paths:
                res = api.pull_crash(target, path, out_dir, erase=erase)
                if res.get("ok"):
                    ok += 1
                else:
                    failed.append(path)
            return {"ok": ok, "failed": failed, "erased": erase}

        self.runner.submit(
            _do_export,
            on_done=self._on_export_done,
            on_error=lambda e: self._after_export(i18n.t("crash.export_failed", error=e)),
        )

    def _ask_keep_original(self) -> "bool | None":
        """Ask whether to keep the original on device. None = cancelled."""
        dlg = QDialog(self)
        dlg.setWindowTitle(i18n.t("crash.export_options_title"))
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel(i18n.t("crash.export_options_body")))
        keep_box = QCheckBox(i18n.t("crash.keep_original"))
        keep_box.setChecked(True)
        layout.addWidget(keep_box)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, dlg)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)
        if dlg.exec() != QDialog.Accepted:
            return None
        return keep_box.isChecked()

    def _on_export_done(self, result: dict) -> None:
        failed = result.get("failed", [])
        suffix = i18n.t("crash.erased_suffix") if result.get("erased") else ""
        if failed:
            self._after_export(i18n.t("crash.exported_partial", ok=result['ok'], failed=len(failed), suffix=suffix))
        else:
            self._after_export(i18n.t("crash.exported_ok", ok=result['ok'], suffix=suffix))
        if result.get("erased"):
            self.reload()

    def _after_export(self, message: str) -> None:
        self.export_btn.setEnabled(True)
        self.status.setText(message)

    # -------------------------------------------------------------- delete

    def _delete_selected(self) -> None:
        target = self._get_target()
        if not target:
            self.status.setText(i18n.t("dev_tools.no_device"))
            return
        entries = self._selected_entries()
        if not entries:
            self.status.setText(i18n.t("crash.need_select_delete"))
            return
        reply = QMessageBox.question(
            self, i18n.t("crash.delete_title"),
            i18n.t("crash.delete_confirm", count=len(entries)),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        paths = [e.get("path", "") for e in entries]
        self.status.setText(i18n.t("crash.deleting", count=len(paths)))
        self.delete_btn.setEnabled(False)

        def _do_delete() -> dict:
            ok, failed = 0, []
            for path in paths:
                res = api.clear_crash(target, path)
                if res.get("ok"):
                    ok += 1
                else:
                    failed.append(path)
            return {"ok": ok, "failed": failed}

        self.runner.submit(
            _do_delete,
            on_done=self._on_delete_done,
            on_error=lambda e: self._after_delete(i18n.t("crash.delete_failed", error=e)),
        )

    def _on_delete_done(self, result: dict) -> None:
        failed = result.get("failed", [])
        if failed:
            self._after_delete(i18n.t("crash.deleted_partial", ok=result['ok'], failed=len(failed)))
        else:
            self._after_delete(i18n.t("crash.deleted_ok", ok=result['ok']))
        self.reload()

    def _after_delete(self, message: str) -> None:
        self.delete_btn.setEnabled(True)
        self.status.setText(message)

"""afc_browser.py — the reusable AFC file browser.

AfcBrowserPanel is an embeddable widget that browses one AFC area and supports
file / folder import & export, rename, delete and make-directory. The area is
selected by ``root``:

* ``documents`` / ``container`` — one app's Documents or sandbox container
  (house-arrest vended, requires ``bundle_id``);
* ``media`` — the device media partition (``com.apple.afc``, no ``bundle_id``).

AfcBrowserDialog is a thin QDialog wrapper around the panel for the per-app
"open browser" flow. _FileTable adds drag-out export (to Finder) and drag-in
import (from Finder).

All non-blocking ios_toolkit calls go through the shared AsyncRunner so the Qt
GUI thread never blocks. The only deliberate exception is drag-export, which
must materialise a local copy synchronously before the drag starts; it runs
behind a wait cursor. File management talks to lockdown/house-arrest/AFC
services directly and needs neither WDA nor the XPC tunnel.
"""

from __future__ import annotations

import os
import posixpath
import tempfile
from typing import Callable

from PySide6.QtCore import QMimeData, Qt, QUrl
from PySide6.QtGui import QCursor, QDrag
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from shiboken6 import isValid

from ios_toolkit import toolkit_api as api

from .. import i18n
from .file_dialogs import open_directory, open_existing_files, save_file
from .errors import localize_error
from .focus import suppress_auto_focus
from .workers import AsyncRunner


def _human_size(num: int) -> str:
    size = float(num)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def _glyph_button(widget: QWidget, label: str, tooltip: str) -> QToolButton:
    """A flat, text-labelled tool button (label may include a trailing glyph,
    e.g. '导出 ↓'). Used for per-item file actions."""
    btn = QToolButton(widget)
    btn.setText(label)
    btn.setToolTip(tooltip)
    btn.setAutoRaise(True)
    return btn


class _FileTable(QTableWidget):
    """A QTableWidget that exports rows by dragging out (to Finder) and accepts
    external file/folder drops for import. Internal moves are disabled."""

    def __init__(
        self,
        export_provider: Callable[[], QMimeData | None],
        import_handler: Callable[[list[str]], None],
    ) -> None:
        super().__init__(0, 3)
        self._export_provider = export_provider
        self._import_handler = import_handler
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.CopyAction)

    def startDrag(self, supportedActions) -> None:  # noqa: N802 - Qt override
        mime = self._export_provider()
        if mime is None:
            return
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.CopyAction)

    def _external_urls(self, event) -> list[str] | None:
        # Only treat drops that originate outside the table as imports; otherwise
        # an export drag dropped back onto the list would re-import itself.
        if event.source() is self:
            return None
        mime = event.mimeData()
        if not mime.hasUrls():
            return None
        paths = [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]
        return paths or None

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._external_urls(event) is not None:
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._external_urls(event) is not None:
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt override
        paths = self._external_urls(event)
        if paths is not None:
            event.acceptProposedAction()
            self._import_handler(paths)
            return
        # Ignore internal drops (no row reordering for a remote listing).
        event.ignore()


class AfcBrowserPanel(QWidget):
    """Embeddable AFC browser for one area selected by ``root``.

    ``root="documents"`` / ``"container"`` browse an app's Documents / sandbox
    container (require ``bundle_id``); ``root="media"`` browses the device media
    partition (no ``bundle_id``). When ``target`` is empty the panel shows a
    "select a device" prompt and issues no calls until ``set_target`` is given a
    real device.
    """

    def __init__(
        self,
        parent: QWidget | None,
        runner: AsyncRunner,
        target: str,
        bundle_id: str,
        root: str,
        multi_select: bool = False,
    ) -> None:
        super().__init__(parent)
        self.runner = runner
        self.target = target
        self.bundle_id = bundle_id
        self.root = root
        # multi_select enables row multi-selection plus right-click batch
        # download / delete; the per-app sandbox dialog keeps the single-select
        # default so its behavior is unchanged.
        self.multi_select = multi_select
        self.cur_path = "/"
        self._list_request_seq = 0

        self._build_ui()
        if self.target:
            self._refresh()
        else:
            self.status.setText(i18n.t("common.select_device_first"))

    def set_target(self, target: str) -> None:
        """Point the panel at a (possibly empty) device and reload from root."""
        self.target = target or ""
        self.cur_path = "/"
        self._list_request_seq += 1
        if self.target:
            self._refresh()
        else:
            self.table.setRowCount(0)
            self.path_edit.setText(self._display_path())
            self.up_btn.setEnabled(False)
            self.status.setText(i18n.t("common.select_device_first"))

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Header: a "go up" button + editable relative path (Enter to navigate)
        # + refresh / make-folder. The go-up button is the unified parent-dir
        # navigation across all browsers (album / crash / AFC).
        nav = QHBoxLayout()
        self.up_btn = QPushButton(i18n.t("common.up"))
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText(i18n.t("afc.path_placeholder"))
        self.path_edit.returnPressed.connect(self._on_path_entered)
        self.refresh_btn = QPushButton(i18n.t("common.refresh"))
        self.mkdir_btn = QPushButton(i18n.t("afc.add_folder"))
        for btn in (self.up_btn, self.refresh_btn, self.mkdir_btn):
            btn.setAutoDefault(False)
            btn.setDefault(False)
        nav.addWidget(self.up_btn)
        nav.addWidget(self.path_edit, 1)
        nav.addWidget(self.refresh_btn)
        nav.addWidget(self.mkdir_btn)
        layout.addLayout(nav)

        self.table = _FileTable(self._make_export_mime, self._import_paths)
        self.table.setHorizontalHeaderLabels(
            [i18n.t("afc.col.name"), i18n.t("afc.col.size"), i18n.t("afc.col.actions")]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(
            QAbstractItemView.ExtendedSelection
            if self.multi_select
            else QAbstractItemView.SingleSelection
        )
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.itemDoubleClicked.connect(self._on_double_click)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.table, 1)

        self.status = QLabel("")
        layout.addWidget(self.status)

        self.up_btn.clicked.connect(self._go_up)
        self.refresh_btn.clicked.connect(self._refresh)
        self.mkdir_btn.clicked.connect(self._mkdir)

    # ------------------------------------------------------------- submission

    def _submit(self, call, ok_msg: str, fail_prefix: str, *, refresh: bool = True) -> None:
        """Run a blocking afc_* call off-thread and fold the {ok}/{error}
        envelope into a status message (refreshing the listing on success)."""
        def on_done(result: dict) -> None:
            # Guard against the panel being deleted while the call was in flight.
            if not isValid(self):
                return
            if result.get("ok"):
                self.status.setText(ok_msg)
                if refresh:
                    self._refresh()
            else:
                self.status.setText(f"{fail_prefix}: " + localize_error(result.get("error")))

        def on_error(exc: object) -> None:
            if not isValid(self):
                return
            self.status.setText(f"{fail_prefix}: {exc}")

        self.runner.submit(call, on_done=on_done, on_error=on_error)

    # --------------------------------------------------------------- listing

    def _display_path(self) -> str:
        """Render the current logical path with the context root shown as '/'.

        Every AFC area (documents / container / media) presents its own root as
        '/', so the path bar is consistent across browsers regardless of which
        device folder the root maps to underneath. Sub-levels are shown as a
        '/'-rooted relative path (e.g. '/', '/Subdir')."""
        return self.cur_path or "/"

    def _parse_path(self, text: str) -> str:
        """Inverse of _display_path: a '/'-rooted edit maps to the logical path
        under the selected AFC root. The real device-path mapping is unchanged."""
        text = text.strip()
        if not text.startswith("/"):
            text = "/" + text
        return text or "/"

    def _on_path_entered(self) -> None:
        self.cur_path = self._parse_path(self.path_edit.text())
        self._refresh()

    def _refresh(self) -> None:
        request_path = self.cur_path
        self.path_edit.setText(request_path or "/")
        self.up_btn.setEnabled(request_path != "/")
        if not self.target:
            self.table.setRowCount(0)
            self.status.setText(i18n.t("common.select_device_first"))
            return
        self.status.setText(i18n.t("afc.loading"))
        self.table.setRowCount(0)
        self._list_request_seq += 1
        request_seq = self._list_request_seq
        self.runner.submit(
            lambda: api.afc_list(self.target, self.bundle_id, self.root, request_path),
            on_done=lambda result, seq=request_seq, path=request_path: self._on_list(result, seq, path),
            on_error=lambda e, seq=request_seq: self._on_list_error(e, seq),
        )

    def _on_list_error(self, error: object, request_seq: int) -> None:
        if not isValid(self) or request_seq != self._list_request_seq:
            return
        self.status.setText(i18n.t("afc.load_failed_detail", error=error))

    def _on_list(self, result: dict, request_seq: int, request_path: str) -> None:
        # A modal browse dialog can be closed (and its C++ widgets deleted) while
        # an afc_list load is still in flight; the queued callback then fires on a
        # dead panel. Drop it instead of touching freed Qt objects.
        if not isValid(self):
            return
        if request_seq != self._list_request_seq:
            return
        if not result.get("ok"):
            self.status.setText(i18n.t("afc.load_failed") + ": " + localize_error(result.get("error")))
            return
        actual_path = ((result.get("data") or {}).get("path") or request_path or "/")
        self.cur_path = actual_path
        self.path_edit.setText(self._display_path())
        self.up_btn.setEnabled(self.cur_path != "/")
        entries = result["data"].get("entries", [])
        # Parent-dir navigation is provided by the top "上一级" button, so the
        # listing no longer carries a ".." row.
        self.table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            is_dir = bool(entry.get("isDir"))
            name = entry.get("name", "")
            icon = "📁 " if is_dir else "📄 "
            name_item = QTableWidgetItem(icon + name)
            name_item.setData(Qt.UserRole, entry)
            self.table.setItem(row, 0, name_item)
            size_text = "" if is_dir else _human_size(entry.get("size", 0))
            self.table.setItem(row, 1, QTableWidgetItem(size_text))
            self.table.setCellWidget(row, 2, self._row_actions(entry))
        self.status.setText(i18n.t("afc.item_count", count=len(entries)))

    def _row_actions(self, entry: dict) -> QWidget:
        cell = QWidget()
        lay = QHBoxLayout(cell)
        lay.setContentsMargins(4, 0, 4, 0)
        lay.setSpacing(2)
        # Import (upload) only makes sense as "upload into this folder".
        if entry.get("isDir"):
            up = _glyph_button(cell, i18n.t("afc.action.import"), i18n.t("afc.action.import_tip"))
            up.clicked.connect(lambda _=False, e=entry: self._import_into(e))
            lay.addWidget(up)
        down = _glyph_button(cell, i18n.t("afc.action.export"), i18n.t("afc.action.export_tip"))
        down.clicked.connect(lambda _=False, e=entry: self._export(e))
        lay.addWidget(down)
        rename = _glyph_button(cell, i18n.t("afc.action.rename"), i18n.t("afc.action.rename_tip"))
        rename.clicked.connect(lambda _=False, e=entry: self._rename(e))
        lay.addWidget(rename)
        delete = _glyph_button(cell, i18n.t("afc.action.delete"), i18n.t("afc.action.delete_tip"))
        delete.clicked.connect(lambda _=False, e=entry: self._delete(e))
        lay.addWidget(delete)
        lay.addStretch(1)
        return cell

    def _show_context_menu(self, _pos) -> None:
        # Resolve the row from the global cursor so header offset never matters.
        vp_pos = self.table.viewport().mapFromGlobal(QCursor.pos())
        item = self.table.itemAt(vp_pos)
        if item is None:
            return
        entry = self.table.item(item.row(), 0).data(Qt.UserRole)
        if not entry:
            return

        # In multi-select mode, when more than one selectable item is selected,
        # offer batch operations instead of single-item ones.
        selected = self._selected_entries() if self.multi_select else []
        menu = QMenu(self)
        if self.multi_select and len(selected) > 1:
            menu.addAction(
                i18n.t("afc.menu.batch_export", count=len(selected)),
                lambda: self._batch_export(selected),
            )
            menu.addSeparator()
            menu.addAction(
                i18n.t("afc.menu.batch_delete", count=len(selected)),
                lambda: self._batch_delete(selected),
            )
            menu.exec(QCursor.pos())
            return

        if entry.get("isDir"):
            menu.addAction(i18n.t("afc.menu.import_into"), lambda: self._import_into(entry))
        menu.addAction(i18n.t("afc.menu.export"), lambda: self._export(entry))
        menu.addAction(i18n.t("afc.menu.rename"), lambda: self._rename(entry))
        menu.addSeparator()
        menu.addAction(i18n.t("afc.menu.delete"), lambda: self._delete(entry))
        menu.exec(QCursor.pos())

    def _current_entry(self) -> dict | None:
        item = self.table.item(self.table.currentRow(), 0)
        return item.data(Qt.UserRole) if item else None

    def _selected_entries(self) -> list[dict]:
        """Selectable entries in the current selection."""
        entries: list[dict] = []
        seen_rows: set[int] = set()
        for item in self.table.selectedItems():
            row = item.row()
            if row in seen_rows:
                continue
            seen_rows.add(row)
            entry = self.table.item(row, 0).data(Qt.UserRole)
            if entry:
                entries.append(entry)
        return entries

    # ------------------------------------------------------------ navigation

    def _go_up(self) -> None:
        if self.cur_path != "/":
            self.cur_path = posixpath.dirname(self.cur_path.rstrip("/")) or "/"
            self._refresh()

    def _on_double_click(self, item: QTableWidgetItem) -> None:
        entry = self.table.item(item.row(), 0).data(Qt.UserRole)
        if not entry:
            return
        if entry.get("isDir"):
            self.cur_path = posixpath.join(self.cur_path, entry.get("name", ""))
            self._refresh()

    # --------------------------------------------------------- import/export

    def _import_into(self, folder: dict) -> None:
        remote_dir = posixpath.join(self.cur_path, folder.get("name", ""))
        paths = open_existing_files(self, i18n.t("afc.dialog.choose_import"))
        for path in paths:
            self._do_push(path, remote_dir)

    def _import_paths(self, paths: list[str]) -> None:
        """Drag-drop import into the current directory (files or folders)."""
        for path in paths:
            if os.path.exists(path):
                self._do_push(path, self.cur_path)

    def _do_push(self, local_path: str, remote_dir: str) -> None:
        self.status.setText(i18n.t("afc.importing", name=os.path.basename(local_path)))
        self._submit(
            lambda: api.afc_push(self.target, self.bundle_id, self.root, local_path, remote_dir),
            i18n.t("afc.import_ok"), i18n.t("afc.import_failed"),
        )

    def _export(self, entry: dict) -> None:
        name = entry.get("name", "file")
        remote = posixpath.join(self.cur_path, name)
        if entry.get("isDir"):
            parent = open_directory(self, i18n.t("afc.dialog.export_folder_to"))
            if not parent:
                return
            # pull creates parent/<name> for a directory source.
            local_path = parent
            done_path = os.path.join(parent, name)
        else:
            download_dir = os.path.expanduser("~/Downloads")
            if not os.path.isdir(download_dir):
                download_dir = os.path.expanduser("~")
            local_path = save_file(
                self, i18n.t("afc.dialog.export_to"), os.path.join(download_dir, name)
            )
            if not local_path:
                return
            done_path = local_path
        self.status.setText(i18n.t("afc.exporting", name=name))
        self._submit(
            lambda: api.afc_pull(self.target, self.bundle_id, self.root, remote, local_path),
            i18n.t("afc.export_ok", path=done_path), i18n.t("afc.export_failed"), refresh=False,
        )

    def _make_export_mime(self) -> QMimeData | None:
        """Materialise the selected entry into a temp dir so it can be dragged
        out to Finder. Runs synchronously behind a wait cursor."""
        entry = self._current_entry()
        if not entry:
            return None
        name = entry.get("name", "")
        remote = posixpath.join(self.cur_path, name)
        tmp_dir = tempfile.mkdtemp(prefix="cabledios_")
        if entry.get("isDir"):
            # pull a directory into tmp_dir; result lives at tmp_dir/<name>.
            local_path = tmp_dir
            result_path = os.path.join(tmp_dir, name)
        else:
            local_path = os.path.join(tmp_dir, name)
            result_path = local_path
        self.status.setText(i18n.t("afc.preparing_export", name=name))
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            result = api.afc_pull(
                self.target, self.bundle_id, self.root, remote, local_path
            )
        finally:
            QApplication.restoreOverrideCursor()
        if not result.get("ok"):
            self.status.setText(
                i18n.t("afc.export_prepare_failed") + ": " + localize_error(result.get("error"))
            )
            return None
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(result_path)])
        self.status.setText(i18n.t("afc.drag_export", name=name))
        return mime

    # ----------------------------------------------------------- mkdir/rename/delete

    def _mkdir(self) -> None:
        name, ok = QInputDialog.getText(
            self, i18n.t("afc.add_folder"), i18n.t("afc.dialog.name_label")
        )
        if not ok or not name.strip():
            return
        remote = posixpath.join(self.cur_path, name.strip())
        self._submit(
            lambda: api.afc_mkdir(self.target, self.bundle_id, self.root, remote),
            i18n.t("afc.mkdir_ok"), i18n.t("afc.mkdir_failed"),
        )

    def _rename(self, entry: dict) -> None:
        old = entry.get("name", "")
        new, ok = QInputDialog.getText(
            self, i18n.t("afc.dialog.rename_title"), i18n.t("afc.dialog.new_name_label"), text=old
        )
        new = new.strip() if ok else ""
        if not ok or not new or new == old:
            return
        if "/" in new:
            self.status.setText(i18n.t("afc.name_no_slash"))
            return
        src = posixpath.join(self.cur_path, old)
        dst = posixpath.join(self.cur_path, new)
        self.status.setText(i18n.t("afc.renaming", old=old, new=new))
        self._submit(
            lambda: api.afc_rename(self.target, self.bundle_id, self.root, src, dst),
            i18n.t("afc.rename_ok"), i18n.t("afc.rename_failed"),
        )

    def _delete(self, entry: dict) -> None:
        name = entry.get("name", "")
        reply = QMessageBox.question(
            self, i18n.t("afc.dialog.delete_title"), i18n.t("afc.confirm_delete", name=name),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        remote = posixpath.join(self.cur_path, name)
        self.status.setText(i18n.t("afc.deleting", name=name))
        self._submit(
            lambda: api.afc_rm(self.target, self.bundle_id, self.root, remote),
            i18n.t("afc.delete_ok"), i18n.t("afc.delete_failed"),
        )

    # ----------------------------------------------------------- batch ops

    def _batch_export(self, entries: list[dict]) -> None:
        """Download several selected items into one chosen directory."""
        out_dir = open_directory(self, i18n.t("afc.dialog.batch_export_to"))
        if not out_dir:
            return
        names = [e.get("name", "") for e in entries]
        cur_path, target, bundle_id, root = (
            self.cur_path, self.target, self.bundle_id, self.root
        )
        self.status.setText(i18n.t("afc.batch.downloading", count=len(names)))

        def _do() -> dict:
            ok, failed = 0, []
            for name in names:
                remote = posixpath.join(cur_path, name)
                # For a directory source, pull creates out_dir/<name>; for a file
                # it writes out_dir/<name>. Same-name files are overwritten.
                local = os.path.join(out_dir, name)
                res = api.afc_pull(target, bundle_id, root, remote, local)
                if res.get("ok"):
                    ok += 1
                else:
                    failed.append(name)
            return {"ok": ok, "failed": failed}

        self.runner.submit(
            _do,
            on_done=lambda r: self._on_batch_done(r, "downloaded", refresh=False),
            on_error=lambda e: isValid(self) and self.status.setText(i18n.t("afc.batch.download_failed", error=e)),
        )

    def _batch_delete(self, entries: list[dict]) -> None:
        """Delete several selected items after one summary confirmation."""
        names = [e.get("name", "") for e in entries]
        sample = "、".join(names[:3]) + ("…" if len(names) > 3 else "")
        reply = QMessageBox.question(
            self, i18n.t("afc.batch.delete_title"),
            i18n.t("afc.batch.confirm_delete", count=len(names), sample=sample),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        cur_path, target, bundle_id, root = (
            self.cur_path, self.target, self.bundle_id, self.root
        )
        self.status.setText(i18n.t("afc.batch.deleting", count=len(names)))

        def _do() -> dict:
            ok, failed = 0, []
            for name in names:
                remote = posixpath.join(cur_path, name)
                res = api.afc_rm(target, bundle_id, root, remote)
                if res.get("ok"):
                    ok += 1
                else:
                    failed.append(name)
            return {"ok": ok, "failed": failed}

        self.runner.submit(
            _do,
            on_done=lambda r: self._on_batch_done(r, "deleted", refresh=True),
            on_error=lambda e: isValid(self) and self.status.setText(i18n.t("afc.batch.delete_failed", error=e)),
        )

    def _on_batch_done(self, result: dict, action: str, *, refresh: bool) -> None:
        if not isValid(self):
            return
        failed = result.get("failed", [])
        if failed:
            self.status.setText(
                i18n.t(f"afc.batch.{action}_partial", ok=result["ok"], failed=len(failed))
            )
        else:
            self.status.setText(i18n.t(f"afc.batch.{action}_ok", ok=result["ok"]))
        if refresh:
            self._refresh()


class AfcBrowserDialog(QDialog):
    """Thin dialog wrapper hosting an AfcBrowserPanel for the per-app flow."""

    def __init__(
        self,
        parent: QWidget,
        runner: AsyncRunner,
        target: str,
        bundle_id: str,
        root: str,
        app_name: str,
    ) -> None:
        super().__init__(parent)
        scope = i18n.t("afc.scope.documents") if root == "documents" else i18n.t("afc.scope.sandbox")
        self.setWindowTitle(f"{app_name} — {scope}")
        self.resize(620, 480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.panel = AfcBrowserPanel(self, runner, target, bundle_id, root)
        layout.addWidget(self.panel)
        # Don't auto-focus the path field when the browse dialog opens.
        suppress_auto_focus(self)

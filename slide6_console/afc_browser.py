"""afc_browser.py — the per-app file browser dialog.

AfcBrowserDialog browses one app's Documents (root="documents") or sandbox
container (root="container") and supports file / folder import & export, rename,
delete and make-directory. _FileTable adds drag-out export (to Finder) and
drag-in import (from Finder).

All non-blocking executor_ios calls go through the shared AsyncRunner so the Qt
GUI thread never blocks. The only deliberate exception is drag-export, which
must materialise a local copy synchronously before the drag starts; it runs
behind a wait cursor. File management talks to lockdown/house-arrest services
directly and needs neither WDA nor the XPC tunnel.
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
    QFileDialog,
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

from executor_ios import toolkit_api as api

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


class AfcBrowserDialog(QDialog):
    """Browse one app's Documents (root="documents") or sandbox container
    (root="container") with file / folder import & export."""

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
        self.runner = runner
        self.target = target
        self.bundle_id = bundle_id
        self.root = root
        self.cur_path = "/"

        scope = "Documents" if root == "documents" else "沙盒"
        self.setWindowTitle(f"{app_name} — {scope}")
        self.resize(620, 480)
        self._build_ui()
        self._refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Header: editable relative path (Enter to navigate) + refresh / make-folder.
        nav = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("输入路径后回车跳转")
        self.path_edit.returnPressed.connect(self._on_path_entered)
        self.refresh_btn = QPushButton("刷新")
        self.mkdir_btn = QPushButton("添加文件夹")
        nav.addWidget(self.path_edit, 1)
        nav.addWidget(self.refresh_btn)
        nav.addWidget(self.mkdir_btn)
        layout.addLayout(nav)

        self.table = _FileTable(self._make_export_mime, self._import_paths)
        self.table.setHorizontalHeaderLabels(["名称", "大小", "操作"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
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

        self.refresh_btn.clicked.connect(self._refresh)
        self.mkdir_btn.clicked.connect(self._mkdir)

    # ------------------------------------------------------------- submission

    def _submit(self, call, ok_msg: str, fail_prefix: str, *, refresh: bool = True) -> None:
        """Run a blocking afc_* call off-thread and fold the {ok}/{error}
        envelope into a status message (refreshing the listing on success)."""
        def on_done(result: dict) -> None:
            if result.get("ok"):
                self.status.setText(ok_msg)
                if refresh:
                    self._refresh()
            else:
                self.status.setText(f"{fail_prefix}: " + result.get("error", {}).get("message", ""))

        self.runner.submit(
            call,
            on_done=on_done,
            on_error=lambda e: self.status.setText(f"{fail_prefix}: {e}"),
        )

    # --------------------------------------------------------------- listing

    def _display_path(self) -> str:
        """Render the current logical path as an editable relative string.

        documents root: logical '/' maps to the app's Documents folder, so it is
        shown prefixed with 'Documents'. container root: shown as an absolute
        sandbox path ('/', '/Documents', ...)."""
        if self.root == "documents":
            rel = self.cur_path.strip("/")
            return f"Documents/{rel}" if rel else "Documents"
        return self.cur_path or "/"

    def _parse_path(self, text: str) -> str:
        """Inverse of _display_path: turn the edited text back into a logical
        path rooted at the selected AFC root."""
        text = text.strip()
        if self.root == "documents":
            rel = text.strip("/")
            if rel == "Documents":
                return "/"
            if rel.startswith("Documents/"):
                rel = rel[len("Documents/"):]
            return "/" + rel if rel else "/"
        if not text.startswith("/"):
            text = "/" + text
        return text or "/"

    def _on_path_entered(self) -> None:
        self.cur_path = self._parse_path(self.path_edit.text())
        self._refresh()

    def _refresh(self) -> None:
        self.path_edit.setText(self._display_path())
        self.status.setText("正在加载…")
        self.table.setRowCount(0)
        self.runner.submit(
            lambda: api.afc_list(self.target, self.bundle_id, self.root, self.cur_path),
            on_done=self._on_list,
            on_error=lambda e: self.status.setText(f"加载失败: {e}"),
        )

    def _on_list(self, result: dict) -> None:
        if not result.get("ok"):
            self.status.setText("加载失败: " + result.get("error", {}).get("message", ""))
            return
        entries = result["data"].get("entries", [])
        # Prepend a ".." navigation row whenever we are below the root.
        rows: list[dict] = []
        if self.cur_path != "/":
            rows.append({"name": "..", "isDir": True, "_parent": True})
        rows.extend(entries)
        self.table.setRowCount(len(rows))
        for row, entry in enumerate(rows):
            is_parent = bool(entry.get("_parent"))
            is_dir = bool(entry.get("isDir"))
            name = entry.get("name", "")
            icon = "↩ " if is_parent else ("📁 " if is_dir else "📄 ")
            name_item = QTableWidgetItem(icon + name)
            name_item.setData(Qt.UserRole, entry)
            self.table.setItem(row, 0, name_item)
            size_text = "" if is_dir else _human_size(entry.get("size", 0))
            self.table.setItem(row, 1, QTableWidgetItem(size_text))
            self.table.setCellWidget(row, 2, self._row_actions(entry))
        self.status.setText(f"{len(entries)} 项")

    def _row_actions(self, entry: dict) -> QWidget:
        cell = QWidget()
        lay = QHBoxLayout(cell)
        lay.setContentsMargins(4, 0, 4, 0)
        lay.setSpacing(2)
        # The ".." navigation row carries no per-item actions.
        if entry.get("_parent"):
            return cell
        # Import (upload) only makes sense as "upload into this folder".
        if entry.get("isDir"):
            up = _glyph_button(cell, "导入 ↑", "导入到此文件夹")
            up.clicked.connect(lambda _=False, e=entry: self._import_into(e))
            lay.addWidget(up)
        down = _glyph_button(cell, "导出 ↓", "导出到本地")
        down.clicked.connect(lambda _=False, e=entry: self._export(e))
        lay.addWidget(down)
        rename = _glyph_button(cell, "重命名 ✎", "重命名")
        rename.clicked.connect(lambda _=False, e=entry: self._rename(e))
        lay.addWidget(rename)
        delete = _glyph_button(cell, "删除 ✕", "删除")
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
        if not entry or entry.get("_parent"):
            return
        menu = QMenu(self)
        if entry.get("isDir"):
            menu.addAction("导入到此文件夹…", lambda: self._import_into(entry))
        menu.addAction("导出…", lambda: self._export(entry))
        menu.addAction("重命名…", lambda: self._rename(entry))
        menu.addSeparator()
        menu.addAction("删除…", lambda: self._delete(entry))
        menu.exec(QCursor.pos())

    def _current_entry(self) -> dict | None:
        item = self.table.item(self.table.currentRow(), 0)
        return item.data(Qt.UserRole) if item else None

    # ------------------------------------------------------------ navigation

    def _go_up(self) -> None:
        if self.cur_path != "/":
            self.cur_path = posixpath.dirname(self.cur_path.rstrip("/")) or "/"
            self._refresh()

    def _on_double_click(self, item: QTableWidgetItem) -> None:
        entry = self.table.item(item.row(), 0).data(Qt.UserRole)
        if not entry:
            return
        if entry.get("_parent"):
            self._go_up()
        elif entry.get("isDir"):
            self.cur_path = posixpath.join(self.cur_path, entry.get("name", ""))
            self._refresh()

    # --------------------------------------------------------- import/export

    def _import_into(self, folder: dict) -> None:
        remote_dir = posixpath.join(self.cur_path, folder.get("name", ""))
        paths, _ = QFileDialog.getOpenFileNames(self, "选择要导入的文件", "")
        for path in paths:
            self._do_push(path, remote_dir)

    def _import_paths(self, paths: list[str]) -> None:
        """Drag-drop import into the current directory (files or folders)."""
        for path in paths:
            if os.path.exists(path):
                self._do_push(path, self.cur_path)

    def _do_push(self, local_path: str, remote_dir: str) -> None:
        self.status.setText(f"正在导入 {os.path.basename(local_path)}…")
        self._submit(
            lambda: api.afc_push(self.target, self.bundle_id, self.root, local_path, remote_dir),
            "导入成功", "导入失败",
        )

    def _export(self, entry: dict) -> None:
        name = entry.get("name", "file")
        remote = posixpath.join(self.cur_path, name)
        if entry.get("isDir"):
            parent = QFileDialog.getExistingDirectory(self, "导出文件夹到")
            if not parent:
                return
            # pull creates parent/<name> for a directory source.
            local_path = parent
            done_path = os.path.join(parent, name)
        else:
            download_dir = os.path.expanduser("~/Downloads")
            if not os.path.isdir(download_dir):
                download_dir = os.path.expanduser("~")
            local_path, _ = QFileDialog.getSaveFileName(
                self, "导出到", os.path.join(download_dir, name)
            )
            if not local_path:
                return
            done_path = local_path
        self.status.setText(f"正在导出 {name}…")
        self._submit(
            lambda: api.afc_pull(self.target, self.bundle_id, self.root, remote, local_path),
            f"已导出到 {done_path}", "导出失败", refresh=False,
        )

    def _make_export_mime(self) -> QMimeData | None:
        """Materialise the selected entry into a temp dir so it can be dragged
        out to Finder. Runs synchronously behind a wait cursor."""
        entry = self._current_entry()
        if not entry or entry.get("_parent"):
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
        self.status.setText(f"正在准备导出 {name}…")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            result = api.afc_pull(
                self.target, self.bundle_id, self.root, remote, local_path
            )
        finally:
            QApplication.restoreOverrideCursor()
        if not result.get("ok"):
            self.status.setText(
                "导出准备失败: " + result.get("error", {}).get("message", "")
            )
            return None
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(result_path)])
        self.status.setText(f"拖拽导出 {name}")
        return mime

    # ----------------------------------------------------------- mkdir/rename/delete

    def _mkdir(self) -> None:
        name, ok = QInputDialog.getText(self, "添加文件夹", "名称:")
        if not ok or not name.strip():
            return
        remote = posixpath.join(self.cur_path, name.strip())
        self._submit(
            lambda: api.afc_mkdir(self.target, self.bundle_id, self.root, remote),
            "已创建", "创建失败",
        )

    def _rename(self, entry: dict) -> None:
        old = entry.get("name", "")
        new, ok = QInputDialog.getText(self, "重命名", "新名称:", text=old)
        new = new.strip() if ok else ""
        if not ok or not new or new == old:
            return
        if "/" in new:
            self.status.setText("名称不能包含 /")
            return
        src = posixpath.join(self.cur_path, old)
        dst = posixpath.join(self.cur_path, new)
        self.status.setText(f"正在重命名 {old} → {new}…")
        self._submit(
            lambda: api.afc_rename(self.target, self.bundle_id, self.root, src, dst),
            "已重命名", "重命名失败",
        )

    def _delete(self, entry: dict) -> None:
        name = entry.get("name", "")
        reply = QMessageBox.question(
            self, "删除", f"确定删除 {name}？此操作不可撤销。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        remote = posixpath.join(self.cur_path, name)
        self.status.setText(f"正在删除 {name}…")
        self._submit(
            lambda: api.afc_rm(self.target, self.bundle_id, self.root, remote),
            "已删除", "删除失败",
        )

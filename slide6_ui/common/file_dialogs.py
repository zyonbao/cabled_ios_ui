"""file_dialogs.py — file-picker helpers with a native / non-native toggle.

The packaged CablediOS app is currently **unsigned** and **not App-Sandboxed**,
so the macOS native open/save panel — which is rendered out-of-process by the
system Powerbox service (``com.apple.appkit.xpc.openAndSavePanelService``) — is
unreliable in that build (it may fail to appear, fail to navigate, or return an
empty selection). Until the app ships code-signed with the entitlements in
``packaging/entitlements.plist`` we force Qt's in-process non-native dialog.

The non-native picker is ``_PathBarFileDialog``: the standard Qt
``QFileDialog`` (non-native) with an extra editable **path bar** injected at the
top. Navigating folders keeps the bar in sync, and typing/pasting a folder or
file path + Enter jumps there. Because the app is not sandboxed it can browse
the whole filesystem with no loss of access.

Flip ``USE_NATIVE_FILE_DIALOG`` to ``True`` once the bundle is code-signed (see
``packaging/build_macos_app.sh`` and ``packaging/entitlements.plist``).
"""

from __future__ import annotations

import os
from typing import Optional, Sequence

from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

# Keep the native panel disabled until the app is codesigned. This is the single
# switch to flip later; all file pickers should route through this module.
USE_NATIVE_FILE_DIALOG = False


class _PathBarFileDialog(QFileDialog):
    """Standard non-native QFileDialog with an editable path bar at the top.

    The path bar mirrors the current directory as the user navigates and lets
    them type/paste an absolute folder or file path + Enter to jump anywhere —
    on top of the familiar QFileDialog browser the rest of the app uses.
    """

    def __init__(
        self,
        parent: "Optional[QWidget]",
        caption: str,
        start_dir: str,
        name_filters: "Sequence[str]",
    ) -> None:
        super().__init__(parent, caption, start_dir)
        self.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        self.setFileMode(QFileDialog.FileMode.ExistingFile)
        self.setAcceptMode(QFileDialog.AcceptMode.AcceptOpen)
        if name_filters:
            self.setNameFilters(list(name_filters))
        self._inject_path_bar()
        # Keep the bar in sync while the user clicks through folders.
        self.directoryEntered.connect(self._on_directory_entered)

    def _inject_path_bar(self) -> None:
        grid = self.layout()
        # The non-native dialog uses a QGridLayout; if that ever changes, skip
        # injection rather than crash (the dialog still works without the bar).
        if not isinstance(grid, QGridLayout):
            self._path_bar = None
            return

        bar = QWidget(self)
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        self._path_bar = QLineEdit(self.directory().absolutePath())
        self._path_bar.setPlaceholderText("输入文件夹或文件的绝对路径后回车跳转")
        go = QPushButton("跳转", bar)
        row.addWidget(QLabel("路径", bar))
        row.addWidget(self._path_bar, 1)
        row.addWidget(go)

        # Shift every existing grid item down one row, then place the bar on
        # row 0. QFileDialog's top navigation row is added as a *sub-layout*
        # (not a widget), so we must move all item kinds (widgets, layouts,
        # spacers) — handled uniformly via takeAt/addItem — or they stay on
        # row 0 and overlap the bar.
        cols = max(1, grid.columnCount())
        captured = []
        for i in range(grid.count()):
            captured.append((grid.itemAt(i),) + tuple(grid.getItemPosition(i)))
        while grid.count():
            grid.takeAt(0)
        for item, r, c, rs, cs in captured:
            grid.addItem(item, r + 1, c, rs, cs)
        grid.addWidget(bar, 0, 0, 1, cols)

        self._path_bar.returnPressed.connect(self._jump)
        go.clicked.connect(self._jump)

    def _on_directory_entered(self, path: str) -> None:
        if getattr(self, "_path_bar", None) is not None:
            self._path_bar.setText(path)

    def _jump(self) -> None:
        text = os.path.expanduser(self._path_bar.text().strip())
        if os.path.isdir(text):
            self.setDirectory(text)
        elif os.path.isfile(text):
            self.selectFile(text)
            self.accept()


def open_existing_file(
    parent: "Optional[QWidget]",
    caption: str,
    name_filters: "Sequence[str]",
    start_dir: "Optional[str]" = None,
) -> str:
    """Pick one existing file; returns its path, or "" if cancelled.

    Routes through the native panel or the non-native ``_PathBarFileDialog``
    per ``USE_NATIVE_FILE_DIALOG``. ``name_filters`` is a list of Qt filter
    strings, e.g. ``["GPX 文件 (*.gpx)", "所有文件 (*)"]``.
    """
    start = start_dir or os.path.expanduser("~")
    filters = list(name_filters)

    if USE_NATIVE_FILE_DIALOG:
        # Native out-of-process panel: reliable only on a signed/sandboxed app.
        path, _ = QFileDialog.getOpenFileName(
            parent, caption, start, ";;".join(filters)
        )
        return path or ""

    dlg = _PathBarFileDialog(parent, caption, start, filters)
    if dlg.exec() and dlg.selectedFiles():
        return dlg.selectedFiles()[0]
    return ""


def open_directory(
    parent: "Optional[QWidget]",
    caption: str,
    start_dir: "Optional[str]" = None,
) -> str:
    """Pick an existing directory; returns its path, or "" if cancelled.

    Honours ``USE_NATIVE_FILE_DIALOG`` (native panel only on a signed/sandboxed
    build); otherwise uses Qt's in-process non-native directory chooser.
    """
    start = start_dir or os.path.expanduser("~")
    options = QFileDialog.Option.ShowDirsOnly
    if not USE_NATIVE_FILE_DIALOG:
        options |= QFileDialog.Option.DontUseNativeDialog
    return QFileDialog.getExistingDirectory(parent, caption, start, options) or ""

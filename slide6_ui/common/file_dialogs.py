"""file_dialogs.py — file-picker helpers with a system / built-in toggle.

By default the app uses the operating system's native open/save panel. On some
systems that native panel can hit access restrictions (e.g. the out-of-process
Powerbox service on an unsigned/un-sandboxed macOS build may fail to appear or
return an empty selection). For those cases the user can switch to the app's
built-in picker from Preferences → General.

The preference is persisted in ``QSettings`` under
``settings/use_builtin_file_dialog`` and read fresh on every call via
:func:`use_builtin_file_dialog`, so flipping it takes effect immediately for
every picker — provided all file pickers route through this module.

The built-in picker is ``_PathBarFileDialog``: the standard Qt ``QFileDialog``
(non-native) with an extra editable **path bar** injected at the top. Navigating
folders keeps the bar in sync, and typing/pasting a folder or file path + Enter
jumps there. Because the app is not sandboxed it can browse the whole filesystem
with no loss of access.
"""

from __future__ import annotations

import os
from typing import Optional, Sequence

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

from .. import i18n

# QSettings key for the file-picker preference. Default is the system (native)
# panel; users can opt into the app's built-in picker when the system one is
# restricted.
USE_BUILTIN_FILE_DIALOG_KEY = "settings/use_builtin_file_dialog"
DEFAULT_USE_BUILTIN_FILE_DIALOG = False


def use_builtin_file_dialog() -> bool:
    """Whether to use the app's built-in picker (vs the system native panel).

    Read fresh from QSettings on each call so a Preferences change applies to the
    next picker without restarting. Defaults to the system panel.
    """
    value = QSettings().value(USE_BUILTIN_FILE_DIALOG_KEY, DEFAULT_USE_BUILTIN_FILE_DIALOG)
    if isinstance(value, str):
        return value.lower() in ("1", "true", "yes", "on")
    return bool(value)


def use_native_file_dialog() -> bool:
    """Whether to use the system native panel (the inverse of built-in)."""
    return not use_builtin_file_dialog()


class _PathBarFileDialog(QFileDialog):
    """Standard non-native QFileDialog with an editable path bar at the top.

    The path bar mirrors the current directory as the user navigates and lets
    them type/paste an absolute folder or file path + Enter to jump anywhere —
    on top of the familiar QFileDialog browser the rest of the app uses.

    The same widget backs every non-native picker (open file/files, save, and
    directory) via ``file_mode`` / ``accept_mode`` so the experience is uniform.
    """

    def __init__(
        self,
        parent: "Optional[QWidget]",
        caption: str,
        start_dir: str,
        *,
        file_mode: "QFileDialog.FileMode" = QFileDialog.FileMode.ExistingFile,
        accept_mode: "QFileDialog.AcceptMode" = QFileDialog.AcceptMode.AcceptOpen,
        name_filters: "Optional[Sequence[str]]" = None,
        show_dirs_only: bool = False,
        default_name: "Optional[str]" = None,
    ) -> None:
        super().__init__(parent, caption, start_dir)
        self.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        if show_dirs_only:
            self.setOption(QFileDialog.Option.ShowDirsOnly, True)
        self.setFileMode(file_mode)
        self.setAcceptMode(accept_mode)
        if name_filters:
            self.setNameFilters(list(name_filters))
        if default_name:
            self.selectFile(default_name)
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
        self._path_bar.setPlaceholderText(i18n.t("file_dialog.path_placeholder"))
        # Keep the start of long paths visible (cursor at end scrolls to tail).
        self._path_bar.setCursorPosition(0)
        go = QPushButton(i18n.t("file_dialog.go"), bar)
        row.addWidget(QLabel(i18n.t("file_dialog.path_label"), bar))
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
            # Show the leading part of long paths rather than the trailing tail.
            self._path_bar.setCursorPosition(0)

    def _jump(self) -> None:
        text = os.path.expanduser(self._path_bar.text().strip())
        if not text:
            return
        if os.path.isdir(text):
            # Navigate into the folder. For directory-picking this also makes it
            # the current selection; the user confirms with the Choose button.
            self.setDirectory(text)
            return
        if os.path.isfile(text):
            self.setDirectory(os.path.dirname(text))
            self.selectFile(text)
            # Auto-confirm only when opening an existing file; for save the user
            # may want to tweak the name first.
            if self.acceptMode() == QFileDialog.AcceptMode.AcceptOpen:
                self.accept()
            return
        # Non-existent path (typical when typing a new save target): jump to the
        # parent folder and pre-fill the file name field.
        parent_dir = os.path.dirname(text)
        if os.path.isdir(parent_dir):
            self.setDirectory(parent_dir)
            self.selectFile(os.path.basename(text))


def open_existing_file(
    parent: "Optional[QWidget]",
    caption: str,
    name_filters: "Optional[Sequence[str]]" = None,
    start_dir: "Optional[str]" = None,
) -> str:
    """Pick one existing file; returns its path, or "" if cancelled.

    Routes through the native panel or the non-native ``_PathBarFileDialog`` per
    :func:`use_native_file_dialog`. ``name_filters`` is a list of Qt filter
    strings, e.g. ``["GPX 文件 (*.gpx)", "所有文件 (*)"]``.
    """
    start = start_dir or os.path.expanduser("~")
    filters = list(name_filters) if name_filters else []

    if use_native_file_dialog():
        # Native out-of-process panel: reliable only on a signed/sandboxed app.
        path, _ = QFileDialog.getOpenFileName(
            parent, caption, start, ";;".join(filters)
        )
        return path or ""

    dlg = _PathBarFileDialog(
        parent, caption, start,
        file_mode=QFileDialog.FileMode.ExistingFile,
        accept_mode=QFileDialog.AcceptMode.AcceptOpen,
        name_filters=filters,
    )
    if dlg.exec() and dlg.selectedFiles():
        return dlg.selectedFiles()[0]
    return ""


def open_existing_files(
    parent: "Optional[QWidget]",
    caption: str,
    name_filters: "Optional[Sequence[str]]" = None,
    start_dir: "Optional[str]" = None,
) -> "list[str]":
    """Pick one or more existing files; returns their paths (empty if cancelled).

    Honours :func:`use_native_file_dialog`; the non-native path uses the shared
    ``_PathBarFileDialog`` so the experience matches the single-file picker.
    """
    start = start_dir or os.path.expanduser("~")
    filters = list(name_filters) if name_filters else []

    if use_native_file_dialog():
        paths, _ = QFileDialog.getOpenFileNames(
            parent, caption, start, ";;".join(filters)
        )
        return list(paths or [])

    dlg = _PathBarFileDialog(
        parent, caption, start,
        file_mode=QFileDialog.FileMode.ExistingFiles,
        accept_mode=QFileDialog.AcceptMode.AcceptOpen,
        name_filters=filters,
    )
    if dlg.exec():
        return list(dlg.selectedFiles())
    return []


def save_file(
    parent: "Optional[QWidget]",
    caption: str,
    default_path: "Optional[str]" = None,
    name_filters: "Optional[Sequence[str]]" = None,
) -> str:
    """Pick a destination path for saving; returns the path, or "" if cancelled.

    Honours :func:`use_native_file_dialog`; the non-native path uses the shared
    ``_PathBarFileDialog`` (with a pre-filled name) for a consistent experience.
    ``default_path`` may be a directory or a suggested file path/name.
    """
    filters = list(name_filters) if name_filters else []
    default = default_path or os.path.expanduser("~")

    if use_native_file_dialog():
        path, _ = QFileDialog.getSaveFileName(
            parent, caption, default, ";;".join(filters)
        )
        return path or ""

    # Split the suggested path into a starting directory and a file name so the
    # path bar lands in the right folder with the name field pre-filled.
    if os.path.isdir(default):
        start, default_name = default, ""
    else:
        start = os.path.dirname(default) or os.path.expanduser("~")
        default_name = os.path.basename(default)
    if not os.path.isdir(start):
        start = os.path.expanduser("~")

    dlg = _PathBarFileDialog(
        parent, caption, start,
        file_mode=QFileDialog.FileMode.AnyFile,
        accept_mode=QFileDialog.AcceptMode.AcceptSave,
        name_filters=filters,
        default_name=default_name or None,
    )
    if dlg.exec() and dlg.selectedFiles():
        return dlg.selectedFiles()[0]
    return ""


def open_directory(
    parent: "Optional[QWidget]",
    caption: str,
    start_dir: "Optional[str]" = None,
) -> str:
    """Pick an existing directory; returns its path, or "" if cancelled.

    Honours :func:`use_native_file_dialog`; the non-native path uses the shared
    ``_PathBarFileDialog`` so directory picking matches the file pickers.
    """
    start = start_dir or os.path.expanduser("~")

    if use_native_file_dialog():
        options = QFileDialog.Option.ShowDirsOnly
        return QFileDialog.getExistingDirectory(parent, caption, start, options) or ""

    dlg = _PathBarFileDialog(
        parent, caption, start,
        file_mode=QFileDialog.FileMode.Directory,
        accept_mode=QFileDialog.AcceptMode.AcceptOpen,
        show_dirs_only=True,
    )
    if dlg.exec() and dlg.selectedFiles():
        return dlg.selectedFiles()[0]
    return ""

"""context_copy.py — right-click "copy value" menus for list / table / log views.

Provides a uniform right-click affordance across the app's data lists: copying
the value of the cell (table/list) or the line (plain-text log) under the cursor
to the system clipboard. Centralized here so every list area behaves the same.
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QMenu,
    QPlainTextEdit,
)

from .. import i18n

# Called with the copied text after a successful copy (e.g. to flash a status).
CopiedCallback = Optional[Callable[[str], None]]


def _copy(text: str, on_copied: CopiedCallback) -> None:
    QApplication.clipboard().setText(text)
    if on_copied is not None:
        on_copied(text)


def add_copy_value_action(
    menu: QMenu,
    view: QAbstractItemView,
    pos,
    on_copied: CopiedCallback = None,
):
    """Append a "copy value" action for the cell under ``pos`` to ``menu``.

    Returns the created action so callers can merge copy into an existing
    context menu. The action is disabled when no cell sits under ``pos``.
    """
    index = view.indexAt(pos)
    value = "" if not index.isValid() else str(index.data(Qt.DisplayRole) or "")
    action = menu.addAction(i18n.t("common.copy_value"))
    action.setEnabled(index.isValid())
    action.triggered.connect(lambda: _copy(value, on_copied))
    return action


def install_table_copy_menu(view: QAbstractItemView, on_copied: CopiedCallback = None) -> None:
    """Install a standalone right-click "copy value" menu on a table/list view."""
    view.setContextMenuPolicy(Qt.CustomContextMenu)

    def handler(pos):
        menu = QMenu(view)
        add_copy_value_action(menu, view, pos, on_copied)
        menu.exec(view.viewport().mapToGlobal(pos))

    view.customContextMenuRequested.connect(handler)


def install_plaintext_copy_menu(edit: QPlainTextEdit, on_copied: CopiedCallback = None) -> None:
    """Augment a read-only QPlainTextEdit with a "copy line under cursor" action.

    Keeps the standard context menu (Copy / Select All) and appends a "copy
    line" action so a single right-click can grab the whole log line without a
    manual text selection.
    """
    edit.setContextMenuPolicy(Qt.CustomContextMenu)

    def handler(pos):
        menu = edit.createStandardContextMenu()
        cursor = edit.cursorForPosition(pos)
        cursor.select(QTextCursor.LineUnderCursor)
        line = cursor.selectedText()
        menu.addSeparator()
        action = menu.addAction(i18n.t("common.copy_line"))
        action.setEnabled(bool(line))
        action.triggered.connect(lambda: _copy(line, on_copied))
        menu.exec(edit.viewport().mapToGlobal(pos))

    edit.customContextMenuRequested.connect(handler)

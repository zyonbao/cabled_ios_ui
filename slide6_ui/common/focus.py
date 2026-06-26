"""focus.py — keep controls from auto-grabbing focus on show / tab change.

Qt hands keyboard focus to the first Tab-focusable child when a page or dialog
becomes visible. With filter / path / search fields that lands focus on a text
box the moment a tab is switched to (or a sub-page / dialog opens); when text
inputs are demoted, focus instead falls through to the first button, which on
macOS renders it with the accent color (and a default button is also bound to
Enter). Both are intrusive on a passive settings / tool pane.

``suppress_auto_focus`` demotes text inputs, buttons, item views and combo
boxes to ClickFocus so none of them auto-grabs focus on show, and strips the
default-button state from push buttons. Programmatic ``setFocus()`` (e.g. the
key/mouse keyboard-capture field) is unaffected and still works.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QAbstractSpinBox,
    QComboBox,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QWidget,
)

# Controls that should not auto-grab focus (and thus not get highlighted /
# selected) when the containing page/dialog is shown.
_CLICK_FOCUS_TYPES = (
    QLineEdit,
    QPlainTextEdit,
    QTextEdit,
    QAbstractSpinBox,
    QAbstractButton,
    QAbstractItemView,
    QComboBox,
)


def suppress_auto_focus(root: QWidget) -> None:
    """Open ``root`` with no default button, no focused field, no selection.

    Iterates ``root`` and its descendants. Every push button has its default-
    button state cleared (so macOS does not tint it with the accent color and
    Enter does not trigger it); every focusable input/button/list/combo is
    switched to ClickFocus so it only takes focus on an explicit mouse click and
    is therefore never auto-focused (or auto-selected) on show. Widgets
    explicitly set to NoFocus are left untouched.
    """
    candidates = list(root.findChildren(QWidget))
    candidates.append(root)
    for widget in candidates:
        if isinstance(widget, QPushButton):
            widget.setAutoDefault(False)
            widget.setDefault(False)
        if isinstance(widget, _CLICK_FOCUS_TYPES) and widget.focusPolicy() != Qt.NoFocus:
            widget.setFocusPolicy(Qt.ClickFocus)

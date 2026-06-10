"""focus.py — keep text inputs from auto-grabbing focus on show / tab change.

Qt hands keyboard focus to the first Tab-focusable child when a page or dialog
becomes visible. With filter / path / search fields that lands focus on a text
box the moment a tab is switched to (or a sub-page / dialog opens), which is
intrusive. ``suppress_auto_focus`` demotes such inputs to ClickFocus so they
only take focus on an explicit mouse click. Programmatic ``setFocus()`` (e.g.
the key/mouse keyboard-capture field) is unaffected and still works.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QLineEdit,
    QPlainTextEdit,
    QTextEdit,
    QWidget,
)

# Text-entry widgets that should not be auto-focused on show / tab switch.
_TEXT_INPUT_TYPES = (QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox)


def suppress_auto_focus(root: QWidget) -> None:
    """Demote text inputs under ``root`` (inclusive) to click-only focus.

    Iterates ``root`` and its descendants; any text-entry widget that currently
    accepts Tab focus is switched to ClickFocus so it no longer becomes the
    default focus when the containing page/dialog is shown. Widgets explicitly
    set to NoFocus are left untouched.
    """
    candidates = list(root.findChildren(QWidget))
    candidates.append(root)
    for widget in candidates:
        if isinstance(widget, _TEXT_INPUT_TYPES) and widget.focusPolicy() != Qt.NoFocus:
            widget.setFocusPolicy(Qt.ClickFocus)

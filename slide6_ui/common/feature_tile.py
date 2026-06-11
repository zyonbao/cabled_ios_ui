"""feature_tile.py — a reusable card-like feature button.

Shared by the Developer Tools and Diagnostics tabs: a large clickable tile that
shows a prominent title and a muted subtitle, used inside a FlowLayout grid.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QToolButton, QVBoxLayout


class FeatureTile(QToolButton):
    """A large, card-like feature button with a distinct title and subtitle.

    ``QToolButton.setText`` cannot style two text parts differently, so the
    title (prominent: bold + larger) and subtitle (secondary: smaller + muted)
    are rendered as two child ``QLabel``s. The labels are transparent to mouse
    events so clicks reach the button, preserving the standard
    ``clicked`` / ``setEnabled`` / ``setToolTip`` behavior callers rely on.
    When the tile is disabled the labels inherit the parent's disabled look.
    """

    def __init__(self, title: str, subtitle: str) -> None:
        super().__init__()
        self.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.setMinimumSize(220, 90)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)

        self._title_label = QLabel(title)
        title_font = self._title_label.font()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() + 2)
        self._title_label.setFont(title_font)
        self._title_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        lay.addWidget(self._title_label)

        self._subtitle_label = QLabel(subtitle)
        if subtitle:
            self._subtitle_label.setWordWrap(True)
            sub_font = self._subtitle_label.font()
            sub_font.setPointSize(max(sub_font.pointSize() - 1, 1))
            self._subtitle_label.setFont(sub_font)
            # Render with the muted, theme-aware "disabled" text brush to read as
            # secondary text (independent of the tile's own enabled state).
            self._subtitle_label.setEnabled(False)
            self._subtitle_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            lay.addWidget(self._subtitle_label)
        else:
            self._subtitle_label.hide()
        lay.addStretch(1)

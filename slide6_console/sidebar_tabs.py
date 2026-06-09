"""sidebar_tabs.py — a reusable left-side (vertical) tab container.

`SidebarTabs` is a QTabWidget whose tabs run down the left edge while their
labels stay horizontal (Qt rotates West/East tab text by default). The
horizontal-text rendering is done with a small QProxyStyle so the look is
consistent regardless of the active widget style.

Extracted as its own view so new tabs can be added in one place as the console
grows beyond the current key/mouse and app-list tabs.
"""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import (
    QProxyStyle,
    QStyle,
    QStyleOptionTab,
    QTabBar,
    QTabWidget,
    QWidget,
)

# Fixed tab metrics so a growing tab column stays visually uniform.
_TAB_MIN_WIDTH = 132
_TAB_MIN_HEIGHT = 40


class _HorizontalWestTabStyle(QProxyStyle):
    """Render West/East tab labels with horizontal (un-rotated) text.

    Based on the Fusion style: the native macOS style (QMacStyle) draws tabs
    entirely in its own renderer and never calls CE_TabBarTabLabel, so a
    drawControl override there has no effect (text stays rotated/clipped).
    Fusion routes through the standard control elements and honours both our
    size transpose and the north-shape label override, giving reliable
    horizontal text on the left-side tabs across platforms.
    """

    def __init__(self) -> None:
        super().__init__("Fusion")

    def sizeFromContents(self, content_type, option, size, widget):  # noqa: N802 - Qt override
        result = super().sizeFromContents(content_type, option, size, widget)
        if content_type == QStyle.CT_TabBarTab:
            # West/East tabs are sized as if rotated; transpose so each tab is
            # wide/short enough to fit horizontal text, then enforce uniform
            # minimum metrics so every tab in the column has the same footprint.
            result.transpose()
            result = QSize(
                max(result.width(), _TAB_MIN_WIDTH),
                max(result.height(), _TAB_MIN_HEIGHT),
            )
        return result

    def drawControl(self, element, option, painter, widget=None):  # noqa: N802 - Qt override
        if element == QStyle.CE_TabBarTabLabel and isinstance(option, QStyleOptionTab):
            # Draw the label as if it were a top (north) tab → horizontal text.
            opt = QStyleOptionTab(option)
            opt.shape = QTabBar.RoundedNorth
            super().drawControl(element, opt, painter, widget)
            return
        super().drawControl(element, option, painter, widget)


class SidebarTabs(QTabWidget):
    """A QTabWidget with left-side tabs and horizontal tab labels."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTabPosition(QTabWidget.TabPosition.West)
        # Icons (optional, via addTab(widget, icon, label)) render to the left
        # of the horizontal label since labels are drawn as north tabs.
        self.setIconSize(QSize(18, 18))
        # Keep a reference so the proxy style is not garbage-collected. Apply
        # to both the tab widget (pane layout / frame) and its bar so the tab
        # column and content pane render consistently.
        self._tab_style = _HorizontalWestTabStyle()
        self._tab_style.setParent(self)
        self.setStyle(self._tab_style)
        self.tabBar().setStyle(self._tab_style)

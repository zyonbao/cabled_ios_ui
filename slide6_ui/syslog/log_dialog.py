"""log_dialog.py — system-log viewer hosted from the Developer Tools tab.

Picks the view by device major version: iOS 17+ → structured OslogPanel, iOS <17
→ raw-text SyslogPanel. Non-modal (``show()``); stops its stream on close. The
log streams are lockdown services and need neither DDI nor an XPC tunnel.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import QDialog, QVBoxLayout

from ..common import tunnel
from ..common.focus import suppress_auto_focus
from .oslog_panel import OslogPanel
from .syslog_panel import SyslogPanel


class LogDialog(QDialog):
    """A standalone, non-modal system-log window (syslog / oslog by version)."""

    def __init__(
        self,
        runner,
        get_target: Callable[[], str],
        get_os_version: Callable[[], str],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.resize(960, 600)
        major = tunnel.ios_major(get_os_version())
        if major >= 17:
            self.setWindowTitle("系统日志 — oslog (iOS 17+)")
            self.panel = OslogPanel(runner, get_target, get_os_version)
        else:
            self.setWindowTitle("系统日志 — syslog (iOS <17)")
            self.panel = SyslogPanel(runner, get_target, get_os_version)
        layout = QVBoxLayout(self)
        layout.addWidget(self.panel)
        self.panel.set_target(get_target())
        suppress_auto_focus(self)

    def shutdown(self) -> None:
        self.panel.shutdown()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        self.panel.shutdown()
        super().closeEvent(event)

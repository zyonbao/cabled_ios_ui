"""app.py — entry point for the slide6_ui desktop application.

Run from the repository root:
    python3 -m slide6_ui.app

The app calls ios_toolkit.toolkit_api in-process; it does not start any HTTP
server. iOS 17+ devices still require the XPC tunnel, which the app can launch
with administrator authorization after a device is selected.
"""

from __future__ import annotations

import signal
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from .main_window import MainWindow


def _install_sigint_handler(app: QApplication, window: MainWindow) -> QTimer:
    """Make Ctrl+C (SIGINT) quit the app cleanly instead of crashing.

    Qt's C++ event loop does not return to the Python interpreter on its own, so
    a pending Python signal handler would never run while the GUI is idle (the
    process appears to hang or crash on Ctrl+C). A low-frequency QTimer with a
    no-op callback periodically yields to the interpreter so the installed SIGINT
    handler can fire; the handler then routes through the window's normal close
    path (stops the mirror / keyboard threads, tunnel prompt) before quitting.
    """

    def _handler(_signum, _frame) -> None:
        window.close()
        app.quit()

    signal.signal(signal.SIGINT, _handler)
    timer = QTimer()
    timer.start(200)
    timer.timeout.connect(lambda: None)
    return timer


def main() -> None:
    app = QApplication(sys.argv)
    # Kept as the legacy name on purpose to stay consistent with the QSettings
    # storage key (see main_window._SETTINGS_APP) and preserve saved preferences.
    app.setApplicationName("slide6_console")
    window = MainWindow()
    window.show()
    # Keep a reference so the wake-up timer is not garbage-collected.
    _sigint_timer = _install_sigint_handler(app, window)  # noqa: F841
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

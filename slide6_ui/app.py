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

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication

from ios_toolkit import logsys

from . import i18n
from .main_window import (
    MainWindow,
    _LOGGING_DIR_KEY,
    _LOGGING_ENABLED_KEY,
    _SETTINGS_APP,
    _SETTINGS_ORG,
)


def _install_sigint_handler(app: QApplication, window: MainWindow) -> QTimer:
    """Make Ctrl+C (SIGINT) quit the app cleanly instead of crashing.

    Qt's C++ event loop does not return to the Python interpreter on its own, so
    a pending Python signal handler would never run while the GUI is idle (the
    process appears to hang or crash on Ctrl+C). A low-frequency QTimer with a
    no-op callback periodically yields to the interpreter so the installed SIGINT
    handler can fire; the handler then routes through the window's normal close
    path (stops the mirror / keyboard threads, tunnel prompt) before quitting.
    """

    # Guard against re-entry: a second Ctrl+C while shutdown is in progress
    # must not call close() again on a window whose C++ object is already gone
    # (that raises a libshiboken "Internal C++ object already deleted" error).
    state = {"closing": False}

    def _handler(_signum, _frame) -> None:
        if state["closing"]:
            return
        state["closing"] = True
        try:
            window.close()
        except RuntimeError:
            # Window already torn down (e.g. rapid double Ctrl+C): nothing to do.
            pass
        app.quit()

    signal.signal(signal.SIGINT, _handler)
    timer = QTimer()
    timer.start(200)
    timer.timeout.connect(lambda: None)
    return timer


def _init_logging() -> None:
    """Configure logging from saved preferences before the UI starts."""
    settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
    enabled = bool(settings.value(_LOGGING_ENABLED_KEY, True, type=bool))
    log_dir = settings.value(_LOGGING_DIR_KEY, "", type=str) or None
    logsys.setup_logging(enabled=enabled, log_dir=log_dir)


def main() -> None:
    app = QApplication(sys.argv)
    # Match the QSettings identifier (see main_window._SETTINGS_ORG/_SETTINGS_APP)
    # so QStandardPaths and the preferences plist resolve under the same name
    # (com.unnamed.cabled_ios on macOS).
    app.setOrganizationName("unnamed")
    app.setApplicationName("cabled_ios")
    _init_logging()
    # Select the UI language before constructing any window (restart-to-apply).
    i18n.init()
    window = MainWindow()
    window.show()
    # Keep a reference so the wake-up timer is not garbage-collected.
    _sigint_timer = _install_sigint_handler(app, window)  # noqa: F841
    try:
        exit_code = app.exec()
    finally:
        logsys.shutdown_logging()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()

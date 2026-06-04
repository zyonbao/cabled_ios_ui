"""app.py — entry point for the slide6_console desktop application.

Run from the repository root:
    python3 -m slide6_console.app

The app calls executor_ios.toolkit_api in-process; it does not start any HTTP
server. iOS 17+ devices still require the XPC tunnel, which the app can launch
with administrator authorization after a device is selected.
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .main_window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("slide6_console")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

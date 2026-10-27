"""
main.py
=======
Entry point for the Unified Device Monitor application.

This is the file that PyInstaller targets. It does exactly four things:

    1.  Create a QApplication.
    2.  Create the MainWindow.
    3.  Show the window.
    4.  Run the Qt event loop.

Nothing else lives here. All UI, all device I/O, and all logging are in
main_window.py and the modules it imports.
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

import config
from main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_NAME)
    app.setApplicationVersion(config.APP_VERSION)

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

from __future__ import annotations

import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from pm.ui.main_window import MainWindow
from pm.ui.styles import STUDIO_DARK_QSS


def run() -> None:
    # Enable high DPI scaling
    if hasattr(Qt, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)

    # Apply the Studio Dark Luxury stylesheet
    app.setStyleSheet(STUDIO_DARK_QSS)

    # Set application-wide font
    app.setStyle('Fusion')

    window = MainWindow()
    window.show()

    sys.exit(app.exec())

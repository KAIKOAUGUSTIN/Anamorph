# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from pm.about import APP_NAME, VERSION
from pm.ui.main_window import MainWindow
from pm.ui.styles import STUDIO_DARK_QSS


def run() -> None:
    # Enable high DPI scaling
    if hasattr(Qt, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)

    # Display name and version only. `setApplicationName`/`setOrganizationName`
    # are deliberately left alone: QStandardPaths derives AppDataLocation from
    # them, so setting them would move the session file out from under anyone
    # who already has unsaved work there - the crash net would come up empty
    # exactly once, silently, on the version that "just renamed the app".
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(VERSION)

    # Apply the Studio Dark Luxury stylesheet
    app.setStyleSheet(STUDIO_DARK_QSS)

    # Set application-wide font
    app.setStyle('Fusion')

    window = MainWindow()
    window.show()

    sys.exit(app.exec())

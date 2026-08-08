# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from about import APP_NAME, ORGANIZATION, VERSION
from app_paths import asset_path, remember_legacy_app_data
from ui.main_window import MainWindow
from ui.styles import STUDIO_DARK_QSS


def run() -> None:
    # Enable high DPI scaling
    if hasattr(Qt, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)

    # Before the rename, not after: QStandardPaths derives AppDataLocation
    # from the application and organization names, so this is the last moment
    # the previous location can be computed. `workspace_base_path` carries the
    # old session across on the first run under the new name - otherwise an
    # operator with an hour of unsaved work would find the crash net empty.
    remember_legacy_app_data()

    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORGANIZATION)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(VERSION)

    # The window and taskbar mark. Set here rather than per window, so
    # every projection window and dialog inherits it.
    icon = asset_path("icon.png")
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))

    # Apply the Studio Dark Luxury stylesheet
    app.setStyleSheet(STUDIO_DARK_QSS)

    # Set application-wide font
    app.setStyle('Fusion')

    window = MainWindow()
    window.show()

    sys.exit(app.exec())

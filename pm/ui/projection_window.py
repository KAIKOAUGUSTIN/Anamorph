# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QWidget

from pm.model.project import Project
from pm.render.gl_renderer import GLRenderer


class ProjectionWindow(QWidget):
    def __init__(self, project: Project, parent=None, output=None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        # One window per projector, each showing its own view of the shared
        # canvas through its own calibration.
        self.renderer = GLRenderer(project, self, output=output)
        project.changed.connect(self.renderer.update)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.renderer)

    def open_on_screen(self, screen) -> None:
        if screen:
            geometry = screen.geometry()
            self.setGeometry(geometry)
        self.showFullScreen()

    def closeEvent(self, event) -> None:
        self.renderer.cleanup()
        super().closeEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

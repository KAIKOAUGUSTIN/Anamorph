from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from pm.ui.main_window import MainWindow


DARK_QSS = """
QMainWindow {
    background-color: #1b1b1e;
    color: #e0e0e0;
}
QToolBar {
    background: #232327;
    border-bottom: 1px solid #2d2d33;
}
QMenuBar {
    background: #232327;
    color: #e0e0e0;
}
QMenuBar::item:selected {
    background: #2f2f36;
}
QMenu {
    background: #232327;
    color: #e0e0e0;
}
QMenu::item:selected {
    background: #2f2f36;
}
QListWidget, QLineEdit, QComboBox, QDoubleSpinBox, QSlider {
    background: #1f1f24;
    color: #e0e0e0;
    border: 1px solid #2d2d33;
}
QPushButton {
    background: #2a2a30;
    color: #e0e0e0;
    border: 1px solid #33333a;
    padding: 4px 8px;
}
QPushButton:hover {
    background: #32323a;
}
QGroupBox {
    border: 1px solid #2d2d33;
    margin-top: 6px;
    color: #d0d0d0;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
}
QLabel#panelTitle {
    font-weight: 600;
}
"""


def run() -> None:
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_QSS)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

"""The shortcut sheet.

Every gesture in this app is a modifier on a drag, which is fast once you know
it and invisible until you do. A projection show is not the moment to go
looking for a manual, so the manual is one keypress away and stays open on a
second monitor if that is what you want.
"""

from __future__ import annotations

from typing import List, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

Section = Tuple[str, List[Tuple[str, str]]]

SHORTCUTS: List[Section] = [
    ("Selecting", [
        ("Click", "Select a surface. A grouped one brings its group along"),
        ("Ctrl + click", "Add a surface to the selection, or take it back out"),
        ("Click again", "Swap between the white transform grips and the shape's own points"),
        ("Click empty canvas", "Clear the selection"),
        ("Drag empty canvas", "Pan the view"),
    ]),
    ("Moving and shaping", [
        ("Drag the body", "Move. Shift locks to one axis"),
        ("Alt + drag", "Rotate about the centre. Shift snaps to 15 degrees"),
        ("Ctrl + drag", "Scale from the centre"),
        ("Drag a cyan point", "Reshape that corner, or bend that mesh control point"),
        ("Drag an amber point", "Bend a curved edge"),
        ("Drag a red point", "Reshape a mask"),
        ("Alt while dragging a point", "Ignore snapping for this drag"),
        ("Arrow keys", "Nudge by 1 unit. Shift + arrows nudge by 10"),
    ]),
    ("Building surfaces", [
        ("Double-click an edge", "Insert a vertex there"),
        ("Alt + double-click an edge", "Curve it, or straighten it again"),
        ("Ctrl + D", "Duplicate the selected surface"),
        ("Ctrl + M", "Cut a mask - a window, a doorway, a pillar"),
        ("Ctrl + G", "Group the selected surfaces"),
        ("Ctrl + Shift + G", "Ungroup them"),
        ("Delete / Backspace", "Remove the selected surface"),
    ]),
    ("Project", [
        ("Ctrl + Z", "Undo"),
        ("Ctrl + Shift + Z  or  Ctrl + Y", "Redo"),
        ("Ctrl + N / O / S", "New, open, save"),
        ("Escape", "Close the fullscreen projection"),
        ("F1", "This sheet"),
    ]),
]


class HelpDialog(QDialog):
    """Non-modal on purpose: it is a reference, not a question."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Keyboard and mouse")
        self.resize(560, 620)

        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)

        grid = QGridLayout(body)
        grid.setContentsMargins(16, 12, 16, 12)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)

        row = 0
        for title, entries in SHORTCUTS:
            header = QLabel(title.upper())
            header.setStyleSheet(
                "color: #00d4aa; font-size: 10px; font-weight: 700;"
                " letter-spacing: 2px; padding: 14px 0 4px 0;"
            )
            grid.addWidget(header, row, 0, 1, 2)
            row += 1
            for keys, meaning in entries:
                key_label = QLabel(keys)
                key_label.setStyleSheet(
                    "color: #e0e0e0; font-weight: 600; background: #202024;"
                    " border: 1px solid #3a3a3e; border-radius: 3px; padding: 3px 8px;"
                )
                key_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                text = QLabel(meaning)
                text.setWordWrap(True)
                text.setStyleSheet("color: #a0a0a0;")
                grid.addWidget(key_label, row, 0)
                grid.addWidget(text, row, 1)
                row += 1
        grid.setRowStretch(row, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)

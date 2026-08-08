# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-only

"""Point a project at media that has moved.

Relative paths already handle the case where the whole show folder travels as
one piece. This is the other case: the project stayed put and the media went
somewhere else - a drive remounted under a different name, a library
reorganised, a file collected from an editor's machine.

Relinking one file at a time is not the shape of the problem. Media moves by
the folder, so pointing at one file's new home is taken as an offer to look
for its neighbours in the same place.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from media.availability import forget, missing_paths
from model.commands import RelinkMediaCommand
from model.project import Project


def find_in_folder(path: str, folder: str) -> Optional[str]:
    """`path`'s basename inside `folder`, if it is there."""
    if not path or not folder:
        return None
    candidate = os.path.join(folder, os.path.basename(path))
    return candidate if os.path.isfile(candidate) else None


def relink_map(paths: List[str], folder: str) -> Dict[str, str]:
    """Which of `paths` can be found in `folder`, old path -> new path."""
    found: Dict[str, str] = {}
    for path in paths:
        candidate = find_in_folder(path, folder)
        if candidate:
            found[path] = candidate
    return found


def apply_relink(project: Project, mapping: Dict[str, str], undo_stack=None) -> int:
    """Repoint every surface using an old path. Returns how many moved.

    Through the undo stack when there is one: pointing at the wrong folder is
    exactly the sort of mistake that should cost one Ctrl+Z.
    """
    if not mapping:
        return 0
    command = RelinkMediaCommand(project, mapping)
    if undo_stack is not None:
        undo_stack.push(command)
    else:
        command.redo()
    for old in mapping:
        forget(old)
    return command.changed


class RelinkDialog(QDialog):
    """Lists what is missing and offers one folder to look in."""

    def __init__(self, project: Project, undo_stack=None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Relink media")
        self.resize(620, 380)
        self._project = project
        self._undo_stack = undo_stack
        self.relinked = 0

        layout = QVBoxLayout(self)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        self.list = QListWidget()
        layout.addWidget(self.list, 1)

        buttons = QHBoxLayout()
        self.folder_button = QPushButton("Look in folder...")
        self.folder_button.setToolTip(
            "Pick where the media went. Every missing file with a match in\n"
            "that folder is repointed at once."
        )
        self.folder_button.clicked.connect(self._on_pick_folder)
        self.file_button = QPushButton("Locate selected file...")
        self.file_button.setToolTip(
            "Point at one file. Its neighbours in the same folder are\n"
            "relinked too - media moves by the folder, not one at a time."
        )
        self.file_button.clicked.connect(self._on_locate_file)
        buttons.addWidget(self.folder_button)
        buttons.addWidget(self.file_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        box = QDialogButtonBox(QDialogButtonBox.Close)
        box.rejected.connect(self.accept)
        layout.addWidget(box)

        self.refresh()

    def refresh(self) -> None:
        forget()
        paths = missing_paths(self._project.shapes)
        self.list.clear()
        for path in paths:
            self.list.addItem(QListWidgetItem(path))
        if paths:
            self.summary.setText(
                f"{len(paths)} file(s) the project cannot find. "
                "Pick the folder they moved to."
            )
        else:
            self.summary.setText("Every file this project uses is where it should be.")
        self.file_button.setEnabled(bool(paths))
        self.folder_button.setEnabled(bool(paths))
        if paths:
            self.list.setCurrentRow(0)

    # --- actions ---------------------------------------------------------

    def _on_pick_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Where did the media go?")
        if folder:
            self._relink_from(folder)

    def _on_locate_file(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        path, _filter = QFileDialog.getOpenFileName(
            self, f"Locate {os.path.basename(item.text())}"
        )
        if path:
            self._relink_from(os.path.dirname(path))

    def _relink_from(self, folder: str) -> None:
        mapping = relink_map(missing_paths(self._project.shapes), folder)
        moved = apply_relink(self._project, mapping, self._undo_stack)
        self.relinked += moved
        self.refresh()
        if moved:
            self.summary.setText(
                f"Relinked {moved} surface(s) from {folder}.\n" + self.summary.text()
            )
        else:
            self.summary.setText(
                f"Nothing matching was found in {folder}.\n" + self.summary.text()
            )

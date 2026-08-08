# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-only

"""What each projector actually sees, without turning the projector on.

Everything downstream of the canvas - the region crop, the keystone, the blend
ramp, the colour correction - only exists in the output pass. Until now the
only way to look at it was to darken the room and project, which means the
calibration you are checking is the calibration you cannot see while you edit.

One renderer, one output at a time. Two projectors' worth of live GL beside
the editor costs more than it tells you, and the interesting question is
always "what does *this* one look like".
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from model.project import Project
from ui.widgets import NoScrollComboBox


class OutputPreview(QDialog):
    """A live view of one output, through everything that output applies."""

    def __init__(self, project: Project, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Output preview")
        self.resize(720, 520)
        self._project = project
        self._renderer: Optional[QWidget] = None
        self._error: Optional[QLabel] = None
        self._wired = False

        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        label = QLabel("Projector")
        label.setStyleSheet("color: #808080;")
        self.output_combo = NoScrollComboBox()
        self.output_combo.currentIndexChanged.connect(lambda _i: self._rebuild_renderer())
        self.follow_check = QCheckBox("Follow selection")
        self.follow_check.setChecked(True)
        self.follow_check.setToolTip(
            "Switch the preview to whichever projector is being edited in the\n"
            "outputs dialog."
        )
        top.addWidget(label)
        top.addWidget(self.output_combo, 1)
        top.addWidget(self.follow_check)
        layout.addLayout(top)

        self._holder = QWidget()
        self._holder_layout = QVBoxLayout(self._holder)
        self._holder_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._holder, 1)

        self.aspect_label = QLabel()
        self.aspect_label.setStyleSheet("color: #808080; font-size: 11px;")
        layout.addWidget(self.aspect_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)

        self._project.changed.connect(self._on_project_changed)
        self._wired = True
        self.refresh()

    # --- outputs ---------------------------------------------------------

    def refresh(self) -> None:
        """Re-read the output list, keeping the current one selected if it lives."""
        current = self.current_output_id()
        self.output_combo.blockSignals(True)
        self.output_combo.clear()
        for output in self._project.outputs:
            self.output_combo.addItem(output.name or "Projector", output.id)
        index = self.output_combo.findData(current)
        self.output_combo.setCurrentIndex(index if index >= 0 else 0)
        self.output_combo.blockSignals(False)
        self._rebuild_renderer()

    def current_output_id(self) -> Optional[str]:
        return self.output_combo.currentData()

    def current_output(self):
        return self._project.get_output(self.current_output_id() or "")

    def show_output(self, output_id: Optional[str]) -> None:
        """Point the preview at one projector, if the user has not opted out."""
        if not output_id or not self.follow_check.isChecked():
            return
        index = self.output_combo.findData(output_id)
        if index >= 0 and index != self.output_combo.currentIndex():
            self.output_combo.setCurrentIndex(index)

    def _on_project_changed(self) -> None:
        ids = [self._project.outputs[i].id for i in range(len(self._project.outputs))]
        known = [self.output_combo.itemData(i) for i in range(self.output_combo.count())]
        if ids != known:
            # Outputs added, removed or reordered: the combo is stale.
            self.refresh()
            return
        self._update_aspect_label()

    # --- the renderer ----------------------------------------------------

    def _rebuild_renderer(self) -> None:
        """A GLRenderer is bound to its output at construction, so switching
        projectors means a new one."""
        self._teardown_renderer()
        output = self.current_output()
        if output is None:
            self._show_message("No outputs to preview.")
            return

        try:
            from render.gl_renderer import GLRenderer

            renderer = GLRenderer(self._project, self._holder, output=output)
        except Exception as exc:  # pragma: no cover - depends on the GL driver
            # A machine with no usable GL still has to be able to open this
            # window; saying so beats a blank rectangle.
            self._show_message(f"OpenGL preview unavailable: {exc}")
            return

        self._renderer = renderer
        self._holder_layout.addWidget(renderer)
        self._update_aspect_label()

    def _teardown_renderer(self) -> None:
        if self._renderer is not None:
            cleanup = getattr(self._renderer, "cleanup", None)
            if cleanup is not None:
                cleanup()
            self._renderer.setParent(None)
            self._renderer.deleteLater()
            self._renderer = None
        if self._error is not None:
            self._error.setParent(None)
            self._error.deleteLater()
            self._error = None

    def _show_message(self, text: str) -> None:
        self._error = QLabel(text)
        self._error.setAlignment(Qt.AlignCenter)
        self._error.setWordWrap(True)
        self._error.setStyleSheet("color: #808080;")
        self._holder_layout.addWidget(self._error)
        self.aspect_label.clear()

    def _update_aspect_label(self) -> None:
        output = self.current_output()
        if output is None:
            self.aspect_label.clear()
            return
        canvas = self._project.canvas
        region = output.region.normalised()
        width = max(int(canvas.width * region.width), 1)
        height = max(int(canvas.height * region.height), 1)
        notes = []
        if output.has_keystone():
            notes.append("keystone")
        if any((output.blend.left, output.blend.right, output.blend.top, output.blend.bottom)):
            notes.append("blend")
        suffix = f" - {', '.join(notes)}" if notes else ""
        self.aspect_label.setText(f"{width}x{height} of the canvas{suffix}")

    def closeEvent(self, event) -> None:
        # The renderer runs a repaint timer; leaving it alive behind a closed
        # window burns a frame's work every 16ms for nothing.
        self._teardown_renderer()
        # A window can be closed more than once - by the user, then by the
        # application shutting down - and disconnecting twice is a warning
        # from PySide rather than an exception, so the flag is the guard.
        if self._wired:
            self._wired = False
            self._project.changed.disconnect(self._on_project_changed)
        super().closeEvent(event)

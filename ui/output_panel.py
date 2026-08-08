# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-only

"""Calibration for each projector: region, keystone, blend and colour.

A dialog rather than a fourth panel. Calibration is bench work done once when
the rig is built and again when something gets knocked - not something you
want eating canvas width for the rest of the show.
"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from model.commands import (
    AddOutputCommand,
    CanvasSizeCommand,
    OutputSession,
    RemoveOutputCommand,
)
from model.media import SourceRect
from model.output import Output, split_outputs
from model.project import Project
from model.project_store import available_screens, screen_geometry
from ui.widgets import ArrowSpinBox, NoScrollComboBox, NoScrollSpinBox

# The one-line explanation under each section of the dialog. Named because it
# is worn by four of them, and four copies of a colour drift apart the first
# time one is adjusted.
HINT_STYLE = "color: #b8b8b8; font-size: 11px;"


def _spin(minimum: float, maximum: float, step: float, decimals: int = 3) -> ArrowSpinBox:
    box = ArrowSpinBox()
    box.setRange(minimum, maximum)
    box.setSingleStep(step)
    box.setDecimals(decimals)
    box.setFixedWidth(74)
    box.setFixedHeight(24)
    return box


class OutputDialog(QDialog):
    outputs_changed = Signal()
    preview_requested = Signal(object)
    output_selected = Signal(object)

    def __init__(self, project: Project, undo_stack, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Projector Outputs")
        self.resize(820, 660)
        self._project = project
        self._session = OutputSession(undo_stack)
        self._undo_stack = undo_stack
        self._updating = False

        layout = QHBoxLayout(self)

        # --- the list of projectors -------------------------------------
        left = QVBoxLayout()
        left.addWidget(QLabel("Outputs"))
        self.list = QListWidget()
        self.list.setFixedWidth(190)
        self.list.currentRowChanged.connect(lambda _row: self._load_selected())
        left.addWidget(self.list, 1)

        # One button per row-half, each wide enough for its own label. They
        # used to be squeezed against the dialog's bottom edge under a list
        # that took every spare pixel, with the Close box landing on top.
        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        self.add_btn = QPushButton("Add")
        self.remove_btn = QPushButton("Remove")
        for btn in (self.add_btn, self.remove_btn):
            btn.setMinimumHeight(28)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.add_btn.setToolTip("Add another projector")
        self.remove_btn.setToolTip("Remove the selected projector")
        self.add_btn.clicked.connect(self._on_add)
        self.remove_btn.clicked.connect(self._on_remove)
        buttons.addWidget(self.add_btn)
        buttons.addWidget(self.remove_btn)
        left.addLayout(buttons)

        tile_row = QHBoxLayout()
        tile_row.setSpacing(6)
        self.tile_count = NoScrollSpinBox()
        self.tile_count.setRange(2, 8)
        self.tile_count.setValue(2)
        self.tile_count.setFixedWidth(60)
        self.tile_btn = QPushButton("Tile")
        self.tile_btn.setMinimumHeight(28)
        self.tile_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.tile_btn.setToolTip(
            "Replace the outputs with N projectors side by side, already\n"
            "overlapping and already carrying matching blend ramps."
        )
        self.tile_btn.clicked.connect(self._on_tile)
        tile_row.addWidget(self.tile_count)
        tile_row.addWidget(self.tile_btn)
        left.addLayout(tile_row)

        # Everything on this dialog only exists in the output pass. Being able
        # to watch it while turning the knobs is the difference between
        # calibrating and guessing.
        self.preview_btn = QPushButton("Preview output")
        self.preview_btn.setMinimumHeight(28)
        self.preview_btn.setToolTip("Watch what this projector shows, without projecting")
        self.preview_btn.clicked.connect(lambda: self.preview_requested.emit(self._current_output_id()))
        left.addWidget(self.preview_btn)
        left.addWidget(self._build_canvas_group())
        left.addSpacing(8)

        left_panel = QWidget()
        left_panel.setLayout(left)
        left_panel.setFixedWidth(210)
        layout.addWidget(left_panel)

        # --- the selected projector's settings ---------------------------
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        # The groups are laid out in rows of four spin boxes; below this the
        # rightmost one gets clipped instead of the dialog scrolling.
        scroll.setMinimumWidth(560)
        self.editor = QWidget()
        scroll.setWidget(self.editor)
        layout.addWidget(scroll, 1)

        form = QVBoxLayout(self.editor)
        form.addWidget(self._build_identity_group())
        form.addWidget(self._build_region_group())
        form.addWidget(self._build_keystone_group())
        form.addWidget(self._build_blend_group())
        form.addWidget(self._build_color_group())
        form.addStretch(1)

        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.accept)
        left.addWidget(close)

        self.refresh()

    def _build_canvas_group(self) -> QGroupBox:
        """The artwork's own resolution.

        It lives here because this is the dialog where you find out what the
        projector actually is. A canvas smaller than the screen is upscaled on
        the way out and the show is soft for a reason nothing on screen
        explains.
        """
        group = QGroupBox("Canvas")
        form = QFormLayout(group)
        self.canvas_width = NoScrollSpinBox()
        self.canvas_height = NoScrollSpinBox()
        for box in (self.canvas_width, self.canvas_height):
            box.setRange(64, 16384)
            box.setSingleStep(2)
            box.setFixedWidth(84)
            box.valueChanged.connect(lambda _v: self._on_canvas_size_changed())
        form.addRow("Width", self.canvas_width)
        form.addRow("Height", self.canvas_height)

        self.match_btn = QPushButton("Match to screen")
        self.match_btn.setMinimumHeight(26)
        self.match_btn.setToolTip("Set the canvas to the selected projector's native resolution")
        self.match_btn.clicked.connect(self._on_match_canvas)
        form.addRow(self.match_btn)
        return group

    def _adopt_screen_resolution(self, output) -> None:
        """A fresh project takes its canvas from the first screen it is aimed at.

        The default 1280x720 is a placeholder nobody chose; leaving it while
        the projector reports 1920x1080 means the whole show - test pattern
        included - is composited small and upscaled on the way out. A canvas
        the operator has already set is never touched.
        """
        canvas = self._project.canvas
        if not canvas.is_default():
            return
        geometry = screen_geometry(output.screen_id)
        if geometry is None or geometry.width() < 64 or geometry.height() < 64:
            return
        canvas.width, canvas.height = geometry.width(), geometry.height()
        self._updating = True
        self.canvas_width.setValue(canvas.width)
        self.canvas_height.setValue(canvas.height)
        self._updating = False

    def _on_canvas_size_changed(self) -> None:
        if self._updating:
            return
        canvas = self._project.canvas
        width, height = int(self.canvas_width.value()), int(self.canvas_height.value())
        if (canvas.width, canvas.height) == (width, height):
            return
        self._undo_stack.push(CanvasSizeCommand(self._project, width, height))
        self.outputs_changed.emit()

    def _on_match_canvas(self) -> None:
        output = self.current_output()
        geometry = screen_geometry(output.screen_id) if output else None
        if geometry is None:
            return
        self._updating = True
        self.canvas_width.setValue(geometry.width())
        self.canvas_height.setValue(geometry.height())
        self._updating = False
        self._on_canvas_size_changed()

    # --- construction ----------------------------------------------------

    def _build_identity_group(self) -> QGroupBox:
        group = QGroupBox("Projector")
        form = QFormLayout(group)

        self.name_edit = QLineEdit()
        self.name_edit.editingFinished.connect(lambda: self._commit("Rename Output"))
        form.addRow("Name", self.name_edit)

        self.screen_combo = NoScrollComboBox()
        self.screen_combo.currentIndexChanged.connect(lambda _i: self._commit("Output Screen"))
        form.addRow("Screen", self.screen_combo)

        self.enabled_check = QCheckBox("Enabled")
        self.enabled_check.toggled.connect(lambda _v: self._commit("Enable Output"))
        form.addRow("", self.enabled_check)
        return group

    def _build_region_group(self) -> QGroupBox:
        group = QGroupBox("Canvas region")
        outer = QVBoxLayout(group)
        hint = QLabel(
            "Which part of the shared canvas this projector covers. Two "
            "projectors overlap here, and the blend below hides the seam."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(HINT_STYLE)
        outer.addWidget(hint)

        row = QHBoxLayout()
        self.region_spins: List[ArrowSpinBox] = []
        for label in ("U0", "V0", "U1", "V1"):
            box = _spin(0.0, 1.0, 0.01)
            box.valueChanged.connect(lambda _v: self._commit("Output Region"))
            row.addWidget(QLabel(label))
            row.addWidget(box)
            self.region_spins.append(box)
        row.addStretch(1)
        outer.addLayout(row)
        return group

    def _build_keystone_group(self) -> QGroupBox:
        group = QGroupBox("Keystone")
        outer = QVBoxLayout(group)
        hint = QLabel(
            "Corner positions in the projector's own frame, for squaring it "
            "against the surface. This sits above the per-surface corner pin."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(HINT_STYLE)
        outer.addWidget(hint)

        self.corner_spins: List[List[ArrowSpinBox]] = []
        for label in ("Top left", "Top right", "Bottom right", "Bottom left"):
            row = QHBoxLayout()
            name = QLabel(label)
            name.setFixedWidth(92)
            row.addWidget(name)
            pair = []
            for _axis in range(2):
                box = _spin(-1.0, 2.0, 0.005)
                box.valueChanged.connect(lambda _v: self._commit("Keystone"))
                row.addWidget(box)
                pair.append(box)
            row.addStretch(1)
            self.corner_spins.append(pair)
            outer.addLayout(row)

        reset = QPushButton("Reset keystone")
        reset.clicked.connect(self._on_reset_keystone)
        outer.addWidget(reset)
        return group

    def _build_blend_group(self) -> QGroupBox:
        group = QGroupBox("Edge blend")
        outer = QVBoxLayout(group)
        hint = QLabel(
            "Ramp widths as a fraction of this projector's frame, on the edges "
            "that meet a neighbour. Tune the exponent by eye until the seam "
            "stops showing as a bright or dark band."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(HINT_STYLE)
        outer.addWidget(hint)

        row = QHBoxLayout()
        self.blend_spins: List[ArrowSpinBox] = []
        for label in ("Left", "Right", "Top", "Bottom"):
            box = _spin(0.0, 0.5, 0.01)
            box.valueChanged.connect(lambda _v: self._commit("Edge Blend"))
            row.addWidget(QLabel(label))
            row.addWidget(box)
            self.blend_spins.append(box)
        row.addStretch(1)
        outer.addLayout(row)

        gamma_row = QHBoxLayout()
        self.blend_gamma = _spin(0.1, 6.0, 0.1, decimals=2)
        self.blend_gamma.valueChanged.connect(lambda _v: self._commit("Blend Curve"))
        gamma_row.addWidget(QLabel("Curve"))
        gamma_row.addWidget(self.blend_gamma)
        gamma_row.addStretch(1)
        outer.addLayout(gamma_row)
        return group

    def _build_color_group(self) -> QGroupBox:
        group = QGroupBox("Colour")
        outer = QVBoxLayout(group)
        hint = QLabel("Two projectors never match out of the box; pull them into line here.")
        hint.setWordWrap(True)
        hint.setStyleSheet(HINT_STYLE)
        outer.addWidget(hint)

        form = QFormLayout()
        self.brightness = _spin(-1.0, 1.0, 0.01)
        self.contrast = _spin(0.0, 4.0, 0.01)
        self.gamma = _spin(0.1, 4.0, 0.01)
        for box in (self.brightness, self.contrast, self.gamma):
            box.valueChanged.connect(lambda _v: self._commit("Output Colour"))
        form.addRow("Brightness", self.brightness)
        form.addRow("Contrast", self.contrast)
        form.addRow("Gamma", self.gamma)
        outer.addLayout(form)

        gain_row = QHBoxLayout()
        self.gain_spins: List[ArrowSpinBox] = []
        for label in ("R", "G", "B"):
            box = _spin(0.0, 4.0, 0.01)
            box.valueChanged.connect(lambda _v: self._commit("Output Colour"))
            gain_row.addWidget(QLabel(label))
            gain_row.addWidget(box)
            self.gain_spins.append(box)
        gain_row.addStretch(1)
        outer.addLayout(gain_row)
        return group

    # --- state -----------------------------------------------------------

    def current_output(self) -> Optional[Output]:
        row = self.list.currentRow()
        if 0 <= row < len(self._project.outputs):
            return self._project.outputs[row]
        return None

    def refresh(self) -> None:
        self._updating = True
        row = self.list.currentRow()
        self.list.clear()
        for output in self._project.outputs:
            screen = output.screen_id or "no screen"
            suffix = "" if output.enabled else "  (off)"
            item = QListWidgetItem(f"{output.name}  -  {screen}{suffix}")
            self.list.addItem(item)
        if self._project.outputs:
            self.list.setCurrentRow(min(max(row, 0), len(self._project.outputs) - 1))
        self._updating = False
        self._load_selected()

    def _current_output_id(self):
        output = self.current_output()
        return output.id if output is not None else None

    def _load_selected(self) -> None:
        output = self.current_output()
        self.editor.setEnabled(output is not None)
        self.output_selected.emit(output.id if output is not None else None)
        if output is None:
            return

        self._updating = True
        try:
            canvas = self._project.canvas
            self.canvas_width.setValue(canvas.width)
            self.canvas_height.setValue(canvas.height)
            self.name_edit.setText(output.name)
            self.enabled_check.setChecked(output.enabled)

            self.screen_combo.clear()
            self.screen_combo.addItem("None", None)
            for _index, screen_id, screen_name, geometry in available_screens():
                self.screen_combo.addItem(
                    f"{screen_name} ({geometry.width()}x{geometry.height()})", screen_id
                )
            found = self.screen_combo.findData(output.screen_id)
            self.screen_combo.setCurrentIndex(found if found >= 0 else 0)

            region = output.region
            for box, value in zip(self.region_spins, (region.u0, region.v0, region.u1, region.v1)):
                box.setValue(value)

            for pair, (x, y) in zip(self.corner_spins, output.corners):
                pair[0].setValue(x)
                pair[1].setValue(y)

            blend = output.blend
            for box, value in zip(self.blend_spins, (blend.left, blend.right, blend.top, blend.bottom)):
                box.setValue(value)
            self.blend_gamma.setValue(blend.gamma)

            color = output.color
            self.brightness.setValue(color.brightness)
            self.contrast.setValue(color.contrast)
            self.gamma.setValue(color.gamma)
            for box, value in zip(self.gain_spins, (color.gain_r, color.gain_g, color.gain_b)):
                box.setValue(value)
        finally:
            self._updating = False

        # Re-arm so the next edit is measured from what is on screen now.
        self._session.cancel()
        self._session.begin(output)

    def _commit(self, text: str) -> None:
        """Write the widgets back to the output as one undo step."""
        if self._updating:
            return
        output = self.current_output()
        if output is None:
            return

        output.name = self.name_edit.text() or output.name
        output.screen_id = self.screen_combo.currentData()
        self._adopt_screen_resolution(output)
        output.enabled = self.enabled_check.isChecked()
        output.region = SourceRect(*(box.value() for box in self.region_spins)).normalised()
        output.corners = [(pair[0].value(), pair[1].value()) for pair in self.corner_spins]
        output.blend.left, output.blend.right, output.blend.top, output.blend.bottom = (
            box.value() for box in self.blend_spins
        )
        output.blend.gamma = self.blend_gamma.value()
        output.color.brightness = self.brightness.value()
        output.color.contrast = self.contrast.value()
        output.color.gamma = self.gamma.value()
        output.color.gain_r, output.color.gain_g, output.color.gain_b = (
            box.value() for box in self.gain_spins
        )

        self._session.commit(self._project, text)
        self._session.begin(output)
        self._project.touch()
        self._refresh_list_labels()
        self.outputs_changed.emit()

    def _refresh_list_labels(self) -> None:
        self._updating = True
        for row, output in enumerate(self._project.outputs):
            item = self.list.item(row)
            if item is None:
                continue
            screen = output.screen_id or "no screen"
            suffix = "" if output.enabled else "  (off)"
            item.setText(f"{output.name}  -  {screen}{suffix}")
        self._updating = False

    # --- actions ---------------------------------------------------------

    def _on_add(self) -> None:
        output = Output(name=f"Projector {len(self._project.outputs) + 1}")
        self._undo_stack.push(AddOutputCommand(self._project, output))
        self.refresh()
        self.list.setCurrentRow(len(self._project.outputs) - 1)
        self.outputs_changed.emit()

    def _on_remove(self) -> None:
        output = self.current_output()
        if output is None:
            return
        self._session.cancel()
        self._undo_stack.push(RemoveOutputCommand(self._project, output.id))
        self.refresh()
        self.outputs_changed.emit()

    def _on_tile(self) -> None:
        """Lay out N projectors across the canvas, pre-overlapped."""
        self._session.cancel()
        count = self.tile_count.value()
        screens = [info[1] for info in available_screens()]

        self._undo_stack.beginMacro(f"Tile {count} Outputs")
        for existing in list(self._project.outputs):
            self._undo_stack.push(RemoveOutputCommand(self._project, existing.id))
        for index, output in enumerate(split_outputs(count)):
            if index < len(screens):
                output.screen_id = screens[index]
            self._undo_stack.push(AddOutputCommand(self._project, output))
        self._undo_stack.endMacro()

        self.refresh()
        self.outputs_changed.emit()

    def _on_reset_keystone(self) -> None:
        output = self.current_output()
        if output is None:
            return
        self._updating = True
        for pair, (x, y) in zip(self.corner_spins, [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]):
            pair[0].setValue(x)
            pair[1].setValue(y)
        self._updating = False
        self._commit("Reset Keystone")

# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QInputDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QFrame,
    QSpacerItem,
    QSizePolicy,
)

from pm.model.commands import EditSession, ShapeEditCommand
from pm.model.media import MediaRef, SourceRect
from pm.model.project import Project
from pm.model.shapes import (
    CircleShape, EdgeVisibility, MeshShape, PolygonShape, Shape, convert_shape,
    mask_from_rect, shape_to_dict,
)
from pm.ui.source_region import SourceRegionPicker
from pm.ui.widgets import ArrowSlider, ArrowSpinBox, NoScrollComboBox


class SectionHeader(QLabel):
    """A styled section header label."""
    def __init__(self, text: str, parent=None) -> None:
        super().__init__(text.upper(), parent)
        self.setStyleSheet("""
            QLabel {
                color: #505050;
                font-size: 10px;
                font-weight: 700;
                letter-spacing: 2px;
                padding: 12px 0px 6px 0px;
            }
        """)


class PropertyPanel(QWidget):
    shape_changed = Signal()

    _LABEL_DIM_STYLE = "color: #808080;"
    _CHECKBOX_DIM_STYLE = "QCheckBox { color: #a0a0a0; }"

    # (display label, serialised value)
    SHAPE_TYPES = (
        ("Polygon", "polygon"),
        ("Circle", "circle"),
        ("Mesh", "mesh"),
    )

    BLEND_MODES = (
        ("Normal", "normal"),
        ("Add", "add"),
        ("Screen", "screen"),
        ("Multiply", "multiply"),
    )

    FIT_MODES = (
        ("Stretch", "stretch"),
        ("Contain", "contain"),
        ("Cover", "cover"),
        ("Corner pin", "warp"),
    )

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._shape: Optional[Shape] = None
        self._updating = False
        self._edge_rows: List[tuple] = []
        self._mask_rows: List[tuple] = []
        self._project: Optional[Project] = None
        self._session: Optional[EditSession] = None
        self._stack = None
        self._coord_rows: List[QWidget] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(4)

        # Panel header
        title = QLabel("PROPERTIES")
        title.setObjectName("panelTitle")
        layout.addWidget(title)

        # Name section
        layout.addWidget(SectionHeader("Name"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Shape name")
        self.name_edit.editingFinished.connect(self._on_name_changed)
        layout.addWidget(self.name_edit)

        # Type. Picked before you know what the wall looks like, so it has to
        # be changeable afterwards - deleting and redrawing loses the media,
        # the fit mode and the calibration that came with the surface.
        type_row = QWidget()
        type_layout = QHBoxLayout(type_row)
        type_layout.setContentsMargins(0, 0, 0, 0)
        type_layout.setSpacing(8)
        type_label = QLabel("Type")
        type_label.setStyleSheet(PropertyPanel._LABEL_DIM_STYLE)
        self.type_combo = NoScrollComboBox()
        for label, value in PropertyPanel.SHAPE_TYPES:
            self.type_combo.addItem(label, value)
        self.type_combo.setToolTip(
            "Change the surface's type. The new shape keeps its media, colour\n"
            "and name, and lands on the old one's bounding box."
        )
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        type_layout.addWidget(type_label)
        type_layout.addWidget(self.type_combo, 1)
        layout.addWidget(type_row)

        # Appearance section
        layout.addWidget(SectionHeader("Appearance"))

        # Fill color
        fill_row = QWidget()
        fill_layout = QHBoxLayout(fill_row)
        fill_layout.setContentsMargins(0, 0, 0, 0)
        fill_layout.setSpacing(8)
        fill_label = QLabel("Fill")
        fill_label.setStyleSheet(PropertyPanel._LABEL_DIM_STYLE)
        self.fill_button = QPushButton()
        self.fill_button.setFixedHeight(28)
        self.fill_button.setObjectName("colorButton")
        self.fill_button.clicked.connect(lambda: self._pick_color("fill"))
        fill_layout.addWidget(fill_label)
        fill_layout.addWidget(self.fill_button, 1)
        layout.addWidget(fill_row)

        # Stroke color
        stroke_row = QWidget()
        stroke_layout = QHBoxLayout(stroke_row)
        stroke_layout.setContentsMargins(0, 0, 0, 0)
        stroke_layout.setSpacing(8)
        stroke_label = QLabel("Stroke")
        stroke_label.setStyleSheet(PropertyPanel._LABEL_DIM_STYLE)
        self.stroke_button = QPushButton()
        self.stroke_button.setFixedHeight(28)
        self.stroke_button.setObjectName("colorButton")
        self.stroke_button.clicked.connect(lambda: self._pick_color("stroke"))
        stroke_layout.addWidget(stroke_label)
        stroke_layout.addWidget(self.stroke_button, 1)
        layout.addWidget(stroke_row)

        # Stroke width
        width_row = QWidget()
        width_layout = QHBoxLayout(width_row)
        width_layout.setContentsMargins(0, 0, 0, 0)
        width_layout.setSpacing(8)
        width_label = QLabel("Stroke Width")
        width_label.setStyleSheet(PropertyPanel._LABEL_DIM_STYLE)
        self.stroke_width = ArrowSpinBox()
        self.stroke_width.setRange(0.0, 50.0)
        self.stroke_width.setSingleStep(0.5)
        self.stroke_width.setFixedWidth(80)
        self.stroke_width.valueChanged.connect(self._on_stroke_width_changed)
        width_layout.addWidget(width_label)
        width_layout.addStretch(1)
        width_layout.addWidget(self.stroke_width)
        layout.addWidget(width_row)

        # Opacity
        opacity_row = QWidget()
        opacity_layout = QHBoxLayout(opacity_row)
        opacity_layout.setContentsMargins(0, 0, 0, 0)
        opacity_layout.setSpacing(8)
        opacity_label = QLabel("Opacity")
        opacity_label.setStyleSheet(PropertyPanel._LABEL_DIM_STYLE)
        self.opacity_slider = ArrowSlider(Qt.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)
        self.opacity_value = QLabel("100%")
        self.opacity_value.setStyleSheet("color: #00d4aa; font-weight: 600; min-width: 40px;")
        self.opacity_value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        opacity_layout.addWidget(opacity_label)
        opacity_layout.addWidget(self.opacity_slider, 1)
        opacity_layout.addWidget(self.opacity_value)
        layout.addWidget(opacity_row)

        # Blend mode. Projected light adds: two beams on the same wall sum
        # rather than one replacing the other, which is what Add and Screen
        # are for. The field has been in the file format since the beginning.
        blend_row = QWidget()
        blend_layout = QHBoxLayout(blend_row)
        blend_layout.setContentsMargins(0, 0, 0, 0)
        blend_layout.setSpacing(8)
        blend_label = QLabel("Blend")
        blend_label.setStyleSheet(PropertyPanel._LABEL_DIM_STYLE)
        self.blend_mode = NoScrollComboBox()
        for label, value in PropertyPanel.BLEND_MODES:
            self.blend_mode.addItem(label, value)
        self.blend_mode.currentIndexChanged.connect(self._on_blend_mode_changed)
        blend_layout.addWidget(blend_label)
        blend_layout.addWidget(self.blend_mode, 1)
        layout.addWidget(blend_row)

        # The model has honoured `locked` in the canvas all along; there was
        # simply no way to switch it on.
        self.lock_check = QCheckBox("Lock shape")
        self.lock_check.setStyleSheet(PropertyPanel._CHECKBOX_DIM_STYLE)
        self.lock_check.setToolTip("Stop this surface being moved or reshaped once it is calibrated.")
        self.lock_check.toggled.connect(self._on_lock_toggled)
        layout.addWidget(self.lock_check)

        # Edges section (for polygons)
        self.edges_group = QGroupBox("Edges")
        self.edges_layout = QVBoxLayout(self.edges_group)
        self.edges_layout.setContentsMargins(8, 8, 8, 8)
        self.edges_layout.setSpacing(4)
        layout.addWidget(self.edges_group)

        # Masks: the holes a surface does not project into - a window, a
        # doorway, a pillar standing in front of the wall.
        self.masks_group = QGroupBox("Masks")
        masks_outer = QVBoxLayout(self.masks_group)
        masks_outer.setContentsMargins(8, 8, 8, 8)
        masks_outer.setSpacing(4)
        self.masks_layout = QVBoxLayout()
        self.masks_layout.setContentsMargins(0, 0, 0, 0)
        self.masks_layout.setSpacing(4)
        masks_outer.addLayout(self.masks_layout)
        mask_buttons = QHBoxLayout()
        self.add_mask_btn = QPushButton("+ Mask")
        self.add_mask_btn.setToolTip("Cut a hole in this surface; drag the red corners on the canvas")
        self.remove_mask_btn = QPushButton("- Mask")
        self.add_mask_btn.clicked.connect(self._on_add_mask)
        self.remove_mask_btn.clicked.connect(self._on_remove_mask)
        mask_buttons.addWidget(self.add_mask_btn)
        mask_buttons.addWidget(self.remove_mask_btn)
        masks_outer.addLayout(mask_buttons)
        layout.addWidget(self.masks_group)

        # Points section (for circles/polygons)
        self.points_group = QGroupBox("Points")
        points_layout = QVBoxLayout(self.points_group)
        points_layout.setContentsMargins(8, 8, 8, 8)
        points_layout.setSpacing(6)

        # Mesh density. Coarse grids are easier to place; fine grids follow a
        # tighter curve. Changing it resamples the existing surface rather
        # than resetting it, so detail can be added late without losing work.
        self.mesh_row = QWidget()
        mesh_layout = QHBoxLayout(self.mesh_row)
        mesh_layout.setContentsMargins(0, 0, 0, 0)
        mesh_layout.setSpacing(6)
        rows_label = QLabel("Rows")
        rows_label.setStyleSheet(PropertyPanel._LABEL_DIM_STYLE)
        cols_label = QLabel("Cols")
        cols_label.setStyleSheet(PropertyPanel._LABEL_DIM_STYLE)
        self.mesh_rows = ArrowSpinBox()
        self.mesh_cols = ArrowSpinBox()
        for box in (self.mesh_rows, self.mesh_cols):
            box.setRange(1, 12)
            box.setDecimals(0)
            box.setSingleStep(1.0)
            box.setFixedWidth(64)
            box.setFixedHeight(24)
            box.valueChanged.connect(self._on_mesh_grid_changed)
        mesh_layout.addWidget(rows_label)
        mesh_layout.addWidget(self.mesh_rows)
        mesh_layout.addWidget(cols_label)
        mesh_layout.addWidget(self.mesh_cols)
        mesh_layout.addStretch(1)
        points_layout.addWidget(self.mesh_row)

        polygon_buttons = QHBoxLayout()
        self.add_vertex_btn = QPushButton("+ Vertex")
        self.remove_vertex_btn = QPushButton("- Vertex")
        self.add_vertex_btn.clicked.connect(self._on_add_vertex)
        self.remove_vertex_btn.clicked.connect(self._on_remove_vertex)
        polygon_buttons.addWidget(self.add_vertex_btn)
        polygon_buttons.addWidget(self.remove_vertex_btn)
        points_layout.addLayout(polygon_buttons)

        # Typed coordinates. Dragging is not reproducible: rebuilding a
        # mapping in another venue, or matching a wall measured with a tape,
        # needs numbers.
        self.coords_layout = QVBoxLayout()
        self.coords_layout.setContentsMargins(0, 6, 0, 0)
        self.coords_layout.setSpacing(4)
        points_layout.addLayout(self.coords_layout)

        # The panel lives in a scroll area with widgetResizable(True), which
        # squeezes children that are willing to shrink. Groups that grow with
        # the vertex count must refuse, so the scroll bar appears instead of
        # the rows collapsing into slivers.
        for group in (self.edges_group, self.points_group):
            group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)

        layout.addWidget(self.points_group)

        # Media section
        layout.addWidget(SectionHeader("Media"))

        self.media_group = QWidget()
        media_layout = QVBoxLayout(self.media_group)
        media_layout.setContentsMargins(0, 0, 0, 0)
        media_layout.setSpacing(8)

        self.media_label = QLabel("No media assigned")
        self.media_label.setWordWrap(True)
        self.media_label.setStyleSheet("color: #606060; font-style: italic;")
        media_layout.addWidget(self.media_label)

        media_buttons = QHBoxLayout()
        self.load_image_btn = QPushButton("Image")
        self.load_video_btn = QPushButton("Video")
        self.clear_media_btn = QPushButton("Clear")
        self.load_image_btn.clicked.connect(lambda: self._pick_media("image"))
        self.load_video_btn.clicked.connect(lambda: self._pick_media("video"))
        self.clear_media_btn.clicked.connect(self._clear_media)
        self.load_camera_btn = QPushButton("Camera")
        self.load_camera_btn.setToolTip("Use a capture device as this surface's source")
        self.load_camera_btn.clicked.connect(lambda: self._pick_media("camera"))
        media_buttons.addWidget(self.load_image_btn)
        media_buttons.addWidget(self.load_video_btn)
        media_buttons.addWidget(self.load_camera_btn)
        self._build_playback_group(media_layout)
        media_buttons.addWidget(self.clear_media_btn)
        media_layout.addLayout(media_buttons)

        fit_row = QWidget()
        fit_layout = QHBoxLayout(fit_row)
        fit_layout.setContentsMargins(0, 0, 0, 0)
        fit_layout.setSpacing(8)
        fit_label = QLabel("Fit Mode")
        fit_label.setStyleSheet(PropertyPanel._LABEL_DIM_STYLE)
        self.fit_mode = NoScrollComboBox()
        # Labels are for humans, userData is what gets serialised - renaming
        # the display text must not invalidate existing .pmap.json files.
        for label, value in self.FIT_MODES:
            self.fit_mode.addItem(label, value)
        self.fit_mode.setFixedWidth(110)
        self.fit_mode.currentIndexChanged.connect(self._on_fit_mode_changed)
        fit_layout.addWidget(fit_label)
        fit_layout.addStretch(1)
        fit_layout.addWidget(self.fit_mode)
        media_layout.addWidget(fit_row)

        self.reset_corners_btn = QPushButton("Reset Corners")
        self.reset_corners_btn.setToolTip(
            "Snap the four corners back to an upright rectangle.\n"
            "Use this when a quad has been dragged over itself."
        )
        self.reset_corners_btn.clicked.connect(self._on_reset_corners)
        media_layout.addWidget(self.reset_corners_btn)

        media_layout.addWidget(SectionHeader("Source region"))
        self.source_hint = QLabel(
            "Which part of the media feeds this surface. Drag the box; corners resize."
        )
        self.source_hint.setWordWrap(True)
        self.source_hint.setStyleSheet("color: #606060; font-size: 11px;")
        media_layout.addWidget(self.source_hint)

        self.source_picker = SourceRegionPicker()
        self.source_picker.region_changed.connect(self._on_source_region_preview)
        self.source_picker.region_committed.connect(self._on_source_region_committed)
        media_layout.addWidget(self.source_picker)

        # Two rows of two. Four label/box pairs on one line do not fit the
        # panel's width, and the labels end up drawn over the boxes.
        self.source_spins = []
        for pair in (("U0", "V0"), ("U1", "V1")):
            source_row = QWidget()
            source_row.setFixedHeight(28)
            source_layout = QHBoxLayout(source_row)
            source_layout.setContentsMargins(0, 0, 0, 0)
            source_layout.setSpacing(6)
            for label_text in pair:
                label = QLabel(label_text)
                label.setStyleSheet(PropertyPanel._LABEL_DIM_STYLE)
                label.setFixedWidth(22)
                spin = ArrowSpinBox()
                spin.setRange(0.0, 1.0)
                spin.setDecimals(3)
                spin.setSingleStep(0.01)
                spin.setFixedWidth(72)
                spin.setFixedHeight(24)
                spin.valueChanged.connect(self._on_source_spin_changed)
                source_layout.addWidget(label)
                source_layout.addWidget(spin)
                self.source_spins.append(spin)
            source_layout.addStretch(1)
            media_layout.addWidget(source_row)

        self.reset_source_btn = QPushButton("Use Full Frame")
        self.reset_source_btn.clicked.connect(self._on_reset_source_region)
        media_layout.addWidget(self.reset_source_btn)

        media_layout.addWidget(self._create_transform_section())
        layout.addWidget(self.media_group)

        # Effects section
        layout.addWidget(SectionHeader("Effects"))

        self.effects_group = QWidget()
        effects_layout = QVBoxLayout(self.effects_group)
        effects_layout.setContentsMargins(0, 0, 0, 0)
        effects_layout.setSpacing(8)

        # RGB Shift
        self.rgb_enable = QCheckBox("RGB Shift")
        self.rgb_enable.setStyleSheet(PropertyPanel._CHECKBOX_DIM_STYLE)
        self.rgb_enable.stateChanged.connect(self._on_effects_changed)
        effects_layout.addWidget(self.rgb_enable)

        rgb_params = QWidget()
        rgb_layout = QHBoxLayout(rgb_params)
        rgb_layout.setContentsMargins(20, 0, 0, 0)
        rgb_layout.setSpacing(8)
        self.rgb_amount = ArrowSpinBox()
        self.rgb_amount.setRange(0.0, 10.0)
        self.rgb_amount.setSingleStep(0.1)
        self.rgb_amount.setFixedWidth(60)
        self.rgb_amount.valueChanged.connect(self._on_effects_changed)
        self.rgb_speed = ArrowSpinBox()
        self.rgb_speed.setRange(0.1, 10.0)
        self.rgb_speed.setSingleStep(0.1)
        self.rgb_speed.setFixedWidth(60)
        self.rgb_speed.valueChanged.connect(self._on_effects_changed)
        rgb_layout.addWidget(QLabel("Amt"))
        rgb_layout.addWidget(self.rgb_amount)
        rgb_layout.addWidget(QLabel("Spd"))
        rgb_layout.addWidget(self.rgb_speed)
        rgb_layout.addStretch(1)
        effects_layout.addWidget(rgb_params)

        # Pulse
        self.pulse_enable = QCheckBox("Pulse")
        self.pulse_enable.setStyleSheet(PropertyPanel._CHECKBOX_DIM_STYLE)
        self.pulse_enable.stateChanged.connect(self._on_effects_changed)
        effects_layout.addWidget(self.pulse_enable)

        pulse_params = QWidget()
        pulse_layout = QHBoxLayout(pulse_params)
        pulse_layout.setContentsMargins(20, 0, 0, 0)
        pulse_layout.setSpacing(8)
        self.pulse_amount = ArrowSpinBox()
        self.pulse_amount.setRange(0.0, 2.0)
        self.pulse_amount.setSingleStep(0.05)
        self.pulse_amount.setFixedWidth(60)
        self.pulse_amount.valueChanged.connect(self._on_effects_changed)
        self.pulse_speed = ArrowSpinBox()
        self.pulse_speed.setRange(0.1, 10.0)
        self.pulse_speed.setSingleStep(0.1)
        self.pulse_speed.setFixedWidth(60)
        self.pulse_speed.valueChanged.connect(self._on_effects_changed)
        pulse_layout.addWidget(QLabel("Amt"))
        pulse_layout.addWidget(self.pulse_amount)
        pulse_layout.addWidget(QLabel("Spd"))
        pulse_layout.addWidget(self.pulse_speed)
        pulse_layout.addStretch(1)
        effects_layout.addWidget(pulse_params)

        # Strobe
        self.strobe_enable = QCheckBox("Strobe")
        self.strobe_enable.setStyleSheet(PropertyPanel._CHECKBOX_DIM_STYLE)
        self.strobe_enable.stateChanged.connect(self._on_effects_changed)
        effects_layout.addWidget(self.strobe_enable)

        strobe_params = QWidget()
        strobe_layout = QHBoxLayout(strobe_params)
        strobe_layout.setContentsMargins(20, 0, 0, 0)
        strobe_layout.setSpacing(8)
        self.strobe_hz = ArrowSpinBox()
        self.strobe_hz.setRange(0.1, 30.0)
        self.strobe_hz.setSingleStep(0.5)
        self.strobe_hz.setFixedWidth(60)
        self.strobe_hz.valueChanged.connect(self._on_effects_changed)
        strobe_layout.addWidget(QLabel("Hz"))
        strobe_layout.addWidget(self.strobe_hz)
        strobe_layout.addStretch(1)
        effects_layout.addWidget(strobe_params)

        layout.addWidget(self.effects_group)
        layout.addStretch(1)

    def _create_transform_section(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(6)

        self.offset_x = ArrowSpinBox()
        self.offset_x.setRange(-9999, 9999)
        self.offset_x.setSingleStep(5.0)
        self.offset_x.valueChanged.connect(self._on_transform_changed)

        self.offset_y = ArrowSpinBox()
        self.offset_y.setRange(-9999, 9999)
        self.offset_y.setSingleStep(5.0)
        self.offset_y.valueChanged.connect(self._on_transform_changed)

        self.rotation = ArrowSpinBox()
        self.rotation.setRange(-180, 180)
        self.rotation.setSingleStep(1.0)
        self.rotation.valueChanged.connect(self._on_transform_changed)

        layout.addRow("Offset X", self.offset_x)
        layout.addRow("Offset Y", self.offset_y)
        layout.addRow("Rotation", self.rotation)

        return widget

    def _wrap_row(self, label: str, widget: QWidget) -> QWidget:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)
        label_widget = QLabel(label)
        label_widget.setStyleSheet(PropertyPanel._LABEL_DIM_STYLE)
        row_layout.addWidget(label_widget)
        row_layout.addStretch(1)
        row_layout.addWidget(widget)
        return row

    def set_shape(self, shape: Optional[Shape]) -> None:
        self._shape = shape
        # Re-arm against the new shape; any half-open session belonged to the
        # previous one and must not be attributed to this edit.
        if self._session is not None:
            self._session.cancel()
            self._session.begin(shape)
        self._updating = True
        if not shape:
            # Actually blank it. Greying the panel out while it still showed
            # the deleted surface's name, colours and coordinates read as "this
            # is still here, just not editable", which is the opposite of true.
            self.setEnabled(False)
            self.name_edit.clear()
            self.type_combo.setCurrentIndex(-1)
            self._clear_coord_rows()
            self._populate_edges(None)
            self._populate_masks(None)
            self.edges_group.setVisible(False)
            self.masks_group.setVisible(False)
            self.points_group.setVisible(False)
            self._update_media(None)
            self._sync_playback(None)
            self.source_picker.set_media(None, None, media=None)
            self._updating = False
            self.updateGeometry()
            return
        self.setEnabled(True)
        self.name_edit.setText(shape.name)
        index = self.type_combo.findData(shape.type)
        self.type_combo.setCurrentIndex(index if index >= 0 else -1)
        self._apply_button_color(self.fill_button, shape.fill_color)
        self._apply_button_color(self.stroke_button, shape.stroke_color)
        self.stroke_width.setValue(shape.stroke_width)
        self.opacity_slider.setValue(int(shape.opacity * 100))
        self.opacity_value.setText(f"{int(shape.opacity * 100)}%")
        self.lock_check.setChecked(bool(shape.locked))
        blend_index = self.blend_mode.findData(shape.blend_mode or "normal")
        self.blend_mode.setCurrentIndex(blend_index if blend_index >= 0 else 0)
        self._populate_edges(shape)
        self._populate_masks(shape)
        self._update_point_controls(shape)
        self._populate_coords(shape)
        self._update_media(shape.media)
        self._sync_playback(shape.media)
        self._select_fit_mode(shape.media.fit_mode if shape.media else "stretch")
        self._update_corner_pin_controls()
        self._sync_source_region(shape)
        if shape.media:
            self.offset_x.setValue(shape.media.transform.offset_x)
            self.offset_y.setValue(shape.media.transform.offset_y)
            self.rotation.setValue(shape.media.transform.rotation)
        self.rgb_enable.setChecked(shape.effects.rgb_shift.enabled)
        self.rgb_amount.setValue(shape.effects.rgb_shift.amount)
        self.rgb_speed.setValue(shape.effects.rgb_shift.speed)
        self.pulse_enable.setChecked(shape.effects.pulse.enabled)
        self.pulse_amount.setValue(shape.effects.pulse.amount)
        self.pulse_speed.setValue(shape.effects.pulse.speed)
        self.strobe_enable.setChecked(shape.effects.strobe.enabled)
        self.strobe_hz.setValue(shape.effects.strobe.hz)
        self._updating = False

    def set_undo_context(self, project: Project, stack) -> None:
        self._project = project
        self._stack = stack
        self._session = EditSession(stack)
        self._session.begin(self._shape)

    def _commit(self, text: str) -> None:
        """Record the edit as one undo step, then re-arm for the next one.

        Sliders fire continuously; ShapeEditCommand merges same-labelled edits
        to the same shape inside a short window, so a slider drag collapses
        into a single entry.
        """
        if self._session is not None and self._project is not None:
            self._session.commit(self._project, text)
            # The command restores the shape from a snapshot, which puts a
            # *new* object in the project. Re-point at it before re-arming, or
            # every edit after the first one writes to an orphan.
            if self._shape is not None:
                current = self._project.get_shape(self._shape.id)
                if current is not None:
                    self._shape = current
            self._session.begin(self._shape)
        self.shape_changed.emit()

    def _populate_edges(self, shape: Shape) -> None:
        for i in reversed(range(self.edges_layout.count())):
            item = self.edges_layout.takeAt(i)
            widget = item.widget() if item else None
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._edge_rows.clear()
        if not isinstance(shape, PolygonShape):
            self.edges_group.setVisible(False)
            return
        self.edges_group.setVisible(True)
        shape.ensure_edges()
        for idx, edge in enumerate(shape.edges):
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            label = QLabel(f"Edge {idx + 1}")
            label.setStyleSheet(PropertyPanel._LABEL_DIM_STYLE)
            checkbox = QCheckBox()
            checkbox.setChecked(edge.visible)
            slider = ArrowSlider(Qt.Horizontal)
            slider.setRange(0, 100)
            slider.setValue(int(edge.percent * 100))
            # The discoverable way in to a curved edge; the fast way is
            # Alt+double-click on the edge itself.
            curve = QCheckBox("Curve")
            curve.setChecked(edge.curved)
            curve.setToolTip("Bend this edge; drag the amber controls on the canvas")
            checkbox.stateChanged.connect(lambda state, i=idx: self._on_edge_visible(i, state))
            slider.valueChanged.connect(lambda value, i=idx: self._on_edge_percent(i, value))
            curve.stateChanged.connect(lambda state, i=idx: self._on_edge_curved(i, state))
            row_layout.addWidget(checkbox)
            row_layout.addWidget(label)
            row_layout.addWidget(slider, 1)
            row_layout.addWidget(curve)
            self.edges_layout.addWidget(row)
            self._edge_rows.append((checkbox, slider, curve))
        self.updateGeometry()

    def _clear_coord_rows(self) -> None:
        for i in reversed(range(self.coords_layout.count())):
            item = self.coords_layout.takeAt(i)
            widget = item.widget() if item else None
            if widget is not None:
                # Unparent now, not just deleteLater: until the event loop
                # gets around to the deletion the widget is still a visible
                # child, and having left the layout it keeps its old geometry
                # and paints on top of whatever moved into that space.
                widget.setParent(None)
                widget.deleteLater()
        self._coord_rows.clear()

    def _coord_spin(self, value: float) -> ArrowSpinBox:
        spin = ArrowSpinBox()
        # Room for surfaces parked well outside the canvas while being built.
        spin.setRange(-99999.0, 99999.0)
        spin.setDecimals(1)
        spin.setSingleStep(1.0)
        spin.setValue(float(value))
        spin.setFixedWidth(76)
        # Without an explicit height these rows get squeezed to a few pixels
        # when the Points group runs short of vertical space.
        spin.setFixedHeight(24)
        return spin

    def _populate_coords(self, shape: Shape) -> None:
        """One editable X/Y row per vertex, or centre/radius for a circle."""
        self._clear_coord_rows()

        if isinstance(shape, MeshShape):
            # A 4x4 grid is 25 rows of boxes - the canvas handles are the
            # usable way in, and the density control is what belongs here.
            self.updateGeometry()
            return

        if isinstance(shape, PolygonShape):
            for idx, (x, y) in enumerate(shape.points):
                row = QWidget()
                row.setFixedHeight(28)
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.setSpacing(6)
                label = QLabel(f"V{idx + 1}")
                label.setStyleSheet(PropertyPanel._LABEL_DIM_STYLE)
                label.setFixedWidth(28)
                x_spin = self._coord_spin(x)
                y_spin = self._coord_spin(y)
                x_spin.valueChanged.connect(lambda v, i=idx: self._on_vertex_coord(i, 0, v))
                y_spin.valueChanged.connect(lambda v, i=idx: self._on_vertex_coord(i, 1, v))
                row_layout.addWidget(label)
                row_layout.addWidget(x_spin)
                row_layout.addWidget(y_spin)
                row_layout.addStretch(1)
                self.coords_layout.addWidget(row)
                self._coord_rows.append(row)

        elif isinstance(shape, CircleShape):
            for label_text, value, setter in (
                ("X", shape.center[0], "center_x"),
                ("Y", shape.center[1], "center_y"),
                ("RX", shape.radius_x, "radius_x"),
                ("RY", shape.radius_y, "radius_y"),
            ):
                spin = self._coord_spin(value)
                spin.valueChanged.connect(lambda v, f=setter: self._on_circle_geometry(f, v))
                row = self._wrap_row(label_text, spin)
                self.coords_layout.addWidget(row)
                self._coord_rows.append(row)

        # These rows appear and disappear with the vertex count, and the
        # enclosing scroll area only re-reads the size hint when told to.
        # Without this it keeps the height from before the rows existed and
        # clips them.
        self.updateGeometry()

    def refresh_geometry(self) -> None:
        """Pull coordinates back from the model after a canvas-side edit.

        Without this the spin boxes keep showing where a vertex used to be
        the moment the user drags it.
        """
        shape = self._shape
        if shape is None:
            return

        # Undo restores a shape from a snapshot rather than mutating it, so
        # the object this panel is holding can be an orphan by now. Editing
        # an orphan writes to nothing the project will ever read.
        if self._project is not None:
            current = self._project.get_shape(shape.id)
            if current is not None and current is not shape:
                self.set_shape(current)
                return

        if isinstance(shape, MeshShape):
            return
        expected = len(shape.points) if isinstance(shape, PolygonShape) else 4
        if len(self._coord_rows) != expected:
            self._updating = True
            self._populate_coords(shape)
            self._updating = False
            return

        self._updating = True
        try:
            if isinstance(shape, PolygonShape):
                for row, (x, y) in zip(self._coord_rows, shape.points):
                    spins = row.findChildren(ArrowSpinBox)
                    if len(spins) == 2:
                        spins[0].setValue(float(x))
                        spins[1].setValue(float(y))
            elif isinstance(shape, CircleShape):
                values = (shape.center[0], shape.center[1], shape.radius_x, shape.radius_y)
                for row, value in zip(self._coord_rows, values):
                    spins = row.findChildren(ArrowSpinBox)
                    if spins:
                        spins[0].setValue(float(value))
        finally:
            self._updating = False

    def _on_vertex_coord(self, index: int, axis: int, value: float) -> None:
        if self._updating or not isinstance(self._shape, PolygonShape):
            return
        if index >= len(self._shape.points):
            return
        point = list(self._shape.points[index])
        if point[axis] == value:
            return
        point[axis] = float(value)
        points = list(self._shape.points)
        points[index] = (point[0], point[1])
        self._shape.points = points
        self._commit("Set Vertex")

    # --- source region ---------------------------------------------------

    def _sync_source_region(self, shape: Shape) -> None:
        media = shape.media
        region = media.source_rect.normalised()
        self.source_picker.set_media(
            media.path if media.kind == "image" else "", region, media=media
        )
        self.source_picker._transport = self._project.transport if self._project else None
        for spin, value in zip(self.source_spins, (region.u0, region.v0, region.u1, region.v1)):
            spin.setValue(value)
        # Video and camera feeds are previewable now that decoders are shared,
        # so the region can be aimed by eye instead of typed blind.
        previewable = media.kind in ("image", "video", "camera")
        self.source_picker.setVisible(previewable)
        self.source_hint.setVisible(previewable)

    def _apply_source_region(self, region: SourceRect, commit: bool) -> None:
        if self._updating or not self._shape:
            return
        if not self._shape.media:
            self._shape.media = MediaRef()

        region = region.normalised()
        self._shape.media.source_rect = region

        self._updating = True
        for spin, value in zip(self.source_spins, (region.u0, region.v0, region.u1, region.v1)):
            spin.setValue(value)
        self._updating = False

        if commit:
            self._commit("Source Region")
        else:
            # Live feedback while dragging; the undo entry waits for release,
            # exactly like a drag on the canvas.
            self.shape_changed.emit()

    def _on_source_region_preview(self, region: SourceRect) -> None:
        self._apply_source_region(region, commit=False)

    def _on_source_region_committed(self, region: SourceRect) -> None:
        self._apply_source_region(region, commit=True)

    def _on_source_spin_changed(self, _value: float) -> None:
        if self._updating or not self._shape:
            return
        region = SourceRect(*(spin.value() for spin in self.source_spins))
        self._apply_source_region(region, commit=True)
        self.source_picker.set_media(
            self._shape.media.path if self._shape.media.kind == "image" else "",
            self._shape.media.source_rect,
        )

    def _on_reset_source_region(self) -> None:
        self._apply_source_region(SourceRect(), commit=True)
        if self._shape:
            self.source_picker.set_media(
                self._shape.media.path if self._shape.media.kind == "image" else "",
                self._shape.media.source_rect,
            )

    def _on_mesh_grid_changed(self, _value: float) -> None:
        if self._updating or not isinstance(self._shape, MeshShape):
            return
        rows, cols = int(self.mesh_rows.value()), int(self.mesh_cols.value())
        if (rows, cols) == (self._shape.rows, self._shape.cols):
            return
        self._shape.resize_grid(rows, cols)
        self._populate_coords(self._shape)
        self._commit("Mesh Density")

    def _build_playback_group(self, parent_layout) -> None:
        """How this surface's clip runs against the show clock.

        Per surface rather than per file: the same video is a looping backdrop
        on one wall and a one-shot sting on another. Two surfaces whose
        settings match share a decoder and stay frame-accurate against each
        other, which is how synchronisation is spelled here.
        """
        self.playback_group = QGroupBox("Playback")
        form = QFormLayout(self.playback_group)

        self.loop_check = QCheckBox("Loop")
        self.loop_check.setToolTip("Restart the clip when it ends")
        self.loop_check.toggled.connect(lambda _v: self._commit_playback("Loop"))
        form.addRow("", self.loop_check)

        self.hold_check = QCheckBox("Hold last frame")
        self.hold_check.setToolTip(
            "When a one-shot clip ends, keep its last frame up.\n"
            "Going black mid-show is a failure the audience sees."
        )
        self.hold_check.toggled.connect(lambda _v: self._commit_playback("Hold Last Frame"))
        form.addRow("", self.hold_check)

        self.clip_speed = ArrowSpinBox()
        self.clip_speed.setRange(0.05, 4.0)
        self.clip_speed.setSingleStep(0.05)
        self.clip_speed.setDecimals(2)
        self.clip_speed.setFixedWidth(80)
        self.clip_speed.setToolTip("This clip's rate, on top of the show's own speed")
        self.clip_speed.valueChanged.connect(lambda _v: self._commit_playback("Clip Speed"))
        form.addRow("Speed", self.clip_speed)

        self.clip_start = ArrowSpinBox()
        self.clip_start.setRange(-3600.0, 3600.0)
        self.clip_start.setSingleStep(0.5)
        self.clip_start.setDecimals(2)
        self.clip_start.setFixedWidth(80)
        self.clip_start.setToolTip(
            "Where show time zero lands in this clip, in seconds.\n"
            "Negative delays the clip; positive skips into it."
        )
        self.clip_start.valueChanged.connect(lambda _v: self._commit_playback("Clip Start"))
        form.addRow("Offset", self.clip_start)

        parent_layout.addWidget(self.playback_group)

    def _commit_playback(self, label: str) -> None:
        if self._updating or not self._shape or not self._shape.media:
            return
        playback = self._shape.media.playback
        playback.loop = self.loop_check.isChecked()
        playback.hold_last = self.hold_check.isChecked()
        playback.speed = float(self.clip_speed.value())
        playback.start = float(self.clip_start.value())
        self._commit(label)

    def _sync_playback(self, media) -> None:
        # Only a clip has a timeline. A still or a live feed has nothing here
        # to set, and showing the controls anyway invites the operator to set
        # something that will be ignored.
        timed = bool(media and media.is_timed)
        self.playback_group.setVisible(timed)
        if not timed:
            return
        playback = media.playback
        self.loop_check.setChecked(playback.loop)
        self.hold_check.setChecked(playback.hold_last)
        self.hold_check.setEnabled(not playback.loop)
        self.clip_speed.setValue(playback.speed)
        self.clip_start.setValue(playback.start)

    def _on_blend_mode_changed(self, _index: int) -> None:
        if self._updating or not self._shape:
            return
        mode = self.blend_mode.currentData() or "normal"
        if mode == self._shape.blend_mode:
            return
        self._shape.blend_mode = mode
        self._commit("Blend Mode")

    def _on_lock_toggled(self, checked: bool) -> None:
        if self._updating or not self._shape:
            return
        if self._shape.locked == checked:
            return
        self._shape.locked = bool(checked)
        self._commit("Lock" if checked else "Unlock")

    def _on_circle_geometry(self, field: str, value: float) -> None:
        if self._updating or not isinstance(self._shape, CircleShape):
            return
        cx, cy = self._shape.center
        if field == "center_x":
            self._shape.center = (float(value), cy)
        elif field == "center_y":
            self._shape.center = (cx, float(value))
        elif field == "radius_x":
            self._shape.radius_x = max(1.0, float(value))
        elif field == "radius_y":
            self._shape.radius_y = max(1.0, float(value))
        self._commit("Set Circle Geometry")

    def _update_point_controls(self, shape: Shape) -> None:
        self.mesh_row.setVisible(isinstance(shape, MeshShape))
        if isinstance(shape, MeshShape):
            self.points_group.setVisible(True)
            self.add_vertex_btn.setEnabled(False)
            self.remove_vertex_btn.setEnabled(False)
            self._updating = True
            self.mesh_rows.setValue(shape.rows)
            self.mesh_cols.setValue(shape.cols)
            self._updating = False
        elif isinstance(shape, CircleShape):
            # Circles are edited through the four axis handles and the
            # RX/RY boxes; there are no vertices to add or remove.
            self.points_group.setVisible(True)
            self.add_vertex_btn.setEnabled(False)
            self.remove_vertex_btn.setEnabled(False)
        elif isinstance(shape, PolygonShape):
            self.points_group.setVisible(True)
            self.add_vertex_btn.setEnabled(True)
            self.remove_vertex_btn.setEnabled(True)
        else:
            self.points_group.setVisible(False)

    def _apply_button_color(self, button: QPushButton, rgba: List[int]) -> None:
        color = QColor(*rgba)
        button.setStyleSheet(f"""
            QPushButton {{
                background-color: {color.name()};
                border: 2px solid #2a2a2e;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                border-color: #3a3a3e;
            }}
        """)

    def _pick_color(self, target: str) -> None:
        if not self._shape:
            return
        initial = QColor(*(self._shape.fill_color if target == "fill" else self._shape.stroke_color))
        color = QColorDialog.getColor(initial, self, "Select Color")
        if not color.isValid():
            return
        rgba = [color.red(), color.green(), color.blue(), color.alpha()]
        if target == "fill":
            self._shape.fill_color = rgba
            self._apply_button_color(self.fill_button, rgba)
        else:
            self._shape.stroke_color = rgba
            self._apply_button_color(self.stroke_button, rgba)
        self._commit("Change Colour")

    def _on_name_changed(self) -> None:
        if self._updating or not self._shape:
            return
        self._shape.name = self.name_edit.text().strip() or self._shape.name
        self._commit("Rename Shape")

    def _on_stroke_width_changed(self, value: float) -> None:
        if self._updating or not self._shape:
            return
        self._shape.stroke_width = float(value)
        self._commit("Stroke Width")

    def _on_opacity_changed(self, value: int) -> None:
        if self._updating or not self._shape:
            return
        self._shape.opacity = float(value) / 100.0
        self.opacity_value.setText(f"{value}%")
        self._commit("Opacity")

    def _on_edge_visible(self, idx: int, state: int) -> None:
        if self._updating or not isinstance(self._shape, PolygonShape):
            return
        self._shape.ensure_edges()
        self._shape.edges[idx].visible = state == Qt.Checked.value
        self._commit("Edge Visibility")

    def _on_edge_percent(self, idx: int, value: float) -> None:
        if self._updating or not isinstance(self._shape, PolygonShape):
            return
        self._shape.ensure_edges()
        self._shape.edges[idx].percent = float(value) / 100.0
        self._commit("Edge Length")

    # --- masks ------------------------------------------------------------

    def _populate_masks(self, shape: Shape) -> None:
        for i in reversed(range(self.masks_layout.count())):
            item = self.masks_layout.takeAt(i)
            widget = item.widget() if item else None
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._mask_rows.clear()

        # A mesh has no masks: cutting a hole means re-triangulating the
        # boundary, which throws away the grid parametrisation the mesh
        # exists for.
        if shape is None or not hasattr(shape, "masks"):
            self.masks_group.setVisible(False)
            self.updateGeometry()
            return

        self.masks_group.setVisible(True)
        for idx, mask in enumerate(shape.masks):
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            checkbox = QCheckBox()
            checkbox.setChecked(mask.enabled)
            checkbox.setToolTip("Turn the hole off without losing where it is")
            label = QLabel(f"{mask.name} ({len(mask.points)} pts)")
            label.setStyleSheet(PropertyPanel._LABEL_DIM_STYLE)
            checkbox.stateChanged.connect(lambda state, i=idx: self._on_mask_enabled(i, state))
            row_layout.addWidget(checkbox)
            row_layout.addWidget(label, 1)
            self.masks_layout.addWidget(row)
            self._mask_rows.append((checkbox, label))
        self.remove_mask_btn.setEnabled(bool(shape.masks))
        self.updateGeometry()

    def _on_mask_enabled(self, idx: int, state: int) -> None:
        if self._updating or self._shape is None:
            return
        masks = getattr(self._shape, "masks", [])
        if idx >= len(masks):
            return
        masks[idx].enabled = state == Qt.Checked.value
        self._commit("Mask Visibility")

    def _on_add_mask(self) -> None:
        if self._updating or self._shape is None or not hasattr(self._shape, "masks"):
            return
        centre, size = self._mask_placement(self._shape)
        self._shape.masks.append(
            mask_from_rect(centre, size[0], size[1], name=f"Mask {len(self._shape.masks) + 1}")
        )
        self._populate_masks(self._shape)
        self._commit("Add Mask")

    def _on_remove_mask(self) -> None:
        if self._updating or self._shape is None:
            return
        masks = getattr(self._shape, "masks", [])
        if not masks:
            return
        masks.pop()
        self._populate_masks(self._shape)
        self._commit("Remove Mask")

    @staticmethod
    def _mask_placement(shape: Shape):
        """A starter hole in the middle of the surface, scaled to it."""
        if isinstance(shape, CircleShape):
            cx, cy = shape.center
            return (cx, cy), (max(shape.radius_x * 0.6, 20.0), max(shape.radius_y * 0.6, 20.0))
        points = shape.outline() if isinstance(shape, PolygonShape) else shape.points
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return (
            ((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0),
            (max((max(xs) - min(xs)) * 0.3, 20.0), max((max(ys) - min(ys)) * 0.3, 20.0)),
        )

    def _on_type_changed(self, _index: int) -> None:
        """Swap the surface's type in place, as one undo step."""
        if self._updating or self._shape is None or self._project is None:
            return
        target = self.type_combo.currentData()
        if not target or target == self._shape.type:
            return

        converted = convert_shape(self._shape, target)
        if converted is self._shape:
            return

        # Straight through a command rather than the usual session: the shape
        # is replaced outright here, so there is no "mutate then snapshot" to
        # hang the edit on - the after state has to be handed over directly.
        before = shape_to_dict(self._shape)
        after = shape_to_dict(converted)
        if self._stack is not None:
            if self._session is not None:
                self._session.cancel()
            self._stack.push(
                ShapeEditCommand(self._project, converted.id, before, after, "Change Type")
            )
        else:
            for index, shape in enumerate(self._project.shapes):
                if shape.id == converted.id:
                    self._project.shapes[index] = converted
                    self._project.touch()
                    break

        self.set_shape(self._project.get_shape(converted.id))
        self.shape_changed.emit()

    def _on_edge_curved(self, idx: int, state: int) -> None:
        if self._updating or not isinstance(self._shape, PolygonShape):
            return
        self._shape.ensure_edges()
        edge = self._shape.edges[idx]
        checked = state == Qt.Checked.value
        if checked == edge.curved:
            return
        if checked:
            self._shape.bow_edge(idx)
        else:
            edge.straighten()
        self._commit("Curve Edge" if checked else "Straighten Edge")

    def _on_add_vertex(self) -> None:
        if self._updating or not isinstance(self._shape, PolygonShape):
            return
        points = list(self._shape.points)
        if len(points) < 2:
            return
        max_len = -1.0
        insert_idx = 0
        for idx in range(len(points)):
            p1 = points[idx]
            p2 = points[(idx + 1) % len(points)]
            dx = p2[0] - p1[0]
            dy = p2[1] - p1[1]
            dist = (dx * dx + dy * dy) ** 0.5
            if dist > max_len:
                max_len = dist
                insert_idx = idx
        p1 = points[insert_idx]
        p2 = points[(insert_idx + 1) % len(points)]
        mid = ((p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0)
        points.insert(insert_idx + 1, mid)
        self._shape.points = points
        edges = list(self._shape.edges)
        old_count = len(points) - 1
        if len(edges) < old_count:
            edges.extend(EdgeVisibility() for _ in range(old_count - len(edges)))
        elif len(edges) > old_count:
            edges = edges[:old_count]
        edges.insert(insert_idx + 1, EdgeVisibility())
        self._shape.edges = edges[: len(points)]
        self._populate_edges(self._shape)
        self._update_corner_pin_controls()
        self._populate_coords(self._shape)
        self._commit("Add Vertex")

    def _on_remove_vertex(self) -> None:
        if self._updating or not isinstance(self._shape, PolygonShape):
            return
        points = list(self._shape.points)
        if len(points) <= 3:
            return
        points.pop()
        self._shape.points = points
        self._shape.ensure_edges()
        if len(self._shape.edges) > len(points):
            self._shape.edges = self._shape.edges[:len(points)]
        self._populate_edges(self._shape)
        self._update_corner_pin_controls()
        self._populate_coords(self._shape)
        self._commit("Remove Vertex")

    def _pick_media(self, kind: str) -> None:
        if not self._shape:
            return
        if kind == "image":
            path, _ = QFileDialog.getOpenFileName(self, "Select Image", "", "Images (*.png *.jpg *.jpeg *.bmp)")
        elif kind == "camera":
            # A device index, not a file. Cameras have no names OpenCV can be
            # asked for portably, so the number is what there is.
            index, accepted = QInputDialog.getInt(self, "Camera", "Device index", 0, 0, 15)
            path = str(index) if accepted else ""
        else:
            path, _ = QFileDialog.getOpenFileName(self, "Select Video", "", "Videos (*.mp4 *.mov *.avi *.mkv)")
        if not path:
            return
        had_media = bool(self._shape.media and self._shape.media.path)
        if not self._shape.media:
            self._shape.media = MediaRef()
        self._shape.media.kind = kind
        self._shape.media.path = path

        # Dropping media on a quad almost always means mapping it to a
        # surface, so start in corner pin. Only on the first assignment - a
        # deliberate fit mode chosen earlier is not overridden.
        if not had_media and self._is_corner_pinnable():
            self._shape.media.fit_mode = "warp"
            self._updating = True
            self._select_fit_mode("warp")
            self._updating = False

        self._update_media(self._shape.media)
        self._update_corner_pin_controls()
        self._commit("Load Media")

    def _clear_media(self) -> None:
        if not self._shape:
            return
        self._shape.media = MediaRef()
        self._update_media(self._shape.media)
        self._updating = True
        self._select_fit_mode(self._shape.media.fit_mode)
        self._updating = False
        self._update_corner_pin_controls()
        self._commit("Clear Media")

    def _update_media(self, media: MediaRef) -> None:
        if media and media.path:
            self.media_label.setText(f"{media.kind}: {media.path}")
            self.media_label.setStyleSheet("color: #00d4aa;")
        else:
            self.media_label.setText("No media assigned")
            self.media_label.setStyleSheet("color: #606060; font-style: italic;")

    def _on_fit_mode_changed(self, _index: int) -> None:
        if self._updating or not self._shape:
            return
        if not self._shape.media:
            self._shape.media = MediaRef()
        self._shape.media.fit_mode = self.fit_mode.currentData() or "stretch"
        self._update_corner_pin_controls()
        self._commit("Fit Mode")

    def _select_fit_mode(self, value: str) -> None:
        index = self.fit_mode.findData(value)
        self.fit_mode.setCurrentIndex(index if index >= 0 else 0)

    def _is_corner_pinnable(self) -> bool:
        """Corner pin needs exactly four corners to pin."""
        return isinstance(self._shape, PolygonShape) and len(self._shape.points) == 4

    def _update_corner_pin_controls(self) -> None:
        pinnable = self._is_corner_pinnable()
        index = self.fit_mode.findData("warp")
        if index >= 0:
            # Leave the entry visible but inert on non-quads, so it is clear
            # the mode exists and why it does not apply here.
            item = self.fit_mode.model().item(index)
            if item is not None:
                item.setEnabled(pinnable)
        active = pinnable and (self.fit_mode.currentData() == "warp")
        self.reset_corners_btn.setVisible(active)

    def _on_reset_corners(self) -> None:
        if not self._is_corner_pinnable():
            return
        xs = [p[0] for p in self._shape.points]
        ys = [p[1] for p in self._shape.points]
        minx, maxx = min(xs), max(xs)
        miny, maxy = min(ys), max(ys)
        self._shape.points = [(minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy)]
        self._shape.ensure_edges()
        self._populate_coords(self._shape)
        self._commit("Reset Corners")

    def _on_transform_changed(self) -> None:
        if self._updating or not self._shape:
            return
        if not self._shape.media:
            self._shape.media = MediaRef()
        self._shape.media.transform.offset_x = self.offset_x.value()
        self._shape.media.transform.offset_y = self.offset_y.value()
        self._shape.media.transform.rotation = self.rotation.value()
        self._commit("Media Transform")

    def _on_effects_changed(self) -> None:
        if self._updating or not self._shape:
            return
        self._shape.effects.rgb_shift.enabled = self.rgb_enable.isChecked()
        self._shape.effects.rgb_shift.amount = self.rgb_amount.value()
        self._shape.effects.rgb_shift.speed = self.rgb_speed.value()
        self._shape.effects.pulse.enabled = self.pulse_enable.isChecked()
        self._shape.effects.pulse.amount = self.pulse_amount.value()
        self._shape.effects.pulse.speed = self.pulse_speed.value()
        self._shape.effects.strobe.enabled = self.strobe_enable.isChecked()
        self._shape.effects.strobe.hz = self.strobe_hz.value()
        self._commit("Effects")

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pm.model.media import MediaRef
from pm.model.shapes import CircleShape, EdgeVisibility, PolygonShape, Shape
from pm.ui.widgets import ArrowSlider, ArrowSpinBox


class PropertyPanel(QWidget):
    shape_changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._shape: Optional[Shape] = None
        self._updating = False
        self._edge_rows: List[tuple] = []
        self.setMinimumSize(0, 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        title = QLabel("Propriedades")
        title.setObjectName("panelTitle")
        layout.addWidget(title)

        self.name_edit = QLineEdit()
        self.name_edit.editingFinished.connect(self._on_name_changed)
        layout.addWidget(self._wrap_row("Nome", self.name_edit))

        self.fill_button = QPushButton("Cor de preenchimento")
        self.fill_button.clicked.connect(lambda: self._pick_color("fill"))
        layout.addWidget(self.fill_button)

        self.stroke_button = QPushButton("Cor da borda")
        self.stroke_button.clicked.connect(lambda: self._pick_color("stroke"))
        layout.addWidget(self.stroke_button)

        self.stroke_width = ArrowSpinBox()
        self.stroke_width.setRange(0.0, 50.0)
        self.stroke_width.setSingleStep(0.5)
        self.stroke_width.valueChanged.connect(self._on_stroke_width_changed)
        layout.addWidget(self._wrap_row("Largura borda", self.stroke_width))

        self.opacity_slider = ArrowSlider(Qt.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)
        layout.addWidget(self._wrap_row("Opacidade", self.opacity_slider))

        self.edges_group = QGroupBox("Arestas")
        self.edges_layout = QVBoxLayout(self.edges_group)
        self.edges_layout.setContentsMargins(6, 6, 6, 6)
        self.edges_layout.setSpacing(4)
        layout.addWidget(self.edges_group)

        self.points_group = QGroupBox("Pontos de Ajuste")
        points_layout = QVBoxLayout(self.points_group)
        points_layout.setContentsMargins(6, 6, 6, 6)
        points_layout.setSpacing(6)
        self.circle_points_spin = ArrowSpinBox()
        self.circle_points_spin.setRange(4, 32)
        self.circle_points_spin.setSingleStep(2.0)
        self.circle_points_spin.valueChanged.connect(self._on_circle_points_changed)
        points_layout.addWidget(self._wrap_row("Pontos (círculo)", self.circle_points_spin))

        polygon_buttons = QHBoxLayout()
        self.add_vertex_btn = QPushButton("Adicionar vértice")
        self.remove_vertex_btn = QPushButton("Remover vértice")
        self.add_vertex_btn.clicked.connect(self._on_add_vertex)
        self.remove_vertex_btn.clicked.connect(self._on_remove_vertex)
        polygon_buttons.addWidget(self.add_vertex_btn)
        polygon_buttons.addWidget(self.remove_vertex_btn)
        points_layout.addLayout(polygon_buttons)
        layout.addWidget(self.points_group)

        self.media_group = QGroupBox("Mídia")
        media_layout = QVBoxLayout(self.media_group)
        media_layout.setContentsMargins(6, 6, 6, 6)
        media_layout.setSpacing(6)
        self.media_label = QLabel("Nenhuma mídia")
        self.media_label.setWordWrap(True)
        media_layout.addWidget(self.media_label)

        media_buttons = QHBoxLayout()
        self.load_image_btn = QPushButton("Imagem")
        self.load_video_btn = QPushButton("Vídeo")
        self.clear_media_btn = QPushButton("Limpar")
        self.load_image_btn.clicked.connect(lambda: self._pick_media("image"))
        self.load_video_btn.clicked.connect(lambda: self._pick_media("video"))
        self.clear_media_btn.clicked.connect(self._clear_media)
        media_buttons.addWidget(self.load_image_btn)
        media_buttons.addWidget(self.load_video_btn)
        media_buttons.addWidget(self.clear_media_btn)
        media_layout.addLayout(media_buttons)

        self.fit_mode = QComboBox()
        self.fit_mode.addItems(["stretch", "contain", "cover"])
        self.fit_mode.currentTextChanged.connect(self._on_fit_mode_changed)
        media_layout.addWidget(self._wrap_row("Ajuste", self.fit_mode))

        transform_layout = QFormLayout()
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
        transform_layout.addRow("Offset X", self.offset_x)
        transform_layout.addRow("Offset Y", self.offset_y)
        transform_layout.addRow("Rotação", self.rotation)
        media_layout.addLayout(transform_layout)
        layout.addWidget(self.media_group)

        self.effects_group = QGroupBox("Efeitos")
        effects_layout = QVBoxLayout(self.effects_group)
        effects_layout.setContentsMargins(6, 6, 6, 6)
        effects_layout.setSpacing(8)
        self.rgb_enable = QCheckBox("RGB Shift")
        self.rgb_enable.stateChanged.connect(self._on_effects_changed)
        self.rgb_amount = ArrowSpinBox()
        self.rgb_amount.setRange(0.0, 10.0)
        self.rgb_amount.setSingleStep(0.1)
        self.rgb_amount.valueChanged.connect(self._on_effects_changed)
        self.rgb_speed = ArrowSpinBox()
        self.rgb_speed.setRange(0.1, 10.0)
        self.rgb_speed.setSingleStep(0.1)
        self.rgb_speed.valueChanged.connect(self._on_effects_changed)
        effects_layout.addWidget(self.rgb_enable)
        effects_layout.addWidget(self._wrap_row("RGB Intens.", self.rgb_amount))
        effects_layout.addWidget(self._wrap_row("RGB Vel.", self.rgb_speed))

        self.pulse_enable = QCheckBox("Pulso")
        self.pulse_enable.stateChanged.connect(self._on_effects_changed)
        self.pulse_amount = ArrowSpinBox()
        self.pulse_amount.setRange(0.0, 2.0)
        self.pulse_amount.setSingleStep(0.05)
        self.pulse_amount.valueChanged.connect(self._on_effects_changed)
        self.pulse_speed = ArrowSpinBox()
        self.pulse_speed.setRange(0.1, 10.0)
        self.pulse_speed.setSingleStep(0.1)
        self.pulse_speed.valueChanged.connect(self._on_effects_changed)
        effects_layout.addWidget(self.pulse_enable)
        effects_layout.addWidget(self._wrap_row("Pulso Intens.", self.pulse_amount))
        effects_layout.addWidget(self._wrap_row("Pulso Vel.", self.pulse_speed))

        self.strobe_enable = QCheckBox("Strobe")
        self.strobe_enable.stateChanged.connect(self._on_effects_changed)
        self.strobe_hz = ArrowSpinBox()
        self.strobe_hz.setRange(0.1, 30.0)
        self.strobe_hz.setSingleStep(0.5)
        self.strobe_hz.valueChanged.connect(self._on_effects_changed)
        effects_layout.addWidget(self.strobe_enable)
        effects_layout.addWidget(self._wrap_row("Strobe Hz", self.strobe_hz))
        layout.addWidget(self.effects_group)

        layout.addStretch(1)

    def _wrap_row(self, label: str, widget: QWidget) -> QWidget:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)
        row_layout.addWidget(QLabel(label))
        row_layout.addWidget(widget, 1)
        return row

    def set_shape(self, shape: Optional[Shape]) -> None:
        self._shape = shape
        self._updating = True
        if not shape:
            self.setEnabled(False)
            self.edges_group.setVisible(False)
            self.points_group.setVisible(False)
            self._updating = False
            return
        self.setEnabled(True)
        self.name_edit.setText(shape.name)
        self._apply_button_color(self.fill_button, shape.fill_color)
        self._apply_button_color(self.stroke_button, shape.stroke_color)
        self.stroke_width.setValue(shape.stroke_width)
        self.opacity_slider.setValue(int(shape.opacity * 100))
        self._populate_edges(shape)
        self._update_point_controls(shape)
        self._update_media(shape.media)
        self.fit_mode.setCurrentText(shape.media.fit_mode if shape.media else "stretch")
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

    def _populate_edges(self, shape: Shape) -> None:
        for i in reversed(range(self.edges_layout.count())):
            item = self.edges_layout.takeAt(i)
            if item and item.widget():
                item.widget().deleteLater()
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
            row_layout.setSpacing(6)
            label = QLabel(f"Aresta {idx + 1}")
            checkbox = QCheckBox()
            checkbox.setChecked(edge.visible)
            slider = ArrowSlider(Qt.Horizontal)
            slider.setRange(0, 100)
            slider.setValue(int(edge.percent * 100))
            checkbox.stateChanged.connect(lambda state, i=idx: self._on_edge_visible(i, state))
            slider.valueChanged.connect(lambda value, i=idx: self._on_edge_percent(i, value))
            row_layout.addWidget(label)
            row_layout.addWidget(checkbox)
            row_layout.addWidget(slider, 1)
            self.edges_layout.addWidget(row)
            self._edge_rows.append((checkbox, slider))

    def _update_point_controls(self, shape: Shape) -> None:
        if isinstance(shape, CircleShape):
            self.points_group.setVisible(True)
            self.circle_points_spin.setEnabled(True)
            self.add_vertex_btn.setEnabled(False)
            self.remove_vertex_btn.setEnabled(False)
            self.circle_points_spin.setValue(int(getattr(shape, "control_points", 4)))
        elif isinstance(shape, PolygonShape):
            self.points_group.setVisible(True)
            self.circle_points_spin.setEnabled(False)
            self.add_vertex_btn.setEnabled(True)
            self.remove_vertex_btn.setEnabled(True)
        else:
            self.points_group.setVisible(False)

    def _apply_button_color(self, button: QPushButton, rgba: List[int]) -> None:
        color = QColor(*rgba)
        button.setStyleSheet(f"background-color: {color.name()};")

    def _pick_color(self, target: str) -> None:
        if not self._shape:
            return
        initial = QColor(*(self._shape.fill_color if target == "fill" else self._shape.stroke_color))
        color = QColorDialog.getColor(initial, self, "Selecionar cor")
        if not color.isValid():
            return
        rgba = [color.red(), color.green(), color.blue(), color.alpha()]
        if target == "fill":
            self._shape.fill_color = rgba
            self._apply_button_color(self.fill_button, rgba)
        else:
            self._shape.stroke_color = rgba
            self._apply_button_color(self.stroke_button, rgba)
        self.shape_changed.emit()

    def _on_name_changed(self) -> None:
        if self._updating or not self._shape:
            return
        self._shape.name = self.name_edit.text().strip() or self._shape.name
        self.shape_changed.emit()

    def _on_stroke_width_changed(self, value: float) -> None:
        if self._updating or not self._shape:
            return
        self._shape.stroke_width = float(value)
        self.shape_changed.emit()

    def _on_opacity_changed(self, value: int) -> None:
        if self._updating or not self._shape:
            return
        self._shape.opacity = float(value) / 100.0
        self.shape_changed.emit()

    def _on_edge_visible(self, idx: int, state: int) -> None:
        if self._updating or not isinstance(self._shape, PolygonShape):
            return
        self._shape.ensure_edges()
        self._shape.edges[idx].visible = state == Qt.Checked
        self.shape_changed.emit()

    def _on_edge_percent(self, idx: int, value: int) -> None:
        if self._updating or not isinstance(self._shape, PolygonShape):
            return
        self._shape.ensure_edges()
        self._shape.edges[idx].percent = float(value) / 100.0
        self.shape_changed.emit()

    def _on_circle_points_changed(self, value: float) -> None:
        if self._updating or not isinstance(self._shape, CircleShape):
            return
        count = max(4, int(value))
        if count % 2 != 0:
            count += 1
        self._shape.control_points = count
        self.shape_changed.emit()

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
        self.shape_changed.emit()

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
        self.shape_changed.emit()

    def _pick_media(self, kind: str) -> None:
        if not self._shape:
            return
        if kind == "image":
            path, _ = QFileDialog.getOpenFileName(self, "Selecionar imagem", "", "Imagens (*.png *.jpg *.jpeg *.bmp)")
        else:
            path, _ = QFileDialog.getOpenFileName(self, "Selecionar vídeo", "", "Vídeos (*.mp4 *.mov *.avi *.mkv)")
        if not path:
            return
        if not self._shape.media:
            self._shape.media = MediaRef()
        self._shape.media.kind = kind
        self._shape.media.path = path
        self._update_media(self._shape.media)
        self.shape_changed.emit()

    def _clear_media(self) -> None:
        if not self._shape:
            return
        self._shape.media = MediaRef()
        self._update_media(self._shape.media)
        self.shape_changed.emit()

    def _update_media(self, media: MediaRef) -> None:
        if media and media.path:
            self.media_label.setText(f"{media.kind}: {media.path}")
        else:
            self.media_label.setText("Nenhuma mídia")

    def _on_fit_mode_changed(self, mode: str) -> None:
        if self._updating or not self._shape:
            return
        if not self._shape.media:
            self._shape.media = MediaRef()
        self._shape.media.fit_mode = mode
        self.shape_changed.emit()

    def _on_transform_changed(self) -> None:
        if self._updating or not self._shape:
            return
        if not self._shape.media:
            self._shape.media = MediaRef()
        self._shape.media.transform.offset_x = self.offset_x.value()
        self._shape.media.transform.offset_y = self.offset_y.value()
        self._shape.media.transform.rotation = self.rotation.value()
        self.shape_changed.emit()

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
        self.shape_changed.emit()

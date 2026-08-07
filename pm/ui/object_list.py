from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pm.media.availability import is_missing
from pm.model.shapes import Shape


class ObjectList(QWidget):
    shape_selected = Signal(str)
    visibility_changed = Signal(str, bool)
    solo_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._updating = False
        self.setMinimumSize(0, 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Panel header
        title = QLabel("LAYERS")
        title.setObjectName("panelTitle")
        layout.addWidget(title)

        self.list = QListWidget()
        self.list.itemSelectionChanged.connect(self._on_selection_changed)
        self.list.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.list)

        # Solo is how you work out which quad on screen is which surface in
        # the list - hide everything else and look at the wall.
        self.solo_button = QPushButton("Solo")
        self.solo_button.setToolTip("Show only the selected surface; press again to show all")
        self.solo_button.clicked.connect(self._on_solo_clicked)
        layout.addWidget(self.solo_button)

    def set_shapes(self, shapes: List[Shape]) -> None:
        self._updating = True
        self.list.clear()
        # Groups are invisible in the canvas until something moves, so the
        # layer list is where membership has to be legible. Numbered, because
        # "grouped" without saying *which* group tells the operator nothing
        # when a facade has four of them.
        group_numbers = {}
        for shape in shapes:
            group_id = getattr(shape, "group_id", None)
            if group_id and group_id not in group_numbers:
                group_numbers[group_id] = len(group_numbers) + 1

        for shape in shapes:
            item = QListWidgetItem(shape.name)
            item.setData(Qt.UserRole, shape.id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if shape.visible else Qt.Unchecked)
            label = shape.name
            # A file that is not there is the difference between "I mapped it
            # wrong" and "the drive is not plugged in", and in a dark room
            # that is not a difference you can work out from a blank surface.
            if is_missing(getattr(shape, "media", None)):
                label = f"{label}  ⚠"
                item.setToolTip(f"Media not found: {shape.media.path}")
            group_id = getattr(shape, "group_id", None)
            if group_id:
                label = f"{label}  ⛓{group_numbers[group_id]}"
            if shape.locked:
                label = f"{label}  🔒"
            item.setText(label)
            self.list.addItem(item)
        self._updating = False

    def _on_solo_clicked(self) -> None:
        items = self.list.selectedItems()
        if not items:
            return
        shape_id = items[0].data(Qt.UserRole)
        if shape_id:
            self.solo_requested.emit(shape_id)

    def select_shape(self, shape_id: Optional[str]) -> None:
        self._updating = True
        self.list.clearSelection()
        if shape_id:
            for i in range(self.list.count()):
                item = self.list.item(i)
                if item.data(Qt.UserRole) == shape_id:
                    item.setSelected(True)
                    break
        self._updating = False

    def _on_selection_changed(self) -> None:
        if self._updating:
            return
        items = self.list.selectedItems()
        if not items:
            return
        shape_id = items[0].data(Qt.UserRole)
        if shape_id:
            self.shape_selected.emit(shape_id)

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        if self._updating:
            return
        shape_id = item.data(Qt.UserRole)
        if shape_id:
            visible = item.checkState() == Qt.Checked
            self.visibility_changed.emit(shape_id, visible)

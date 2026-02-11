from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QVBoxLayout, QWidget, QLabel

from pm.model.shapes import Shape


class ObjectList(QWidget):
    shape_selected = Signal(str)
    visibility_changed = Signal(str, bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._updating = False
        self.setMinimumSize(0, 0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        title = QLabel("Objetos")
        title.setObjectName("panelTitle")
        layout.addWidget(title)

        self.list = QListWidget()
        self.list.itemSelectionChanged.connect(self._on_selection_changed)
        self.list.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.list)

    def set_shapes(self, shapes: List[Shape]) -> None:
        self._updating = True
        self.list.clear()
        for shape in shapes:
            item = QListWidgetItem(shape.name)
            item.setData(Qt.UserRole, shape.id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if shape.visible else Qt.Unchecked)
            self.list.addItem(item)
        self._updating = False

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

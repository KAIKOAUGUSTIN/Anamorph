from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractSpinBox, QSlider, QStyle, QStyleOptionSpinBox, QDoubleSpinBox


class ArrowSlider(QSlider):
    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Up:
            self.setValue(self.value() + self.singleStep())
            event.accept()
            return
        if event.key() == Qt.Key_Down:
            self.setValue(self.value() - self.singleStep())
            event.accept()
            return
        super().keyPressEvent(event)


class ArrowSpinBox(QDoubleSpinBox):
    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Up:
            self.stepUp()
            event.accept()
            return
        if event.key() == Qt.Key_Down:
            self.stepDown()
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:
        option = QStyleOptionSpinBox()
        self.initStyleOption(option)
        up_rect = self.style().subControlRect(QStyle.CC_SpinBox, option, QStyle.SC_SpinBoxUp, self)
        down_rect = self.style().subControlRect(QStyle.CC_SpinBox, option, QStyle.SC_SpinBoxDown, self)
        if up_rect.contains(event.pos()):
            self.stepUp()
            event.accept()
            return
        if down_rect.contains(event.pos()):
            self.stepDown()
            event.accept()
            return
        super().mousePressEvent(event)

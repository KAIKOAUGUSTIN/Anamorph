from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractSpinBox, QComboBox, QSlider, QSpinBox, QStyle, QStyleOptionSpinBox,
    QDoubleSpinBox,
)


class NoScrollMixin:
    """Ignore the wheel unless the widget has been clicked into.

    The property panel scrolls. Rolling the wheel over it used to change
    whichever field happened to be under the cursor on the way past, which
    silently edits a calibrated surface - and the operator has no idea which
    value moved or by how much.
    """

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        if not self.hasFocus():
            event.ignore()
            return
        super().wheelEvent(event)


class ArrowSlider(NoScrollMixin, QSlider):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.StrongFocus)

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


class ArrowSpinBox(NoScrollMixin, QDoubleSpinBox):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Click-to-focus only: without this the box takes focus on hover-scroll
        # from the wheel itself and the guard above never bites.
        self.setFocusPolicy(Qt.StrongFocus)

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


class NoScrollComboBox(NoScrollMixin, QComboBox):
    """A combo that will not change what it shows just because you scrolled past."""


class NoScrollSpinBox(NoScrollMixin, QSpinBox):
    """Integer counterpart of `ArrowSpinBox`'s wheel guard."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.StrongFocus)

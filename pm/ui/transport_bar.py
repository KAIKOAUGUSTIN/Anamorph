# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The show's transport: one place that stops everything.

A projection show is not a collection of independently drifting clips. It has
a position and a state, and a single button that pauses it - because the thing
you need when something goes wrong is not "pause this surface", it is "stop".
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from pm.model.project import Project
from pm.ui.widgets import ArrowSpinBox


def format_time(seconds: float) -> str:
    """`m:ss.t` - short enough for a toolbar, precise enough to call a cue on."""
    seconds = max(0.0, float(seconds))
    minutes = int(seconds // 60)
    return f"{minutes}:{seconds % 60:04.1f}"


class TransportBar(QWidget):
    """Play/pause, restart and rate for the whole project."""

    changed = Signal()

    # Fast enough that the readout looks like a clock rather than a stopwatch
    # someone forgot to start.
    TICK_MS = 100

    def __init__(self, project: Project, parent=None) -> None:
        super().__init__(parent)
        self._project = project
        self._updating = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.play_button = QPushButton()
        self.play_button.setFixedWidth(64)
        self.play_button.setToolTip("Play or pause every clip in the show (Space)")
        self.play_button.clicked.connect(self.toggle)
        layout.addWidget(self.play_button)

        self.restart_button = QPushButton("Restart")
        self.restart_button.setToolTip("Send the show back to zero")
        self.restart_button.clicked.connect(self.restart)
        layout.addWidget(self.restart_button)

        self.position_label = QLabel("0:00.0")
        self.position_label.setStyleSheet("color: #00d4aa; font-weight: 600; min-width: 56px;")
        self.position_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.position_label)

        speed_label = QLabel("Speed")
        speed_label.setStyleSheet("color: #808080;")
        layout.addWidget(speed_label)
        self.speed_box = ArrowSpinBox()
        self.speed_box.setRange(0.05, 4.0)
        self.speed_box.setSingleStep(0.05)
        self.speed_box.setDecimals(2)
        self.speed_box.setFixedWidth(72)
        self.speed_box.setToolTip("Rate for the whole show; each clip can scale it further")
        self.speed_box.valueChanged.connect(self._on_speed_changed)
        layout.addWidget(self.speed_box)

        # Only ticks while the bar is on screen. A timer that outlives its
        # widget fires once more into a deleted C++ object, which is a crash
        # rather than an exception.
        self._timer = QTimer(self)
        self._timer.setInterval(self.TICK_MS)
        self._timer.timeout.connect(self._refresh_readout)

        self.refresh()

    # --- actions ---------------------------------------------------------

    def toggle(self) -> None:
        self._project.transport.toggle()
        self._project.touch()
        self.refresh()
        self.changed.emit()

    def restart(self) -> None:
        self._project.transport.restart()
        self.refresh()
        self.changed.emit()

    def _on_speed_changed(self, value: float) -> None:
        if self._updating:
            return
        self._project.transport.set_speed(value)
        self._project.touch()
        self.changed.emit()

    # --- display ---------------------------------------------------------

    def set_project(self, project: Project) -> None:
        self._project = project
        self.refresh()

    def refresh(self) -> None:
        transport = self._project.transport
        self._updating = True
        self.play_button.setText("Pause" if transport.playing else "Play")
        self.speed_box.setValue(transport.speed)
        self._updating = False
        self._refresh_readout()

    def _refresh_readout(self) -> None:
        try:
            self.position_label.setText(format_time(self._project.transport.position()))
        except RuntimeError:
            # The widget went away underneath the timer.
            self._timer.stop()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._timer.start()

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QObject, Signal

from model.output import Output
from model.transport import Transport
from model.shapes import Shape, shape_from_dict, shape_to_dict


@dataclass
class CanvasSettings:
    # The canvas is the artwork's own resolution, and everything - the test
    # pattern included - is composited at it before the output pass resamples
    # it onto each projector. Leaving it below the projector's native size
    # throws away detail nothing downstream can put back, so a fresh project
    # adopts the resolution of the first screen an output is aimed at.
    DEFAULT_WIDTH = 1280
    DEFAULT_HEIGHT = 720

    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    background_color: List[int] = field(default_factory=lambda: [0, 0, 0, 255])

    def is_default(self) -> bool:
        """Still the size nobody chose - safe to adopt a screen's resolution."""
        return (self.width, self.height) == (self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "width": int(self.width),
            "height": int(self.height),
            "background_color": list(self.background_color),
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "CanvasSettings":
        if not data:
            return CanvasSettings()
        return CanvasSettings(
            width=int(data.get("width", 1280)),
            height=int(data.get("height", 720)),
            background_color=list(data.get("background_color", [0, 0, 0, 255])),
        )


class Project(QObject):
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.canvas: CanvasSettings = CanvasSettings()
        self.shapes: List[Shape] = []
        # One canvas, many projectors. Every output is a view of *this*
        # canvas, which is what lets two of them overlap and blend.
        self.outputs: List[Output] = []
        self.media_library: List[str] = []
        # The show clock. Every clip reads its position from here, which is
        # what makes two surfaces on the same file frame-accurate and what
        # lets one button stop the whole show.
        self.transport = Transport()
        # The panic button. Not serialised on purpose: a project that opens
        # black leaves the operator hunting for why nothing is on the wall,
        # and blackout is a live-operation state like the playhead, not a
        # property of the artwork.
        self.blackout: bool = False
        self.ui_state: Dict[str, Any] = {"last_projection_screen_id": None, "test_mode": False}
        self.path: Optional[str] = None
        self.name: str = "Untitled"
        # Every mutation routes through touch(), so this stays honest without
        # anyone having to remember to set it.
        self.dirty: bool = False

    def set_blackout(self, value: bool) -> None:
        """Kill or restore every projector at once."""
        value = bool(value)
        if value == self.blackout:
            return
        self.blackout = value
        # Straight to `changed`, without `touch`: blacking out is not an edit
        # to the show, and marking the project dirty would ask the operator to
        # save a state that is deliberately not saved.
        self.changed.emit()

    def touch(self) -> None:
        self.dirty = True
        self.changed.emit()

    def mark_saved(self) -> None:
        """Call after the project has been written to or read from disk."""
        self.dirty = False

    def add_shape(self, shape: Shape) -> None:
        self.shapes.append(shape)
        self.touch()

    def remove_shape(self, shape_id: str) -> None:
        self.shapes = [s for s in self.shapes if s.id != shape_id]
        self.touch()

    def get_shape(self, shape_id: str) -> Optional[Shape]:
        for shape in self.shapes:
            if shape.id == shape_id:
                return shape
        return None

    def get_output(self, output_id: str) -> Optional[Output]:
        for output in self.outputs:
            if output.id == output_id:
                return output
        return None

    def add_output(self, output: Output) -> None:
        self.outputs.append(output)
        self.touch()

    def remove_output(self, output_id: str) -> None:
        self.outputs = [o for o in self.outputs if o.id != output_id]
        self.touch()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "canvas": self.canvas.to_dict(),
            "shapes": [shape_to_dict(s) for s in self.shapes],
            "outputs": [o.to_dict() for o in self.outputs],
            "media_library": list(self.media_library),
            "transport": self.transport.to_dict(),
            "ui": dict(self.ui_state),
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "Project":
        project = Project()
        project.name = data.get("name", "Untitled")
        project.canvas = CanvasSettings.from_dict(data.get("canvas", {}))
        project.shapes = [shape_from_dict(s) for s in data.get("shapes", [])]
        # Absent in files written before outputs existed. Those projects had
        # exactly one projector, described by the screen id in ui_state.
        project.outputs = [Output.from_dict(o) for o in data.get("outputs", [])]
        project.media_library = list(data.get("media_library", []))
        project.transport = Transport.from_dict(data.get("transport", {}))
        project.ui_state = dict(data.get("ui", {"last_projection_screen_id": None, "test_mode": False}))
        if not project.outputs:
            project.outputs = [
                Output(
                    name="Projector 1",
                    screen_id=project.ui_state.get("last_projection_screen_id"),
                )
            ]
        return project

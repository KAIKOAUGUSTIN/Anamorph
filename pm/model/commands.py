"""Undoable edits, built on snapshots rather than inverse operations.

Shapes are mutable dataclasses that the canvas edits in place during a drag,
so there is no clean inverse to replay. Instead every command stores the
shape's serialised state before and after the edit and swaps them - the same
`shape_to_dict`/`shape_from_dict` pair the project file format already uses,
so anything that survives a save/load round trip survives undo.

Commands are pushed on release, not on every mouse move: dragging a corner
across the canvas is one undo step, not two hundred.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from PySide6.QtGui import QUndoCommand

from pm.model.project import Project
from pm.model.shapes import Shape, new_shape_id, shape_from_dict, shape_to_dict

SHAPE_EDIT_ID = 1

# Consecutive edits of the same kind within this window are treated as one
# gesture. It is what keeps dragging an opacity slider from filling the undo
# stack with a hundred entries, while a deliberate second tweak a moment later
# still gets its own step.
MERGE_WINDOW_SECONDS = 0.6


class ShapeEditCommand(QUndoCommand):
    """Replaces one shape's state, in place, keeping its position in the list."""

    def __init__(
        self,
        project: Project,
        shape_id: str,
        before: Dict[str, Any],
        after: Dict[str, Any],
        text: str,
    ) -> None:
        super().__init__(text)
        self._project = project
        self._shape_id = shape_id
        self._before = before
        self._after = after
        self._touched_at = time.monotonic()

    def id(self) -> int:
        return SHAPE_EDIT_ID

    def mergeWith(self, other: QUndoCommand) -> bool:
        if not isinstance(other, ShapeEditCommand):
            return False
        if other._shape_id != self._shape_id or other.text() != self.text():
            return False
        if other._touched_at - self._touched_at > MERGE_WINDOW_SECONDS:
            return False
        # Keep our "before" - it is the start of the gesture - and take the
        # newer "after" as the gesture's current end.
        self._after = other._after
        self._touched_at = other._touched_at
        return True

    def _restore(self, state: Dict[str, Any]) -> None:
        for index, shape in enumerate(self._project.shapes):
            if shape.id == self._shape_id:
                self._project.shapes[index] = shape_from_dict(state)
                self._project.touch()
                return

    def undo(self) -> None:
        self._restore(self._before)

    def redo(self) -> None:
        self._restore(self._after)


class AddShapeCommand(QUndoCommand):
    def __init__(self, project: Project, shape: Shape, text: str = "Add Shape") -> None:
        super().__init__(text)
        self._project = project
        self._state = shape_to_dict(shape)
        self._shape_id = shape.id

    def redo(self) -> None:
        if self._project.get_shape(self._shape_id) is None:
            self._project.add_shape(shape_from_dict(self._state))

    def undo(self) -> None:
        self._project.remove_shape(self._shape_id)


def duplicate_shape(shape: Shape, offset: float = 20.0) -> Shape:
    """A copy of `shape`, nudged clear of the original and given a fresh id.

    Mapping a facade means twelve identical windows; drawing each one by hand
    is not the workflow. The offset is what stops the copy landing exactly on
    top of its source, where nobody can tell them apart.
    """
    state = shape_to_dict(shape)
    state["id"] = new_shape_id()
    state["name"] = f"{shape.name} copy"

    if "points" in state:
        state["points"] = [{"x": p["x"] + offset, "y": p["y"] + offset} for p in state["points"]]
    if "center" in state:
        state["center"] = {"x": state["center"]["x"] + offset, "y": state["center"]["y"] + offset}
    if state.get("anchors"):
        state["anchors"] = [{"x": p["x"] + offset, "y": p["y"] + offset} for p in state["anchors"]]

    return shape_from_dict(state)


class RemoveShapesCommand(QUndoCommand):
    """Deletes shapes, remembering where each sat so undo restores z-order."""

    def __init__(self, project: Project, shape_ids: List[str], text: str = "Delete") -> None:
        super().__init__(text)
        self._project = project
        self._removed: List[tuple] = []
        for index, shape in enumerate(project.shapes):
            if shape.id in shape_ids:
                self._removed.append((index, shape_to_dict(shape)))

    def redo(self) -> None:
        ids = {state["id"] for _, state in self._removed}
        self._project.shapes = [s for s in self._project.shapes if s.id not in ids]
        self._project.touch()

    def undo(self) -> None:
        for index, state in self._removed:
            self._project.shapes.insert(min(index, len(self._project.shapes)), shape_from_dict(state))
        self._project.touch()


class EditSession:
    """Captures a shape before an interaction and pushes a command after it.

    Drags mutate the model continuously; this is what turns that stream into
    a single undo entry. `begin` is a no-op when a session is already open, so
    nested handlers (a vertex handle inside a shape drag) collapse into one.
    """

    def __init__(self, undo_stack) -> None:
        self._stack = undo_stack
        self._shape_id: Optional[str] = None
        self._before: Optional[Dict[str, Any]] = None

    @property
    def active(self) -> bool:
        return self._before is not None

    def begin(self, shape: Optional[Shape]) -> None:
        if shape is None or self.active:
            return
        self._shape_id = shape.id
        self._before = shape_to_dict(shape)

    def commit(self, project: Project, text: str) -> bool:
        """Push the command if anything actually changed. Returns True if so."""
        before, shape_id = self._before, self._shape_id
        self.cancel()
        if before is None or shape_id is None:
            return False

        shape = project.get_shape(shape_id)
        if shape is None:
            return False

        after = shape_to_dict(shape)
        if after == before:
            return False

        self._stack.push(ShapeEditCommand(project, shape_id, before, after, text))
        return True

    def cancel(self) -> None:
        self._shape_id = None
        self._before = None

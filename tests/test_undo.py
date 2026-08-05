import pytest
from PySide6.QtGui import QUndoStack

from pm.model.commands import (
    AddShapeCommand,
    EditSession,
    RemoveShapesCommand,
    ShapeEditCommand,
)
from pm.model.project import Project
from pm.model.shapes import polygon_from_points, shape_to_dict

QUAD = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]
MOVED = [(10.0, 10.0), (110.0, 0.0), (100.0, 100.0), (0.0, 100.0)]


@pytest.fixture
def project():
    return Project()


@pytest.fixture
def stack(qapp):
    return QUndoStack()


def test_add_shape_is_undoable(project, stack):
    shape = polygon_from_points(list(QUAD), name="Wall")

    stack.push(AddShapeCommand(project, shape))
    assert [s.name for s in project.shapes] == ["Wall"]

    stack.undo()
    assert project.shapes == []

    stack.redo()
    assert [s.name for s in project.shapes] == ["Wall"]


def test_remove_restores_original_z_order(project, stack):
    for name in ("back", "middle", "front"):
        project.add_shape(polygon_from_points(list(QUAD), name=name))
    middle_id = project.shapes[1].id

    stack.push(RemoveShapesCommand(project, [middle_id]))
    assert [s.name for s in project.shapes] == ["back", "front"]

    stack.undo()
    assert [s.name for s in project.shapes] == ["back", "middle", "front"]


def test_remove_multiple_restores_all(project, stack):
    for name in ("a", "b", "c", "d"):
        project.add_shape(polygon_from_points(list(QUAD), name=name))
    ids = [project.shapes[0].id, project.shapes[2].id]

    stack.push(RemoveShapesCommand(project, ids))
    assert [s.name for s in project.shapes] == ["b", "d"]

    stack.undo()
    assert [s.name for s in project.shapes] == ["a", "b", "c", "d"]


def test_shape_edit_round_trips_geometry(project, stack):
    shape = polygon_from_points(list(QUAD))
    project.add_shape(shape)
    before = shape_to_dict(shape)

    shape.points = list(MOVED)
    after = shape_to_dict(shape)
    stack.push(ShapeEditCommand(project, shape.id, before, after, "Move Points"))

    stack.undo()
    assert project.shapes[0].points == QUAD

    stack.redo()
    assert project.shapes[0].points == MOVED


def test_edit_session_ignores_a_no_op(project, stack):
    shape = polygon_from_points(list(QUAD))
    project.add_shape(shape)

    session = EditSession(stack)
    session.begin(shape)
    # A click that selects but moves nothing must not add an undo entry.
    assert session.commit(project, "Move Points") is False
    assert stack.count() == 0


def test_edit_session_records_a_real_change(project, stack):
    shape = polygon_from_points(list(QUAD))
    project.add_shape(shape)

    session = EditSession(stack)
    session.begin(shape)
    shape.points = list(MOVED)
    assert session.commit(project, "Move Points") is True
    assert stack.count() == 1

    stack.undo()
    assert project.shapes[0].points == QUAD


def test_nested_begin_keeps_the_outer_snapshot(project, stack):
    """A handle press inside a shape drag must not restart the snapshot."""
    shape = polygon_from_points(list(QUAD))
    project.add_shape(shape)

    session = EditSession(stack)
    session.begin(shape)
    shape.points = list(MOVED)
    session.begin(shape)  # inner handler, mid-drag

    session.commit(project, "Move Points")
    stack.undo()
    assert project.shapes[0].points == QUAD


def test_rapid_same_label_edits_merge_into_one_step(project, stack):
    shape = polygon_from_points(list(QUAD))
    project.add_shape(shape)
    original = shape.opacity

    for value in (0.9, 0.8, 0.7):
        before = shape_to_dict(shape)
        shape.opacity = value
        stack.push(ShapeEditCommand(project, shape.id, before, shape_to_dict(shape), "Opacity"))

    # A slider drag is one gesture, not three.
    assert stack.count() == 1
    stack.undo()
    assert project.shapes[0].opacity == pytest.approx(original)


def test_different_labels_do_not_merge(project, stack):
    shape = polygon_from_points(list(QUAD))
    project.add_shape(shape)

    before = shape_to_dict(shape)
    shape.opacity = 0.5
    stack.push(ShapeEditCommand(project, shape.id, before, shape_to_dict(shape), "Opacity"))

    before = shape_to_dict(shape)
    shape.name = "Renamed"
    stack.push(ShapeEditCommand(project, shape.id, before, shape_to_dict(shape), "Rename Shape"))

    assert stack.count() == 2


def test_edits_to_different_shapes_do_not_merge(project, stack):
    first = polygon_from_points(list(QUAD), name="one")
    second = polygon_from_points(list(QUAD), name="two")
    project.add_shape(first)
    project.add_shape(second)

    for shape in (first, second):
        before = shape_to_dict(shape)
        shape.opacity = 0.5
        stack.push(ShapeEditCommand(project, shape.id, before, shape_to_dict(shape), "Opacity"))

    assert stack.count() == 2


def test_canvas_drag_becomes_one_undo_step(project, stack):
    """Exercises the wiring the canvas uses: snapshot on press, push on release."""
    from pm.ui.canvas_editor import CanvasEditor

    shape = polygon_from_points(list(QUAD))
    project.add_shape(shape)

    canvas = CanvasEditor(project)
    canvas.set_undo_stack(stack)
    item = canvas.items_by_id[shape.id]

    canvas._begin_edit_for(item)
    for step in (2.0, 4.0, 6.0):  # a drag arrives as many small moves
        shape.points = [(x + step, y) for x, y in QUAD]
    canvas._commit_edit()

    assert stack.count() == 1
    stack.undo()
    assert project.shapes[0].points == QUAD


def test_canvas_click_without_movement_adds_nothing(project, stack):
    from pm.ui.canvas_editor import CanvasEditor

    shape = polygon_from_points(list(QUAD))
    project.add_shape(shape)

    canvas = CanvasEditor(project)
    canvas.set_undo_stack(stack)

    canvas._begin_edit_for(canvas.items_by_id[shape.id])
    canvas._commit_edit()

    assert stack.count() == 0


def test_undo_marks_the_project_changed(project, stack):
    shape = polygon_from_points(list(QUAD))
    stack.push(AddShapeCommand(project, shape))

    seen = []
    project.changed.connect(lambda: seen.append(True))
    stack.undo()

    assert seen, "undo must repaint the canvas and the projection output"

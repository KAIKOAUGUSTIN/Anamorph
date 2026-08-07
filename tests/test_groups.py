# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Grouping: surfaces that move as one.

A window frame is four panels; a colonnade is a dozen identical columns.
Once they are placed relative to each other, nudging the arrangement has to
move all of them - a group is that promise, and nothing more. The members
stay independent shapes with their own vertices, media and masks.
"""

import math

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QUndoStack

from pm.model.commands import SetGroupCommand
from pm.model.project import Project
from pm.model.shapes import (
    circle_from_center,
    group_members,
    new_group_id,
    polygon_from_points,
    shape_from_dict,
    shape_to_dict,
)

LEFT = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]
RIGHT = [(200.0, 0.0), (300.0, 0.0), (300.0, 100.0), (200.0, 100.0)]


# --- the model --------------------------------------------------------------

def test_a_shape_starts_ungrouped():
    assert polygon_from_points(list(LEFT)).group_id is None


def test_group_members_finds_everything_sharing_the_id():
    a, b, c = (polygon_from_points(list(LEFT)) for _ in range(3))
    a.group_id = b.group_id = "frame"
    c.group_id = "other"

    assert group_members([a, b, c], "frame") == [a, b]
    assert group_members([a, b, c], None) == []


def test_group_ids_are_unique():
    assert new_group_id() != new_group_id()


def test_a_group_survives_a_round_trip():
    shape = polygon_from_points(list(LEFT))
    shape.group_id = "frame"
    assert shape_from_dict(shape_to_dict(shape)).group_id == "frame"


def test_an_ungrouped_shape_writes_no_key():
    assert "group_id" not in shape_to_dict(polygon_from_points(list(LEFT)))


# --- the command ------------------------------------------------------------

@pytest.fixture
def project():
    project = Project()
    project.add_shape(polygon_from_points(list(LEFT), name="left"))
    project.add_shape(polygon_from_points(list(RIGHT), name="right"))
    return project


def test_grouping_is_one_undo_step(project):
    stack = QUndoStack()
    ids = [s.id for s in project.shapes]

    stack.push(SetGroupCommand(project, {i: "frame" for i in ids}, "Group"))
    assert [s.group_id for s in project.shapes] == ["frame", "frame"]
    assert stack.count() == 1

    stack.undo()
    assert [s.group_id for s in project.shapes] == [None, None]


def test_ungrouping_restores_the_group_on_undo(project):
    stack = QUndoStack()
    ids = [s.id for s in project.shapes]
    stack.push(SetGroupCommand(project, {i: "frame" for i in ids}, "Group"))

    stack.push(SetGroupCommand(project, {i: None for i in ids}, "Ungroup"))
    assert [s.group_id for s in project.shapes] == [None, None]

    stack.undo()
    assert [s.group_id for s in project.shapes] == ["frame", "frame"]


def test_grouping_leaves_the_geometry_alone(project):
    stack = QUndoStack()
    stack.push(SetGroupCommand(project, {project.shapes[0].id: "frame"}, "Group"))
    assert project.shapes[0].points == LEFT


# --- the canvas -------------------------------------------------------------

@pytest.fixture
def canvas(qapp):
    from pm.ui.canvas_editor import CanvasEditor

    project = Project()
    project.add_shape(polygon_from_points(list(LEFT), name="left"))
    project.add_shape(polygon_from_points(list(RIGHT), name="right"))
    view = CanvasEditor(project)
    view.set_undo_stack(QUndoStack())
    view.set_zoom(1.0)
    return view


def _grouped(canvas):
    for shape in canvas.project.shapes:
        shape.group_id = "frame"
    return canvas.project.shapes


def test_selecting_one_member_selects_the_group(canvas):
    shapes = _grouped(canvas)
    canvas.select_shape(shapes[0].id)

    assert sorted(canvas.selected_shape_ids()) == sorted(s.id for s in shapes)


def test_selecting_an_ungrouped_shape_selects_only_it(canvas):
    canvas.select_shape(canvas.project.shapes[0].id)
    assert canvas.selected_shape_ids() == [canvas.project.shapes[0].id]


def test_ctrl_click_adds_a_loose_shape_to_the_selection(canvas):
    first, second = canvas.project.shapes
    canvas.select_shape(first.id)

    canvas.select_shape(second.id, additive=True)
    assert sorted(canvas.selected_shape_ids()) == sorted([first.id, second.id])

    canvas.select_shape(second.id, additive=True)
    assert canvas.selected_shape_ids() == [first.id], "a second Ctrl+click takes it back out"


def test_dragging_one_member_moves_the_whole_group(canvas):
    shapes = _grouped(canvas)
    item = canvas.items_by_id[shapes[0].id]

    canvas._begin_body_drag(item, QPointF(50.0, 50.0), Qt.NoModifier)
    canvas._update_body_drag(QPointF(80.0, 90.0), Qt.NoModifier)

    assert canvas.project.shapes[0].points == [(x + 30.0, y + 40.0) for x, y in LEFT]
    assert canvas.project.shapes[1].points == [(x + 30.0, y + 40.0) for x, y in RIGHT]


def test_an_ungrouped_neighbour_stays_put(canvas):
    shapes = canvas.project.shapes
    item = canvas.items_by_id[shapes[0].id]

    canvas._begin_body_drag(item, QPointF(50.0, 50.0), Qt.NoModifier)
    canvas._update_body_drag(QPointF(80.0, 90.0), Qt.NoModifier)

    assert shapes[1].points == RIGHT


def test_a_group_rotates_about_its_shared_centre(canvas):
    """Rotating about each member's own centre would spin the parts in place
    and leave the arrangement untouched."""
    shapes = _grouped(canvas)
    item = canvas.items_by_id[shapes[0].id]
    # Group bbox is x 0..300, y 0..100, so the pivot is (150, 50).
    canvas._begin_body_drag(item, QPointF(300.0, 50.0), Qt.AltModifier)
    canvas._update_body_drag(QPointF(150.0, 200.0), Qt.AltModifier)  # a quarter turn

    left, right = canvas.project.shapes
    for original, moved in ((LEFT, left.points), (RIGHT, right.points)):
        for (ox, oy), (nx, ny) in zip(original, moved):
            assert math.hypot(nx - 150.0, ny - 50.0) == pytest.approx(math.hypot(ox - 150.0, oy - 50.0))
    assert left.points != LEFT and right.points != RIGHT


def test_a_group_scales_about_its_shared_centre(canvas):
    shapes = _grouped(canvas)
    item = canvas.items_by_id[shapes[0].id]

    canvas._begin_body_drag(item, QPointF(300.0, 50.0), Qt.ControlModifier)
    canvas._update_body_drag(QPointF(450.0, 50.0), Qt.ControlModifier)  # factor 2

    left, right = canvas.project.shapes
    assert left.points == pytest.approx([(150 + (x - 150) * 2, 50 + (y - 50) * 2) for x, y in LEFT])
    assert right.points == pytest.approx([(150 + (x - 150) * 2, 50 + (y - 50) * 2) for x, y in RIGHT])


def test_a_locked_member_stays_where_it_is(canvas):
    shapes = _grouped(canvas)
    shapes[1].locked = True
    item = canvas.items_by_id[shapes[0].id]

    canvas._begin_body_drag(item, QPointF(50.0, 50.0), Qt.NoModifier)
    canvas._update_body_drag(QPointF(80.0, 50.0), Qt.NoModifier)

    assert canvas.project.shapes[0].points != LEFT
    assert canvas.project.shapes[1].points == RIGHT


def test_a_group_drag_is_one_undo_step(canvas):
    shapes = _grouped(canvas)
    item = canvas.items_by_id[shapes[0].id]
    canvas.select_shape(shapes[0].id)
    canvas._begin_edit_for(item)

    canvas._begin_body_drag(item, QPointF(50.0, 50.0), Qt.NoModifier)
    for x in (60.0, 70.0, 80.0):
        canvas._update_body_drag(QPointF(x, 50.0), Qt.NoModifier)
    canvas._end_body_drag()
    canvas._commit_edit("Move Shape")

    assert canvas.undo_stack.count() == 1

    canvas.undo_stack.undo()
    assert canvas.project.shapes[0].points == LEFT
    assert canvas.project.shapes[1].points == RIGHT, "undo has to put every member back"


def test_the_grips_span_the_whole_group(canvas):
    shapes = _grouped(canvas)
    canvas.select_shape(shapes[0].id)

    corners = {(h.pos().x(), h.pos().y()) for h in canvas._transform_handles if h.mode == "scale"}
    assert corners == {(0.0, 0.0), (300.0, 0.0), (300.0, 100.0), (0.0, 100.0)}


def test_a_vertex_still_belongs_to_its_own_shape(canvas):
    """Grouping ties the bodies together, not the geometry."""
    shapes = _grouped(canvas)
    canvas.select_shape(shapes[0].id)
    item = canvas.items_by_id[shapes[0].id]

    canvas._on_handle_moved(item, 0, QPointF(-20.0, -20.0))

    assert canvas.project.shapes[0].points[0] == (-20.0, -20.0)
    assert canvas.project.shapes[1].points == RIGHT


def test_a_multi_selection_moves_together_without_a_group(canvas):
    shapes = canvas.project.shapes
    for shape in shapes:
        canvas.items_by_id[shape.id].setSelected(True)
    item = canvas.items_by_id[shapes[0].id]

    canvas._begin_body_drag(item, QPointF(50.0, 50.0), Qt.NoModifier)
    canvas._update_body_drag(QPointF(60.0, 50.0), Qt.NoModifier)

    assert shapes[0].points == [(x + 10.0, y) for x, y in LEFT]
    assert shapes[1].points == [(x + 10.0, y) for x, y in RIGHT]


def test_a_circle_in_a_group_travels_rather_than_spinning_in_place(canvas):
    circle = circle_from_center((200.0, 50.0), 20.0)
    circle.group_id = "frame"
    canvas.project.add_shape(circle)
    canvas.project.shapes[0].group_id = "frame"
    canvas.project.shapes[1].group_id = None
    canvas._sync_items()

    item = canvas.items_by_id[canvas.project.shapes[0].id]
    canvas._begin_body_drag(item, QPointF(100.0, 25.0), Qt.AltModifier)
    canvas._update_body_drag(QPointF(0.0, 125.0), Qt.AltModifier)

    assert circle.center != (200.0, 50.0), "a grouped circle orbits the group's pivot"


# --- the window -------------------------------------------------------------

@pytest.fixture
def window(qapp):
    from pm.ui.main_window import MainWindow

    win = MainWindow()
    for points, name in ((LEFT, "left"), (RIGHT, "right")):
        win.project.add_shape(polygon_from_points(list(points), name=name))
    yield win
    win.project.mark_saved()
    win.close()


def test_ctrl_g_groups_the_selection(window):
    for shape in window.project.shapes:
        window.canvas.items_by_id[shape.id].setSelected(True)

    window._group_selected()

    ids = {s.group_id for s in window.project.shapes}
    assert len(ids) == 1 and None not in ids


def test_grouping_needs_two_surfaces(window):
    window.canvas.select_shape(window.project.shapes[0].id)
    depth = window.undo_stack.count()

    window._group_selected()

    assert window.undo_stack.count() == depth, "a group of one is just a shape"
    assert window.project.shapes[0].group_id is None


def test_ungrouping_frees_every_member(window):
    for shape in window.project.shapes:
        shape.group_id = "frame"
    window.canvas.select_shape(window.project.shapes[0].id)

    window._ungroup_selected()

    assert [s.group_id for s in window.project.shapes] == [None, None]


def test_ungrouping_is_undoable(window):
    for shape in window.project.shapes:
        shape.group_id = "frame"
    window.canvas.select_shape(window.project.shapes[0].id)

    window._ungroup_selected()
    window.undo_stack.undo()

    assert all(s.group_id == "frame" for s in window.project.shapes)


def test_the_layer_list_says_which_group_a_surface_is_in(window):
    for shape in window.project.shapes:
        shape.group_id = "frame"
    window.object_list.set_shapes(window.project.shapes)

    labels = [window.object_list.list.item(i).text() for i in range(window.object_list.list.count())]
    assert all("⛓1" in label for label in labels)


def test_separate_groups_get_separate_numbers(window):
    window.project.shapes[0].group_id = "a"
    window.project.shapes[1].group_id = "b"
    window.object_list.set_shapes(window.project.shapes)

    labels = [window.object_list.list.item(i).text() for i in range(window.object_list.list.count())]
    assert "⛓1" in labels[0] and "⛓2" in labels[1]

# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-only

import math

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QUndoStack

from model.commands import duplicate_shape
from model.project import Project
from model.shapes import circle_from_center, polygon_from_points

QUAD = [(100.0, 100.0), (200.0, 100.0), (200.0, 200.0), (100.0, 200.0)]
CENTRE = (150.0, 150.0)


@pytest.fixture
def canvas(qapp):
    from ui.canvas_editor import CanvasEditor

    project = Project()
    project.add_shape(polygon_from_points(list(QUAD), name="wall"))
    view = CanvasEditor(project)
    view.set_undo_stack(QUndoStack())
    view.set_zoom(1.0)
    return view


def _drag_body(canvas, to, modifiers=Qt.NoModifier, start=CENTRE):
    shape = canvas.project.shapes[0]
    item = canvas.items_by_id[shape.id]
    canvas.select_shape(shape.id)
    canvas._begin_edit_for(item)
    canvas._begin_body_drag(item, QPointF(*start), modifiers)
    canvas._update_body_drag(QPointF(*to), modifiers)
    return shape


# --- move ----------------------------------------------------------------

def test_plain_drag_moves_the_shape(canvas):
    """It used to need Shift, and a bare drag did nothing but select."""
    shape = _drag_body(canvas, (170.0, 190.0))
    assert shape.points == [(x + 20.0, y + 40.0) for x, y in QUAD]


def test_shift_locks_the_move_to_one_axis(canvas):
    shape = _drag_body(canvas, (190.0, 155.0), Qt.ShiftModifier)
    # Horizontal travel dominates, so vertical is discarded entirely.
    assert shape.points == [(x + 40.0, y) for x, y in QUAD]


def test_a_locked_shape_does_not_move(canvas):
    canvas.project.shapes[0].locked = True
    shape = _drag_body(canvas, (400.0, 400.0))
    assert shape.points == QUAD


# --- rotate --------------------------------------------------------------

def test_alt_drag_rotates_about_the_centre(canvas):
    # Start due east of centre, end due south: a quarter turn.
    shape = _drag_body(canvas, (150.0, 200.0), Qt.AltModifier, start=(200.0, 150.0))

    cx, cy = CENTRE
    for (ox, oy), (nx, ny) in zip(QUAD, shape.points):
        # Rotation preserves distance from the centre.
        assert math.hypot(nx - cx, ny - cy) == pytest.approx(math.hypot(ox - cx, oy - cy))
    # And it is a real quarter turn, not the identity.
    assert shape.points != QUAD


def _rotation_of(points):
    """Angle the shape turned through, read off its first vertex."""
    cx, cy = CENTRE
    before = math.atan2(QUAD[0][1] - cy, QUAD[0][0] - cx)
    after = math.atan2(points[0][1] - cy, points[0][0] - cx)
    return math.degrees(after - before)


def test_shift_snaps_rotation_to_fifteen_degree_steps(canvas):
    # Starting due east, 8 units up over 50 across is ~9.1 degrees - past the
    # 7.5 degree half-step, so it lands on 15.
    shape = _drag_body(canvas, (200.0, 158.0), Qt.AltModifier | Qt.ShiftModifier, start=(200.0, 150.0))
    assert _rotation_of(shape.points) == pytest.approx(15.0, abs=1e-6)


def test_shift_snaps_a_small_rotation_back_to_zero(canvas):
    # ~3 degrees is inside the half-step, so the shape does not move at all.
    shape = _drag_body(canvas, (200.0, 152.6), Qt.AltModifier | Qt.ShiftModifier, start=(200.0, 150.0))
    assert shape.points == pytest.approx(QUAD, abs=1e-6)


# --- scale ---------------------------------------------------------------

def test_ctrl_drag_scales_from_the_centre(canvas):
    # Start 50 units from centre, drag to 100: a factor of two.
    shape = _drag_body(canvas, (250.0, 150.0), Qt.ControlModifier, start=(200.0, 150.0))

    cx, cy = CENTRE
    for (ox, oy), (nx, ny) in zip(QUAD, shape.points):
        assert nx - cx == pytest.approx((ox - cx) * 2.0)
        assert ny - cy == pytest.approx((oy - cy) * 2.0)


def test_scaling_cannot_collapse_the_shape(canvas):
    shape = _drag_body(canvas, (150.0, 150.0), Qt.ControlModifier, start=(200.0, 150.0))
    xs = [p[0] for p in shape.points]
    assert max(xs) > min(xs)


def test_circle_scales_both_radii(qapp):
    from ui.canvas_editor import CanvasEditor

    project = Project()
    circle = circle_from_center((150.0, 150.0), 50.0)
    circle.radius_x, circle.radius_y = 60.0, 30.0
    project.add_shape(circle)
    canvas = CanvasEditor(project)
    canvas.set_undo_stack(QUndoStack())
    item = canvas.items_by_id[circle.id]

    canvas._begin_body_drag(item, QPointF(200.0, 150.0), Qt.ControlModifier)
    canvas._update_body_drag(QPointF(250.0, 150.0), Qt.ControlModifier)

    assert circle.radius_x == pytest.approx(120.0)
    assert circle.radius_y == pytest.approx(60.0)


# --- one undo step per gesture -------------------------------------------

@pytest.mark.parametrize(
    "modifiers,label",
    [(Qt.NoModifier, "Move Shape"), (Qt.AltModifier, "Rotate Shape"), (Qt.ControlModifier, "Scale Shape")],
)
def test_a_gesture_is_one_labelled_undo_step(canvas, modifiers, label):
    shape = canvas.project.shapes[0]
    item = canvas.items_by_id[shape.id]
    canvas.select_shape(shape.id)
    canvas._begin_edit_for(item)
    canvas._begin_body_drag(item, QPointF(200.0, 150.0), modifiers)
    for x in (210.0, 230.0, 260.0):  # a drag arrives as many small moves
        canvas._update_body_drag(QPointF(x, 170.0), modifiers)

    gesture = canvas.GESTURE_LABELS[canvas._body_drag["mode"]]
    canvas._end_body_drag()
    canvas._commit_edit(gesture)

    assert canvas.undo_stack.count() == 1
    assert canvas.undo_stack.command(0).text() == label

    canvas.undo_stack.undo()
    assert canvas.project.shapes[0].points == QUAD


# --- handles are no longer modal -----------------------------------------

def test_a_selected_shape_starts_on_the_transform_grips(canvas):
    """The grips sit exactly on the corner vertices, so only one set can be
    live at a time. Selection opens on the grips; the points are a click away."""
    shape = canvas.project.shapes[0]
    canvas.select_shape(shape.id)
    item = canvas.items_by_id[shape.id]

    assert canvas._transform_handles
    assert len(item.handles) == len(QUAD)
    assert not any(h.isVisible() for h in item.handles)


def test_a_second_click_swaps_to_the_vertices(canvas):
    shape = canvas.project.shapes[0]
    canvas.select_shape(shape.id)
    item = canvas.items_by_id[shape.id]

    canvas.toggle_handle_mode()

    assert all(h.isVisible() for h in item.handles)
    assert not canvas._transform_handles, "the grips get out of the way"

    canvas.toggle_handle_mode()
    assert not any(h.isVisible() for h in item.handles)
    assert canvas._transform_handles


def test_selecting_something_else_goes_back_to_the_grips(canvas):
    from model.shapes import polygon_from_points

    other = polygon_from_points([(400.0, 400.0), (500.0, 400.0), (500.0, 500.0)])
    canvas.project.add_shape(other)
    canvas.select_shape(canvas.project.shapes[0].id)
    canvas.toggle_handle_mode()

    canvas.select_shape(other.id)

    assert canvas._transform_handles
    assert not any(h.isVisible() for h in canvas.items_by_id[other.id].handles)


def test_a_locked_shape_offers_no_handles_at_all(canvas):
    """Locking used to stop the body moving and leave the corners draggable."""
    shape = canvas.project.shapes[0]
    shape.locked = True
    canvas.select_shape(shape.id)
    canvas.toggle_handle_mode()
    item = canvas.items_by_id[shape.id]

    assert not any(h.isVisible() for h in item.handles)
    assert not canvas._transform_handles


# --- the bounding box is what makes the gestures findable ----------------

def test_selecting_a_shape_shows_scale_and_rotate_grips(canvas):
    shape = canvas.project.shapes[0]
    canvas.select_shape(shape.id)

    modes = [h.mode for h in canvas._transform_handles]
    assert modes.count("scale") == 4
    assert modes.count("rotate") == 1


def test_grips_sit_on_the_bounding_box(canvas):
    shape = canvas.project.shapes[0]
    canvas.select_shape(shape.id)

    corners = {(h.pos().x(), h.pos().y()) for h in canvas._transform_handles if h.mode == "scale"}
    assert corners == {(100.0, 100.0), (200.0, 100.0), (200.0, 200.0), (100.0, 200.0)}

    rotate = next(h for h in canvas._transform_handles if h.mode == "rotate")
    assert rotate.pos().x() == pytest.approx(150.0)
    assert rotate.pos().y() < 100.0, "the rotate grip floats above the box"


def test_grips_follow_the_shape(canvas):
    shape = canvas.project.shapes[0]
    canvas.select_shape(shape.id)
    _drag_body(canvas, (200.0, 150.0))  # move right by 50

    corners = {h.pos().x() for h in canvas._transform_handles if h.mode == "scale"}
    assert corners == {150.0, 250.0}


def test_grips_disappear_with_the_selection(canvas):
    shape = canvas.project.shapes[0]
    canvas.select_shape(shape.id)
    assert canvas._transform_handles

    canvas.select_shape(None)
    assert canvas._transform_handles == []


def test_a_locked_shape_gets_no_grips(canvas):
    shape = canvas.project.shapes[0]
    shape.locked = True
    canvas.select_shape(shape.id)

    assert canvas._transform_handles == []


def test_a_grip_forces_its_own_gesture_regardless_of_modifiers(canvas):
    """The grip says what it does; the modifiers are for dragging the body."""
    shape = canvas.project.shapes[0]
    canvas.select_shape(shape.id)
    item = canvas.items_by_id[shape.id]

    canvas._begin_body_drag(item, QPointF(200.0, 150.0), Qt.NoModifier, mode="scale")
    canvas._update_body_drag(QPointF(250.0, 150.0), Qt.NoModifier)

    cx, cy = CENTRE
    for (ox, oy), (nx, ny) in zip(QUAD, shape.points):
        assert nx - cx == pytest.approx((ox - cx) * 2.0)


def test_releasing_a_grip_commits_one_undo_step(canvas):
    shape = canvas.project.shapes[0]
    canvas.select_shape(shape.id)
    item = canvas.items_by_id[shape.id]

    canvas._begin_edit_for(item)
    canvas._begin_body_drag(item, QPointF(200.0, 150.0), Qt.NoModifier, mode="scale")
    for x in (220.0, 240.0, 250.0):
        canvas._update_body_drag(QPointF(x, 150.0), Qt.NoModifier)
    canvas._release_transform_handle()

    assert canvas.undo_stack.count() == 1
    assert canvas.undo_stack.command(0).text() == "Scale Shape"

    canvas.undo_stack.undo()
    assert canvas.project.shapes[0].points == QUAD


def test_grips_track_a_circle_by_its_radii(qapp):
    from ui.canvas_editor import CanvasEditor

    project = Project()
    circle = circle_from_center((150.0, 150.0), 50.0)
    circle.radius_x, circle.radius_y = 80.0, 20.0
    project.add_shape(circle)
    canvas = CanvasEditor(project)
    canvas.set_undo_stack(QUndoStack())
    canvas.select_shape(circle.id)

    corners = {(h.pos().x(), h.pos().y()) for h in canvas._transform_handles if h.mode == "scale"}
    assert corners == {(70.0, 130.0), (230.0, 130.0), (230.0, 170.0), (70.0, 170.0)}


# --- duplicate -----------------------------------------------------------

def test_duplicate_offsets_and_renames():
    original = polygon_from_points(list(QUAD), name="Window")
    copy = duplicate_shape(original, offset=20.0)

    assert copy.id != original.id
    assert copy.name == "Window copy"
    assert copy.points == [(x + 20.0, y + 20.0) for x, y in QUAD]
    assert original.points == QUAD, "the source must not move"


def test_duplicate_carries_media_and_effects():
    original = polygon_from_points(list(QUAD))
    original.media.kind = "image"
    original.media.path = "/tmp/x.png"
    original.media.fit_mode = "warp"
    original.effects.pulse.enabled = True
    original.opacity = 0.4

    copy = duplicate_shape(original)

    assert copy.media.path == "/tmp/x.png"
    assert copy.media.fit_mode == "warp"
    assert copy.effects.pulse.enabled is True
    assert copy.opacity == pytest.approx(0.4)


def test_duplicate_of_a_circle_moves_centre_and_anchors():
    original = circle_from_center((100.0, 100.0), 30.0, name="Dot")
    copy = duplicate_shape(original, offset=15.0)

    assert copy.center == (115.0, 115.0)
    assert all(ax >= 85.0 for ax, _ in copy.anchors)
    assert original.center == (100.0, 100.0)


def test_duplicate_is_undoable(qapp):
    from ui.main_window import MainWindow

    window = MainWindow()
    try:
        shape = polygon_from_points(list(QUAD), name="Window")
        window.project.add_shape(shape)
        window.canvas.select_shape(shape.id)

        window._duplicate_selected()
        assert len(window.project.shapes) == 2

        window.undo_stack.undo()
        assert len(window.project.shapes) == 1
    finally:
        window.project.mark_saved()
        window.close()


# --- solo ----------------------------------------------------------------

def test_solo_hides_everything_else_and_toggles_back(qapp):
    from ui.main_window import MainWindow

    window = MainWindow()
    try:
        shapes = [polygon_from_points(list(QUAD), name=n) for n in ("a", "b", "c")]
        for s in shapes:
            window.project.add_shape(s)

        window._on_solo_requested(shapes[1].id)
        assert [s.visible for s in window.project.shapes] == [False, True, False]

        window._on_solo_requested(shapes[1].id)
        assert all(s.visible for s in window.project.shapes)
    finally:
        window.project.mark_saved()
        window.close()


def test_solo_is_a_single_undo_step(qapp):
    from ui.main_window import MainWindow

    window = MainWindow()
    try:
        shapes = [polygon_from_points(list(QUAD), name=n) for n in ("a", "b", "c")]
        for s in shapes:
            window.project.add_shape(s)
        depth = window.undo_stack.count()

        window._on_solo_requested(shapes[0].id)
        assert window.undo_stack.count() == depth + 1

        window.undo_stack.undo()
        assert all(s.visible for s in window.project.shapes)
    finally:
        window.project.mark_saved()
        window.close()

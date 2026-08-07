# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent, QUndoStack

from pm.model.project import Project
from pm.model.shapes import circle_from_center, polygon_from_points
from pm.ui.widgets import ArrowSpinBox

QUAD = [(10.0, 20.0), (110.0, 20.0), (110.0, 120.0), (10.0, 120.0)]


@pytest.fixture
def canvas(qapp):
    from pm.ui.canvas_editor import CanvasEditor

    project = Project()
    project.add_shape(polygon_from_points(list(QUAD), name="quad"))
    view = CanvasEditor(project)
    view.set_undo_stack(QUndoStack())
    return view


def _press(canvas, key, shift=False):
    modifiers = Qt.ShiftModifier if shift else Qt.NoModifier
    canvas.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, key, modifiers))


# --- keyboard nudge ------------------------------------------------------

def test_arrow_moves_the_whole_shape_by_one_unit(canvas):
    shape = canvas.project.shapes[0]
    canvas.select_shape(shape.id)

    _press(canvas, Qt.Key_Right)

    assert shape.points == [(x + 1.0, y) for x, y in QUAD]


def test_shift_arrow_moves_by_ten(canvas):
    shape = canvas.project.shapes[0]
    canvas.select_shape(shape.id)

    _press(canvas, Qt.Key_Down, shift=True)

    assert shape.points == [(x, y + 10.0) for x, y in QUAD]


def test_arrow_moves_only_the_armed_vertex(canvas):
    shape = canvas.project.shapes[0]
    canvas.select_shape(shape.id)
    item = canvas.items_by_id[shape.id]
    canvas._active_vertex = (item, 2)

    _press(canvas, Qt.Key_Left)

    expected = list(QUAD)
    expected[2] = (QUAD[2][0] - 1.0, QUAD[2][1])
    assert shape.points == expected


def test_nudge_is_undoable(canvas):
    shape = canvas.project.shapes[0]
    canvas.select_shape(shape.id)

    _press(canvas, Qt.Key_Right)
    canvas.undo_stack.undo()

    assert canvas.project.shapes[0].points == QUAD


def test_nudge_does_nothing_without_a_selection(canvas):
    shape = canvas.project.shapes[0]

    _press(canvas, Qt.Key_Right)

    assert shape.points == QUAD
    assert canvas.undo_stack.count() == 0


def test_locked_shapes_ignore_nudges(canvas):
    shape = canvas.project.shapes[0]
    shape.locked = True
    canvas.select_shape(shape.id)

    _press(canvas, Qt.Key_Right)

    assert shape.points == QUAD


def test_circle_nudge_moves_centre_and_anchors(qapp):
    from pm.ui.canvas_editor import CanvasEditor

    project = Project()
    circle = circle_from_center((100.0, 100.0), 40.0)
    project.add_shape(circle)
    canvas = CanvasEditor(project)
    canvas.set_undo_stack(QUndoStack())
    canvas.select_shape(circle.id)

    _press(canvas, Qt.Key_Right, shift=True)

    assert circle.center == (110.0, 100.0)
    assert all(x >= 70.0 for x, _ in circle.anchors)


def _circle_canvas(rx, ry):
    from pm.ui.canvas_editor import CanvasEditor

    project = Project()
    circle = circle_from_center((200.0, 200.0), 50.0)
    circle.radius_x, circle.radius_y = rx, ry
    project.add_shape(circle)
    canvas = CanvasEditor(project)
    canvas.set_undo_stack(QUndoStack())
    canvas.select_shape(circle.id)
    return canvas, circle, canvas.items_by_id[circle.id]


def test_handles_sit_on_the_ellipse_not_a_circle(qapp):
    """A single max(rx, ry) radius left the handles floating off the outline."""
    canvas, circle, item = _circle_canvas(120.0, 40.0)
    cx, cy = circle.center

    offsets = [(h.pos().x() - cx, h.pos().y() - cy) for h in item.handles]
    distances = sorted(round((dx * dx + dy * dy) ** 0.5, 3) for dx, dy in offsets)

    # Two handles at rx, two at ry - not four at max(rx, ry).
    assert distances == [40.0, 40.0, 120.0, 120.0]


def test_dragging_one_axis_leaves_the_other_alone(qapp):
    from PySide6.QtCore import QPointF

    canvas, circle, item = _circle_canvas(120.0, 40.0)
    # Handle 1 rides the horizontal axis (handle_angle defaults to -pi/2).
    canvas._on_circle_handle_pressed(item, 1, item.handles[1].pos())
    canvas._on_circle_handle_moved(item, 1, QPointF(400.0, 200.0))

    assert circle.radius_y == pytest.approx(40.0), "the untouched axis moved"
    assert circle.radius_x != pytest.approx(120.0)


def test_dragging_the_vertical_axis_leaves_the_horizontal_alone(qapp):
    from PySide6.QtCore import QPointF

    canvas, circle, item = _circle_canvas(120.0, 40.0)
    canvas._on_circle_handle_pressed(item, 0, item.handles[0].pos())
    canvas._on_circle_handle_moved(item, 0, QPointF(200.0, 20.0))

    assert circle.radius_x == pytest.approx(120.0)
    assert circle.radius_y != pytest.approx(40.0)


def test_shift_keeps_a_circle_circular(qapp, monkeypatch):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QGuiApplication

    canvas, circle, item = _circle_canvas(60.0, 60.0)
    monkeypatch.setattr(
        QGuiApplication, "keyboardModifiers", staticmethod(lambda: Qt.ShiftModifier)
    )
    canvas._on_circle_handle_pressed(item, 1, item.handles[1].pos())
    canvas._on_circle_handle_moved(item, 1, QPointF(400.0, 200.0))

    assert circle.radius_x == pytest.approx(circle.radius_y)


def test_arming_a_vertex_clears_when_selection_moves_away(canvas):
    shape = canvas.project.shapes[0]
    other = polygon_from_points(list(QUAD), name="other")
    canvas.project.add_shape(other)

    canvas.select_shape(shape.id)
    canvas._active_vertex = (canvas.items_by_id[shape.id], 1)
    canvas.select_shape(other.id)

    assert canvas._active_vertex is None


# --- typed coordinates ---------------------------------------------------

@pytest.fixture
def panel(qapp):
    from pm.ui.property_panel import PropertyPanel

    project = Project()
    widget = PropertyPanel()
    widget.set_undo_context(project, QUndoStack())
    return widget, project


def _spins(panel_widget):
    return [row.findChildren(ArrowSpinBox) for row in panel_widget._coord_rows]


def test_polygon_gets_one_coordinate_row_per_vertex(panel):
    widget, project = panel
    shape = polygon_from_points(list(QUAD))
    project.add_shape(shape)
    widget.set_shape(shape)

    rows = _spins(widget)
    assert len(rows) == 4
    assert [(sx.value(), sy.value()) for sx, sy in rows] == QUAD


def test_typing_a_coordinate_moves_that_vertex(panel):
    widget, project = panel
    shape = polygon_from_points(list(QUAD))
    project.add_shape(shape)
    widget.set_shape(shape)

    _spins(widget)[1][0].setValue(250.0)

    assert shape.points[1] == (250.0, 20.0)
    assert shape.points[0] == QUAD[0]


def test_typed_coordinate_is_undoable(panel):
    widget, project = panel
    shape = polygon_from_points(list(QUAD))
    project.add_shape(shape)
    widget.set_shape(shape)

    _spins(widget)[0][1].setValue(999.0)
    widget._session._stack.undo()

    assert project.shapes[0].points == QUAD


def test_rows_track_a_vertex_being_added(panel):
    widget, project = panel
    shape = polygon_from_points(list(QUAD))
    project.add_shape(shape)
    widget.set_shape(shape)

    widget._on_add_vertex()

    assert len(widget._coord_rows) == 5
    assert len(shape.points) == 5


def test_refresh_pulls_coordinates_back_from_the_model(panel):
    widget, project = panel
    shape = polygon_from_points(list(QUAD))
    project.add_shape(shape)
    widget.set_shape(shape)

    # Stands in for a canvas drag mutating the model directly.
    shape.points = [(x + 7.0, y - 3.0) for x, y in QUAD]
    widget.refresh_geometry()

    assert [(sx.value(), sy.value()) for sx, sy in _spins(widget)] == shape.points


def test_refresh_does_not_write_back_to_the_model(panel):
    widget, project = panel
    shape = polygon_from_points(list(QUAD))
    project.add_shape(shape)
    widget.set_shape(shape)
    stack = widget._session._stack

    shape.points = [(x + 7.0, y) for x, y in QUAD]
    widget.refresh_geometry()

    assert stack.count() == 0, "syncing the panel must not look like a user edit"


def test_circle_exposes_centre_and_radii(panel):
    widget, project = panel
    circle = circle_from_center((60.0, 80.0), 25.0)
    project.add_shape(circle)
    widget.set_shape(circle)

    values = [row.findChildren(ArrowSpinBox)[0].value() for row in widget._coord_rows]
    assert values == [60.0, 80.0, 25.0, 25.0]


def test_typing_a_radius_updates_the_circle(panel):
    widget, project = panel
    circle = circle_from_center((60.0, 80.0), 25.0)
    project.add_shape(circle)
    widget.set_shape(circle)

    widget._coord_rows[2].findChildren(ArrowSpinBox)[0].setValue(90.0)

    assert circle.radius_x == 90.0
    assert circle.radius_y == 25.0


def test_radius_cannot_be_driven_to_zero(panel):
    widget, project = panel
    circle = circle_from_center((60.0, 80.0), 25.0)
    project.add_shape(circle)
    widget.set_shape(circle)

    widget._coord_rows[2].findChildren(ArrowSpinBox)[0].setValue(0.0)

    assert circle.radius_x >= 1.0

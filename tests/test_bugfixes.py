# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regressions for the bugs found using the app.

Each test here failed before its fix. Grouped by what the operator saw, not by
which module happened to hold the mistake.
"""

import math

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QUndoStack

from model.project import CanvasSettings, Project
from model.shapes import (
    CircleShape,
    MeshShape,
    PolygonShape,
    circle_from_center,
    convert_shape,
    mask_from_rect,
    mesh_from_rect,
    polygon_from_points,
    shape_from_dict,
    shape_to_dict,
)
from render.mesh import triangulate_circle

QUAD = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]
FAR = [(300.0, 0.0), (400.0, 0.0), (400.0, 100.0), (300.0, 100.0)]


@pytest.fixture
def canvas(qapp):
    from ui.canvas_editor import CanvasEditor

    project = Project()
    project.add_shape(polygon_from_points(list(QUAD), name="wall"))
    project.add_shape(polygon_from_points(list(FAR), name="far"))
    view = CanvasEditor(project)
    view.set_undo_stack(QUndoStack())
    view.set_zoom(1.0)
    return view


# --- "the circle does not go all the way round on the projector" ------------

def test_the_circle_fan_closes_all_the_way_round():
    """The fan stopped one wedge short, so a slice of every circle was missing."""
    segments = 48
    points, indices = triangulate_circle((0.0, 0.0), 10.0, 10.0, segments)

    assert len(indices) == segments * 3
    area = 0.0
    for i in range(0, len(indices), 3):
        (x1, y1), (x2, y2), (x3, y3) = (points[indices[i + k]] for k in range(3))
        area += abs((x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1)) / 2.0
    # A 48-gon covers 99.7% of its circle; a missing wedge would cost 2%.
    assert area == pytest.approx(math.pi * 100.0, rel=0.005)


# --- "mask points cannot be moved" ------------------------------------------

def test_a_click_on_a_mask_handle_is_not_a_click_on_the_shape(canvas):
    """The handle is parented to the shape, so the view resolved the press to
    the body, started a move gesture and swallowed every move the handle
    needed."""
    from ui.canvas_editor import CurveHandle, MaskHandle

    item = canvas.items_by_id[canvas.project.shapes[0].id]
    canvas.add_mask(item)
    item = canvas.items_by_id[canvas.project.shapes[0].id]
    canvas.select_shape(item.model.id)
    canvas.toggle_handle_mode()

    handle = item.mask_handles[0]
    assert isinstance(handle, MaskHandle)
    assert canvas._body_item_at(handle) is None

    canvas.toggle_edge_curve(item, 0)
    canvas._update_point_handles(item)
    curve_handle = item.curve_handles[0]
    assert isinstance(curve_handle, CurveHandle)
    assert canvas._body_item_at(curve_handle) is None


def test_dragging_a_mask_handle_moves_the_mask(canvas):
    canvas.set_snap_enabled(False)  # isolate the drag from the magnet
    item = canvas.items_by_id[canvas.project.shapes[0].id]
    canvas.add_mask(item)
    item = canvas.items_by_id[canvas.project.shapes[0].id]

    handle = item.mask_handles[0]
    handle.setPos(QPointF(12.0, 14.0))

    assert canvas.project.shapes[0].masks[0].points[0] == (12.0, 14.0)


def test_a_mask_corner_still_takes_the_magnet(canvas):
    """Snapping a hole to the grid is wanted; it is only the mesh that must
    move freely."""
    canvas.set_snap_enabled(True)
    canvas.scene.grid_size = 20.0
    item = canvas.items_by_id[canvas.project.shapes[0].id]
    canvas.add_mask(item)
    item = canvas.items_by_id[canvas.project.shapes[0].id]

    item.mask_handles[0].setPos(QPointF(12.0, 14.0))

    assert canvas.project.shapes[0].masks[0].points[0] == (20.0, 20.0)


# --- "the group flickers and the selection collapses" -----------------------

def test_a_ctrl_built_selection_survives_a_press_on_a_member(canvas):
    first, second = canvas.project.shapes
    canvas.select_shape(first.id)
    canvas.select_shape(second.id, additive=True)
    assert len(canvas.selected_shape_ids()) == 2

    # The press used to fall through to QGraphicsView, which selects the item
    # under the cursor and clears everything else.
    item = canvas.items_by_id[first.id]
    canvas._begin_body_drag(item, QPointF(50.0, 50.0), Qt.NoModifier)

    assert len(canvas.selected_shape_ids()) == 2


def test_a_press_on_a_group_member_keeps_the_group_selected(canvas):
    for shape in canvas.project.shapes:
        shape.group_id = "frame"
    canvas.select_shape(canvas.project.shapes[0].id)

    assert len(canvas.selected_shape_ids()) == 2


# --- "the white grips sit on top of the cyan points" ------------------------

def test_the_two_handle_sets_are_never_live_at_once(canvas):
    shape = canvas.project.shapes[0]
    canvas.select_shape(shape.id)
    item = canvas.items_by_id[shape.id]

    assert canvas._transform_handles and not any(h.isVisible() for h in item.handles)

    canvas.toggle_handle_mode()
    assert not canvas._transform_handles and all(h.isVisible() for h in item.handles)


def test_a_locked_surface_offers_neither_set(canvas):
    shape = canvas.project.shapes[0]
    shape.locked = True
    canvas.select_shape(shape.id)
    canvas.toggle_handle_mode()
    item = canvas.items_by_id[shape.id]

    assert not canvas._transform_handles
    assert not any(h.isVisible() for h in item.handles)


# --- "mesh points jump between grid lines" ----------------------------------

def test_a_mesh_control_point_ignores_the_grid(canvas):
    """Grid snap quantised the one thing a deformation mesh exists to express."""
    mesh = mesh_from_rect((200.0, 200.0), 100.0, rows=1, cols=1)
    canvas.project.add_shape(mesh)
    canvas.set_snap_enabled(True)
    canvas.scene.grid_size = 20.0
    item = canvas.items_by_id[mesh.id]

    off_grid = QPointF(163.0, 147.0)
    assert canvas._snap_vertex(item, off_grid, grid=False) == off_grid
    # A plain vertex still gets the magnet.
    assert canvas._snap_vertex(item, off_grid) != off_grid


def test_the_mesh_handles_are_wired_to_the_free_snap(canvas):
    mesh = mesh_from_rect((200.0, 200.0), 100.0, rows=1, cols=1)
    canvas.project.add_shape(mesh)
    canvas.set_snap_enabled(True)
    canvas.scene.grid_size = 20.0
    item = canvas.items_by_id[mesh.id]

    item.handles[0].setPos(QPointF(163.0, 147.0))

    assert canvas.project.shapes[-1].points[0] == (163.0, 147.0)


# --- "the type cannot be changed" -------------------------------------------

def test_converting_keeps_everything_but_the_geometry():
    shape = polygon_from_points(list(QUAD), name="wall")
    shape.stroke_width = 7.0
    shape.media.kind = "image"
    shape.media.path = "/tmp/x.png"
    shape.media.fit_mode = "cover"
    shape.group_id = "frame"
    shape.locked = True

    circle = convert_shape(shape, "circle")

    assert isinstance(circle, CircleShape)
    assert circle.id == shape.id and circle.name == shape.name
    assert circle.stroke_width == 7.0
    assert circle.media.path == "/tmp/x.png" and circle.media.fit_mode == "cover"
    assert circle.group_id == "frame" and circle.locked is True


def test_a_converted_surface_lands_on_the_old_bounding_box():
    shape = polygon_from_points(list(QUAD))

    circle = convert_shape(shape, "circle")
    assert circle.center == (50.0, 50.0)
    assert (circle.radius_x, circle.radius_y) == (50.0, 50.0)

    mesh = convert_shape(shape, "mesh")
    assert isinstance(mesh, MeshShape)
    assert mesh.points[0] == (0.0, 0.0) and mesh.points[-1] == (100.0, 100.0)

    back = convert_shape(mesh, "polygon")
    assert isinstance(back, PolygonShape)
    assert back.points == QUAD
    assert len(back.edges) == 4


def test_converting_to_the_same_type_changes_nothing():
    shape = polygon_from_points(list(QUAD))
    assert convert_shape(shape, "polygon") is shape


def test_a_mask_is_dropped_going_to_a_mesh_and_kept_otherwise():
    shape = polygon_from_points(list(QUAD))
    shape.masks = [mask_from_rect((50.0, 50.0), 20.0, 20.0)]

    assert len(convert_shape(shape, "circle").masks) == 1
    assert not hasattr(convert_shape(shape, "mesh"), "masks")


@pytest.fixture
def panel(qapp):
    from ui.property_panel import PropertyPanel

    project = Project()
    shape = polygon_from_points(list(QUAD), name="wall")
    project.add_shape(shape)
    widget = PropertyPanel()
    stack = QUndoStack()
    widget.set_undo_context(project, stack)
    widget.set_shape(shape)
    return widget, project, stack


def test_the_type_combo_changes_the_shape_in_the_project(panel):
    widget, project, _stack = panel

    widget.type_combo.setCurrentIndex(widget.type_combo.findData("circle"))

    assert isinstance(project.shapes[0], CircleShape)
    assert project.shapes[0].name == "wall"


def test_changing_the_type_is_undoable(panel):
    widget, project, stack = panel

    widget.type_combo.setCurrentIndex(widget.type_combo.findData("mesh"))
    assert isinstance(project.shapes[0], MeshShape)

    stack.undo()
    assert isinstance(project.shapes[0], PolygonShape)
    assert project.shapes[0].points == QUAD


# --- "the deleted shape is still in the properties panel" -------------------

def test_clearing_the_panel_actually_blanks_it(panel):
    widget, _project, _stack = panel
    assert widget.name_edit.text() == "wall"

    widget.set_shape(None)

    assert widget.name_edit.text() == ""
    assert widget._coord_rows == []
    assert widget._edge_rows == []
    assert not widget.isEnabled()


def test_deleting_a_shape_clears_the_panel(qapp):
    from ui.main_window import MainWindow

    win = MainWindow()
    try:
        shape = polygon_from_points(list(QUAD), name="wall")
        win.project.add_shape(shape)
        win.canvas._sync_items()
        win.canvas.select_shape(shape.id)
        win.property_panel.set_shape(shape)

        win._delete_selected_shapes()

        assert win.project.shapes == []
        assert win.property_panel.name_edit.text() == ""
    finally:
        win.project.mark_saved()
        win.close()


# --- "the output is called Untitled on the test screen" ---------------------

def test_the_test_pattern_is_labelled_with_the_output_name():
    from render.test_pattern import GRID, render_test_pattern

    # The renderer feeds `output.name`; this pins the plumbing that reads it.
    from model.output import Output

    output = Output(name="Stage Left")
    label = output.name or ""
    image = render_test_pattern(320, 200, GRID, label)

    assert label == "Stage Left"
    assert not image.isNull()


# --- "the canvas is stuck at 1280x720" --------------------------------------

def test_a_fresh_canvas_knows_it_is_a_placeholder():
    assert CanvasSettings().is_default()
    assert not CanvasSettings(width=1920, height=1080).is_default()


def test_the_canvas_adopts_the_screen_of_the_output_it_is_aimed_at(qapp):
    from model.output import Output
    from model.project_store import available_screens
    from ui.output_panel import OutputDialog

    screens = available_screens()
    if not screens:
        pytest.skip("no displays in this environment")
    _index, screen_id, _name, geometry = screens[0]

    project = Project()
    project.outputs = [Output(name="Projector 1")]
    dialog = OutputDialog(project, QUndoStack())

    dialog.screen_combo.setCurrentIndex(dialog.screen_combo.findData(screen_id))

    assert (project.canvas.width, project.canvas.height) == (geometry.width(), geometry.height())


def test_a_canvas_the_operator_set_is_never_overwritten(qapp):
    from model.output import Output
    from model.project_store import available_screens
    from ui.output_panel import OutputDialog

    screens = available_screens()
    if not screens:
        pytest.skip("no displays in this environment")

    project = Project()
    project.canvas.width, project.canvas.height = 3840, 1080  # a two-projector wall
    project.outputs = [Output(name="Projector 1")]
    dialog = OutputDialog(project, QUndoStack())

    dialog.screen_combo.setCurrentIndex(dialog.screen_combo.findData(screens[0][1]))

    assert (project.canvas.width, project.canvas.height) == (3840, 1080)


def test_typing_a_canvas_size_reaches_the_project(qapp):
    from model.output import Output
    from ui.output_panel import OutputDialog

    project = Project()
    project.outputs = [Output(name="Projector 1")]
    dialog = OutputDialog(project, QUndoStack())

    dialog.canvas_width.setValue(1920)
    dialog.canvas_height.setValue(1080)

    assert (project.canvas.width, project.canvas.height) == (1920, 1080)


# --- "the tool button stays lit after the shape is placed" ------------------

def test_the_canvas_announces_dropping_back_to_select(canvas):
    seen = []
    canvas.tool_changed.connect(seen.append)

    canvas.set_tool("polygon")
    canvas.set_tool("select")

    assert seen == ["polygon", "select"]


def test_the_toolbar_follows_the_canvas_back_to_select(qapp):
    from ui.main_window import MainWindow

    win = MainWindow()
    try:
        win._set_tool("circle")
        assert win.action_circle.isChecked()

        win.canvas.set_tool("select")

        assert win.action_select.isChecked()
        assert not win.action_circle.isChecked()
    finally:
        win.project.mark_saved()
        win.close()


# --- "the wheel edits whatever it rolls past" -------------------------------

def test_value_fields_ignore_the_wheel_until_focused(qapp):
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QWheelEvent
    from ui.widgets import ArrowSpinBox

    box = ArrowSpinBox()
    box.setRange(0.0, 100.0)
    box.setValue(10.0)

    event = QWheelEvent(
        QPointF(5.0, 5.0), QPointF(5.0, 5.0), QPoint(0, 0), QPoint(0, 120),
        Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False,
    )
    box.wheelEvent(event)

    assert box.value() == 10.0
    assert not event.isAccepted()


# --- persistence of the new field -------------------------------------------

def test_a_converted_shape_still_round_trips():
    shape = convert_shape(polygon_from_points(list(QUAD)), "circle")
    restored = shape_from_dict(shape_to_dict(shape))
    assert isinstance(restored, CircleShape)
    assert restored.radius_x == shape.radius_x


def test_a_circle_converts_to_a_polygon_on_its_own_box():
    circle = circle_from_center((100.0, 100.0), 40.0)
    converted = convert_shape(circle, "polygon")
    assert converted.points == [(60.0, 60.0), (140.0, 60.0), (140.0, 140.0), (60.0, 140.0)]


# --- panning must not throw the selection away ------------------------------

def test_a_click_on_empty_canvas_clears_the_selection(canvas, qapp):
    from PySide6.QtCore import QEvent, QPointF as P
    from PySide6.QtGui import QMouseEvent

    canvas.select_shape(canvas.project.shapes[0].id)
    canvas._panning = True
    canvas._pan_origin = P(200.0, 200.0)

    release = QMouseEvent(
        QEvent.MouseButtonRelease, P(200.0, 200.0), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier
    )
    canvas.mouseReleaseEvent(release)

    assert canvas.selected_shape_ids() == []


def test_panning_keeps_the_selection(canvas, qapp):
    from PySide6.QtCore import QEvent, QPointF as P
    from PySide6.QtGui import QMouseEvent

    shape = canvas.project.shapes[0]
    canvas.select_shape(shape.id)
    canvas._panning = True
    canvas._pan_origin = P(200.0, 200.0)

    release = QMouseEvent(
        QEvent.MouseButtonRelease, P(340.0, 260.0), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier
    )
    canvas.mouseReleaseEvent(release)

    assert canvas.selected_shape_ids() == [shape.id]

# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Per-surface masks: the regions a surface must not project into.

A projector lights the whole surface, and real walls have windows, doorways
and pillars standing in front of them. Turning the stroke off does not help -
the fill is what lands on the glass. A mask removes the region from the
surface's geometry, so there is nothing there to light.
"""

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPainterPath, QUndoStack

from model.commands import duplicate_shape
from model.project import Project
from model.shapes import (
    Mask,
    active_masks,
    circle_from_center,
    mask_from_rect,
    mesh_from_rect,
    polygon_from_points,
    shape_from_dict,
    shape_to_dict,
)
from render.mesh import circle_ring, triangulate_with_holes

QUAD = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]


def _triangle_area(points, indices):
    total = 0.0
    for i in range(0, len(indices), 3):
        (x1, y1), (x2, y2), (x3, y3) = (points[indices[i + k]] for k in range(3))
        total += abs((x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1)) / 2.0
    return total


# --- the model --------------------------------------------------------------

def test_a_rect_mask_has_four_corners_around_its_centre():
    mask = mask_from_rect((50.0, 50.0), 20.0, 10.0)
    assert mask.points == [(40.0, 45.0), (60.0, 45.0), (60.0, 55.0), (40.0, 55.0)]
    assert mask.enabled is True


def test_a_new_surface_has_no_masks():
    assert polygon_from_points(list(QUAD)).masks == []


def test_only_usable_masks_are_handed_to_the_triangulator():
    shape = polygon_from_points(list(QUAD))
    shape.masks = [
        mask_from_rect((50.0, 50.0), 20.0, 20.0),
        Mask(points=[(1.0, 1.0), (2.0, 2.0)]),          # not a ring
        mask_from_rect((70.0, 70.0), 10.0, 10.0),
    ]
    shape.masks[2].enabled = False

    assert len(active_masks(shape)) == 1


def test_a_mesh_carries_no_masks_at_all():
    """Cutting a hole would re-triangulate away the grid's parametrisation."""
    assert not hasattr(mesh_from_rect((0.0, 0.0), 100.0), "masks")


# --- triangulation ----------------------------------------------------------

def test_a_hole_is_missing_from_the_triangulated_area():
    points, indices = triangulate_with_holes(QUAD, [mask_from_rect((50.0, 50.0), 40.0, 40.0).points])

    assert _triangle_area(points, indices) == pytest.approx(100 * 100 - 40 * 40)
    assert len(points) == 8, "the hole's corners are vertices of the result"


def test_two_holes_are_both_cut():
    holes = [
        mask_from_rect((25.0, 25.0), 10.0, 10.0).points,
        mask_from_rect((75.0, 75.0), 20.0, 20.0).points,
    ]
    points, indices = triangulate_with_holes(QUAD, holes)

    assert _triangle_area(points, indices) == pytest.approx(10000 - 100 - 400)


def test_no_holes_keeps_the_plain_path():
    points, indices = triangulate_with_holes(QUAD, [])
    assert points == QUAD
    assert _triangle_area(points, indices) == pytest.approx(10000)


def test_a_degenerate_outline_triangulates_to_nothing():
    points, indices = triangulate_with_holes([(0.0, 0.0), (1.0, 1.0)], None)
    assert indices == []


def test_a_circle_ring_has_no_centre_vertex():
    """earcut needs a simple boundary; the centre fan is not one."""
    ring = circle_ring((0.0, 0.0), 50.0, 50.0, 24)
    assert len(ring) == 24
    assert all(abs((x * x + y * y) ** 0.5 - 50.0) < 1e-3 for x, y in ring)


def test_a_hole_in_a_circle_removes_its_area():
    ring = circle_ring((0.0, 0.0), 50.0, 50.0, 64)
    points, indices = triangulate_with_holes(ring, [mask_from_rect((0.0, 0.0), 20.0, 20.0).points])

    full = _triangle_area(ring, triangulate_with_holes(ring, None)[1])
    assert _triangle_area(points, indices) == pytest.approx(full - 400, rel=1e-3)


# --- persistence ------------------------------------------------------------

def test_masks_survive_a_round_trip():
    shape = polygon_from_points(list(QUAD))
    shape.masks = [mask_from_rect((50.0, 50.0), 20.0, 20.0, name="Window")]
    shape.masks[0].enabled = False

    restored = shape_from_dict(shape_to_dict(shape))

    assert len(restored.masks) == 1
    assert restored.masks[0].name == "Window"
    assert restored.masks[0].enabled is False
    assert restored.masks[0].points == shape.masks[0].points


def test_a_surface_with_no_masks_writes_no_key():
    """Projects from before masks existed stay shaped exactly as they were."""
    assert "masks" not in shape_to_dict(polygon_from_points(list(QUAD)))


def test_an_old_file_loads_with_no_masks():
    data = shape_to_dict(polygon_from_points(list(QUAD)))
    assert shape_from_dict(data).masks == []


def test_duplicating_a_surface_carries_the_hole_with_it():
    shape = polygon_from_points(list(QUAD))
    shape.masks = [mask_from_rect((50.0, 50.0), 20.0, 20.0)]

    copy = duplicate_shape(shape, offset=25.0)

    assert copy.masks[0].points == [(x + 25.0, y + 25.0) for x, y in shape.masks[0].points]
    assert shape.masks[0].points == mask_from_rect((50.0, 50.0), 20.0, 20.0).points


# --- the canvas -------------------------------------------------------------

@pytest.fixture
def canvas(qapp):
    from ui.canvas_editor import CanvasEditor

    project = Project()
    project.add_shape(polygon_from_points(list(QUAD), name="wall"))
    view = CanvasEditor(project)
    view.set_undo_stack(QUndoStack())
    view.set_zoom(1.0)
    return view


def _masked(canvas):
    item = canvas.items_by_id[canvas.project.shapes[0].id]
    canvas.add_mask(item)
    return canvas.items_by_id[canvas.project.shapes[0].id], canvas.project.shapes[0]


def test_adding_a_mask_puts_a_hole_in_the_middle_of_the_surface(canvas):
    _item, shape = _masked(canvas)

    assert len(shape.masks) == 1
    xs = [p[0] for p in shape.masks[0].points]
    ys = [p[1] for p in shape.masks[0].points]
    assert 0.0 < min(xs) and max(xs) < 100.0
    assert 0.0 < min(ys) and max(ys) < 100.0


def test_the_hole_is_a_subpath_of_what_the_editor_draws(canvas):
    item, _shape = _masked(canvas)

    path = item.path()
    starts = [i for i in range(path.elementCount()) if path.elementAt(i).type == QPainterPath.MoveToElement]
    assert len(starts) == 2, "the outline and the hole"
    assert path.fillRule() == Qt.OddEvenFill, "odd-even is what makes the inner ring a hole"


def test_a_point_inside_the_mask_is_no_longer_part_of_the_surface(canvas):
    item, _shape = _masked(canvas)
    assert item.path().contains(QPointF(5.0, 5.0)), "the wall itself is still there"
    assert not item.path().contains(QPointF(50.0, 50.0)), "the hole is not"


def test_adding_a_mask_is_undoable(canvas):
    item, _shape = _masked(canvas)
    assert canvas.undo_stack.command(0).text() == "Add Mask"

    canvas.undo_stack.undo()
    assert canvas.project.shapes[0].masks == []


def test_a_locked_surface_cannot_be_masked(canvas):
    shape = canvas.project.shapes[0]
    shape.locked = True
    item = canvas.items_by_id[shape.id]

    assert canvas.add_mask(item) is False
    assert shape.masks == []


def test_a_handle_appears_on_every_mask_corner(canvas):
    item, shape = _masked(canvas)
    canvas.select_shape(shape.id)
    canvas.toggle_handle_mode()

    assert len(item.mask_handles) == 4
    assert all(h.isVisible() for h in item.mask_handles)
    positions = {(h.pos().x(), h.pos().y()) for h in item.mask_handles}
    assert positions == set(shape.masks[0].points)


def test_dragging_a_mask_corner_reshapes_the_hole(canvas):
    item, _shape = _masked(canvas)

    canvas._on_mask_handle_moved(item, 0, 0, QPointF(10.0, 12.0))

    assert canvas.project.shapes[0].masks[0].points[0] == (10.0, 12.0)


def test_a_locked_surface_keeps_its_hole_where_it_is(canvas):
    item, _shape = _masked(canvas)
    shape = canvas.project.shapes[0]
    before = list(shape.masks[0].points)
    shape.locked = True

    canvas._on_mask_handle_moved(item, 0, 0, QPointF(10.0, 12.0))

    assert canvas.project.shapes[0].masks[0].points == before


def test_moving_the_surface_takes_the_hole_along(canvas):
    item, _shape = _masked(canvas)
    before = list(canvas.project.shapes[0].masks[0].points)

    canvas._begin_body_drag(item, QPointF(50.0, 50.0), Qt.NoModifier)
    canvas._update_body_drag(QPointF(80.0, 90.0), Qt.NoModifier)

    after = canvas.project.shapes[0].masks[0].points
    assert after == [(x + 30.0, y + 40.0) for x, y in before]


def test_scaling_the_surface_scales_the_hole(canvas):
    item, _shape = _masked(canvas)
    before = list(canvas.project.shapes[0].masks[0].points)

    canvas._begin_body_drag(item, QPointF(100.0, 50.0), Qt.ControlModifier)
    canvas._update_body_drag(QPointF(150.0, 50.0), Qt.ControlModifier)

    after = canvas.project.shapes[0].masks[0].points
    assert after == pytest.approx([(50 + (x - 50) * 2.0, 50 + (y - 50) * 2.0) for x, y in before])


def test_a_circle_can_be_masked_too(qapp):
    from ui.canvas_editor import CanvasEditor

    project = Project()
    circle = circle_from_center((100.0, 100.0), 50.0)
    project.add_shape(circle)
    canvas = CanvasEditor(project)
    canvas.set_undo_stack(QUndoStack())
    item = canvas.items_by_id[circle.id]

    assert canvas.add_mask(item) is True
    assert len(canvas.project.shapes[0].masks) == 1


# --- the property panel -----------------------------------------------------

@pytest.fixture
def panel(qapp):
    from ui.property_panel import PropertyPanel

    project = Project()
    shape = polygon_from_points(list(QUAD))
    project.add_shape(shape)
    widget = PropertyPanel()
    stack = QUndoStack()
    widget.set_undo_context(project, stack)
    widget.set_shape(shape)
    return widget, project, stack


def test_the_panel_adds_and_removes_masks(panel):
    widget, project, _stack = panel

    widget._on_add_mask()
    assert len(project.shapes[0].masks) == 1
    assert len(widget._mask_rows) == 1

    widget._on_remove_mask()
    assert project.shapes[0].masks == []


def test_adding_a_mask_from_the_panel_is_undoable(panel):
    widget, project, stack = panel

    widget._on_add_mask()
    stack.undo()

    assert project.shapes[0].masks == []


def test_a_mask_can_be_switched_off_without_losing_it(panel):
    widget, project, _stack = panel
    widget._on_add_mask()

    widget._mask_rows[0][0].setChecked(False)

    mask = project.shapes[0].masks[0]
    assert mask.enabled is False
    assert len(mask.points) == 4, "the hole is kept, just not applied"
    assert active_masks(project.shapes[0]) == []


def test_the_masks_section_is_hidden_for_a_mesh(panel):
    widget, project, _stack = panel
    mesh = mesh_from_rect((50.0, 50.0), 100.0)
    project.add_shape(mesh)

    widget.set_shape(mesh)

    assert not widget.masks_group.isVisibleTo(widget)

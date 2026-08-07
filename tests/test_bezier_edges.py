# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Curved polygon edges.

Arches, vaults and anything projected onto fabric have edges that bend. A
polygon that can only approximate them with more vertices is fiddly to place
and still wrong at the corners, so each edge carries its own cubic.

The invariant that makes the whole thing cheap: a cubic whose controls sit at
one and two thirds of the chord, with no perpendicular offset, *is* the
straight segment. Straight is therefore the default value, not a branch.
"""

import math

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QUndoStack

from model.project import Project
from model.shapes import (
    STRAIGHT_C1,
    STRAIGHT_C2,
    EdgeVisibility,
    polygon_from_points,
    shape_from_dict,
    shape_to_dict,
)
from render.mesh import (
    bezier_control_points,
    bezier_local_control,
    cubic_point,
    edge_samples,
    polygon_outline,
)

QUAD = [(100.0, 100.0), (200.0, 100.0), (200.0, 200.0), (100.0, 200.0)]


def _quad(curved_edge=None, offset=0.25):
    shape = polygon_from_points(list(QUAD), name="wall")
    shape.ensure_edges()
    if curved_edge is not None:
        shape.bow_edge(curved_edge, offset)
    return shape


# --- straight is the default value ------------------------------------------

def test_a_fresh_edge_is_straight():
    edge = EdgeVisibility()
    assert edge.curve1 == STRAIGHT_C1
    assert edge.curve2 == STRAIGHT_C2
    assert edge.curved is False


def test_the_straight_control_points_reproduce_the_chord():
    a, b = (0.0, 0.0), (90.0, 30.0)
    c1, c2 = bezier_control_points(a, b, STRAIGHT_C1, STRAIGHT_C2)

    assert c1 == pytest.approx((30.0, 10.0))
    assert c2 == pytest.approx((60.0, 20.0))
    for t in (0.0, 0.25, 0.5, 0.75, 1.0):
        point = cubic_point(a, c1, c2, b, t)
        assert point == pytest.approx((90.0 * t, 30.0 * t), abs=1e-9)


def test_straightening_undoes_a_bow_exactly():
    edge = EdgeVisibility()
    edge.bow(0.4)
    assert edge.curved
    edge.straighten()
    assert edge.curved is False


# --- edge-local coordinates -------------------------------------------------

def test_controls_are_stored_relative_to_the_edge():
    """Move the shape and the curve comes with it - no transform to forget."""
    a, b = (0.0, 0.0), (100.0, 0.0)
    c1, _c2 = bezier_control_points(a, b, (1 / 3, 0.5), STRAIGHT_C2)
    assert c1 == pytest.approx((100 / 3, 50.0))

    moved_a, moved_b = (40.0, 70.0), (140.0, 70.0)
    moved_c1, _ = bezier_control_points(moved_a, moved_b, (1 / 3, 0.5), STRAIGHT_C2)
    assert moved_c1 == pytest.approx((40 + 100 / 3, 120.0))


def test_the_bulge_scales_with_the_edge():
    """The perpendicular is the chord turned a quarter, not a unit vector."""
    short = bezier_control_points((0.0, 0.0), (10.0, 0.0), (0.5, 0.2), STRAIGHT_C2)[0]
    long = bezier_control_points((0.0, 0.0), (100.0, 0.0), (0.5, 0.2), STRAIGHT_C2)[0]

    assert short[1] == pytest.approx(2.0)
    assert long[1] == pytest.approx(20.0), "a curve must not flatten out as the shape grows"


def test_canvas_point_to_local_control_round_trips():
    a, b = (10.0, 20.0), (110.0, 90.0)
    local = (0.42, -0.3)
    canvas = bezier_control_points(a, b, local, STRAIGHT_C2)[0]
    assert bezier_local_control(a, b, canvas) == pytest.approx(local)


def test_a_degenerate_edge_reports_the_straight_control():
    assert bezier_local_control((5.0, 5.0), (5.0, 5.0), (9.0, 9.0)) == pytest.approx(STRAIGHT_C1)


# --- the outline ------------------------------------------------------------

def test_a_polygon_with_no_curves_comes_back_untouched():
    """The all-straight path stays cheap: no sampling, no extra points."""
    shape = _quad()
    assert shape.curve_pairs() is None
    assert shape.outline() == QUAD


def test_a_curved_edge_is_sampled_and_the_others_are_not():
    shape = _quad(curved_edge=0)
    outline = shape.outline(samples=16)

    # 16 samples for the curved edge, one vertex each for the other three.
    assert len(outline) == 16 + 3
    assert outline[0] == QUAD[0]
    assert outline[16] == QUAD[1]


def test_the_curve_actually_leaves_the_chord():
    shape = _quad(curved_edge=0, offset=0.25)
    outline = shape.outline()

    # Edge 0 runs left to right along y=100; the perpendicular sends it up.
    off_chord = [y for x, y in outline if 100.0 < x < 200.0]
    assert min(off_chord) < 90.0


def test_the_bow_is_symmetric_about_the_midpoint():
    a, b = (0.0, 0.0), (100.0, 0.0)
    edge = EdgeVisibility()
    edge.bow(0.3)
    walk = edge_samples(a, b, edge.curve1, edge.curve2, 20) + [b]

    for i in range(len(walk) // 2):
        left, right = walk[i], walk[-1 - i]
        assert left[1] == pytest.approx(right[1], abs=1e-9)
        assert left[0] == pytest.approx(100.0 - right[0], abs=1e-9)


def test_percent_truncates_a_curve_along_its_arc():
    a, b = (0.0, 0.0), (100.0, 0.0)
    edge = EdgeVisibility()
    edge.bow(0.3)
    half = edge_samples(a, b, edge.curve1, edge.curve2, 8, 0.5)
    full = edge_samples(a, b, edge.curve1, edge.curve2, 8, 1.0)

    assert half[0] == full[0]
    assert half[-1][0] < full[-1][0], "half the edge must not reach as far"


def test_polygon_outline_needs_no_curve_list():
    assert polygon_outline(QUAD, None) == QUAD
    assert polygon_outline(QUAD, []) == QUAD


def test_a_two_point_polygon_does_not_explode():
    assert polygon_outline([(0.0, 0.0), (1.0, 1.0)], None) == [(0.0, 0.0), (1.0, 1.0)]


# --- persistence ------------------------------------------------------------

def test_a_curved_edge_survives_a_round_trip():
    shape = _quad(curved_edge=1, offset=0.4)
    restored = shape_from_dict(shape_to_dict(shape))

    assert restored.edges[1].curved
    assert restored.edges[1].curve1 == pytest.approx(shape.edges[1].curve1)
    assert restored.edges[1].curve2 == pytest.approx(shape.edges[1].curve2)
    assert restored.edges[0].curved is False


def test_a_straight_edge_writes_nothing_extra():
    """Files from before curves existed stay byte-identical in shape."""
    data = shape_to_dict(_quad())
    assert all("curve1" not in edge for edge in data["edges"])


def test_an_old_file_reads_back_straight():
    edge = EdgeVisibility.from_dict({"visible": True, "percent": 1.0})
    assert edge.curved is False


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


def test_a_straight_polygon_draws_only_line_segments(canvas):
    from PySide6.QtGui import QPainterPath

    item = canvas.items_by_id[canvas.project.shapes[0].id]
    kinds = {item.path().elementAt(i).type for i in range(item.path().elementCount())}
    assert QPainterPath.CurveToElement not in kinds


def test_curving_an_edge_puts_a_cubic_in_the_path(canvas):
    from PySide6.QtGui import QPainterPath

    shape = canvas.project.shapes[0]
    item = canvas.items_by_id[shape.id]

    canvas.toggle_edge_curve(item, 0)

    kinds = [item.path().elementAt(i).type for i in range(item.path().elementCount())]
    assert QPainterPath.CurveToElement in kinds


def test_control_handles_appear_only_for_curved_edges(canvas):
    shape = canvas.project.shapes[0]
    item = canvas.items_by_id[shape.id]
    canvas.select_shape(shape.id)
    assert item.curve_handles == []

    canvas.toggle_edge_curve(item, 2)
    canvas.toggle_handle_mode()
    canvas._update_point_handles(item)

    assert [h.edge_index for h in item.curve_handles] == [2, 2]
    assert [h.slot for h in item.curve_handles] == [0, 1]
    assert all(h.isVisible() for h in item.curve_handles)


def test_the_handles_sit_on_the_control_points(canvas):
    shape = canvas.project.shapes[0]
    item = canvas.items_by_id[shape.id]
    canvas.select_shape(shape.id)
    canvas.toggle_edge_curve(item, 0)
    canvas._update_point_handles(item)

    expected = bezier_control_points(QUAD[0], QUAD[1], shape.edges[0].curve1, shape.edges[0].curve2)
    for handle, point in zip(item.curve_handles, expected):
        assert (handle.pos().x(), handle.pos().y()) == pytest.approx(point)


def test_dragging_a_control_handle_reshapes_the_curve(canvas):
    shape = canvas.project.shapes[0]
    item = canvas.items_by_id[shape.id]
    canvas.toggle_edge_curve(item, 0)

    canvas._on_curve_handle_moved(item, 0, 0, QPointF(133.0, 40.0))

    shape = canvas.project.shapes[0]
    # Edge 0 runs (100,100) -> (200,100): a 100-unit chord along +x, so the
    # frame's normal points *down* the screen and dragging up reads negative.
    assert shape.edges[0].curve1 == pytest.approx((0.33, -0.6))


def test_a_locked_shape_keeps_its_curve(canvas):
    shape = canvas.project.shapes[0]
    item = canvas.items_by_id[shape.id]
    canvas.toggle_edge_curve(item, 0)
    shape = canvas.project.shapes[0]
    before = shape.edges[0].curve1
    shape.locked = True

    canvas._on_curve_handle_moved(item, 0, 0, QPointF(133.0, 40.0))

    assert canvas.project.shapes[0].edges[0].curve1 == before


def test_curving_and_straightening_are_undoable(canvas):
    shape = canvas.project.shapes[0]
    item = canvas.items_by_id[shape.id]

    canvas.toggle_edge_curve(item, 1)
    assert shape.edges[1].curved
    assert canvas.undo_stack.command(0).text() == "Curve Edge"

    canvas.toggle_edge_curve(item, 1)
    assert canvas.project.shapes[0].edges[1].curved is False

    canvas.undo_stack.undo()
    assert canvas.project.shapes[0].edges[1].curved


def test_alt_double_click_finds_the_edge_under_the_cursor(canvas):
    shape = canvas.project.shapes[0]
    # Just below the top edge, which runs y = 100 between x = 100 and 200.
    assert canvas._edge_at(shape, QPointF(150.0, 103.0)) == 0
    # Just inside the left edge, which is edge 3.
    assert canvas._edge_at(shape, QPointF(103.0, 150.0)) == 3
    # Nowhere near anything.
    assert canvas._edge_at(shape, QPointF(150.0, 150.0)) is None


def test_the_edge_hit_test_follows_the_curve(canvas):
    shape = canvas.project.shapes[0]
    item = canvas.items_by_id[shape.id]
    canvas.toggle_edge_curve(item, 0)

    # The bowed top edge now passes well above y = 100; a click on the old
    # chord's midpoint is far from it, but a click on the bulge is not.
    assert canvas._edge_at(shape, QPointF(150.0, 81.0)) == 0


def test_a_moved_shape_carries_its_curve(canvas):
    shape = canvas.project.shapes[0]
    item = canvas.items_by_id[shape.id]
    canvas.toggle_edge_curve(item, 0)
    before = canvas.project.shapes[0].outline()

    canvas._begin_body_drag(item, QPointF(150.0, 150.0), Qt.NoModifier)
    canvas._update_body_drag(QPointF(170.0, 190.0), Qt.NoModifier)

    after = canvas.project.shapes[0].outline()
    assert after == pytest.approx([(x + 20.0, y + 40.0) for x, y in before])


def test_a_curved_edge_snaps_along_its_curve(canvas):
    """Another surface's corner must land on the edge as drawn."""
    shape = canvas.project.shapes[0]
    item = canvas.items_by_id[shape.id]
    canvas.toggle_edge_curve(item, 0)

    _vertices, edges = canvas._snap_candidates(exclude_shape_id=None)
    highest = min(min(a[1], b[1]) for a, b in edges)
    assert highest < 90.0, "the snap edges follow the bulge, not the chord"


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
    return widget, project, stack, shape


def test_every_edge_row_offers_a_curve_toggle(panel):
    widget, _project, _stack, _shape = panel
    assert len(widget._edge_rows) == 4
    assert all(len(row) == 3 for row in widget._edge_rows)


def test_ticking_curve_bends_the_edge(panel):
    widget, _project, _stack, shape = panel

    widget._edge_rows[2][2].setChecked(True)

    assert shape.edges[2].curved
    assert not shape.edges[0].curved


def test_unticking_curve_straightens_it_and_undo_restores_it(panel):
    widget, project, stack, shape = panel
    widget._edge_rows[0][2].setChecked(True)

    widget._edge_rows[0][2].setChecked(False)
    assert project.shapes[0].edges[0].curved is False

    stack.undo()
    assert project.shapes[0].edges[0].curved

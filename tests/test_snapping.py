# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest

from pm.model.snapping import (
    EDGE,
    GRID,
    VERTEX,
    closest_point_on_segment,
    find_snap,
    shape_edges,
    shape_vertices,
    snap_to_grid,
)

# A wall panel; the next panel's corners must land exactly on its right edge.
PANEL = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]


def test_vertex_beats_edge_and_grid():
    result = find_snap(
        (98.0, 2.0),
        vertices=shape_vertices(PANEL),
        edges=shape_edges(PANEL),
        threshold=12.0,
        grid_size=20.0,
    )
    assert result.kind == VERTEX
    assert result.point == (100.0, 0.0)


def test_edge_snap_lands_on_the_segment():
    result = find_snap(
        (104.0, 50.0),
        vertices=shape_vertices(PANEL),
        edges=shape_edges(PANEL),
        threshold=12.0,
    )
    assert result.kind == EDGE
    assert result.point == (100.0, 50.0)


def test_grid_is_the_last_resort():
    result = find_snap(
        (302.0, 398.0),
        vertices=shape_vertices(PANEL),
        edges=shape_edges(PANEL),
        threshold=12.0,
        grid_size=20.0,
    )
    assert result.kind == GRID
    assert result.point == (300.0, 400.0)


def test_nothing_within_threshold_returns_none():
    result = find_snap(
        (500.0, 500.0),
        vertices=shape_vertices(PANEL),
        edges=shape_edges(PANEL),
        threshold=5.0,
        grid_size=0.0,
    )
    assert result is None


def test_grid_can_be_suppressed():
    result = find_snap(
        (302.0, 398.0),
        vertices=[],
        edges=[],
        threshold=12.0,
        grid_size=20.0,
        use_grid=False,
    )
    assert result is None


def test_zero_threshold_disables_snapping():
    assert find_snap((0.0, 0.0), shape_vertices(PANEL), [], threshold=0.0) is None


def test_adjacent_panels_share_the_seam_exactly():
    """The point of the whole module: no sub-pixel gap at a corner."""
    neighbour_corner = (100.4, 99.6)
    result = find_snap(
        neighbour_corner,
        vertices=shape_vertices(PANEL),
        edges=shape_edges(PANEL),
        threshold=12.0,
    )
    assert result.point == (100.0, 100.0)
    assert result.point in [tuple(p) for p in PANEL]


def test_closest_point_clamps_to_the_segment_ends():
    a, b = (0.0, 0.0), (10.0, 0.0)
    assert closest_point_on_segment((-50.0, 3.0), a, b) == a
    assert closest_point_on_segment((50.0, 3.0), a, b) == b
    assert closest_point_on_segment((4.0, 3.0), a, b) == (4.0, 0.0)


def test_closest_point_on_a_degenerate_segment():
    a = (7.0, 7.0)
    assert closest_point_on_segment((0.0, 0.0), a, a) == a


@pytest.mark.parametrize(
    "point,expected",
    [((9.0, 9.0), (0.0, 0.0)), ((11.0, 11.0), (20.0, 20.0)), ((-9.0, -11.0), (0.0, -20.0))],
)
def test_snap_to_grid(point, expected):
    assert snap_to_grid(point, 20.0) == expected


def test_snap_to_grid_ignores_a_zero_grid():
    assert snap_to_grid((3.0, 7.0), 0.0) == (3.0, 7.0)


def test_shape_edges_closes_the_loop():
    edges = shape_edges(PANEL)
    assert len(edges) == len(PANEL)
    assert edges[-1] == ((0.0, 100.0), (0.0, 0.0))


def test_shape_edges_needs_two_points():
    assert shape_edges([(0.0, 0.0)]) == []


# --- canvas wiring -------------------------------------------------------

NEIGHBOUR = [(140.0, 0.0), (240.0, 0.0), (240.0, 100.0), (140.0, 100.0)]


@pytest.fixture
def canvas(qapp):
    from pm.model.project import Project
    from pm.model.shapes import polygon_from_points
    from pm.ui.canvas_editor import CanvasEditor

    project = Project()
    project.add_shape(polygon_from_points(list(PANEL), name="panel"))
    project.add_shape(polygon_from_points(list(NEIGHBOUR), name="neighbour"))
    view = CanvasEditor(project)
    view.set_zoom(1.0)
    return view


def _drag(canvas, shape_name, point):
    from PySide6.QtCore import QPointF

    shape = next(s for s in canvas.project.shapes if s.name == shape_name)
    item = canvas.items_by_id[shape.id]
    return canvas._snap_vertex(item, QPointF(*point))


def test_dragged_vertex_snaps_to_the_neighbouring_corner(canvas):
    result = _drag(canvas, "panel", (138.0, 2.0))
    assert (result.x(), result.y()) == (140.0, 0.0)


def test_a_shape_is_excluded_from_its_own_snap_targets(canvas):
    """Own edges sit zero pixels away and would pin the vertex in place."""
    panel = next(s for s in canvas.project.shapes if s.name == "panel")
    vertices, edges = canvas._snap_candidates(panel.id)

    assert set(vertices) == {tuple(p) for p in NEIGHBOUR}
    assert not any(a in {tuple(p) for p in PANEL} for a, _ in edges)


def test_hidden_surfaces_are_not_snap_targets(canvas):
    neighbour = next(s for s in canvas.project.shapes if s.name == "neighbour")
    neighbour.visible = False

    result = _drag(canvas, "panel", (138.0, 2.0))
    # Falls through to the grid instead of latching onto a surface nobody
    # can see.
    assert canvas.scene.snap_marker is None
    assert (result.x(), result.y()) == (140.0, 0.0)


def test_alt_bypasses_snapping(canvas, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication

    monkeypatch.setattr(
        QGuiApplication, "keyboardModifiers", staticmethod(lambda: Qt.AltModifier)
    )
    result = _drag(canvas, "panel", (138.0, 2.0))
    assert (result.x(), result.y()) == (138.0, 2.0)


def test_snap_toggle_disables_it(canvas):
    canvas.set_snap_enabled(False)
    result = _drag(canvas, "panel", (138.0, 2.0))
    assert (result.x(), result.y()) == (138.0, 2.0)


def test_magnet_radius_shrinks_in_scene_units_as_you_zoom_in(canvas):
    """The magnet should feel the same size on screen at any zoom."""
    far = (126.0, 0.0)  # 14 scene units from the neighbour's corner

    canvas.set_zoom(0.5)  # threshold becomes 24 scene units - catches it
    assert _drag(canvas, "panel", far).x() == 140.0

    canvas.set_zoom(4.0)  # threshold becomes 3 scene units - too far now
    assert _drag(canvas, "panel", far).x() == pytest.approx(126.0)


def test_geometry_snap_shows_a_marker_and_grid_does_not(canvas):
    _drag(canvas, "panel", (138.0, 2.0))
    assert canvas.scene.snap_marker is not None

    _drag(canvas, "panel", (602.0, 398.0))  # far from both panels, grid only
    assert canvas.scene.snap_marker is None

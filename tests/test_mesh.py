"""Deformation mesh: a surface that bends between its corners.

Corner pin describes a flat plane seen off-axis. A column, a dome or a hung
cloth is curved, and these tests pin down the two things that has to mean:
the surface passes through every control point the operator placed, and the
media follows the bend instead of shearing across it.
"""

import math

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QUndoStack

from pm.model.project import Project
from pm.model.shapes import MeshShape, mesh_from_rect, shape_from_dict, shape_to_dict
from pm.render.mesh import mesh_outline, tessellate_mesh

FLAT = mesh_from_rect((100.0, 100.0), 200.0, rows=2, cols=2)  # 0..200 square


def _flat_points(rows=2, cols=2):
    return mesh_from_rect((100.0, 100.0), 200.0, rows=rows, cols=cols).points


# --- the control grid -------------------------------------------------------

def test_a_new_mesh_is_a_flat_grid_of_the_right_size():
    mesh = mesh_from_rect((100.0, 100.0), 200.0, rows=2, cols=3)

    assert (mesh.grid_rows, mesh.grid_cols) == (3, 4)
    assert len(mesh.points) == 12
    assert mesh.point_at(0, 0) == (0.0, 0.0)
    assert mesh.point_at(2, 3) == (200.0, 200.0)


def test_points_are_row_major():
    mesh = mesh_from_rect((100.0, 100.0), 200.0, rows=1, cols=2)
    # Row 0 spans the top edge left to right, then row 1 the bottom.
    assert mesh.points[:3] == [(0.0, 0.0), (100.0, 0.0), (200.0, 0.0)]
    assert mesh.point_at(1, 0) == (0.0, 200.0)


# --- tessellation -----------------------------------------------------------

def test_the_patch_passes_through_every_control_point():
    """What the operator drags is where the surface goes - no approximation."""
    mesh = mesh_from_rect((100.0, 100.0), 200.0, rows=2, cols=2)
    points = list(mesh.points)
    points[4] = (140.0, 60.0)  # yank the middle control point
    mesh.points = points

    subdivisions = 6
    positions, _uvs, _indices = tessellate_mesh(mesh.points, 2, 2, subdivisions)
    stride = 2 * subdivisions + 1

    for row in range(mesh.grid_rows):
        for col in range(mesh.grid_cols):
            sampled = positions[(row * subdivisions) * stride + col * subdivisions]
            assert sampled == pytest.approx(mesh.point_at(row, col), abs=1e-6)


def test_a_flat_grid_tessellates_flat():
    positions, _uvs, _indices = tessellate_mesh(_flat_points(), 2, 2, 4)
    # Every sample sits inside the original square, none bulges out.
    assert min(x for x, _ in positions) == pytest.approx(0.0)
    assert max(x for x, _ in positions) == pytest.approx(200.0)
    # And the top row is a straight line, not a wobble.
    stride = 2 * 4 + 1
    assert all(y == pytest.approx(0.0) for _x, y in positions[:stride])


def test_bending_a_control_point_curves_the_span():
    """The point of the whole feature: the surface leaves the straight line."""
    points = _flat_points()
    points[1] = (100.0, -60.0)  # pull the top mid-point up
    positions, _uvs, _indices = tessellate_mesh(points, 2, 2, 4)

    stride = 2 * 4 + 1
    top_row = positions[:stride]
    quarter = top_row[stride // 4]
    assert quarter[1] < -5.0, "the span between corners has to bow, not kink"


def test_uvs_run_zero_to_one_across_the_grid():
    _positions, uvs, _indices = tessellate_mesh(_flat_points(), 2, 2, 3)
    stride = 2 * 3 + 1

    assert uvs[0] == pytest.approx((0.0, 0.0))
    assert uvs[stride - 1] == pytest.approx((1.0, 0.0))
    assert uvs[-1] == pytest.approx((1.0, 1.0))


def test_uvs_follow_the_bend_not_the_screen():
    """Media flows along the surface, so UV is parametric, not positional."""
    points = _flat_points()
    points[4] = (30.0, 170.0)  # drag the centre far off the middle
    positions, uvs, _indices = tessellate_mesh(points, 2, 2, 4)

    stride = 2 * 4 + 1
    centre_index = 4 * stride + 4
    assert positions[centre_index] == pytest.approx((30.0, 170.0), abs=1e-6)
    assert uvs[centre_index] == pytest.approx((0.5, 0.5)), "the centre of the media stays the centre of the surface"


def test_indices_cover_the_grid_twice_over():
    subdivisions = 5
    _positions, _uvs, indices = tessellate_mesh(_flat_points(2, 3), 2, 3, subdivisions)
    cells = (2 * subdivisions) * (3 * subdivisions)
    assert len(indices) == cells * 6  # two triangles per cell


def test_a_malformed_grid_tessellates_to_nothing_rather_than_crashing():
    assert tessellate_mesh([(0.0, 0.0)], 2, 2) == ([], [], [])
    assert tessellate_mesh(_flat_points(), 0, 2) == ([], [], [])


def test_the_edge_does_not_wrap_into_the_far_side():
    """Clamped neighbours: a pulled top-left must not drag the bottom-right."""
    points = _flat_points()
    points[0] = (-80.0, -80.0)
    positions, _uvs, _indices = tessellate_mesh(points, 2, 2, 4)

    stride = 2 * 4 + 1
    assert positions[-1] == pytest.approx((200.0, 200.0), abs=1e-6)
    assert positions[stride - 1] == pytest.approx((200.0, 0.0), abs=1e-6)


# --- outline ----------------------------------------------------------------

def test_the_outline_walks_the_boundary_once():
    subdivisions = 4
    outline = mesh_outline(_flat_points(), 2, 2, subdivisions)
    steps = 2 * subdivisions
    assert len(outline) == 4 * steps  # each side once, corners not repeated
    assert outline[0] == pytest.approx((0.0, 0.0))
    assert outline[steps] == pytest.approx((200.0, 0.0))


def test_the_outline_bends_with_the_control_points():
    points = _flat_points()
    points[1] = (100.0, -60.0)
    outline = mesh_outline(points, 2, 2, 4)
    assert min(y for _x, y in outline) < -50.0


# --- density ----------------------------------------------------------------

def test_raising_the_density_keeps_the_surface_where_it_was():
    """Adding detail late must not undo the bending already done."""
    mesh = mesh_from_rect((100.0, 100.0), 200.0, rows=2, cols=2)
    points = list(mesh.points)
    points[4] = (130.0, 70.0)
    mesh.points = points
    before, _uvs, _i = tessellate_mesh(mesh.points, 2, 2, 8)

    mesh.resize_grid(4, 4)

    assert (mesh.rows, mesh.cols) == (4, 4)
    assert len(mesh.points) == 25
    after, _uvs, _i = tessellate_mesh(mesh.points, 4, 4, 8)
    # Corners are untouched, and the bulge is still there.
    assert after[0] == pytest.approx(before[0], abs=1e-6)
    assert after[-1] == pytest.approx(before[-1], abs=1e-6)
    assert mesh.point_at(2, 2) == pytest.approx((130.0, 70.0), abs=1.0)


def test_lowering_the_density_resamples_rather_than_resetting():
    mesh = mesh_from_rect((100.0, 100.0), 200.0, rows=4, cols=4)
    points = list(mesh.points)
    points[12] = (60.0, 60.0)  # (row 2, col 2)
    mesh.points = points

    mesh.resize_grid(2, 2)

    assert (mesh.rows, mesh.cols) == (2, 2)
    assert len(mesh.points) == 9
    cx, cy = mesh.point_at(1, 1)
    assert (cx, cy) != (100.0, 100.0), "the surface kept its shape"
    assert math.hypot(cx - 60.0, cy - 60.0) < 45.0


def test_density_never_goes_below_one_cell():
    mesh = mesh_from_rect((100.0, 100.0), 200.0, rows=2, cols=2)
    mesh.resize_grid(0, 0)
    assert (mesh.rows, mesh.cols) == (1, 1)
    assert len(mesh.points) == 4


# --- persistence ------------------------------------------------------------

def test_a_mesh_survives_a_save_load_round_trip():
    mesh = mesh_from_rect((100.0, 100.0), 200.0, rows=2, cols=3, name="Column")
    points = list(mesh.points)
    points[5] = (77.0, 33.0)
    mesh.points = points
    mesh.media.fit_mode = "cover"

    restored = shape_from_dict(shape_to_dict(mesh))

    assert isinstance(restored, MeshShape)
    assert restored.type == "mesh"
    assert (restored.rows, restored.cols) == (2, 3)
    assert restored.points == mesh.points
    assert restored.name == "Column"
    assert restored.media.fit_mode == "cover"


def test_a_truncated_point_list_falls_back_to_a_flat_grid():
    """A hand-edited or half-written file must still open."""
    restored = MeshShape.from_dict({"type": "mesh", "rows": 2, "cols": 2, "points": [{"x": 1, "y": 2}]})
    assert len(restored.points) == 9


# --- the canvas -------------------------------------------------------------

@pytest.fixture
def canvas(qapp):
    from pm.ui.canvas_editor import CanvasEditor

    project = Project()
    project.add_shape(mesh_from_rect((100.0, 100.0), 200.0, rows=2, cols=2, name="wall"))
    view = CanvasEditor(project)
    view.set_undo_stack(QUndoStack())
    view.set_zoom(1.0)
    return view


def test_selecting_a_mesh_shows_a_handle_per_control_point(canvas):
    from pm.ui.canvas_editor import MeshItem

    mesh = canvas.project.shapes[0]
    canvas.select_shape(mesh.id)
    item = canvas.items_by_id[mesh.id]

    assert isinstance(item, MeshItem)
    assert len(item.handles) == 9
    assert all(h.isVisible() for h in item.handles)


def test_dragging_a_control_point_moves_only_that_point(canvas):
    mesh = canvas.project.shapes[0]
    item = canvas.items_by_id[mesh.id]
    before = list(mesh.points)

    canvas._on_mesh_handle_moved(item, 4, QPointF(140.0, 60.0))

    assert mesh.points[4] == (140.0, 60.0)
    assert mesh.points[:4] == before[:4]
    assert mesh.points[5:] == before[5:]


def test_a_locked_mesh_does_not_bend(canvas):
    mesh = canvas.project.shapes[0]
    mesh.locked = True
    item = canvas.items_by_id[mesh.id]
    before = list(mesh.points)

    canvas._on_mesh_handle_moved(item, 4, QPointF(140.0, 60.0))

    assert mesh.points == before


def test_bending_a_mesh_is_one_undo_step(canvas):
    mesh = canvas.project.shapes[0]
    item = canvas.items_by_id[mesh.id]
    canvas.select_shape(mesh.id)
    canvas._begin_edit_for(item)

    for y in (90.0, 80.0, 60.0):  # a drag arrives as many small moves
        canvas._on_mesh_handle_moved(item, 4, QPointF(140.0, y))
    canvas._commit_edit("Move Vertex")

    assert canvas.undo_stack.count() == 1
    canvas.undo_stack.undo()
    assert canvas.project.shapes[0].points[4] == (100.0, 100.0)


def test_dragging_the_body_carries_the_whole_grid(canvas):
    mesh = canvas.project.shapes[0]
    item = canvas.items_by_id[mesh.id]
    before = list(mesh.points)

    canvas._begin_body_drag(item, QPointF(100.0, 100.0), Qt.NoModifier)
    canvas._update_body_drag(QPointF(130.0, 150.0), Qt.NoModifier)

    assert mesh.points == [(x + 30.0, y + 50.0) for x, y in before]


def test_scaling_a_mesh_scales_every_control_point(canvas):
    mesh = canvas.project.shapes[0]
    item = canvas.items_by_id[mesh.id]

    canvas._begin_body_drag(item, QPointF(200.0, 100.0), Qt.ControlModifier)
    canvas._update_body_drag(QPointF(300.0, 100.0), Qt.ControlModifier)

    assert mesh.point_at(0, 0) == pytest.approx((-100.0, -100.0))
    assert mesh.point_at(2, 2) == pytest.approx((300.0, 300.0))


def test_another_shape_can_snap_to_a_mesh_control_point(canvas):
    from pm.model.shapes import polygon_from_points

    quad = polygon_from_points([(300.0, 300.0), (400.0, 300.0), (400.0, 400.0), (300.0, 400.0)])
    canvas.project.add_shape(quad)

    vertices, _edges = canvas._snap_candidates(quad.id)

    assert (200.0, 200.0) in vertices, "a mesh corner is a snap target like any other"


def test_a_mesh_does_not_snap_to_itself(canvas):
    mesh = canvas.project.shapes[0]
    vertices, _edges = canvas._snap_candidates(mesh.id)
    assert vertices == []


# --- the property panel -----------------------------------------------------

@pytest.fixture
def panel(qapp):
    from pm.ui.property_panel import PropertyPanel

    project = Project()
    mesh = mesh_from_rect((100.0, 100.0), 200.0, rows=2, cols=2)
    project.add_shape(mesh)
    widget = PropertyPanel()
    stack = QUndoStack()
    widget.set_undo_context(project, stack)
    widget.set_shape(mesh)
    return widget, project, stack, mesh


def test_the_density_control_appears_only_for_meshes(panel):
    from pm.model.shapes import polygon_from_points

    widget, _project, _stack, _mesh = panel
    assert widget.mesh_row.isVisibleTo(widget)

    widget.set_shape(polygon_from_points([(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]))
    assert not widget.mesh_row.isVisibleTo(widget)


def test_typing_a_density_reshapes_the_grid(panel):
    widget, _project, _stack, mesh = panel

    widget.mesh_cols.setValue(4)

    assert (mesh.rows, mesh.cols) == (2, 4)
    assert len(mesh.points) == 15


def test_changing_the_density_is_undoable(panel):
    widget, project, stack, mesh = panel

    widget.mesh_rows.setValue(3)
    assert mesh.rows == 3

    stack.undo()
    assert project.shapes[0].rows == 2
    assert len(project.shapes[0].points) == 9

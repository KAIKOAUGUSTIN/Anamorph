"""What the renderer costs per frame, and that it stops paying it twice.

The renderer repaints on a 16ms timer whether anything moved or not. Rebuilding
every surface's triangles each time capped a fifty-surface show at 16fps before
the GPU was handed a single vertex.

The budgets here are deliberately loose - they are regression guards, not
benchmarks, and they have to survive a loaded CI box. The measured numbers on
a laptop are two orders of magnitude under them.
"""

import time

import pytest

from pm.model.project import Project
from pm.model.shapes import (
    circle_from_center,
    mask_from_rect,
    mesh_from_rect,
    polygon_from_points,
)
from pm.render.geometry_cache import GeometryCache, build, signature


def _busy_project(count: int) -> Project:
    """A mix of every shape type, laid out like a facade."""
    project = Project()
    for index in range(count):
        x, y = (index % 20) * 60.0, (index // 20) * 60.0
        kind = index % 4
        if kind == 0:
            shape = polygon_from_points([(x, y), (x + 50, y), (x + 50, y + 50), (x, y + 50)])
        elif kind == 1:
            shape = polygon_from_points([(x, y), (x + 50, y), (x + 50, y + 50), (x, y + 50)])
            shape.bow_edge(0, 0.3)
        elif kind == 2:
            shape = mesh_from_rect((x + 25, y + 25), 50.0, rows=2, cols=2)
        else:
            shape = circle_from_center((x + 25, y + 25), 25.0)
            shape.masks = [mask_from_rect((x + 25, y + 25), 12.0, 12.0)]
        project.add_shape(shape)
    return project


def _frame(cache: GeometryCache, project: Project) -> None:
    cache.retain(shape.id for shape in project.shapes)
    for shape in project.shapes:
        cache.get(shape)


# --- the cache does what it says --------------------------------------------

def test_an_unchanged_frame_builds_nothing():
    project = _busy_project(40)
    cache = GeometryCache()

    _frame(cache, project)
    assert cache.misses == 40

    for _ in range(5):
        _frame(cache, project)

    assert cache.misses == 40, "geometry was rebuilt for surfaces that never moved"
    assert cache.hits == 200


def test_moving_one_surface_rebuilds_only_that_one():
    project = _busy_project(40)
    cache = GeometryCache()
    _frame(cache, project)
    before = cache.misses

    shape = project.shapes[0]
    shape.points = [(x + 5.0, y) for x, y in shape.points]
    _frame(cache, project)

    assert cache.misses == before + 1


def test_a_replaced_but_identical_shape_is_still_a_hit():
    """Undo swaps in a fresh object; keying on identity would rebuild the lot."""
    from pm.model.shapes import shape_from_dict, shape_to_dict

    project = _busy_project(8)
    cache = GeometryCache()
    _frame(cache, project)
    before = cache.misses

    project.shapes = [shape_from_dict(shape_to_dict(s)) for s in project.shapes]
    _frame(cache, project)

    assert cache.misses == before


def test_colour_and_opacity_do_not_move_a_vertex():
    """They change constantly during a show and must not invalidate anything."""
    shape = polygon_from_points([(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)])
    before = signature(shape)

    shape.fill_color = [1, 2, 3, 4]
    shape.opacity = 0.3
    shape.effects.pulse.enabled = True

    assert signature(shape) == before


def test_every_kind_of_geometry_change_is_noticed():
    polygon = polygon_from_points([(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)])
    base = signature(polygon)

    polygon.points = [(1.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    moved = signature(polygon)
    assert moved != base

    polygon.bow_edge(0, 0.3)
    curved = signature(polygon)
    assert curved != moved

    polygon.masks = [mask_from_rect((5.0, 5.0), 2.0, 2.0)]
    assert signature(polygon) != curved

    mesh = mesh_from_rect((0.0, 0.0), 40.0, rows=2, cols=2)
    dense = signature(mesh)
    mesh.resize_grid(3, 3)
    assert signature(mesh) != dense

    circle = circle_from_center((0.0, 0.0), 10.0)
    round_ = signature(circle)
    circle.radius_x = 20.0
    assert signature(circle) != round_


def test_deleted_surfaces_are_forgotten():
    """Otherwise a long session leaks exactly the data that is costly to hold."""
    project = _busy_project(20)
    cache = GeometryCache()
    _frame(cache, project)

    project.shapes = project.shapes[:5]
    _frame(cache, project)

    assert len(cache._entries) == 5


def test_a_mesh_is_tessellated_once_per_frame_not_twice():
    """Positions and UVs come out of the same call; asking separately doubled
    the cost of the single most expensive shape type."""
    project = Project()
    project.add_shape(mesh_from_rect((0.0, 0.0), 100.0, rows=2, cols=2))
    cache = GeometryCache()
    mesh = project.shapes[0]

    positions, uvs, indices = cache.get(mesh)
    again = cache.get(mesh)

    assert cache.misses == 1 and cache.hits == 1
    assert again[0] is positions and again[1] is uvs
    assert uvs and len(uvs) == len(positions)


def test_a_shape_type_with_no_geometry_is_handled():
    assert signature(object()) is None
    assert build(object()) == ([], None, [])


# --- budgets ----------------------------------------------------------------

# Measured at ~0.4ms for 200 surfaces; the ceiling is 50x that so a busy CI
# box cannot make this flap.
STEADY_FRAME_BUDGET_MS = 20.0
DRAG_FRAME_BUDGET_MS = 40.0


def _time_frames(cache, project, frames=10, mutate=None):
    for _ in range(2):  # warm
        _frame(cache, project)
    start = time.perf_counter()
    for index in range(frames):
        if mutate is not None:
            mutate(index)
        _frame(cache, project)
    return (time.perf_counter() - start) / frames * 1000.0


def test_two_hundred_surfaces_cost_almost_nothing_when_still():
    project = _busy_project(200)
    per_frame = _time_frames(GeometryCache(), project)

    assert per_frame < STEADY_FRAME_BUDGET_MS, f"{per_frame:.1f}ms per idle frame"


def test_dragging_a_mesh_in_a_busy_project_stays_interactive():
    project = _busy_project(200)
    mesh = next(s for s in project.shapes if hasattr(s, "rows"))

    def nudge(index):
        points = list(mesh.points)
        points[4] = (points[4][0] + 0.1 * index, points[4][1])
        mesh.points = points

    per_frame = _time_frames(GeometryCache(), project, mutate=nudge)

    assert per_frame < DRAG_FRAME_BUDGET_MS, f"{per_frame:.1f}ms per frame while dragging"


def test_the_vectorised_patch_beats_a_frame_budget():
    """One mesh's tessellation used to be 5ms on its own."""
    from pm.render.mesh import tessellate_mesh

    mesh = mesh_from_rect((0.0, 0.0), 100.0, rows=3, cols=3)
    tessellate_mesh(mesh.points, mesh.rows, mesh.cols)

    start = time.perf_counter()
    for _ in range(20):
        tessellate_mesh(mesh.points, mesh.rows, mesh.cols)
    per_call = (time.perf_counter() - start) / 20 * 1000.0

    assert per_call < 16.0, f"{per_call:.1f}ms to tessellate one mesh"

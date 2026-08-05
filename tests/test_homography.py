import numpy as np
import pytest

from pm.render.homography import (
    apply_matrix,
    canvas_to_uv_matrix,
    corner_uv_assignment,
)

# Axis-aligned square: the mapping degenerates to the affine bbox case.
SQUARE = [(0.0, 0.0), (200.0, 0.0), (200.0, 200.0), (0.0, 200.0)]

# Corner-pinned quad: top edge pulled in, the shape a projector produces when
# it is tilted relative to the surface.
TRAPEZOID = [(50.0, 0.0), (150.0, 0.0), (200.0, 200.0), (0.0, 200.0)]


def test_corner_uv_assignment_matches_vertex_order():
    assert corner_uv_assignment(SQUARE) == [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]


def test_corner_uv_assignment_follows_vertices_not_index():
    """A rotated vertex list must keep each corner pointing at the same UV."""
    rotated = SQUARE[2:] + SQUARE[:2]
    assert corner_uv_assignment(rotated) == [(1.0, 1.0), (0.0, 1.0), (0.0, 0.0), (1.0, 0.0)]


@pytest.mark.parametrize("count", [0, 3, 5, 6])
def test_corner_uv_assignment_rejects_non_quads(count):
    points = [(float(i), float(i * i)) for i in range(count)]
    assert corner_uv_assignment(points) is None
    assert canvas_to_uv_matrix(points) is None


@pytest.mark.parametrize("quad", [SQUARE, TRAPEZOID])
def test_corners_map_to_their_uvs(quad):
    matrix = canvas_to_uv_matrix(quad)
    assert matrix is not None
    for point, uv in zip(quad, corner_uv_assignment(quad)):
        assert apply_matrix(matrix, point) == pytest.approx(uv, abs=1e-9)


def test_square_stays_affine():
    """No perspective term for a rectangle, so existing projects are unchanged."""
    matrix = canvas_to_uv_matrix(SQUARE)
    assert matrix[2, :2] == pytest.approx([0.0, 0.0], abs=1e-12)

    # ...and it agrees with the bounding-box UVs the renderer computes today.
    for x, y in [(0.0, 0.0), (50.0, 120.0), (200.0, 200.0), (137.0, 3.0)]:
        assert apply_matrix(matrix, (x, y)) == pytest.approx((x / 200.0, y / 200.0), abs=1e-9)


def test_trapezoid_has_a_perspective_term():
    matrix = canvas_to_uv_matrix(TRAPEZOID)
    assert matrix is not None
    assert not np.allclose(matrix[2, :2], 0.0)


def test_diagonal_intersection_maps_to_uv_center():
    """The quad's diagonals cross where the media's diagonals cross - (0.5, 0.5).

    A projective map sends lines to lines, so this holds exactly. It is the
    sharpest check that the transform really is a homography.
    """
    matrix = canvas_to_uv_matrix(TRAPEZOID)
    # Diagonals of TRAPEZOID: (50,0)-(200,200) and (150,0)-(0,200).
    # Both cross at x = 100, y = 200/3.
    crossing = (100.0, 200.0 / 3.0)
    assert apply_matrix(matrix, crossing) == pytest.approx((0.5, 0.5), abs=1e-9)


def test_trapezoid_differs_from_linear_interpolation():
    """The gap this whole module exists to close.

    Linear interpolation across a triangulated quad puts UV (0.5, 0.5) at the
    average of the four corners; perspective puts it at the diagonal crossing.
    On a trapezoid those are different points, and the difference is the
    diagonal seam users see today.
    """
    matrix = canvas_to_uv_matrix(TRAPEZOID)
    centroid = (
        sum(p[0] for p in TRAPEZOID) / 4.0,
        sum(p[1] for p in TRAPEZOID) / 4.0,
    )
    u, v = apply_matrix(matrix, centroid)
    assert (u, v) != pytest.approx((0.5, 0.5), abs=1e-3)
    # The centroid sits below the diagonal crossing, so it samples lower in
    # the media than a linear fit would claim.
    assert v > 0.5


def test_degenerate_quad_returns_none():
    collinear = [(0.0, 0.0), (100.0, 0.0), (200.0, 0.0), (300.0, 0.0)]
    assert canvas_to_uv_matrix(collinear) is None

    coincident = [(10.0, 10.0), (10.0, 10.0), (10.0, 10.0), (10.0, 10.0)]
    assert canvas_to_uv_matrix(coincident) is None


def test_matrix_is_usable_as_float32():
    """The renderer uploads this as a mat3 uniform; precision must survive."""
    matrix = canvas_to_uv_matrix(TRAPEZOID).astype(np.float32)
    for point, uv in zip(TRAPEZOID, corner_uv_assignment(TRAPEZOID)):
        assert apply_matrix(matrix.astype(np.float64), point) == pytest.approx(uv, abs=1e-5)

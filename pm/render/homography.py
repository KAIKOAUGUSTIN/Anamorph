"""Perspective (projective) mapping of media onto four-corner surfaces.

A projector is almost never perpendicular to the surface it lights, so the
quad the user pins to a wall is a general quadrilateral, not a parallelogram.
Sampling the media with per-vertex UVs interpolated linearly across a
triangulated quad bends the image along the split diagonal; the correct
transform is a homography, computed here and applied per fragment.

Pure numpy on purpose: both the OpenGL output renderer and the editor preview
consume these functions, and neither Qt nor GL belongs in the math.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

import numpy as np

Point = Tuple[float, float]

# UV of the unit square, in the corner order used by _bbox_corners below.
CORNER_UVS: Tuple[Point, ...] = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))

# Below this, the quad is degenerate enough that solving for a homography
# produces coordinates that blow up across the surface.
_DEGENERATE_EPS = 1e-9


def _bbox_corners(points: Sequence[Point]) -> Tuple[Point, ...]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    return ((minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy))


def corner_uv_assignment(points: Sequence[Point]) -> Optional[List[Point]]:
    """Pair each vertex of a four-point shape with a corner of the media.

    The vertex order of a polygon is whatever the user left behind after
    dragging corners around, so corners are matched by proximity to the
    bounding box instead: nearest pair wins, then the next nearest pair among
    what is left. That keeps the media's orientation stable while a corner is
    being dragged.

    Returns one UV per input point, or None if the shape is not a quad.
    """
    if len(points) != 4:
        return None

    corners = _bbox_corners(points)

    distances = []
    for point_idx, (px, py) in enumerate(points):
        for corner_idx, (cx, cy) in enumerate(corners):
            distances.append(((px - cx) ** 2 + (py - cy) ** 2, point_idx, corner_idx))
    distances.sort()

    uvs: List[Point] = [(0.0, 0.0)] * 4
    assigned_points: set = set()
    used_corners: set = set()
    for _, point_idx, corner_idx in distances:
        if point_idx in assigned_points or corner_idx in used_corners:
            continue
        uvs[point_idx] = CORNER_UVS[corner_idx]
        assigned_points.add(point_idx)
        used_corners.add(corner_idx)

    return uvs


def canvas_to_uv_matrix(points: Sequence[Point]) -> Optional[np.ndarray]:
    """Homography taking canvas coordinates to media UVs for a quad.

    Applied to a canvas point as a homogeneous vector: ``h = H @ (x, y, 1)``,
    then ``uv = h.xy / h.z``. The division is what makes the mapping
    projective rather than affine, and it has to happen per sample - which is
    why callers hand this matrix to a fragment shader rather than baking UVs
    into vertices.

    Returns None for non-quads and for degenerate quads, leaving the caller on
    its bounding-box fallback.
    """
    uvs = corner_uv_assignment(points)
    if uvs is None:
        return None

    # Direct linear transform: eight unknowns (h22 is fixed at 1), two
    # equations per corner correspondence.
    a = np.zeros((8, 8), dtype=np.float64)
    b = np.zeros(8, dtype=np.float64)
    for i, ((x, y), (u, v)) in enumerate(zip(points, uvs)):
        a[i * 2] = (x, y, 1.0, 0.0, 0.0, 0.0, -u * x, -u * y)
        b[i * 2] = u
        a[i * 2 + 1] = (0.0, 0.0, 0.0, x, y, 1.0, -v * x, -v * y)
        b[i * 2 + 1] = v

    if abs(np.linalg.det(a)) < _DEGENERATE_EPS:
        return None

    try:
        solution = np.linalg.solve(a, b)
    except np.linalg.LinAlgError:
        return None

    if not np.all(np.isfinite(solution)):
        return None

    return np.append(solution, 1.0).reshape(3, 3)


def apply_matrix(matrix: np.ndarray, point: Point) -> Point:
    """Map a single canvas point through a homography. Mirrors the shader."""
    h = matrix @ np.array([point[0], point[1], 1.0], dtype=np.float64)
    if abs(h[2]) < _DEGENERATE_EPS:
        return (0.0, 0.0)
    return (float(h[0] / h[2]), float(h[1] / h[2]))

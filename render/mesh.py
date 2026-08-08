# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np

try:
    import mapbox_earcut as earcut
except Exception:  # pragma: no cover - optional dependency at runtime
    earcut = None


def triangulate_polygon(points: List[Tuple[float, float]]) -> List[int]:
    if len(points) < 3:
        return []
    if earcut is None:
        return _fan_triangulation(len(points))
    vertices = np.array(points, dtype=np.float32)
    holes = np.array([], dtype=np.uint32)
    try:
        indices = earcut.triangulate_float32(vertices, holes)
        return list(map(int, indices))
    except Exception:
        return _fan_triangulation(len(points))


# --- bezier edges -----------------------------------------------------------
#
# Not every surface is a straight-sided panel. Arches, vaults, curved risers
# and anything projected onto fabric have edges that bend, and a polygon that
# can only approximate them with more and more vertices is both fiddly to
# place and wrong at the corners.
#
# Controls are stored per edge in edge-local (t, n) units - see
# `EdgeVisibility` - so this module never has to know about the model.


def bezier_control_points(
    a: Tuple[float, float],
    b: Tuple[float, float],
    c1: Tuple[float, float],
    c2: Tuple[float, float],
) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """Edge-local `(t, n)` controls -> canvas coordinates.

    The perpendicular is the chord rotated a quarter turn, *not* normalised:
    that is what makes the curve scale with the shape instead of flattening
    out as the edge grows.
    """
    dx, dy = b[0] - a[0], b[1] - a[1]
    px, py = -dy, dx
    return (
        (a[0] + dx * c1[0] + px * c1[1], a[1] + dy * c1[0] + py * c1[1]),
        (a[0] + dx * c2[0] + px * c2[1], a[1] + dy * c2[0] + py * c2[1]),
    )


def bezier_local_control(
    a: Tuple[float, float],
    b: Tuple[float, float],
    point: Tuple[float, float],
) -> Tuple[float, float]:
    """The inverse: a canvas point -> edge-local `(t, n)`.

    Used when a control handle is dragged; a degenerate edge has no local
    frame, so it reports the straight control rather than dividing by zero.
    """
    dx, dy = b[0] - a[0], b[1] - a[1]
    length_sq = dx * dx + dy * dy
    if length_sq < 1e-12:
        return (1.0 / 3.0, 0.0)
    ox, oy = point[0] - a[0], point[1] - a[1]
    return ((ox * dx + oy * dy) / length_sq, (ox * -dy + oy * dx) / length_sq)


def cubic_point(
    a: Tuple[float, float],
    c1: Tuple[float, float],
    c2: Tuple[float, float],
    b: Tuple[float, float],
    t: float,
) -> Tuple[float, float]:
    u = 1.0 - t
    w0, w1, w2, w3 = u * u * u, 3.0 * u * u * t, 3.0 * u * t * t, t * t * t
    return (
        a[0] * w0 + c1[0] * w1 + c2[0] * w2 + b[0] * w3,
        a[1] * w0 + c1[1] * w1 + c2[1] * w2 + b[1] * w3,
    )


def edge_samples(
    a: Tuple[float, float],
    b: Tuple[float, float],
    c1: Tuple[float, float],
    c2: Tuple[float, float],
    samples: int = 16,
    fraction: float = 1.0,
) -> List[Tuple[float, float]]:
    """The edge as a point list, from `a` up to but not including `b`.

    `fraction` truncates it, which is what an edge's `percent` means: on a
    curve that has to be measured along the arc, not along the chord.
    """
    samples = max(1, int(samples))
    fraction = max(0.0, min(1.0, float(fraction)))
    p1, p2 = bezier_control_points(a, b, c1, c2)
    return [cubic_point(a, p1, p2, b, i / samples * fraction) for i in range(samples)]


def polygon_outline(
    points: List[Tuple[float, float]],
    curves: Optional[List[Tuple[Tuple[float, float], Tuple[float, float]]]] = None,
    samples: int = 16,
) -> List[Tuple[float, float]]:
    """The closed boundary of a polygon, with any curved edge sampled.

    `curves` is one `(c1, c2)` pair per edge, or None for an all-straight
    polygon. Straight edges contribute their start vertex alone, so a plain
    polygon comes back exactly as it went in - the triangulator, the stroke
    and the hit test all keep working on the cheap path.
    """
    if len(points) < 3:
        return list(points)
    if not curves:
        return list(points)

    outline: List[Tuple[float, float]] = []
    count = len(points)
    for idx in range(count):
        a = points[idx]
        b = points[(idx + 1) % count]
        pair = curves[idx] if idx < len(curves) else None
        if pair is None:
            outline.append(a)
            continue
        outline.extend(edge_samples(a, b, pair[0], pair[1], samples))
    return outline


def triangulate_with_holes(
    outer: List[Tuple[float, float]],
    holes: Optional[List[List[Tuple[float, float]]]] = None,
) -> Tuple[List[Tuple[float, float]], List[int]]:
    """Triangulate a ring with holes punched out of it.

    Returns the combined vertex list - outer ring first, then each hole - and
    indices into it, because the holes' points are real vertices of the result
    and the caller needs the same array the indices refer to.

    Falling back to the plain outline when the triangulator refuses is
    deliberate: a surface that renders without its mask is wrong, but a
    surface that renders as nothing at all is a black hole in the show.
    """
    if len(outer) < 3:
        return list(outer), []
    if not holes:
        return list(outer), triangulate_polygon(outer)
    if earcut is None:
        return list(outer), _fan_triangulation(len(outer))

    combined = list(outer)
    rings = [len(outer)]
    for hole in holes:
        if len(hole) < 3:
            continue
        combined.extend(hole)
        rings.append(len(combined))

    if len(rings) == 1:
        return list(outer), triangulate_polygon(outer)

    try:
        indices = earcut.triangulate_float32(
            np.array(combined, dtype=np.float32),
            np.array(rings, dtype=np.uint32),
        )
        return combined, list(map(int, indices))
    except Exception:
        return list(outer), triangulate_polygon(outer)


def curve_from_anchors(points: List[Tuple[float, float]], samples_per_seg: int = 12) -> List[Tuple[float, float]]:
    if len(points) < 3:
        return list(points)
    if samples_per_seg < 4:
        samples_per_seg = 4
    out: List[Tuple[float, float]] = []
    n = len(points)
    for i in range(n):
        p0x, p0y = points[(i - 1) % n]
        p1x, p1y = points[i % n]
        p2x, p2y = points[(i + 1) % n]
        p3x, p3y = points[(i + 2) % n]
        for s in range(samples_per_seg):
            t = s / samples_per_seg
            t2 = t * t
            t3 = t2 * t
            x = 0.5 * (
                (2 * p1x)
                + (-p0x + p2x) * t
                + (2 * p0x - 5 * p1x + 4 * p2x - p3x) * t2
                + (-p0x + 3 * p1x - 3 * p2x + p3x) * t3
            )
            y = 0.5 * (
                (2 * p1y)
                + (-p0y + p2y) * t
                + (2 * p0y - 5 * p1y + 4 * p2y - p3y) * t2
                + (-p0y + 3 * p1y - 3 * p2y + p3y) * t3
            )
            out.append((float(x), float(y)))
    return out


def circle_ring(
    center: Tuple[float, float],
    radius_x: float,
    radius_y: float,
    segments: int = 48,
) -> List[Tuple[float, float]]:
    """The ellipse's boundary alone, with no centre vertex.

    `triangulate_circle` fans from the centre, which is faster but is not a
    simple ring - and a hole has to be cut out of a simple ring.
    """
    segments = max(12, int(segments))
    cx, cy = center
    rx = max(float(radius_x), 1.0)
    ry = max(float(radius_y), 1.0)
    two_pi = 2.0 * 3.141592653589793
    return [
        (float(cx + rx * np.cos(i / segments * two_pi)), float(cy + ry * np.sin(i / segments * two_pi)))
        for i in range(segments)
    ]


def triangulate_circle(
    center: Tuple[float, float],
    radius_x: float,
    radius_y: float,
    segments: int = 48,
) -> Tuple[List[Tuple[float, float]], List[int]]:
    if segments < 12:
        segments = 12
    if segments == 0:
        segments = 12
    cx, cy = center
    rx = max(float(radius_x), 1.0)
    ry = max(float(radius_y), 1.0)
    points: List[Tuple[float, float]] = [(cx, cy)]
    for i in range(segments + 1):
        angle = (i / segments) * (2.0 * 3.141592653589793)
        x = cx + rx * np.cos(angle)
        y = cy + ry * np.sin(angle)
        points.append((float(x), float(y)))
    indices: List[int] = []
    # `segments + 1` ring points, the last one repeating the first, so the fan
    # needs `segments` wedges. Stopping one short left a slice of the circle
    # missing on the projector - a pie with a piece taken out.
    for i in range(1, segments + 1):
        indices.extend([0, i, i + 1])
    return points, indices


def _fan_triangulation(count: int) -> List[int]:
    indices: List[int] = []
    for i in range(1, count - 1):
        indices.extend([0, i, i + 1])
    return indices


# --- deformation mesh -------------------------------------------------------
#
# A quad is enough for a flat wall. Columns, cylinders, domes and stretched
# fabric are not flat, and pinning four corners cannot describe them at all -
# the surface has to bend between its corners.
#
# The control grid is coarse because that is what a person can actually drag.
# It is smoothed into a dense render mesh here: a Catmull-Rom patch passes
# through every control point, so what the operator positions is exactly where
# the surface goes, with curvature filled in between.


def _catmull_rom(p0: float, p1: float, p2: float, p3: float, t: float) -> float:
    t2 = t * t
    t3 = t2 * t
    return 0.5 * (
        (2.0 * p1)
        + (-p0 + p2) * t
        + (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * t2
        + (-p0 + 3.0 * p1 - 3.0 * p2 + p3) * t3
    )


def _catmull_weights(t: np.ndarray) -> np.ndarray:
    """The four Catmull-Rom basis weights at each `t`, as an (n, 4) array."""
    t = np.asarray(t, dtype=np.float64)
    t2 = t * t
    t3 = t2 * t
    return 0.5 * np.stack(
        [
            -t + 2.0 * t2 - t3,
            2.0 - 5.0 * t2 + 3.0 * t3,
            t + 4.0 * t2 - 3.0 * t3,
            -t2 + t3,
        ],
        axis=-1,
    )


def _clamped(grid: List[List[Tuple[float, float]]], row: int, col: int) -> Tuple[float, float]:
    """Neighbour lookup that repeats the edge instead of wrapping.

    Catmull-Rom needs a point either side of the span. Wrapping would pull the
    far edge of the surface into the near one; clamping just flattens the
    curvature at the boundary, which is what a surface edge should do.
    """
    rows = len(grid)
    cols = len(grid[0])
    return grid[max(0, min(rows - 1, row))][max(0, min(cols - 1, col))]


def _patch_point(
    grid: List[List[Tuple[float, float]]], row: int, col: int, u: float, v: float
) -> Tuple[float, float]:
    """Interpolate inside the cell whose top-left control point is (row, col)."""
    columns = []
    for offset in range(-1, 3):
        r = row + offset
        x = _catmull_rom(
            _clamped(grid, r, col - 1)[0], _clamped(grid, r, col)[0],
            _clamped(grid, r, col + 1)[0], _clamped(grid, r, col + 2)[0], u,
        )
        y = _catmull_rom(
            _clamped(grid, r, col - 1)[1], _clamped(grid, r, col)[1],
            _clamped(grid, r, col + 1)[1], _clamped(grid, r, col + 2)[1], u,
        )
        columns.append((x, y))

    x = _catmull_rom(columns[0][0], columns[1][0], columns[2][0], columns[3][0], v)
    y = _catmull_rom(columns[0][1], columns[1][1], columns[2][1], columns[3][1], v)
    return (x, y)


def tessellate_mesh(
    points: List[Tuple[float, float]],
    rows: int,
    cols: int,
    subdivisions: int = 6,
) -> Tuple[List[Tuple[float, float]], List[Tuple[float, float]], List[int]]:
    """Smooth a control grid into (positions, uvs, indices) for drawing.

    `points` is row-major over a (rows + 1) x (cols + 1) grid of control
    points. UVs come from the parametric position in the grid, so media flows
    across the surface as it bends - and `source_rect` and the media transform
    still compose on top in the shader.

    Subdivision is what keeps per-vertex UVs honest: interpolating them across
    a coarse cell would be visibly wrong, but across a subdivided one the
    error is far below a pixel.
    """
    grid_rows, grid_cols = rows + 1, cols + 1
    if rows < 1 or cols < 1 or len(points) != grid_rows * grid_cols:
        return [], [], []

    subdivisions = max(1, int(subdivisions))
    steps_x = cols * subdivisions
    steps_y = rows * subdivisions

    # Vectorised, because this runs for every mesh on every frame. The Python
    # triple loop it replaces cost about 5ms per mesh - a dozen columns and
    # the show was under 30fps before the GPU had drawn anything. The maths is
    # unchanged: a Catmull-Rom patch evaluated at every subdivision point.
    grid = np.asarray(points, dtype=np.float64).reshape(grid_rows, grid_cols, 2)

    # Which cell each sample falls in, and where inside it.
    gx = np.arange(steps_x + 1, dtype=np.float64) / subdivisions
    gy = np.arange(steps_y + 1, dtype=np.float64) / subdivisions
    col_index = np.minimum(gx.astype(np.int64), cols - 1)
    row_index = np.minimum(gy.astype(np.int64), rows - 1)
    u = gx - col_index
    v = gy - row_index

    # The four control points either side of the span, clamped at the edges so
    # the surface flattens there instead of wrapping into itself.
    cols_idx = np.clip(col_index[:, None] + np.arange(-1, 3)[None, :], 0, grid_cols - 1)
    rows_idx = np.clip(row_index[:, None] + np.arange(-1, 3)[None, :], 0, grid_rows - 1)

    wu = _catmull_weights(u)            # (steps_x + 1, 4)
    wv = _catmull_weights(v)            # (steps_y + 1, 4)

    # Interpolate along x first: (rows_of_grid, steps_x + 1, 2)
    along_x = np.einsum("rsjc,sj->rsc", grid[:, cols_idx, :], wu)
    # Then along y, gathering the four rows each sample needs.
    stacked = along_x[rows_idx]         # (steps_y + 1, 4, steps_x + 1, 2)
    grid_points = np.einsum("tjsc,tj->tsc", stacked, wv)

    positions = [(float(x), float(y)) for x, y in grid_points.reshape(-1, 2)]

    us = np.arange(steps_x + 1, dtype=np.float64) / steps_x
    vs = np.arange(steps_y + 1, dtype=np.float64) / steps_y
    uv_grid = np.stack(np.broadcast_arrays(us[None, :], vs[:, None]), axis=-1)
    uvs = [(float(a), float(b)) for a, b in uv_grid.reshape(-1, 2)]

    stride = steps_x + 1
    top_left = (
        np.arange(steps_y, dtype=np.int64)[:, None] * stride
        + np.arange(steps_x, dtype=np.int64)[None, :]
    )
    quads = np.stack(
        [
            top_left, top_left + 1, top_left + stride + 1,
            top_left, top_left + stride + 1, top_left + stride,
        ],
        axis=-1,
    )
    indices = quads.reshape(-1).tolist()

    return positions, uvs, indices


def mesh_outline(
    points: List[Tuple[float, float]],
    rows: int,
    cols: int,
    subdivisions: int = 6,
) -> List[Tuple[float, float]]:
    """The smoothed boundary, for stroking and for hit testing."""
    positions, _uvs, _indices = tessellate_mesh(points, rows, cols, subdivisions)
    if not positions:
        return []

    steps_x = cols * subdivisions
    steps_y = rows * subdivisions
    stride = steps_x + 1

    outline: List[Tuple[float, float]] = []
    outline.extend(positions[0:stride])                                   # top
    outline.extend(positions[(r + 1) * stride + steps_x] for r in range(steps_y))  # right
    outline.extend(positions[steps_y * stride + steps_x - c - 1] for c in range(steps_x))  # bottom
    # Left side stops one short of the top-left: the caller closes the path,
    # and repeating the start point would give a zero-length closing segment.
    outline.extend(positions[(steps_y - r - 1) * stride] for r in range(steps_y - 1))  # left
    return outline

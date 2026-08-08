# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Magnetic snapping for vertex dragging.

Two surfaces meeting at a corner have to share the seam exactly. A gap of one
pixel is invisible on screen and shows up on the wall as a black line through
the projection, so snapping is not a convenience here - it is what makes
adjacent surfaces usable.

Priority is vertex, then edge, then grid: an exact corner match is always
worth more than landing on a round number.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

Point = Tuple[float, float]

VERTEX = "vertex"
EDGE = "edge"
GRID = "grid"


@dataclass(frozen=True)
class SnapResult:
    point: Point
    kind: str

    @property
    def is_magnetic(self) -> bool:
        """True for snaps to other geometry, as opposed to the background grid."""
        return self.kind in (VERTEX, EDGE)


def _distance(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def closest_point_on_segment(point: Point, a: Point, b: Point) -> Point:
    abx, aby = b[0] - a[0], b[1] - a[1]
    length_sq = abx * abx + aby * aby
    if length_sq == 0.0:
        return a
    t = ((point[0] - a[0]) * abx + (point[1] - a[1]) * aby) / length_sq
    t = max(0.0, min(1.0, t))
    return (a[0] + abx * t, a[1] + aby * t)


def snap_to_grid(point: Point, grid_size: float) -> Point:
    if grid_size <= 0:
        return point
    return (
        round(point[0] / grid_size) * grid_size,
        round(point[1] / grid_size) * grid_size,
    )


def find_snap(
    point: Point,
    vertices: Iterable[Point],
    edges: Iterable[Tuple[Point, Point]],
    threshold: float,
    grid_size: float = 0.0,
    use_grid: bool = True,
) -> Optional[SnapResult]:
    """Nearest snap target within `threshold`, or None.

    `threshold` is in scene units; callers scale it by the zoom so the magnet
    feels the same size on screen regardless of how far in the user is.
    """
    if threshold <= 0:
        return None

    best: Optional[Point] = None
    best_distance = threshold
    for candidate in vertices:
        distance = _distance(point, candidate)
        if distance < best_distance:
            best, best_distance = candidate, distance
    if best is not None:
        return SnapResult(best, VERTEX)

    best_distance = threshold
    for a, b in edges:
        candidate = closest_point_on_segment(point, a, b)
        distance = _distance(point, candidate)
        if distance < best_distance:
            best, best_distance = candidate, distance
    if best is not None:
        return SnapResult(best, EDGE)

    if use_grid and grid_size > 0:
        candidate = snap_to_grid(point, grid_size)
        if _distance(point, candidate) < threshold:
            return SnapResult(candidate, GRID)

    return None


def shape_vertices(points: Sequence[Point]) -> List[Point]:
    return [(float(x), float(y)) for x, y in points]


def shape_edges(points: Sequence[Point]) -> List[Tuple[Point, Point]]:
    if len(points) < 2:
        return []
    return [
        ((float(points[i][0]), float(points[i][1])),
         (float(points[(i + 1) % len(points)][0]), float(points[(i + 1) % len(points)][1])))
        for i in range(len(points))
    ]

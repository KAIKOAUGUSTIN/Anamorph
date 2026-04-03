from __future__ import annotations

from typing import List, Tuple

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
    for i in range(1, segments):
        indices.extend([0, i, i + 1])
    return points, indices


def _fan_triangulation(count: int) -> List[int]:
    indices: List[int] = []
    for i in range(1, count - 1):
        indices.extend([0, i, i + 1])
    return indices

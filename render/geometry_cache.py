# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-only

"""Per-frame geometry, computed only when the geometry actually changed.

The renderer repaints on a 16ms timer whether anything moved or not, and it
used to rebuild every surface's triangles from scratch each time. Fifty
surfaces cost 60ms of Python before the GPU was handed a single vertex - the
show was capped at 16fps by work whose answer had not changed.

The cache is keyed on a signature of the shape's geometry, not on its object
identity: undo *replaces* a shape rather than mutating it, so identity says
"new shape" for something that is often bit-for-bit what was there before, and
a dragged corner mutates in place without changing identity at all.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from model.shapes import CircleShape, MeshShape, PolygonShape, active_masks
from render.mesh import (
    circle_ring,
    tessellate_mesh,
    triangulate_circle,
    triangulate_with_holes,
)

Point = Tuple[float, float]
# (positions, uvs or None, indices). UVs are only carried for meshes, whose
# parametric UVs come out of the same tessellation - computing them separately
# meant tessellating every mesh twice per frame.
Geometry = Tuple[List[Point], Optional[List[Point]], List[int]]


def signature(shape: Any) -> Optional[Tuple]:
    """Everything the shape's triangles depend on, and nothing else.

    Colour, opacity and effects are absent on purpose: they change constantly
    during a show and none of them moves a vertex.
    """
    masks = tuple(tuple(ring) for ring in active_masks(shape))
    if isinstance(shape, MeshShape):
        return ("mesh", shape.rows, shape.cols, tuple(shape.points))
    if isinstance(shape, PolygonShape):
        curves = shape.curve_pairs()
        return (
            "polygon",
            tuple(shape.points),
            tuple(curves) if curves else None,
            masks,
        )
    if isinstance(shape, CircleShape):
        return ("circle", tuple(shape.center), shape.radius_x, shape.radius_y, masks)
    return None


def build(shape: Any) -> Geometry:
    """Triangulate a shape from scratch."""
    holes = active_masks(shape)
    if isinstance(shape, MeshShape):
        positions, uvs, indices = tessellate_mesh(shape.points, shape.rows, shape.cols)
        return positions, uvs, indices
    if isinstance(shape, PolygonShape):
        points, indices = triangulate_with_holes(shape.outline(), holes)
        return points, None, indices
    if isinstance(shape, CircleShape):
        if holes:
            # A hole has to be cut out of a simple ring, not out of a fan.
            points, indices = triangulate_with_holes(
                circle_ring(shape.center, shape.radius_x, shape.radius_y), holes
            )
            return points, None, indices
        points, indices = triangulate_circle(shape.center, shape.radius_x, shape.radius_y, 48)
        return points, None, indices
    return [], None, []


class GeometryCache:
    """One entry per shape id, invalidated by the geometry signature."""

    def __init__(self) -> None:
        self._entries: Dict[str, Tuple[Tuple, Geometry]] = {}
        self.hits = 0
        self.misses = 0

    def get(self, shape: Any) -> Geometry:
        key = signature(shape)
        if key is None:
            return [], None, []
        cached = self._entries.get(shape.id)
        if cached is not None and cached[0] == key:
            self.hits += 1
            return cached[1]
        self.misses += 1
        geometry = build(shape)
        self._entries[shape.id] = (key, geometry)
        return geometry

    def retain(self, shape_ids) -> None:
        """Forget shapes that are no longer in the project.

        Without this a long session of adding and deleting surfaces leaves the
        cache holding every one of them - a slow leak of exactly the data that
        is expensive to hold.
        """
        keep = set(shape_ids)
        for shape_id in [k for k in self._entries if k not in keep]:
            del self._entries[shape_id]

    def clear(self) -> None:
        self._entries.clear()

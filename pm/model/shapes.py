from __future__ import annotations

from dataclasses import dataclass, field
import uuid
from typing import Any, Dict, List, Optional, Tuple, Union

from pm.model.effects import Effects
from pm.model.media import MediaRef


def new_shape_id() -> str:
    return uuid.uuid4().hex[:8]


def default_fill_color() -> List[int]:
    return [40, 120, 220, 200]


def default_stroke_color() -> List[int]:
    return [220, 220, 220, 255]


@dataclass
class EdgeVisibility:
    visible: bool = True
    percent: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "visible": self.visible,
            "percent": float(self.percent),
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "EdgeVisibility":
        if not data:
            return EdgeVisibility()
        return EdgeVisibility(
            visible=bool(data.get("visible", True)),
            percent=float(data.get("percent", 1.0)),
        )


@dataclass
class PolygonShape:
    id: str
    name: str
    points: List[Tuple[float, float]]
    edges: List[EdgeVisibility]
    fill_color: List[int] = field(default_factory=default_fill_color)
    stroke_color: List[int] = field(default_factory=default_stroke_color)
    stroke_width: float = 2.0
    opacity: float = 1.0
    blend_mode: str = "normal"
    media: MediaRef = field(default_factory=MediaRef)
    effects: Effects = field(default_factory=Effects)
    visible: bool = True
    locked: bool = False

    @property
    def type(self) -> str:
        return "polygon"

    def ensure_edges(self) -> None:
        count = len(self.points)
        if count <= 0:
            self.edges = []
            return
        if len(self.edges) < count:
            for _ in range(count - len(self.edges)):
                self.edges.append(EdgeVisibility())
        elif len(self.edges) > count:
            self.edges = self.edges[:count]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PolygonShape":
        points = [
            (float(p.get("x", 0.0)), float(p.get("y", 0.0)))
            for p in data.get("points", [])
        ]
        edges = [EdgeVisibility.from_dict(e) for e in data.get("edges", [])]
        shape = cls(
            id=data.get("id", new_shape_id()),
            name=data.get("name", "Polígono"),
            points=points,
            edges=edges,
            **_common_shape_kwargs(data),
        )
        shape.ensure_edges()
        return shape


@dataclass
class CircleShape:
    id: str
    name: str
    center: Tuple[float, float]
    radius_x: float
    radius_y: float
    anchors: List[Tuple[float, float]] = field(default_factory=list)
    fill_color: List[int] = field(default_factory=default_fill_color)
    stroke_color: List[int] = field(default_factory=default_stroke_color)
    stroke_width: float = 2.0
    opacity: float = 1.0
    blend_mode: str = "normal"
    media: MediaRef = field(default_factory=MediaRef)
    effects: Effects = field(default_factory=Effects)
    visible: bool = True
    locked: bool = False

    @property
    def type(self) -> str:
        return "circle"

    @property
    def radius(self) -> float:
        return (self.radius_x + self.radius_y) / 2.0

    @radius.setter
    def radius(self, value: float) -> None:
        self.radius_x = float(value)
        self.radius_y = float(value)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CircleShape":
        center = data.get("center", {})
        radius_x = data.get("radius_x")
        radius_y = data.get("radius_y")
        if radius_x is None or radius_y is None:
            radius_val = float(data.get("radius", 40.0))
            radius_x = radius_x if radius_x is not None else radius_val
            radius_y = radius_y if radius_y is not None else radius_val
        shape = cls(
            id=data.get("id", new_shape_id()),
            name=data.get("name", "Círculo"),
            center=(float(center.get("x", 0.0)), float(center.get("y", 0.0))),
            radius_x=float(radius_x),
            radius_y=float(radius_y),
            anchors=[
                (float(p.get("x", 0.0)), float(p.get("y", 0.0)))
                for p in data.get("anchors", [])
            ],
            **_common_shape_kwargs(data),
        )
        if shape.anchors:
            xs = [p[0] for p in shape.anchors]
            ys = [p[1] for p in shape.anchors]
            minx, maxx = min(xs), max(xs)
            miny, maxy = min(ys), max(ys)
            shape.center = ((minx + maxx) / 2.0, (miny + maxy) / 2.0)
            shape.radius_x = max((maxx - minx) / 2.0, 1.0)
            shape.radius_y = max((maxy - miny) / 2.0, 1.0)
        else:
            cx, cy = shape.center
            shape.anchors = [
                (cx, cy - shape.radius_y),
                (cx + shape.radius_x, cy),
                (cx, cy + shape.radius_y),
                (cx - shape.radius_x, cy),
            ]
        return shape


@dataclass
class MeshShape:
    """A surface that bends: a grid of control points, not four corners.

    Corner pin describes a flat plane seen off-axis. A column, a cylinder, a
    dome or a hung cloth is curved, and no arrangement of four corners can
    express that - the surface has to bend between them. `rows` and `cols`
    count cells, so the control grid holds (rows + 1) x (cols + 1) points in
    row-major order.

    Coarse on purpose: the grid is what a person drags. Curvature between the
    control points is filled in by `tessellate_mesh`.
    """

    id: str
    name: str
    rows: int
    cols: int
    points: List[Tuple[float, float]]
    fill_color: List[int] = field(default_factory=default_fill_color)
    stroke_color: List[int] = field(default_factory=default_stroke_color)
    stroke_width: float = 2.0
    opacity: float = 1.0
    blend_mode: str = "normal"
    media: MediaRef = field(default_factory=MediaRef)
    effects: Effects = field(default_factory=Effects)
    visible: bool = True
    locked: bool = False

    @property
    def type(self) -> str:
        return "mesh"

    @property
    def grid_rows(self) -> int:
        return self.rows + 1

    @property
    def grid_cols(self) -> int:
        return self.cols + 1

    def point_at(self, row: int, col: int) -> Tuple[float, float]:
        return self.points[row * self.grid_cols + col]

    def resize_grid(self, rows: int, cols: int) -> None:
        """Change the grid density, keeping the surface where it is.

        The new control points are sampled from the current patch, so raising
        the density adds detail without moving anything the operator already
        placed.
        """
        from pm.render.mesh import tessellate_mesh

        rows = max(1, int(rows))
        cols = max(1, int(cols))
        if (rows, cols) == (self.rows, self.cols):
            return

        positions, _uvs, _indices = tessellate_mesh(self.points, self.rows, self.cols, 8)
        if not positions:
            return
        steps_x = self.cols * 8
        steps_y = self.rows * 8
        stride = steps_x + 1

        sampled: List[Tuple[float, float]] = []
        for r in range(rows + 1):
            for c in range(cols + 1):
                iy = round(r / rows * steps_y)
                ix = round(c / cols * steps_x)
                sampled.append(positions[iy * stride + ix])

        self.rows, self.cols, self.points = rows, cols, sampled

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MeshShape":
        rows = max(1, int(data.get("rows", 2)))
        cols = max(1, int(data.get("cols", 2)))
        points = [
            (float(p.get("x", 0.0)), float(p.get("y", 0.0)))
            for p in data.get("points", [])
        ]
        expected = (rows + 1) * (cols + 1)
        if len(points) != expected:
            points = _flat_grid((0.0, 0.0), (200.0, 200.0), rows, cols)
        return cls(
            id=data.get("id", new_shape_id()),
            name=data.get("name", "Malha"),
            rows=rows,
            cols=cols,
            points=points,
            **_common_shape_kwargs(data),
        )


Shape = Union[PolygonShape, CircleShape, MeshShape]


def _common_shape_kwargs(data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "fill_color": list(data.get("fill_color", default_fill_color())),
        "stroke_color": list(data.get("stroke_color", default_stroke_color())),
        "stroke_width": float(data.get("stroke_width", 2.0)),
        "opacity": float(data.get("opacity", 1.0)),
        "blend_mode": data.get("blend_mode", "normal"),
        "media": MediaRef.from_dict(data.get("media", {})),
        "effects": Effects.from_dict(data.get("effects", {})),
        "visible": bool(data.get("visible", True)),
        "locked": bool(data.get("locked", False)),
    }


def _flat_grid(
    top_left: Tuple[float, float],
    bottom_right: Tuple[float, float],
    rows: int,
    cols: int,
) -> List[Tuple[float, float]]:
    x0, y0 = top_left
    x1, y1 = bottom_right
    return [
        (x0 + (x1 - x0) * (c / cols), y0 + (y1 - y0) * (r / rows))
        for r in range(rows + 1)
        for c in range(cols + 1)
    ]


def mesh_from_rect(
    center: Tuple[float, float],
    size: float,
    rows: int = 2,
    cols: int = 2,
    name: Optional[str] = None,
) -> MeshShape:
    """A flat grid to start from; the operator bends it into the surface."""
    half = size / 2.0
    cx, cy = center
    return MeshShape(
        id=new_shape_id(),
        name=name or "Malha",
        rows=max(1, rows),
        cols=max(1, cols),
        points=_flat_grid((cx - half, cy - half), (cx + half, cy + half), max(1, rows), max(1, cols)),
    )


def polygon_from_points(points: List[Tuple[float, float]], name: Optional[str] = None) -> PolygonShape:
    shape = PolygonShape(
        id=new_shape_id(),
        name=name or "Polígono",
        points=points,
        edges=[EdgeVisibility() for _ in range(len(points))],
    )
    shape.ensure_edges()
    return shape


def circle_from_center(center: Tuple[float, float], radius: float, name: Optional[str] = None) -> CircleShape:
    cx, cy = center
    anchors = [
        (cx, cy - radius),
        (cx + radius, cy),
        (cx, cy + radius),
        (cx - radius, cy),
    ]
    return CircleShape(
        id=new_shape_id(),
        name=name or "Círculo",
        center=center,
        radius_x=radius,
        radius_y=radius,
        anchors=anchors,
    )


def shape_to_dict(shape: Shape) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "id": shape.id,
        "type": shape.type,
        "name": shape.name,
        "fill_color": shape.fill_color,
        "stroke_color": shape.stroke_color,
        "stroke_width": float(shape.stroke_width),
        "opacity": float(shape.opacity),
        "blend_mode": shape.blend_mode,
        "media": shape.media.to_dict(),
        "effects": shape.effects.to_dict(),
        "visible": shape.visible,
        "locked": shape.locked,
    }
    if isinstance(shape, PolygonShape):
        data["points"] = [{"x": p[0], "y": p[1]} for p in shape.points]
        data["edges"] = [edge.to_dict() for edge in shape.edges]
    elif isinstance(shape, MeshShape):
        data["rows"] = int(shape.rows)
        data["cols"] = int(shape.cols)
        data["points"] = [{"x": p[0], "y": p[1]} for p in shape.points]
    elif isinstance(shape, CircleShape):
        data["center"] = {"x": shape.center[0], "y": shape.center[1]}
        data["radius"] = float(shape.radius)
        data["radius_x"] = float(shape.radius_x)
        data["radius_y"] = float(shape.radius_y)
        if shape.anchors:
            data["anchors"] = [{"x": p[0], "y": p[1]} for p in shape.anchors]
    return data


def shape_from_dict(data: Dict[str, Any]) -> Shape:
    shape_type = data.get("type", "polygon")
    if shape_type == "polygon":
        return PolygonShape.from_dict(data)
    elif shape_type == "circle":
        return CircleShape.from_dict(data)
    elif shape_type == "mesh":
        return MeshShape.from_dict(data)
    return PolygonShape.from_dict(data)

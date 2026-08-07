# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

import numpy as np

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QTransform,
)
from PySide6.QtGui import QGuiApplication, QUndoStack
from PySide6.QtWidgets import QStyle
from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsView,
)

from pm.media.availability import is_missing
from pm.media.clip_pool import clip_pool
from pm.media.image_cache import get_qimage
from pm.model.commands import AddShapeCommand, EditSession
from pm.model.project import Project
from pm.model.snapping import (
    closest_point_on_segment,
    find_snap,
    shape_edges,
    shape_vertices,
    snap_to_grid,
)
from pm.model.shapes import (
    DEFAULT_CIRCLE_NAME, DEFAULT_MESH_NAME, DEFAULT_POLYGON_NAME,
    CircleShape, EdgeVisibility, MeshShape, PolygonShape, Shape,
    active_masks, circle_from_center, mask_from_rect, mesh_from_rect,
    polygon_from_points,
)
from pm.render.fit import content_rect
from pm.render.mesh import (
    bezier_control_points,
    bezier_local_control,
    cubic_point,
    edge_samples,
    mesh_outline,
    tessellate_mesh,
)
from pm.render.homography import corner_uv_assignment


class CanvasScene(QGraphicsScene):
    def __init__(self, project: Project) -> None:
        super().__init__()
        self.project = project
        self.grid_size = 20
        self.workspace_background = QColor(10, 10, 12)
        # Set while a drag is latched onto another surface; drawn last so the
        # user can see the magnet engage under the cursor.
        self.snap_marker: Optional[QPointF] = None
        # Bounding box of the selection, and where its rotate grip floats.
        self.transform_box: Optional[QRectF] = None
        self.transform_pivot: Optional[QPointF] = None

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawBackground(painter, rect)
        # Dark workspace background
        painter.fillRect(rect, self.workspace_background)

        canvas_rect = QRectF(0, 0, self.project.canvas.width, self.project.canvas.height)

        # Canvas area with subtle gradient
        painter.fillRect(canvas_rect, QColor(*self.project.canvas.background_color))

        # Refined grid
        painter.save()
        painter.setClipRect(canvas_rect)
        painter.setPen(QPen(QColor(26, 26, 30), 1))
        left = int(canvas_rect.left()) - (int(canvas_rect.left()) % self.grid_size)
        top = int(canvas_rect.top()) - (int(canvas_rect.top()) % self.grid_size)
        right = int(canvas_rect.right())
        bottom = int(canvas_rect.bottom())
        for x in range(left, right + 1, self.grid_size):
            painter.drawLine(x, canvas_rect.top(), x, canvas_rect.bottom())
        for y in range(top, bottom + 1, self.grid_size):
            painter.drawLine(canvas_rect.left(), y, canvas_rect.right(), y)
        painter.restore()

        # Accent border for canvas
        painter.setPen(QPen(QColor(42, 42, 46), 2))
        painter.drawRect(canvas_rect)

        # Corner markers
        corner_size = 12
        painter.setPen(QPen(QColor(0, 212, 170), 2))
        # Top-left
        painter.drawLine(canvas_rect.left(), canvas_rect.top(), canvas_rect.left() + corner_size, canvas_rect.top())
        painter.drawLine(canvas_rect.left(), canvas_rect.top(), canvas_rect.left(), canvas_rect.top() + corner_size)
        # Top-right
        painter.drawLine(canvas_rect.right() - corner_size, canvas_rect.top(), canvas_rect.right(), canvas_rect.top())
        painter.drawLine(canvas_rect.right(), canvas_rect.top(), canvas_rect.right(), canvas_rect.top() + corner_size)
        # Bottom-left
        painter.drawLine(canvas_rect.left(), canvas_rect.bottom() - corner_size, canvas_rect.left(), canvas_rect.bottom())
        painter.drawLine(canvas_rect.left(), canvas_rect.bottom(), canvas_rect.left() + corner_size, canvas_rect.bottom())
        # Bottom-right
        painter.drawLine(canvas_rect.right() - corner_size, canvas_rect.bottom(), canvas_rect.right(), canvas_rect.bottom())
        painter.drawLine(canvas_rect.right(), canvas_rect.bottom() - corner_size, canvas_rect.right(), canvas_rect.bottom())

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawForeground(painter, rect)
        scale = painter.worldTransform().m11() or 1.0

        # Blackout kills the projectors, not the editor - you go on working
        # while the wall is dark. Which means the editor has to say so loudly,
        # or the next twenty minutes are spent wondering why nothing is
        # showing up outside.
        if self.project.blackout:
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, True)
            canvas_rect = QRectF(0, 0, self.project.canvas.width, self.project.canvas.height)
            painter.setBrush(QColor(200, 40, 50, 28))
            painter.setPen(QPen(QColor(220, 60, 70, 220), 3.0 / scale))
            painter.drawRect(canvas_rect)
            painter.restore()

        # The box itself, so the grips read as corners of something rather
        # than as four unexplained dots floating near the shape.
        if self.transform_box is not None:
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(150, 150, 160, 130), 1.0 / scale, Qt.DashLine))
            painter.drawRect(self.transform_box)
            if self.transform_pivot is not None:
                painter.setPen(QPen(QColor(255, 176, 46, 150), 1.0 / scale))
                painter.drawLine(
                    QPointF(self.transform_pivot.x(), self.transform_box.top()),
                    self.transform_pivot,
                )
            painter.restore()

        if self.snap_marker is None:
            return
        # Sized in scene units against the current zoom so the ring stays the
        # same size on screen however far in the user is.
        radius = 9.0 / scale
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(255, 176, 46), 2.0 / scale))
        painter.drawEllipse(self.snap_marker, radius, radius)
        painter.drawLine(
            QPointF(self.snap_marker.x() - radius * 1.7, self.snap_marker.y()),
            QPointF(self.snap_marker.x() + radius * 1.7, self.snap_marker.y()),
        )
        painter.drawLine(
            QPointF(self.snap_marker.x(), self.snap_marker.y() - radius * 1.7),
            QPointF(self.snap_marker.x(), self.snap_marker.y() + radius * 1.7),
        )
        painter.restore()


def media_frame(media, transport=None) -> Optional[QImage]:
    """The image to draw for a surface right now: a still, or a live frame."""
    if media.kind == "image":
        return get_qimage(media.path)
    if media.kind not in ("video", "camera"):
        return None

    show_time = transport.position() if transport is not None else 0.0
    frame, size = clip_pool().frame(media, show_time)
    if frame is None or size == (0, 0):
        return None
    # Wrapped, not copied: the pool hands out its own array and QImage borrows
    # it for the length of this paint. `.copy()` here would be a full-frame
    # memcpy per surface per repaint.
    return QImage(frame.data, size[0], size[1], frame.strides[0], QImage.Format_RGB888)


def paint_missing_marker(painter: QPainter, path: QPainterPath) -> None:
    """Hatch a surface whose media is not on disk.

    Drawn instead of the flat fill colour, because a surface that falls back
    to its fill looks exactly like a surface nobody has assigned media to yet.
    """
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    # A base tint under a bright hatch. The hatch alone was nearly invisible
    # against the dark workspace, which defeats the point: this has to read
    # across a room, at a glance, in the dark.
    painter.fillPath(path, QBrush(QColor(60, 18, 22)))
    painter.fillPath(path, QBrush(QColor(215, 70, 80, 170), Qt.BDiagPattern))
    painter.restore()


def _paint_media(painter: QPainter, shape: Shape, path: QPainterPath, transport=None) -> bool:
    """Draw a shape's media into the editor, matching what gets projected.

    Corner-pinned quads go through QTransform.quadToQuad, which is the same
    homography the output shader applies - so what the user drags here is what
    lands on the wall. Returns False when there is nothing to draw and the
    caller should fall back to the flat fill colour.

    Video and camera feeds are previewed too, now that decoders are shared:
    the editor asks the same pool the projectors do, so a clip already playing
    on the wall costs nothing extra to show here. Calibrating a surface
    against an empty rectangle was guesswork.
    """
    media = getattr(shape, "media", None)
    if not media or not media.kind:
        return False

    image = media_frame(media, transport)
    if image is None:
        return False

    painter.save()
    painter.setClipPath(path)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

    mode = (media.fit_mode or "stretch").lower()
    region = media.source_rect.normalised()
    # The slice of the file that feeds this surface, in image pixels.
    source = QRectF(
        region.u0 * image.width(),
        region.v0 * image.height(),
        region.width * image.width(),
        region.height * image.height(),
    )

    transform = None
    if mode == "warp" and isinstance(shape, PolygonShape):
        transform = _warp_transform(shape, image, region)

    if transform is not None:
        # The transform maps the region onto the quad, so the rest of the
        # image lands outside it and the clip path above removes it.
        painter.setTransform(transform, True)
        painter.drawImage(0, 0, image)
    else:
        # Same `content_rect` the renderer builds its UVs from, so contain
        # letterboxes and cover crops here exactly as they do on the wall.
        # Painting the bounding box directly - which is what this used to do -
        # stretched every mode, and the canvas quietly disagreed with the
        # output for contain and cover.
        box = _fit_box(shape, path)
        offset_x, offset_y, content_w, content_h = content_rect(
            box.width(), box.height(), source.width(), source.height(), mode
        )
        painter.drawImage(
            QRectF(box.x() + offset_x, box.y() + offset_y, content_w, content_h),
            image,
            source,
        )

    painter.restore()
    return True


def _paint_mesh_media(painter: QPainter, shape: MeshShape, transport=None) -> bool:
    """Draw media across a bent surface, triangle by triangle.

    QPainter has no mesh primitive, so each tessellated triangle is filled
    with an affine map from its own slice of the media. Across a subdivided
    patch the pieces are small enough that the seams do not read - and this is
    the preview; the projector gets the same UVs through the shader.
    """
    media = getattr(shape, "media", None)
    if not media or not media.kind:
        return False
    image = media_frame(media, transport)
    if image is None:
        return False

    positions, uvs, indices = tessellate_mesh(shape.points, shape.rows, shape.cols)
    if not indices:
        return False

    region = media.source_rect.normalised()
    width, height = image.width(), image.height()

    painter.save()
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    # Antialiasing off for this pass: an antialiased clip edge blends with
    # whatever is behind it, so every shared triangle edge would show up as a
    # pale hairline and the tessellation would be visible through the media.
    painter.setRenderHint(QPainter.Antialiasing, False)
    for i in range(0, len(indices), 3):
        tri = indices[i:i + 3]
        target = QPolygonF([QPointF(*positions[k]) for k in tri])
        source = QPolygonF([
            QPointF((region.u0 + uvs[k][0] * region.width) * width,
                    (region.v0 + uvs[k][1] * region.height) * height)
            for k in tri
        ])
        transform = _triangle_transform(source, target)
        if transform is None:
            continue
        painter.save()
        painter.setClipPath(_polygon_path(target))
        painter.setTransform(transform, True)
        painter.drawImage(0, 0, image)
        painter.restore()
    painter.restore()
    return True


def _triangle_transform(source: QPolygonF, target: QPolygonF) -> Optional[QTransform]:
    """Affine map between two triangles.

    QTransform.quadToQuad needs four distinct corners and refuses a triangle
    with a repeated point, so the 2x3 affine is solved directly. Three point
    pairs determine it exactly - no homography needed, and none wanted: the
    curvature lives in the tessellation, not in each tiny face.
    """
    a = np.array([[source[i].x(), source[i].y(), 1.0] for i in range(3)], dtype=np.float64)
    if abs(np.linalg.det(a)) < 1e-12:
        return None
    try:
        col_x = np.linalg.solve(a, np.array([target[i].x() for i in range(3)], dtype=np.float64))
        col_y = np.linalg.solve(a, np.array([target[i].y() for i in range(3)], dtype=np.float64))
    except np.linalg.LinAlgError:
        return None

    return QTransform(col_x[0], col_y[0], col_x[1], col_y[1], col_x[2], col_y[2])


# The editor has to composite the way the projector does, or the preview goes
# back to lying about the output - the failure this codebase has spent the most
# effort on. QPainter's modes are the same operations the GL blend pairs are.
COMPOSITION_MODES = {
    "normal": QPainter.CompositionMode_SourceOver,
    "add": QPainter.CompositionMode_Plus,
    "screen": QPainter.CompositionMode_Screen,
    "multiply": QPainter.CompositionMode_Multiply,
}


def apply_blend_mode(painter: QPainter, shape) -> None:
    mode = (getattr(shape, "blend_mode", "normal") or "normal").lower()
    painter.setCompositionMode(COMPOSITION_MODES.get(mode, QPainter.CompositionMode_SourceOver))


def clear_blend_mode(painter: QPainter) -> None:
    """Handles, outlines and selection marks are UI, not artwork."""
    painter.setCompositionMode(QPainter.CompositionMode_SourceOver)


def polygon_path(shape: PolygonShape) -> QPainterPath:
    """The polygon's outline, curved edges included.

    Qt draws the cubic exactly, so the preview is not a sampled approximation
    of the shape the renderer tessellates - both are the same curve, and the
    editor keeps telling the truth about what will be projected.
    """
    path = QPainterPath()
    points = shape.points
    if not points:
        return path

    shape.ensure_edges()
    path.moveTo(*points[0])
    count = len(points)
    for idx in range(count):
        a = points[idx]
        b = points[(idx + 1) % count]
        edge = shape.edges[idx] if idx < len(shape.edges) else None
        if edge is not None and edge.curved:
            c1, c2 = bezier_control_points(a, b, edge.curve1, edge.curve2)
            path.cubicTo(c1[0], c1[1], c2[0], c2[1], b[0], b[1])
        else:
            path.lineTo(b[0], b[1])
    path.closeSubpath()
    return add_mask_subpaths(path, shape)


def add_mask_subpaths(path: QPainterPath, shape) -> QPainterPath:
    """Punch the shape's masks out of `path`.

    A closed inner subpath under the odd-even fill rule is a hole - the same
    path then serves as the fill *and* as the media's clip, so a window stays
    dark in the preview for exactly the same reason it does on the wall.
    """
    rings = active_masks(shape)
    if not rings:
        return path
    path.setFillRule(Qt.OddEvenFill)
    for ring in rings:
        path.moveTo(*ring[0])
        for point in ring[1:]:
            path.lineTo(*point)
        path.closeSubpath()
    return path


def _fit_box(shape, path: QPainterPath) -> QRectF:
    """The box a fit mode measures against.

    The renderer builds its UVs from the *sampled* outline, so a curved
    polygon has to be measured the same way here. Qt's exact path bounds and
    a 16-sample walk differ by a fraction of a pixel, and a fraction of a
    pixel is exactly the sort of drift that makes the editor and the output
    disagree once someone zooms in on a seam.
    """
    if isinstance(shape, PolygonShape):
        outline = shape.outline()
        xs = [p[0] for p in outline]
        ys = [p[1] for p in outline]
        return QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
    if isinstance(shape, CircleShape):
        rx, ry = max(shape.radius_x, 1.0), max(shape.radius_y, 1.0)
        return QRectF(shape.center[0] - rx, shape.center[1] - ry, rx * 2, ry * 2)
    return path.boundingRect()


def _edge_path(a, b, edge) -> QPainterPath:
    """One curved edge, truncated to its `percent` along the arc."""
    path = QPainterPath()
    walk = edge_samples(a, b, edge.curve1, edge.curve2, 24, edge.percent)
    c1, c2 = bezier_control_points(a, b, edge.curve1, edge.curve2)
    walk.append(cubic_point(a, c1, c2, b, max(0.0, min(1.0, edge.percent))))
    path.moveTo(*walk[0])
    for point in walk[1:]:
        path.lineTo(*point)
    return path


def _polygon_path(polygon: QPolygonF) -> QPainterPath:
    path = QPainterPath()
    path.addPolygon(polygon)
    path.closeSubpath()
    return path


def _warp_transform(shape: PolygonShape, image: QImage, region) -> Optional[QTransform]:
    """Image-pixel space -> canvas space for a corner-pinned quad."""
    uvs = corner_uv_assignment(shape.points)
    if uvs is None:
        return None

    width, height = image.width(), image.height()
    # Corner UVs address the chosen region, not the whole file.
    source = QPolygonF([
        QPointF((region.u0 + u * region.width) * width, (region.v0 + v * region.height) * height)
        for u, v in uvs
    ])
    target = QPolygonF([QPointF(x, y) for x, y in shape.points])
    # Returns None when the quad has collapsed - self-crossing corners, or a
    # shape dragged flat.
    return QTransform.quadToQuad(source, target)


class TransformHandle(QGraphicsEllipseItem):
    """A bounding-box grip that scales or rotates the shape it belongs to.

    Alt and Ctrl on the body do the same job for anyone who knows they exist.
    These are how you find out they exist: a modifier with no visible
    affordance is a feature only the manual can tell you about.

    They drive `_apply_body_scale` / `_apply_body_rotate` through the same
    body-drag state the keyboard-modifier path uses, so there is one
    implementation of each transform, not two.
    """

    SIZE = 9.0

    def __init__(self, view, item, mode: str) -> None:
        half = self.SIZE / 2.0
        super().__init__(-half, -half, self.SIZE, self.SIZE)
        self.view = view
        self.item = item
        self.mode = mode

        if mode == "rotate":
            self.setBrush(QBrush(QColor(255, 176, 46)))
            self.setPen(QPen(QColor(168, 108, 12), 1.5))
            self.setToolTip("Drag to rotate (Alt-drag the shape does the same)")
        else:
            self.setBrush(QBrush(QColor(235, 235, 240)))
            self.setPen(QPen(QColor(90, 90, 100), 1.5))
            self.setToolTip("Drag to scale (Ctrl-drag the shape does the same)")

        self.setZValue(11)
        self.setCursor(Qt.SizeAllCursor if mode == "rotate" else Qt.SizeFDiagCursor)

    def mousePressEvent(self, event) -> None:
        self.view._begin_body_drag(self.item, event.scenePos(), event.modifiers(), mode=self.mode)
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        self.view._update_body_drag(event.scenePos(), event.modifiers())
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self.view._release_transform_handle()
        event.accept()


class VertexHandle(QGraphicsEllipseItem):
    def __init__(self, owner, index: int, on_moved, snap_func, on_pressed=None, on_released=None) -> None:
        super().__init__(-5, -5, 10, 10)
        self.owner = owner
        self.index = index
        self.on_moved = on_moved
        self.snap_func = snap_func
        self.on_pressed = on_pressed
        self.on_released = on_released
        self._block = False
        self._restore_parent_move: Optional[bool] = None
        # Refined handle styling - cyan accent
        self.set_accent(False)
        self.setFlags(
            QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setZValue(10)

    def set_accent(self, accent: bool) -> None:
        """Amber marks the corner carrying the media's origin; cyan is neutral."""
        if accent:
            self.setBrush(QBrush(QColor(255, 176, 46)))
            self.setPen(QPen(QColor(168, 108, 12), 1.5))
        else:
            self.setBrush(QBrush(QColor(0, 212, 170)))
            self.setPen(QPen(QColor(0, 136, 102), 1.5))

    def set_pos_silent(self, x: float, y: float) -> None:
        self._block = True
        super().setPos(x, y)
        self._block = False

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange:
            if self._block:
                return value
            pos = value
            if self.snap_func:
                pos = self.snap_func(pos)
            if self.on_moved:
                self.on_moved(self.owner, self.index, pos)
            return pos
        return super().itemChange(change, value)

    def mousePressEvent(self, event) -> None:
        if self.owner:
            self.owner.setSelected(True)
            self._restore_parent_move = self.owner.flags() & QGraphicsItem.ItemIsMovable
            self.owner.setFlag(QGraphicsItem.ItemIsMovable, False)
        if self.on_pressed:
            self.on_pressed(self.owner, self.index, self.pos())
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self.on_released:
            self.on_released(self.owner, self.index, self.pos())
        if self.owner is not None and self._restore_parent_move is not None:
            self.owner.setFlag(QGraphicsItem.ItemIsMovable, bool(self._restore_parent_move))
        self._restore_parent_move = None
        super().mouseReleaseEvent(event)


class CurveHandle(QGraphicsEllipseItem):
    """One control point of a curved edge.

    Deliberately not a `VertexHandle`: it does not snap. Snapping a curve
    control to another surface's corner would drag the tangent somewhere the
    operator never asked for, and there is nothing on the wall it would line
    up with anyway.
    """

    def __init__(self, owner, edge_index: int, slot: int, on_moved) -> None:
        super().__init__(-4, -4, 8, 8)
        self.owner = owner
        self.edge_index = edge_index
        self.slot = slot
        self.on_moved = on_moved
        self._block = False
        self.setBrush(QBrush(QColor(255, 176, 46)))
        self.setPen(QPen(QColor(168, 108, 12), 1.2))
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemSendsGeometryChanges)
        self.setZValue(11)
        self.setToolTip("Curve control - Alt+double-click the edge to straighten it")

    def set_pos_silent(self, x: float, y: float) -> None:
        self._block = True
        super().setPos(x, y)
        self._block = False

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and not self._block:
            if self.on_moved:
                self.on_moved(self.owner, self.edge_index, self.slot, value)
        return super().itemChange(change, value)

    def mousePressEvent(self, event) -> None:
        if self.owner:
            self.owner.setSelected(True)
        super().mousePressEvent(event)


class MaskHandle(QGraphicsEllipseItem):
    """One corner of a mask.

    Red, and square-ish in feel rather than the cyan of a surface vertex: a
    handle that removes projection has to be told apart at a glance from one
    that shapes it, or the operator drags the wall when they meant the window.
    """

    def __init__(self, owner, mask_index: int, point_index: int, on_moved, snap_func) -> None:
        super().__init__(-4.5, -4.5, 9, 9)
        self.owner = owner
        self.mask_index = mask_index
        self.point_index = point_index
        self.on_moved = on_moved
        self.snap_func = snap_func
        self._block = False
        self.setBrush(QBrush(QColor(232, 76, 92)))
        self.setPen(QPen(QColor(140, 30, 44), 1.4))
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemSendsGeometryChanges)
        self.setZValue(12)
        self.setToolTip("Mask corner")

    def set_pos_silent(self, x: float, y: float) -> None:
        self._block = True
        super().setPos(x, y)
        self._block = False

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and not self._block:
            pos = self.snap_func(value) if self.snap_func else value
            if self.on_moved:
                self.on_moved(self.owner, self.mask_index, self.point_index, pos)
            return pos
        return super().itemChange(change, value)

    def mousePressEvent(self, event) -> None:
        if self.owner:
            self.owner.setSelected(True)
        super().mousePressEvent(event)


class PolygonItem(QGraphicsPathItem):
    def __init__(self, model: PolygonShape) -> None:
        super().__init__()
        self.model = model
        self.handles: List[VertexHandle] = []
        self.curve_handles: List[CurveHandle] = []
        self.mask_handles: List[MaskHandle] = []
        # Filled in by the editor. Without it a clip's frame would be picked
        # by whatever clock the item invented for itself, and the canvas would
        # disagree with the projector about which frame is showing.
        self.transport = None
        self.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemSendsGeometryChanges)
        self.setBrush(QBrush(QColor(*model.fill_color)))
        self.setPen(QPen(QColor(*model.stroke_color), max(model.stroke_width, 1.0)))
        self.update_path()

    def set_handles_visible(self, visible: bool) -> None:
        for handle in self.handles:
            handle.setVisible(visible)
        for handle in self.curve_handles:
            handle.setVisible(visible)
        for handle in self.mask_handles:
            handle.setVisible(visible)

    def update_path(self) -> None:
        self.setPath(polygon_path(self.model))

    def sync_style(self) -> None:
        self.setBrush(QBrush(QColor(*self.model.fill_color)))
        self.setPen(QPen(QColor(*self.model.stroke_color), max(self.model.stroke_width, 1.0)))

    def paint(self, painter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.Antialiasing, True)
        apply_blend_mode(painter, self.model)
        if not _paint_media(painter, self.model, self.path(), self.transport):
            if is_missing(self.model.media):
                paint_missing_marker(painter, self.path())
            else:
                painter.fillPath(self.path(), QBrush(QColor(*self.model.fill_color)))
        clear_blend_mode(painter)

        if self.model.stroke_width > 0:
            pen = QPen(QColor(*self.model.stroke_color), max(self.model.stroke_width, 0.5))
            painter.setPen(pen)
            self.model.ensure_edges()
            points = self.model.points
            if points:
                for idx, edge in enumerate(self.model.edges):
                    if not edge.visible:
                        continue
                    p1 = points[idx]
                    p2 = points[(idx + 1) % len(points)]
                    if edge.curved:
                        painter.drawPath(_edge_path(p1, p2, edge))
                        continue
                    if edge.percent < 1.0:
                        dx = (p2[0] - p1[0]) * edge.percent
                        dy = (p2[1] - p1[1]) * edge.percent
                        p2 = (p1[0] + dx, p1[1] + dy)
                    painter.drawLine(p1[0], p1[1], p2[0], p2[1])

        if option.state & QStyle.State_Selected:
            self._paint_curve_leashes(painter)
            pen = QPen(QColor(0, 212, 170, 220), 2.0, Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(self.path())

    def _paint_curve_leashes(self, painter) -> None:
        """Tie each control point back to the vertex it belongs to.

        Without the leash a curve handle floating in space reads as a stray
        vertex, and the operator has no way to tell which end of the edge it
        is bending.
        """
        points = self.model.points
        if not points:
            return
        self.model.ensure_edges()
        painter.setPen(QPen(QColor(255, 176, 46, 120), 1.0, Qt.DotLine))
        painter.setBrush(Qt.NoBrush)
        count = len(points)
        for idx, edge in enumerate(self.model.edges[:count]):
            if not edge.curved:
                continue
            a = points[idx]
            b = points[(idx + 1) % count]
            c1, c2 = bezier_control_points(a, b, edge.curve1, edge.curve2)
            painter.drawLine(a[0], a[1], c1[0], c1[1])
            painter.drawLine(b[0], b[1], c2[0], c2[1])


class MeshItem(QGraphicsPathItem):
    """A bendable surface, drawn from its smoothed patch."""

    def __init__(self, model: MeshShape) -> None:
        super().__init__()
        self.model = model
        self.transport = None
        self.handles: List[VertexHandle] = []
        self.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemSendsGeometryChanges)
        self.update_path()

    def set_handles_visible(self, visible: bool) -> None:
        for handle in self.handles:
            handle.setVisible(visible)

    def update_path(self) -> None:
        outline = mesh_outline(self.model.points, self.model.rows, self.model.cols)
        path = QPainterPath()
        if outline:
            path.moveTo(*outline[0])
            for point in outline[1:]:
                path.lineTo(*point)
            path.closeSubpath()
        self.setPath(path)

    def sync_style(self) -> None:
        self.update_path()

    def paint(self, painter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.Antialiasing, True)
        apply_blend_mode(painter, self.model)
        if not _paint_mesh_media(painter, self.model, self.transport):
            if is_missing(self.model.media):
                paint_missing_marker(painter, self.path())
            else:
                painter.fillPath(self.path(), QBrush(QColor(*self.model.fill_color)))
        clear_blend_mode(painter)

        if self.model.stroke_width > 0:
            painter.setPen(QPen(QColor(*self.model.stroke_color), max(self.model.stroke_width, 0.5)))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(self.path())

        if option.state & QStyle.State_Selected:
            # The control lattice, so it is clear what the handles bend.
            painter.setPen(QPen(QColor(0, 212, 170, 90), 1.0, Qt.DotLine))
            model = self.model
            for r in range(model.grid_rows):
                for c in range(model.grid_cols - 1):
                    a, b = model.point_at(r, c), model.point_at(r, c + 1)
                    painter.drawLine(a[0], a[1], b[0], b[1])
            for c in range(model.grid_cols):
                for r in range(model.grid_rows - 1):
                    a, b = model.point_at(r, c), model.point_at(r + 1, c)
                    painter.drawLine(a[0], a[1], b[0], b[1])

            painter.setPen(QPen(QColor(0, 212, 170, 220), 2.0, Qt.DashLine))
            painter.drawPath(self.path())


class CircleItem(QGraphicsEllipseItem):
    def __init__(self, model: CircleShape) -> None:
        super().__init__()
        self.model = model
        self.handles: List[VertexHandle] = []
        self.mask_handles: List[MaskHandle] = []
        self.transport = None
        self.handle_angle = -math.pi / 2.0
        self.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemSendsGeometryChanges)
        self.setBrush(QBrush(QColor(*model.fill_color)))
        self.setPen(QPen(QColor(*model.stroke_color), max(model.stroke_width, 1.0)))
        self.update_rect()

    def set_handles_visible(self, visible: bool) -> None:
        for handle in self.handles:
            handle.setVisible(visible)
        for handle in self.mask_handles:
            handle.setVisible(visible)

    def update_rect(self) -> None:
        rx = max(self.model.radius_x, 1.0)
        ry = max(self.model.radius_y, 1.0)
        self.setRect(self.model.center[0] - rx, self.model.center[1] - ry, rx * 2, ry * 2)
        # keep anchors synced with true circle
        cx, cy = self.model.center
        base = self.handle_angle
        self.model.anchors = []
        for idx in range(4):
            angle = base + (idx * (math.pi / 2.0))
            x = cx + math.cos(angle) * rx
            y = cy + math.sin(angle) * ry
            self.model.anchors.append((x, y))

    def sync_style(self) -> None:
        self.setBrush(QBrush(QColor(*self.model.fill_color)))
        self.setPen(QPen(QColor(*self.model.stroke_color), max(self.model.stroke_width, 1.0)))

    def paint(self, painter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect()

        ellipse = QPainterPath()
        ellipse.addEllipse(rect)
        ellipse = add_mask_subpaths(ellipse, self.model)
        apply_blend_mode(painter, self.model)
        if _paint_media(painter, self.model, ellipse, self.transport):
            painter.setBrush(Qt.NoBrush)
        elif is_missing(self.model.media):
            paint_missing_marker(painter, ellipse)
            painter.setBrush(Qt.NoBrush)
        else:
            painter.fillPath(ellipse, QBrush(QColor(*self.model.fill_color)))
            painter.setBrush(Qt.NoBrush)
        clear_blend_mode(painter)
        if self.model.stroke_width > 0:
            pen = QPen(QColor(*self.model.stroke_color), max(self.model.stroke_width, 0.5))
            painter.setPen(pen)
        else:
            painter.setPen(Qt.NoPen)
        painter.drawEllipse(rect)

        if option.state & QStyle.State_Selected:
            pen = QPen(QColor(0, 212, 170, 220), 2.0, Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(rect)

        # Orientation line
        cx, cy = self.model.center
        r = max(self.model.radius_x, self.model.radius_y, 1.0)
        angle = getattr(self, "handle_angle", -math.pi / 2.0)
        x = cx + math.cos(angle) * r
        y = cy + math.sin(angle) * r
        painter.setPen(QPen(QColor(0, 212, 170, 120), 1.0))
        painter.drawLine(cx, cy, x, y)

class CanvasEditor(QGraphicsView):
    selection_changed = Signal(object)
    zoom_changed = Signal(float)
    tool_changed = Signal(str)
    handle_mode_changed = Signal(bool)

    # Magnet radius in screen pixels, divided by the zoom before use so it
    # feels constant to the hand rather than to the scene.
    SNAP_THRESHOLD_PX = 12.0

    # The editor is a calibration view, not the show: 30fps is plenty to judge
    # a mapping by, and half the repaint cost of matching the output.
    PLAYBACK_REFRESH_MS = 33

    def __init__(self, project: Project, parent=None) -> None:
        super().__init__(parent)
        self.project = project
        self.scene = CanvasScene(project)
        self.setScene(self.scene)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setSceneRect(0, 0, project.canvas.width, project.canvas.height)
        self._zoom = 1.0
        self._padding = 200
        # Which handles a selected shape offers. The bbox grips land exactly
        # on the corner vertices of a quad, so both sets cannot be live at the
        # same time - one of them is unreachable. A second click on the shape
        # swaps them.
        self._point_mode = False
        self._selection_key: Tuple[str, ...] = ()
        self._pan_origin: Optional[QPointF] = None

        # A QGraphicsView only repaints when something changes, and a playing
        # clip changes nothing the scene knows about. This ticks the viewport
        # while any visible surface is showing moving media - and only then,
        # so a still project costs nothing.
        self._playback_timer = QTimer(self)
        self._playback_timer.setInterval(self.PLAYBACK_REFRESH_MS)
        self._playback_timer.timeout.connect(self._tick_playback)
        self._last_canvas = (project.canvas.width, project.canvas.height)
        self._panning = False
        self._pan_last: Optional[QPointF] = None
        self._circle_drag_state = {}

        self.tool = "select"

        self.undo_stack: Optional[QUndoStack] = None
        self._session: Optional[EditSession] = None
        self.snap_enabled = True
        # (item, vertex index) of the last handle pressed, so arrow keys nudge
        # that corner instead of the whole surface.
        self._active_vertex: Optional[Tuple[object, int]] = None
        self._body_drag: Dict[str, object] = {}
        self._transform_handles: List[TransformHandle] = []
        self.setFocusPolicy(Qt.StrongFocus)

        self.items_by_id: Dict[str, object] = {}
        self.scene.selectionChanged.connect(self._on_selection_changed)
        self._connected_project: Optional[Project] = project
        self.project.changed.connect(self._sync_items)
        self._sync_items()

    def set_project(self, project: Project) -> None:
        """Point the editor at another project, moving the signal with it.

        The view owns this connection so it exists exactly once; having the
        window wire it up as well meant every repaint rebuilt the scene twice.
        """
        if self._connected_project is project:
            return
        if self._connected_project is not None:
            self._connected_project.changed.disconnect(self._sync_items)

        self.project = project
        self.scene.project = project
        self._connected_project = project
        project.changed.connect(self._sync_items)

        self.items_by_id.clear()
        self.scene.clear()
        self._active_vertex = None
        if self._session is not None:
            self._session.cancel()
        self._sync_items()

    def set_snap_enabled(self, enabled: bool) -> None:
        self.snap_enabled = bool(enabled)
        if not self.snap_enabled:
            self._clear_snap_marker()

    def _clear_snap_marker(self) -> None:
        if self.scene.snap_marker is not None:
            self.scene.snap_marker = None
            self.scene.update()

    def _snap_candidates(self, exclude_shape_id: Optional[str]):
        """Geometry from the *other* visible surfaces.

        The dragged shape is excluded on purpose: a vertex is always within
        zero pixels of its own adjacent edges, so including them would pin it
        in place, and snapping a corner onto another corner of the same quad
        just collapses it.
        """
        vertices: List[Tuple[float, float]] = []
        edges: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
        for shape in self.project.shapes:
            if shape.id == exclude_shape_id or not shape.visible:
                continue
            if isinstance(shape, MeshShape):
                vertices.extend(shape_vertices(shape.points))
            elif isinstance(shape, PolygonShape):
                # Vertices stay the corners - sampling a curve would carpet
                # the canvas in magnets. Edges follow the curve, because
                # sliding a corner along a curved edge is the whole point.
                vertices.extend(shape_vertices(shape.points))
                edges.extend(shape_edges(shape.outline()))
            elif isinstance(shape, CircleShape):
                # The four anchors are the useful alignment points; the curve
                # itself has no segments to snap an edge against.
                vertices.extend(shape_vertices(shape.anchors))
        return vertices, edges

    def _snap_vertex(self, owner, pos: QPointF, grid: bool = True) -> QPointF:
        """snap_func for vertex handles. Alt suppresses it for one drag."""
        if not self.snap_enabled:
            return pos
        if QGuiApplication.keyboardModifiers() & Qt.AltModifier:
            self._clear_snap_marker()
            return pos

        shape_id = getattr(getattr(owner, "model", None), "id", None)
        vertices, edges = self._snap_candidates(shape_id)
        threshold = self.SNAP_THRESHOLD_PX / max(self._zoom, 1e-6)

        result = find_snap(
            (pos.x(), pos.y()),
            vertices,
            edges,
            threshold,
            grid_size=self.scene.grid_size if grid else 0.0,
        )
        if result is None:
            self._clear_snap_marker()
            return pos

        snapped = QPointF(result.point[0], result.point[1])
        # Only geometry snaps get a marker - flagging every grid landing
        # would leave the ring blinking across the whole canvas.
        marker = snapped if result.is_magnetic else None
        if self.scene.snap_marker != marker:
            self.scene.snap_marker = marker
            self.scene.update()
        return snapped

    def set_undo_stack(self, stack: QUndoStack) -> None:
        self.undo_stack = stack
        self._session = EditSession(stack)

    def _begin_edit_for(self, hit_item) -> None:
        """Snapshot the shape under the cursor, making the drag one undo step.

        Resolved from the pressed item rather than the selection, because Qt
        updates the selection after the press event we are handling.
        """
        if self._session is None:
            return

        model = None
        if isinstance(hit_item, VertexHandle):
            model = getattr(hit_item.owner, "model", None)
        elif isinstance(hit_item, (PolygonItem, CircleItem, MeshItem)):
            model = hit_item.model
        elif hit_item is not None and isinstance(hit_item.parentItem(), (PolygonItem, CircleItem, MeshItem)):
            model = hit_item.parentItem().model
        else:
            model = getattr(self._current_selected_item(), "model", None)

        # A body gesture on a grouped surface moves every member, so every
        # member has to be snapshotted or undo would put only one of them back.
        if model is not None and isinstance(hit_item, (PolygonItem, CircleItem, MeshItem, TransformHandle)):
            item = hit_item.item if isinstance(hit_item, TransformHandle) else hit_item
            self._session.begin_many([member.model for member in self._drag_members(item)])
        else:
            self._session.begin(model)

    GESTURE_LABELS = {"move": "Move Shape", "rotate": "Rotate Shape", "scale": "Scale Shape"}

    def _commit_edit(self, label: Optional[str] = None) -> None:
        if self._session is None or not self._session.active:
            return
        self._session.commit(self.project, label or "Move Points")

    def set_tool(self, tool: str) -> None:
        changed = tool != self.tool
        self.tool = tool
        if tool == "select":
            self.setDragMode(QGraphicsView.NoDrag)
            self.viewport().setCursor(Qt.ArrowCursor)
        else:
            self.setDragMode(QGraphicsView.NoDrag)
            self.viewport().setCursor(Qt.CrossCursor)
        self.setFocus(Qt.OtherFocusReason)
        if changed:
            # The canvas drops back to select once a shape is placed. Without
            # this the toolbar kept the tool button lit, so the next click on
            # the canvas made a second shape nobody asked for.
            self.tool_changed.emit(tool)

    def set_zoom(self, zoom: float) -> None:
        zoom = max(0.1, min(4.0, zoom))
        self._zoom = zoom
        self.resetTransform()
        self.scale(self._zoom, self._zoom)
        self.zoom_changed.emit(self._zoom)

    def get_zoom(self) -> float:
        return self._zoom

    def fit_to_canvas(self) -> None:
        canvas_rect = QRectF(0, 0, self.project.canvas.width, self.project.canvas.height)
        if canvas_rect.width() <= 0 or canvas_rect.height() <= 0:
            return
        self.fitInView(canvas_rect, Qt.KeepAspectRatio)
        self._zoom = self.transform().m11()
        self.zoom_changed.emit(self._zoom)

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            if delta == 0:
                return
            step = 1.1 if delta > 0 else 0.9
            self.set_zoom(self._zoom * step)
            event.accept()
            return
        super().wheelEvent(event)

    def _sync_items(self) -> None:
        canvas_w = self.project.canvas.width
        canvas_h = self.project.canvas.height
        pad = max(200, int(max(canvas_w, canvas_h) * 0.1))
        self._padding = pad
        self.setSceneRect(-pad, -pad, canvas_w + pad * 2, canvas_h + pad * 2)
        if (canvas_w, canvas_h) != self._last_canvas:
            self._last_canvas = (canvas_w, canvas_h)
            self.fit_to_canvas()
        existing_ids = set(self.items_by_id.keys())
        current_ids = {s.id for s in self.project.shapes}

        for shape_id in existing_ids - current_ids:
            item = self.items_by_id.pop(shape_id)
            if hasattr(item, "handles"):
                self._clear_handles(item)
            self.scene.removeItem(item)

        for shape in self.project.shapes:
            if shape.id not in self.items_by_id:
                item = self._create_item(shape)
                self.items_by_id[shape.id] = item
                self.scene.addItem(item)
            else:
                item = self.items_by_id[shape.id]
                self._update_item(item, shape)


    def _create_item(self, shape: Shape):
        if isinstance(shape, MeshShape):
            item = MeshItem(shape)
            item.transport = self.project.transport
            item.setVisible(shape.visible)
            self._create_mesh_handles(item)
            return item
        if isinstance(shape, PolygonShape):
            item = PolygonItem(shape)
            item.transport = self.project.transport
            item.setVisible(shape.visible)
            self._create_point_handles(item)
            return item
        if isinstance(shape, CircleShape):
            item = CircleItem(shape)
            item.transport = self.project.transport
            item.setVisible(shape.visible)
            self._create_circle_point_handles(item)
            return item
        raise ValueError("Shape desconhecido")

    def _update_item(self, item, shape: Shape) -> None:
        item.transport = self.project.transport
        # Undo replaces the shape *object* (commands restore from a snapshot,
        # they do not mutate in place), so an item that keeps its original
        # reference goes on painting the state that was just undone. Re-point
        # it here, where every project change already passes through.
        item.model = shape
        if isinstance(item, MeshItem):
            item.update_path()
            item.setVisible(shape.visible)
            self._update_mesh_handles(item)
            return
        if isinstance(item, PolygonItem):
            item.update_path()
            item.sync_style()
            item.setVisible(shape.visible)
            self._update_mode_handles(item)
        elif isinstance(item, CircleItem):
            item.update_rect()
            item.sync_style()
            item.setVisible(shape.visible)
            self._update_mode_handles(item)

    def _clear_handles(self, item) -> None:
        for handle in getattr(item, "handles", []):
            handle.setParentItem(None)
            self.scene.removeItem(handle)
        item.handles = []
        if isinstance(item, PolygonItem):
            self._clear_curve_handles(item)
        self._clear_mask_handles(item)

    def _create_mesh_handles(self, item: MeshItem) -> None:
        self._clear_handles(item)
        for index in range(len(item.model.points)):
            handle = VertexHandle(
                item, index, self._on_mesh_handle_moved,
                # No grid for a mesh control point. The grid is a placement
                # aid for whole surfaces; on a bend it quantises the one thing
                # the mesh exists to express, and the points visibly jump
                # between grid lines instead of following the hand.
                lambda p, o=item: self._snap_vertex(o, p, grid=False),
            )
            handle.setParentItem(item)
            handle.setVisible(False)
            item.handles.append(handle)
        self._update_mesh_handles(item)

    def _update_mesh_handles(self, item: MeshItem) -> None:
        if len(item.handles) != len(item.model.points):
            self._create_mesh_handles(item)
            return
        for handle, point in zip(item.handles, item.model.points):
            handle.set_pos_silent(point[0], point[1])
        visible = self._handles_visible_for(item)
        for handle in item.handles:
            handle.setVisible(visible)

    def _on_mesh_handle_moved(self, owner: MeshItem, index: int, pos: QPointF) -> None:
        shape = owner.model
        if shape.locked or index >= len(shape.points):
            return
        scene_pos = owner.mapToScene(pos)
        points = list(shape.points)
        points[index] = (scene_pos.x(), scene_pos.y())
        shape.points = points
        owner.update_path()
        self.project.touch()

    def _create_point_handles(self, item: PolygonItem) -> None:
        self._clear_handles(item)
        item.handles.clear()
        for idx, point in enumerate(item.model.points):
            # VertexHandle calls snap_func(pos), so the owner is bound here.
            handle = VertexHandle(
                item, idx, self._on_handle_moved, lambda p, o=item: self._snap_vertex(o, p)
            )
            handle.setParentItem(item)
            handle.set_pos_silent(point[0], point[1])
            handle.setVisible(False)
            item.handles.append(handle)

    def _update_point_handles(self, item: PolygonItem) -> None:
        if len(item.handles) != len(item.model.points):
            self._create_point_handles(item)
        for handle, point in zip(item.handles, item.model.points):
            handle.set_pos_silent(point[0], point[1])
        self._apply_corner_roles(item)
        visible = self._handles_visible_for(item)
        for handle in item.handles:
            handle.setVisible(visible)
        self._update_curve_handles(item)
        self._update_mask_handles(item)

    # --- masks -----------------------------------------------------------

    def _clear_mask_handles(self, item) -> None:
        for handle in getattr(item, "mask_handles", []):
            handle.setParentItem(None)
            self.scene.removeItem(handle)
        if hasattr(item, "mask_handles"):
            item.mask_handles = []

    def _update_mask_handles(self, item) -> None:
        """One handle per mask corner, rebuilt when the mask list changes."""
        shape = item.model
        if not hasattr(item, "mask_handles"):
            return
        masks = getattr(shape, "masks", [])
        wanted = [
            (mi, pi)
            for mi, mask in enumerate(masks)
            for pi in range(len(mask.points))
        ]
        if [(h.mask_index, h.point_index) for h in item.mask_handles] != wanted:
            self._clear_mask_handles(item)
            for mask_index, point_index in wanted:
                handle = MaskHandle(
                    item, mask_index, point_index, self._on_mask_handle_moved,
                    lambda p, o=item: self._snap_vertex(o, p),
                )
                handle.setParentItem(item)
                item.mask_handles.append(handle)

        visible = self._handles_visible_for(item)
        for handle in item.mask_handles:
            point = masks[handle.mask_index].points[handle.point_index]
            handle.set_pos_silent(point[0], point[1])
            handle.setVisible(visible)

    def _on_mask_handle_moved(self, owner, mask_index: int, point_index: int, pos: QPointF) -> None:
        shape = owner.model
        masks = getattr(shape, "masks", [])
        if shape.locked or mask_index >= len(masks):
            return
        mask = masks[mask_index]
        if point_index >= len(mask.points):
            return
        scene_pos = owner.mapToScene(pos)
        points = list(mask.points)
        points[point_index] = (scene_pos.x(), scene_pos.y())
        mask.points = points
        self._refresh_geometry(owner)
        self.project.touch()

    def _refresh_geometry(self, item) -> None:
        if isinstance(item, CircleItem):
            item.update_rect()
        elif hasattr(item, "update_path"):
            item.update_path()
        item.update()

    def add_mask(self, item) -> bool:
        """Cut a starter hole in the middle of the surface, sized to fit it."""
        shape = item.model
        if shape.locked or not hasattr(shape, "masks"):
            return False

        box = item.boundingRect()
        centre = box.center()
        if self._session is not None:
            self._session.begin(shape)
        shape.masks.append(
            mask_from_rect(
                (centre.x(), centre.y()),
                max(box.width() * 0.3, 20.0),
                max(box.height() * 0.3, 20.0),
                name=f"Mask {len(shape.masks) + 1}",
            )
        )
        self._refresh_geometry(item)
        self._update_mask_handles(item)
        if self._session is not None:
            self._session.commit(self.project, "Add Mask")
        else:
            self.project.touch()
        return True

    # --- curved edges ----------------------------------------------------

    def _clear_curve_handles(self, item: PolygonItem) -> None:
        for handle in getattr(item, "curve_handles", []):
            handle.setParentItem(None)
            self.scene.removeItem(handle)
        item.curve_handles = []

    def _update_curve_handles(self, item: PolygonItem) -> None:
        """Two controls per *curved* edge, and none for the rest.

        A quad with a handle on every edge whether it bends or not is eight
        extra grips to miss the vertex on. They appear when the edge is
        curved, which is the only time they mean anything.
        """
        shape = item.model
        shape.ensure_edges()
        points = shape.points
        wanted = [idx for idx, edge in enumerate(shape.edges[:len(points)]) if edge.curved]

        if [h.edge_index for h in item.curve_handles] != [i for i in wanted for _ in (0, 1)]:
            self._clear_curve_handles(item)
            for idx in wanted:
                for slot in (0, 1):
                    handle = CurveHandle(item, idx, slot, self._on_curve_handle_moved)
                    handle.setParentItem(item)
                    item.curve_handles.append(handle)

        visible = self._handles_visible_for(item)
        count = len(points)
        for handle in item.curve_handles:
            edge = shape.edges[handle.edge_index]
            a = points[handle.edge_index]
            b = points[(handle.edge_index + 1) % count]
            control = bezier_control_points(a, b, edge.curve1, edge.curve2)[handle.slot]
            handle.set_pos_silent(control[0], control[1])
            handle.setVisible(visible)

    def _on_curve_handle_moved(self, owner: PolygonItem, edge_index: int, slot: int, pos: QPointF) -> None:
        shape = owner.model
        shape.ensure_edges()
        if shape.locked or edge_index >= len(shape.edges):
            return
        points = shape.points
        a = points[edge_index]
        b = points[(edge_index + 1) % len(points)]
        scene_pos = owner.mapToScene(pos)
        local = bezier_local_control(a, b, (scene_pos.x(), scene_pos.y()))
        if slot == 0:
            shape.edges[edge_index].curve1 = local
        else:
            shape.edges[edge_index].curve2 = local
        owner.update_path()
        self.project.touch()

    def _edge_at(self, shape: PolygonShape, point: QPointF, threshold: float = 12.0) -> Optional[int]:
        """Which edge a click landed on, curve included."""
        points = shape.points
        if len(points) < 2:
            return None
        shape.ensure_edges()
        limit = (threshold / max(self._zoom, 0.01)) ** 2
        target = (point.x(), point.y())
        best, best_dist = None, limit
        count = len(points)
        for idx in range(count):
            a = points[idx]
            b = points[(idx + 1) % count]
            edge = shape.edges[idx] if idx < len(shape.edges) else None
            if edge is not None and edge.curved:
                walk = edge_samples(a, b, edge.curve1, edge.curve2, 24) + [b]
            else:
                walk = [a, b]
            for i in range(len(walk) - 1):
                closest = closest_point_on_segment(target, walk[i], walk[i + 1])
                dist = (closest[0] - target[0]) ** 2 + (closest[1] - target[1]) ** 2
                if dist < best_dist:
                    best, best_dist = idx, dist
        return best

    def toggle_edge_curve(self, item: PolygonItem, edge_index: int) -> bool:
        """Bow a straight edge, or straighten a curved one."""
        shape = item.model
        if shape.locked:
            return False
        shape.ensure_edges()
        if edge_index is None or edge_index >= len(shape.edges):
            return False

        edge = shape.edges[edge_index]
        if self._session is not None:
            self._session.begin(shape)
        if edge.curved:
            edge.straighten()
            label = "Straighten Edge"
        else:
            shape.bow_edge(edge_index)
            label = "Curve Edge"
        item.update_path()
        self._update_curve_handles(item)
        if self._session is not None:
            self._session.commit(self.project, label)
        else:
            self.project.touch()
        return True

    def _apply_corner_roles(self, item: PolygonItem) -> None:
        """Highlight which vertex holds the media's top-left corner.

        Dragging one corner past another re-pairs them, which rotates the
        media. Without a marker that happens invisibly and the user is left
        wondering why the image jumped.
        """
        media = item.model.media
        uvs = None
        if media and media.kind and (media.fit_mode or "").lower() == "warp":
            uvs = corner_uv_assignment(item.model.points)

        for idx, handle in enumerate(item.handles):
            is_origin = uvs is not None and idx < len(uvs) and uvs[idx] == (0.0, 0.0)
            handle.set_accent(is_origin)
            handle.setToolTip("Media top-left corner" if is_origin else "")

    def _create_circle_point_handles(self, item: CircleItem) -> None:
        self._clear_handles(item)
        self._ensure_circle_anchors(item.model)
        for idx in range(4):
            handle = VertexHandle(
                item,
                idx,
                self._on_circle_handle_moved,
                lambda p, o=item: self._snap_vertex(o, p),
                self._on_circle_handle_pressed,
                self._on_circle_handle_released,
            )
            self.scene.addItem(handle)
            handle.setVisible(False)
            item.handles.append(handle)
        self._update_circle_point_handles(item)

    def _update_circle_point_handles(self, item: CircleItem) -> None:
        if len(item.handles) != 4:
            self._create_circle_point_handles(item)
            return
        cx, cy = item.model.center
        # Each handle rides its own axis. Using a single max(rx, ry) radius -
        # which is what this did - left the handles floating off the outline
        # as soon as the shape was not a perfect circle.
        rx = max(item.model.radius_x, 1.0)
        ry = max(item.model.radius_y, 1.0)
        # handle_angle defaults to -pi/2, so handle 0 points straight up: even
        # indices ride the vertical axis (ry), odd ones the horizontal (rx).
        base = getattr(item, "handle_angle", -math.pi / 2.0)
        anchors: List[Tuple[float, float]] = []
        for idx, handle in enumerate(item.handles):
            angle = base + (idx * (math.pi / 2.0))
            radius = ry if idx % 2 == 0 else rx
            x = cx + math.cos(angle) * radius
            y = cy + math.sin(angle) * radius
            handle.set_pos_silent(x, y)
            anchors.append((x, y))
        item.model.anchors = anchors
        visible = self._handles_visible_for(item)
        for handle in item.handles:
            handle.setVisible(visible)

    def _ensure_circle_anchors(self, shape: CircleShape) -> None:
        # kept for compatibility, but anchors are always derived from circle
        if not shape.anchors:
            cx, cy = shape.center
            rx = max(shape.radius_x, 1.0)
            ry = max(shape.radius_y, 1.0)
            shape.anchors = [
                (cx, cy - ry),
                (cx + rx, cy),
                (cx, cy + ry),
                (cx - rx, cy),
            ]

    def _on_handle_moved(self, owner: PolygonItem, index: int, pos: QPointF) -> None:
        shape = owner.model
        if shape.locked:
            return
        scene_pos = owner.mapToScene(pos)
        points = list(shape.points)
        points[index] = (scene_pos.x(), scene_pos.y())
        shape.points = points
        owner.update_path()
        self.project.touch()

    def _on_circle_handle_pressed(self, owner: CircleItem, index: int, pos: QPointF) -> None:
        if not owner.handles or len(owner.handles) < 4:
            return
        opp_idx = (index + 2) % 4
        opp_pos = owner.handles[opp_idx].pos()
        self._circle_drag_state = {
            "owner": owner,
            "index": index,
            "opp_pos": opp_pos,
        }

    def _on_circle_handle_released(self, owner: CircleItem, index: int, pos: QPointF) -> None:
        if self._circle_drag_state.get("owner") == owner:
            self._circle_drag_state = {}

    def _on_circle_handle_moved(self, owner: CircleItem, index: int, pos: QPointF) -> None:
        if owner.model.locked:
            return
        scene_pos = QPointF(pos)
        if not owner.handles or len(owner.handles) < 4:
            return
        state = self._circle_drag_state
        if state.get("owner") == owner and state.get("index") == index and state.get("opp_pos") is not None:
            opp_pos = state.get("opp_pos")
        else:
            opp_idx = (index + 2) % 4
            opp_pos = owner.handles[opp_idx].pos()
        cx = (scene_pos.x() + opp_pos.x()) / 2.0
        cy = (scene_pos.y() + opp_pos.y()) / 2.0
        vx = scene_pos.x() - cx
        vy = scene_pos.y() - cy
        radius = max((vx * vx + vy * vy) ** 0.5, 1.0)
        angle = math.atan2(vy, vx)
        owner.handle_angle = angle - (index * (math.pi / 2.0))
        owner.model.center = (cx, cy)

        # Even handles ride the vertical axis, odd ones the horizontal (see
        # _update_circle_point_handles), so a drag resizes that axis alone and
        # leaves the other as the user set it. Forcing both - which is what
        # this did - silently threw away any ellipse typed into the RX/RY
        # boxes the moment a handle was touched. Shift keeps it circular.
        uniform = bool(QGuiApplication.keyboardModifiers() & Qt.ShiftModifier)
        if uniform or index % 2 == 1:
            owner.model.radius_x = radius
        if uniform or index % 2 == 0:
            owner.model.radius_y = radius

        owner.update_rect()
        self._update_circle_point_handles(owner)
        self.project.touch()


    def _current_polygon_item(self) -> Optional[PolygonItem]:
        for item in self.scene.selectedItems():
            if isinstance(item, PolygonItem):
                return item
        return None

    def _polygon_item_at(self, viewport_pos) -> Optional[PolygonItem]:
        item = self.itemAt(viewport_pos)
        if isinstance(item, PolygonItem):
            return item
        if isinstance(item, VertexHandle) and isinstance(item.owner, PolygonItem):
            return item.owner
        if item and item.parentItem() and isinstance(item.parentItem(), PolygonItem):
            return item.parentItem()
        return self._current_polygon_item()

    def select_shape(self, shape_id: Optional[str], additive: bool = False) -> None:
        """Select a surface - and, if it is grouped, the rest of its group.

        Clicking one member and getting only that member back would make a
        group invisible: nothing on screen would say the surfaces travel
        together until something moved unexpectedly.
        """
        item = self.items_by_id.get(shape_id) if shape_id else None
        if additive and item is not None:
            wanted = self._group_items(item)
            select = not item.isSelected()
            for member in wanted:
                member.setSelected(select)
            return

        for selected in self.scene.selectedItems():
            selected.setSelected(False)
        if item is None:
            return
        for member in self._group_items(item):
            member.setSelected(True)

    def selected_shape_ids(self) -> List[str]:
        return [
            item.model.id
            for item in self.scene.selectedItems()
            if isinstance(item, (PolygonItem, CircleItem, MeshItem))
        ]

    def set_shape_visibility(self, shape_id: str, visible: bool) -> None:
        item = self.items_by_id.get(shape_id)
        if item:
            item.setVisible(visible)

    def mousePressEvent(self, event) -> None:
        if self.tool == "select" and event.button() == Qt.LeftButton:
            hit_item = self.itemAt(event.position().toPoint())
            body = self._body_item_at(hit_item)

            if isinstance(hit_item, TransformHandle):
                self.setDragMode(QGraphicsView.NoDrag)
                # Snapshot here: the handle's own press starts the gesture,
                # and by then Qt has stopped delivering to the view.
                self._begin_edit_for(hit_item.item)
                self._active_vertex = None
            elif isinstance(hit_item, VertexHandle):
                self.setDragMode(QGraphicsView.NoDrag)
                # Snapshot before Qt starts delivering move events.
                self._begin_edit_for(hit_item)
                self._active_vertex = (hit_item.owner, hit_item.index)
            elif isinstance(hit_item, (CurveHandle, MaskHandle)):
                # Same deal, and the handle moves itself from here on.
                self.setDragMode(QGraphicsView.NoDrag)
                self._begin_edit_for(hit_item.owner)
                self._active_vertex = None
            elif body is not None:
                self.setDragMode(QGraphicsView.NoDrag)
                # Ctrl adds to the selection; without it, clicking a member
                # of a group brings the whole group along.
                if event.modifiers() & Qt.ControlModifier:
                    self.select_shape(body.model.id, additive=True)
                elif not body.isSelected():
                    self.select_shape(body.model.id)
                else:
                    # Already selected: the second click swaps which handles
                    # are on offer, because the bbox grips sit exactly on top
                    # of the corner vertices and one of them has to give way.
                    self.toggle_handle_mode()
                self._begin_edit_for(body)
                self._active_vertex = None
                # Dragging the body used to need Shift and only ever moved.
                # It is the default now, with Alt and Ctrl for rotate/scale.
                self._begin_body_drag(
                    body, self.mapToScene(event.position().toPoint()), event.modifiers()
                )
                # Qt's own handling would clear the selection down to this one
                # item, which is what made a Ctrl-built selection - and a
                # group - flicker and collapse the moment it was clicked.
                event.accept()
                return
            else:
                # Deselect on a *click*, not on a drag: a drag out here is a
                # pan, and losing the selection every time the view moves is
                # not what anyone means by scrolling the canvas.
                self._panning = True
                self._pan_last = event.position()
                self._pan_origin = event.position()
                self.setDragMode(QGraphicsView.NoDrag)
                event.accept()
                return
        if event.button() == Qt.LeftButton and self.tool in ("polygon", "circle", "mesh"):
            scene_pos = self._snap_point(self.mapToScene(event.position().toPoint()))
            if self.tool == "polygon":
                shape = self._create_default_polygon(scene_pos, 120.0, DEFAULT_POLYGON_NAME)
            elif self.tool == "mesh":
                shape = mesh_from_rect((scene_pos.x(), scene_pos.y()), 200.0, name=DEFAULT_MESH_NAME)
            else:
                shape = circle_from_center((scene_pos.x(), scene_pos.y()), 60.0, name=DEFAULT_CIRCLE_NAME)
            if self.undo_stack is not None:
                label = {"polygon": "Add Polygon", "mesh": "Add Mesh"}.get(self.tool, "Add Circle")
                self.undo_stack.push(AddShapeCommand(self.project, shape, label))
            else:
                self.project.add_shape(shape)
            self._sync_items()
            self.select_shape(shape.id)
            self.set_tool("select")
            return
        super().mousePressEvent(event)

    # Handles parented to a shape item. A click on one of these is a click on
    # the handle, never on the body underneath - resolving it to the parent is
    # what made curve and mask controls impossible to drag: the view started a
    # body gesture and swallowed every move event the handle needed.
    HANDLE_TYPES = (VertexHandle, CurveHandle, MaskHandle, TransformHandle)

    def _body_item_at(self, hit_item):
        """The shape a click landed on, ignoring which child it actually hit."""
        if isinstance(hit_item, self.HANDLE_TYPES):
            return None
        if isinstance(hit_item, (PolygonItem, CircleItem, MeshItem)):
            return hit_item
        parent = getattr(hit_item, "parentItem", None)
        if parent is not None and isinstance(hit_item.parentItem(), (PolygonItem, CircleItem, MeshItem)):
            return hit_item.parentItem()
        return None

    def mouseMoveEvent(self, event) -> None:
        if self._body_drag:
            if self._update_body_drag(
                self.mapToScene(event.position().toPoint()), event.modifiers()
            ):
                event.accept()
                return

        if self._panning and self._pan_last is not None:
            delta = event.position() - self._pan_last
            self._pan_last = event.position()
            hbar = self.horizontalScrollBar()
            vbar = self.verticalScrollBar()
            hbar.setValue(hbar.value() - int(delta.x()))
            vbar.setValue(vbar.value() - int(delta.y()))
            return
        super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if self.tool == "select":
            scene_pos = self._snap_point(self.mapToScene(event.position().toPoint()))
            item = self._polygon_item_at(event.position().toPoint())
            if item:
                if event.modifiers() & Qt.AltModifier:
                    # Alt because a plain double-click already inserts a
                    # vertex, and inserting one is the more common act.
                    edge_index = self._edge_at(item.model, scene_pos)
                    if edge_index is not None and self.toggle_edge_curve(item, edge_index):
                        return
                if self._session is not None:
                    self._session.begin(item.model)
                if self._insert_vertex(item, scene_pos):
                    if self._session is not None:
                        self._session.commit(self.project, "Insert Vertex")
                    return
                if self._session is not None:
                    self._session.cancel()
        super().mouseDoubleClickEvent(event)

    # How far the mouse may travel and still count as a click, in screen pixels.
    CLICK_SLOP_PX = 3.0

    def mouseReleaseEvent(self, event) -> None:
        if self._panning and event.button() == Qt.LeftButton:
            origin = self._pan_origin
            self._panning = False
            self._pan_last = None
            self._pan_origin = None
            if (
                origin is not None
                and (event.position() - origin).manhattanLength() <= self.CLICK_SLOP_PX
                and not (event.modifiers() & Qt.ControlModifier)
            ):
                self.select_shape(None)
        if self.tool == "select" and event.button() == Qt.LeftButton:
            self.setDragMode(QGraphicsView.NoDrag)
            self._circle_drag_state = {}
            label = self.GESTURE_LABELS.get(self._body_drag.get("mode")) if self._body_drag else None
            self._end_body_drag()
            self._clear_snap_marker()
            self._commit_edit(label)
        super().mouseReleaseEvent(event)

    NUDGE_STEP = 1.0
    NUDGE_STEP_LARGE = 10.0

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            return

        deltas = {
            Qt.Key_Left: (-1.0, 0.0),
            Qt.Key_Right: (1.0, 0.0),
            Qt.Key_Up: (0.0, -1.0),
            Qt.Key_Down: (0.0, 1.0),
        }
        direction = deltas.get(event.key())
        if direction is not None:
            step = self.NUDGE_STEP_LARGE if event.modifiers() & Qt.ShiftModifier else self.NUDGE_STEP
            if self._nudge(direction[0] * step, direction[1] * step):
                event.accept()
                return

        super().keyPressEvent(event)

    # --- body gestures ---------------------------------------------------
    #
    # Dragging the shape itself moves it; Alt rotates about its centre and
    # Ctrl scales from it. Driving all three from the view rather than from
    # Qt's ItemIsMovable keeps one code path, and is what lets Shift mean
    # "constrain" instead of "actually move this time".

    @staticmethod
    def _shape_centre(shape: Shape) -> Tuple[float, float]:
        if isinstance(shape, CircleShape):
            return shape.center
        points = shape.points
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return ((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0)

    def _body_gesture(self, modifiers) -> str:
        if modifiers & Qt.AltModifier:
            return "rotate"
        if modifiers & Qt.ControlModifier:
            return "scale"
        return "move"

    def _group_items(self, item):
        """Every item that moves when this one does.

        A grouped surface is not a container - the members stay independent
        shapes with their own vertices. Grouping only says that a body gesture
        on any of them is a gesture on all of them, which is what mapping a
        window frame or a row of columns actually needs.
        """
        group_id = getattr(item.model, "group_id", None)
        if not group_id:
            return [item]
        members = [
            self.items_by_id[shape.id]
            for shape in self.project.shapes
            if getattr(shape, "group_id", None) == group_id and shape.id in self.items_by_id
        ]
        return members or [item]

    def _drag_members(self, item):
        """The items a drag will actually touch: the group, or the selection."""
        if getattr(item.model, "group_id", None):
            return self._group_items(item)
        selected = [
            other for other in self.scene.selectedItems()
            if isinstance(other, (PolygonItem, CircleItem, MeshItem))
        ]
        if item in selected and len(selected) > 1:
            return selected
        return [item]

    @staticmethod
    def _member_snapshot(item) -> Dict[str, object]:
        shape = item.model
        return {
            "item": item,
            "shape": shape,
            "points": list(shape.points) if isinstance(shape, (PolygonShape, MeshShape)) else None,
            # Masks are canvas-space rings, so every body gesture has to carry
            # them: a window that stays put while its wall moves is a hole in
            # the wrong place, and the operator will not notice until the show.
            "masks": [list(mask.points) for mask in getattr(shape, "masks", [])],
            "center": tuple(shape.center) if isinstance(shape, CircleShape) else None,
            "anchors": list(shape.anchors) if isinstance(shape, CircleShape) else None,
            "radius_x": getattr(shape, "radius_x", 0.0),
            "radius_y": getattr(shape, "radius_y", 0.0),
            "handle_angle": getattr(item, "handle_angle", 0.0),
        }

    def _members_centre(self, members) -> Tuple[float, float]:
        """The pivot a gesture turns about: the centre of everything moving.

        Rotating a group about each member's own centre would spin the parts
        in place and leave the arrangement untouched, which is not what
        "rotate the group" means to anyone.
        """
        if len(members) == 1:
            return self._shape_centre(members[0]["shape"])
        boxes = [self._shape_bounds(member["shape"]) for member in members]
        return (
            (min(b[0] for b in boxes) + max(b[1] for b in boxes)) / 2.0,
            (min(b[2] for b in boxes) + max(b[3] for b in boxes)) / 2.0,
        )

    @staticmethod
    def _shape_bounds(shape: Shape) -> Tuple[float, float, float, float]:
        if isinstance(shape, CircleShape):
            cx, cy = shape.center
            rx, ry = max(shape.radius_x, 1.0), max(shape.radius_y, 1.0)
            return (cx - rx, cx + rx, cy - ry, cy + ry)
        points = shape.outline() if isinstance(shape, PolygonShape) else shape.points
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return (min(xs), max(xs), min(ys), max(ys))

    def _begin_body_drag(self, item, scene_pos: QPointF, modifiers, mode: Optional[str] = None) -> None:
        if item.model.locked:
            self._body_drag = {}
            return
        # A locked member of a group stays put while the rest of the group
        # moves - that is what locking one surface after calibrating it means.
        members = [
            self._member_snapshot(other)
            for other in self._drag_members(item)
            if not other.model.locked
        ]
        if not members:
            self._body_drag = {}
            return
        self._body_drag = {
            "item": item,
            "members": members,
            # A bounding-box grip names its own gesture; a drag on the body
            # reads it off the modifiers.
            "mode": mode or self._body_gesture(modifiers),
            "start": (scene_pos.x(), scene_pos.y()),
            "centre": self._members_centre(members),
        }

    def _update_body_drag(self, scene_pos: QPointF, modifiers) -> bool:
        state = self._body_drag
        if not state:
            return False

        sx, sy = state["start"]
        cx, cy = state["centre"]
        dx, dy = scene_pos.x() - sx, scene_pos.y() - sy
        mode = state["mode"]

        if mode == "move":
            if modifiers & Qt.ShiftModifier:
                # Lock to whichever axis the hand committed to first.
                if abs(dx) >= abs(dy):
                    dy = 0.0
                else:
                    dx = 0.0
            for member in state["members"]:
                self._apply_body_move(member, dx, dy)
        elif mode == "rotate":
            start_angle = math.atan2(sy - cy, sx - cx)
            angle = math.atan2(scene_pos.y() - cy, scene_pos.x() - cx) - start_angle
            if modifiers & Qt.ShiftModifier:
                step = math.radians(15.0)
                angle = round(angle / step) * step
            for member in state["members"]:
                self._apply_body_rotate(member, (cx, cy), angle)
        else:  # scale
            start_len = math.hypot(sx - cx, sy - cy)
            if start_len < 1e-6:
                return True
            factor = math.hypot(scene_pos.x() - cx, scene_pos.y() - cy) / start_len
            factor = max(0.05, factor)
            for member in state["members"]:
                self._apply_body_scale(member, (cx, cy), factor)

        for member in state["members"]:
            self._update_mode_handles(member["item"])
        self.project.touch()
        return True

    @staticmethod
    def _apply_to_masks(shape, member, transform) -> None:
        """Run a body gesture's point transform over the shape's masks too."""
        for mask, points in zip(getattr(shape, "masks", []), member.get("masks") or []):
            mask.points = [transform(x, y) for x, y in points]

    def _apply_body_move(self, member, dx: float, dy: float) -> None:
        item, shape = member["item"], member["shape"]
        self._apply_to_masks(shape, member, lambda x, y: (x + dx, y + dy))
        if isinstance(shape, (PolygonShape, MeshShape)):
            shape.points = [(x + dx, y + dy) for x, y in member["points"]]
            item.update_path()
        else:
            ox, oy = member["center"]
            shape.center = (ox + dx, oy + dy)
            shape.anchors = [(x + dx, y + dy) for x, y in member["anchors"]]
            item.update_rect()

    def _apply_body_rotate(self, member, centre, angle: float) -> None:
        item, shape = member["item"], member["shape"]
        cx, cy = centre
        cos_a, sin_a = math.cos(angle), math.sin(angle)

        def spin(x, y):
            ox, oy = x - cx, y - cy
            return (cx + ox * cos_a - oy * sin_a, cy + ox * sin_a + oy * cos_a)

        self._apply_to_masks(shape, member, spin)
        if isinstance(shape, (PolygonShape, MeshShape)):
            shape.points = [spin(x, y) for x, y in member["points"]]
            item.update_path()
        else:
            # A circle has no orientation of its own, so rotating it turns the
            # handles and the media inside it rather than the outline. Inside a
            # group its centre still has to travel around the group's pivot.
            item.handle_angle = member["handle_angle"] + angle
            shape.center = spin(*member["center"])
            shape.anchors = [spin(x, y) for x, y in member["anchors"]]
            if shape.media:
                shape.media.transform.rotation = math.degrees(angle)
            item.update_rect()

    def _apply_body_scale(self, member, centre, factor: float) -> None:
        item, shape = member["item"], member["shape"]
        cx, cy = centre
        self._apply_to_masks(
            shape, member, lambda x, y: (cx + (x - cx) * factor, cy + (y - cy) * factor)
        )
        if isinstance(shape, (PolygonShape, MeshShape)):
            shape.points = [
                (cx + (x - cx) * factor, cy + (y - cy) * factor)
                for x, y in member["points"]
            ]
            item.update_path()
        else:
            ox, oy = member["center"]
            shape.center = (cx + (ox - cx) * factor, cy + (oy - cy) * factor)
            shape.radius_x = max(1.0, member["radius_x"] * factor)
            shape.radius_y = max(1.0, member["radius_y"] * factor)
            item.update_rect()

    def _end_body_drag(self) -> None:
        self._body_drag = {}

    def _release_transform_handle(self) -> None:
        """Finish a drag that started on a bounding-box grip.

        The view's own mouseReleaseEvent does not run for these, because the
        handle accepted the press.
        """
        label = self.GESTURE_LABELS.get(self._body_drag.get("mode")) if self._body_drag else None
        self._end_body_drag()
        self._commit_edit(label)

    # --- bounding box ----------------------------------------------------

    # How far above the box the rotate grip floats, in screen pixels.
    ROTATE_HANDLE_OFFSET_PX = 30.0

    def _clear_transform_handles(self) -> None:
        for handle in self._transform_handles:
            self.scene.removeItem(handle)
        self._transform_handles = []
        self.scene.transform_box = None
        self.scene.transform_pivot = None
        self.scene.update()

    def _build_transform_handles(self, item) -> None:
        self._clear_transform_handles()
        if item is None or item.model.locked or self._point_mode:
            return
        for mode in ("scale", "scale", "scale", "scale", "rotate"):
            handle = TransformHandle(self, item, mode)
            self.scene.addItem(handle)
            self._transform_handles.append(handle)
        self._update_transform_handles(item)

    def _update_transform_handles(self, item) -> None:
        if not self._transform_handles or item is None:
            return

        # The box spans everything the grips will move: the group, or the
        # whole multi-selection. A box around one member would promise a
        # transform the drag does not perform.
        members = self._drag_members(item)
        boxes = [self._shape_bounds(member.model) for member in members]
        minx = min(b[0] for b in boxes)
        maxx = max(b[1] for b in boxes)
        miny = min(b[2] for b in boxes)
        maxy = max(b[3] for b in boxes)

        corners = [(minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy)]
        for handle, (x, y) in zip(self._transform_handles[:4], corners):
            handle.setPos(x, y)

        # Offset in screen pixels, so the grip keeps its distance from the box
        # whatever the zoom.
        offset = self.ROTATE_HANDLE_OFFSET_PX / max(self._zoom, 1e-6)
        pivot = QPointF((minx + maxx) / 2.0, miny - offset)
        self._transform_handles[4].setPos(pivot)

        self.scene.transform_box = QRectF(minx, miny, maxx - minx, maxy - miny)
        self.scene.transform_pivot = pivot
        self.scene.update()

    def _nudge(self, dx: float, dy: float) -> bool:
        """Move the active vertex, or the whole shape if no vertex is armed.

        Aligning a projection is sub-pixel work; a mouse cannot do it. Held
        arrow keys collapse into one undo entry via the command merge window.
        """
        item = self._current_selected_item()
        if item is None or item.model.locked:
            return False

        if self._session is not None:
            self._session.begin(item.model)

        vertex_index = None
        if self._active_vertex and self._active_vertex[0] is item:
            vertex_index = self._active_vertex[1]

        shape = item.model
        if isinstance(shape, (PolygonShape, MeshShape)):
            points = list(shape.points)
            if vertex_index is not None and vertex_index < len(points):
                x, y = points[vertex_index]
                points[vertex_index] = (x + dx, y + dy)
                label = "Nudge Vertex"
            else:
                points = [(x + dx, y + dy) for x, y in points]
                label = "Nudge Shape"
            shape.points = points
        elif isinstance(shape, CircleShape):
            shape.center = (shape.center[0] + dx, shape.center[1] + dy)
            shape.anchors = [(x + dx, y + dy) for x, y in shape.anchors]
            label = "Nudge Shape"
        else:
            if self._session is not None:
                self._session.cancel()
            return False

        self.project.touch()
        if self._session is not None:
            self._session.commit(self.project, label)
        return True

    def _create_default_polygon(self, center: QPointF, size: float, name: str) -> PolygonShape:
        half = size / 2.0
        points = [
            (center.x() - half, center.y() - half),
            (center.x() + half, center.y() - half),
            (center.x() + half, center.y() + half),
            (center.x() - half, center.y() + half),
        ]
        shape = polygon_from_points(points, name=name)
        return shape

    def _insert_vertex(self, item: PolygonItem, point: QPointF) -> bool:
        points = item.model.points
        if len(points) < 2:
            return False
        min_dist = None
        insert_index = None
        for idx in range(len(points)):
            p1 = QPointF(*points[idx])
            p2 = QPointF(*points[(idx + 1) % len(points)])
            dist = _distance_point_to_segment(point, p1, p2)
            if min_dist is None or dist < min_dist:
                min_dist = dist
                insert_index = idx
        if min_dist is None or min_dist > 12.0 or insert_index is None:
            return False
        insert_at = insert_index + 1
        points.insert(insert_at, (point.x(), point.y()))
        item.model.points = points
        edges = list(item.model.edges)
        old_count = len(points) - 1
        if len(edges) < old_count:
            edges.extend(EdgeVisibility() for _ in range(old_count - len(edges)))
        elif len(edges) > old_count:
            edges = edges[:old_count]
        edges.insert(insert_at, EdgeVisibility())
        item.model.edges = edges[: len(points)]
        item.update_path()
        self._update_point_handles(item)
        self.project.touch()
        self.selection_changed.emit(item.model)
        return True

    def _on_selection_changed(self) -> None:
        try:
            items = list(self.scene.items())
        except RuntimeError:
            return
        for item in items:
            if isinstance(item, (PolygonItem, CircleItem, MeshItem)):
                item.set_handles_visible(False)
        selected = self.scene.selectedItems()
        # An armed vertex only makes sense while its own shape stays selected.
        if self._active_vertex is not None:
            if not selected or selected[0] is not self._active_vertex[0]:
                self._active_vertex = None
        shapes = [i for i in selected if isinstance(i, (PolygonItem, CircleItem, MeshItem))]

        # A genuinely new selection starts on the transform grips; toggling
        # back to points is a deliberate second click, not something inherited
        # from whatever was selected before.
        key = tuple(sorted(item.model.id for item in shapes))
        if key != self._selection_key:
            self._selection_key = key
            self._point_mode = False

        if shapes:
            for item in shapes:
                self._set_handles_for_item(item)
            # One set of grips around everything selected: a group is dragged
            # as a whole, so the box that says "this is what moves" has to be
            # the whole thing too.
            self._build_transform_handles(shapes[0])
            self.selection_changed.emit(shapes[0].model)
            return
        self._clear_transform_handles()
        self.selection_changed.emit(None)

    def toggle_handle_mode(self) -> None:
        """Swap between the bounding-box grips and the shape's own points."""
        self.set_handle_mode(not self._point_mode)

    def set_handle_mode(self, point_mode: bool) -> None:
        self._point_mode = bool(point_mode)
        for item in self.scene.selectedItems():
            if isinstance(item, (PolygonItem, CircleItem, MeshItem)):
                self._update_mode_handles(item)
        first = self._current_selected_item()
        if first is not None:
            self._build_transform_handles(first)
        self.handle_mode_changed.emit(self._point_mode)

    def _handles_visible_for(self, item) -> bool:
        """Points show when the shape is selected, unlocked and in point mode.

        Locked matters: the shape itself refused to move all along, but the
        handles stayed live, so a calibrated surface could still be reshaped
        corner by corner.
        """
        return bool(item.isSelected() and self._point_mode and not item.model.locked)

    def _current_selected_item(self):
        items = self.scene.selectedItems()
        return items[0] if items else None

    def _set_handles_for_item(self, item) -> None:
        """One set of handles, always the vertices.

        There is no mode to switch any more. Scaling and rotating are gestures
        on the shape's body (Ctrl and Alt), so the canvas no longer has to
        swap the handles out from under the user to offer them - and in a live
        show a trip to the toolbar to change mode is a trip nobody has time
        for.
        """
        if isinstance(item, MeshItem):
            self._create_mesh_handles(item)
        elif isinstance(item, PolygonItem):
            self._create_point_handles(item)
            self._update_point_handles(item)
        elif isinstance(item, CircleItem):
            self._create_circle_point_handles(item)
            self._update_circle_point_handles(item)
        self._update_mask_handles(item)

    def _update_mode_handles(self, item) -> None:
        if not hasattr(item, "handles"):
            return
        if isinstance(item, MeshItem):
            self._update_mesh_handles(item)
        elif isinstance(item, PolygonItem):
            self._update_point_handles(item)
        elif isinstance(item, CircleItem):
            self._update_circle_point_handles(item)
        self._update_mask_handles(item)
        self._update_transform_handles(item)

    def _tick_playback(self) -> None:
        try:
            if not self.project.transport.playing:
                return
        except RuntimeError:
            self._playback_timer.stop()
            return
        for shape in self.project.shapes:
            media = getattr(shape, "media", None)
            if shape.visible and media is not None and (media.is_timed or media.is_live):
                self.viewport().update()
                return

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._playback_timer.start()

    def hideEvent(self, event) -> None:
        self._playback_timer.stop()
        super().hideEvent(event)

    def _snap_point(self, point: QPointF) -> QPointF:
        grid = self.scene.grid_size
        x = round(point.x() / grid) * grid
        y = round(point.y() / grid) * grid
        return QPointF(x, y)


def _distance_point_to_segment(p: QPointF, a: QPointF, b: QPointF) -> float:
    ax, ay = a.x(), a.y()
    bx, by = b.x(), b.y()
    px, py = p.x(), p.y()
    abx = bx - ax
    aby = by - ay
    apx = px - ax
    apy = py - ay
    ab_len2 = abx * abx + aby * aby
    if ab_len2 == 0:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    t = (apx * abx + apy * aby) / ab_len2
    t = max(0.0, min(1.0, t))
    cx = ax + abx * t
    cy = ay + aby * t
    dx = px - cx
    dy = py - cy
    return (dx * dx + dy * dy) ** 0.5

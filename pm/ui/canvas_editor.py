from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
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

from pm.media.image_cache import get_qimage
from pm.model.commands import AddShapeCommand, EditSession
from pm.model.project import Project
from pm.model.snapping import find_snap, shape_edges, shape_vertices, snap_to_grid
from pm.model.shapes import CircleShape, EdgeVisibility, PolygonShape, Shape, circle_from_center, polygon_from_points
from pm.render.fit import content_rect
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
        if self.snap_marker is None:
            return
        # Sized in scene units against the current zoom so the ring stays the
        # same size on screen however far in the user is.
        scale = painter.worldTransform().m11() or 1.0
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


def _paint_media(painter: QPainter, shape: Shape, path: QPainterPath) -> bool:
    """Draw a shape's media into the editor, matching what gets projected.

    Corner-pinned quads go through QTransform.quadToQuad, which is the same
    homography the output shader applies - so what the user drags here is what
    lands on the wall. Returns False when there is nothing to draw and the
    caller should fall back to the flat fill colour.

    Video is deliberately not previewed: a second decoder per shape would
    double the cost of every clip just to feed the editor.
    """
    media = getattr(shape, "media", None)
    if not media or media.kind != "image":
        return False

    image = get_qimage(media.path)
    if image is None:
        return False

    painter.save()
    painter.setClipPath(path)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

    mode = (media.fit_mode or "stretch").lower()

    transform = None
    if mode == "warp" and isinstance(shape, PolygonShape):
        transform = _warp_transform(shape, image)

    if transform is not None:
        painter.setTransform(transform, True)
        painter.drawImage(0, 0, image)
    else:
        # Same `content_rect` the renderer builds its UVs from, so contain
        # letterboxes and cover crops here exactly as they do on the wall.
        # Painting the bounding box directly - which is what this used to do -
        # stretched every mode, and the canvas quietly disagreed with the
        # output for contain and cover.
        box = path.boundingRect()
        offset_x, offset_y, content_w, content_h = content_rect(
            box.width(), box.height(), image.width(), image.height(), mode
        )
        painter.drawImage(
            QRectF(box.x() + offset_x, box.y() + offset_y, content_w, content_h),
            image,
        )

    painter.restore()
    return True


def _warp_transform(shape: PolygonShape, image: QImage) -> Optional[QTransform]:
    """Image-pixel space -> canvas space for a corner-pinned quad."""
    uvs = corner_uv_assignment(shape.points)
    if uvs is None:
        return None

    width, height = image.width(), image.height()
    source = QPolygonF([QPointF(u * width, v * height) for u, v in uvs])
    target = QPolygonF([QPointF(x, y) for x, y in shape.points])
    # Returns None when the quad has collapsed - self-crossing corners, or a
    # shape dragged flat.
    return QTransform.quadToQuad(source, target)


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


class PolygonItem(QGraphicsPathItem):
    def __init__(self, model: PolygonShape, on_moved=None) -> None:
        super().__init__()
        self.model = model
        self._on_moved = on_moved
        self.handles: List[VertexHandle] = []
        self._drag_value = QPointF(0, 0)
        self.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemSendsGeometryChanges)
        self.setBrush(QBrush(QColor(*model.fill_color)))
        self.setPen(QPen(QColor(*model.stroke_color), max(model.stroke_width, 1.0)))
        self.update_path()

    def set_handles_visible(self, visible: bool) -> None:
        for handle in self.handles:
            handle.setVisible(visible)

    def update_path(self) -> None:
        path = QPainterPath()
        if self.model.points:
            path.moveTo(*self.model.points[0])
            for p in self.model.points[1:]:
                path.lineTo(*p)
            path.closeSubpath()
        self.setPath(path)

    def sync_style(self) -> None:
        self.setBrush(QBrush(QColor(*self.model.fill_color)))
        self.setPen(QPen(QColor(*self.model.stroke_color), max(self.model.stroke_width, 1.0)))

    def paint(self, painter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.Antialiasing, True)
        if not _paint_media(painter, self.model, self.path()):
            painter.fillPath(self.path(), QBrush(QColor(*self.model.fill_color)))

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
                    if edge.percent < 1.0:
                        dx = (p2[0] - p1[0]) * edge.percent
                        dy = (p2[1] - p1[1]) * edge.percent
                        p2 = (p1[0] + dx, p1[1] + dy)
                    painter.drawLine(p1[0], p1[1], p2[0], p2[1])

        if option.state & QStyle.State_Selected:
            pen = QPen(QColor(0, 212, 170, 220), 2.0, Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(self.path())
    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange:
            if self.model.locked:
                self._drag_value = QPointF(value.x(), value.y())
                return QPointF(0, 0)
            delta = value - self._drag_value
            if delta.x() != 0 or delta.y() != 0:
                self.model.points = [(x + delta.x(), y + delta.y()) for x, y in self.model.points]
                self._drag_value = QPointF(value.x(), value.y())
                self.update_path()
                if self._on_moved:
                    self._on_moved()
            return QPointF(0, 0)
        return super().itemChange(change, value)

    def reset_drag(self) -> None:
        self._drag_value = QPointF(0, 0)


class CircleItem(QGraphicsEllipseItem):
    def __init__(self, model: CircleShape, on_moved=None) -> None:
        super().__init__()
        self.model = model
        self._on_moved = on_moved
        self.handles: List[VertexHandle] = []
        self._drag_value = QPointF(0, 0)
        self.handle_angle = -math.pi / 2.0
        self.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemSendsGeometryChanges)
        self.setBrush(QBrush(QColor(*model.fill_color)))
        self.setPen(QPen(QColor(*model.stroke_color), max(model.stroke_width, 1.0)))
        self.update_rect()

    def set_handles_visible(self, visible: bool) -> None:
        for handle in self.handles:
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
        if _paint_media(painter, self.model, ellipse):
            painter.setBrush(Qt.NoBrush)
        else:
            painter.setBrush(QBrush(QColor(*self.model.fill_color)))
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

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange:
            if self.model.locked:
                self._drag_value = QPointF(value.x(), value.y())
                return QPointF(0, 0)
            delta = value - self._drag_value
            if delta.x() != 0 or delta.y() != 0:
                self.model.center = (self.model.center[0] + delta.x(), self.model.center[1] + delta.y())
                if self.model.anchors:
                    self.model.anchors = [(p[0] + delta.x(), p[1] + delta.y()) for p in self.model.anchors]
                self._drag_value = QPointF(value.x(), value.y())
                self.update_rect()
                if self._on_moved:
                    self._on_moved()
            return QPointF(0, 0)
        return super().itemChange(change, value)

    def reset_drag(self) -> None:
        self._drag_value = QPointF(0, 0)


class CanvasEditor(QGraphicsView):
    selection_changed = Signal(object)
    zoom_changed = Signal(float)
    edit_mode_changed = Signal(str)

    # Magnet radius in screen pixels, divided by the zoom before use so it
    # feels constant to the hand rather than to the scene.
    SNAP_THRESHOLD_PX = 12.0

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
        self._last_canvas = (project.canvas.width, project.canvas.height)
        self._panning = False
        self._pan_last: Optional[QPointF] = None
        self._edit_mode = "points"
        self._scale_state = {}
        self._rotate_state = {}
        self._circle_drag_state = {}

        self.tool = "select"
        self._items_movable = False

        self.undo_stack: Optional[QUndoStack] = None
        self._session: Optional[EditSession] = None
        self.snap_enabled = True
        # (item, vertex index) of the last handle pressed, so arrow keys nudge
        # that corner instead of the whole surface.
        self._active_vertex: Optional[Tuple[object, int]] = None
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
            if isinstance(shape, PolygonShape):
                vertices.extend(shape_vertices(shape.points))
                edges.extend(shape_edges(shape.points))
            elif isinstance(shape, CircleShape):
                # The four anchors are the useful alignment points; the curve
                # itself has no segments to snap an edge against.
                vertices.extend(shape_vertices(shape.anchors))
        return vertices, edges

    def _snap_vertex(self, owner, pos: QPointF) -> QPointF:
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
            grid_size=self.scene.grid_size,
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
        elif isinstance(hit_item, (PolygonItem, CircleItem)):
            model = hit_item.model
        elif hit_item is not None and isinstance(hit_item.parentItem(), (PolygonItem, CircleItem)):
            model = hit_item.parentItem().model
        else:
            model = getattr(self._current_selected_item(), "model", None)

        self._session.begin(model)

    def _commit_edit(self) -> None:
        if self._session is None or not self._session.active:
            return
        labels = {"points": "Move Points", "scale": "Scale Shape", "rotate": "Rotate Shape"}
        self._session.commit(self.project, labels.get(self._edit_mode, "Edit Shape"))

    def set_tool(self, tool: str) -> None:
        self.tool = tool
        if tool == "select":
            self.setDragMode(QGraphicsView.NoDrag)
            self.viewport().setCursor(Qt.ArrowCursor)
        else:
            self.setDragMode(QGraphicsView.NoDrag)
            self.viewport().setCursor(Qt.CrossCursor)
        self.setFocus(Qt.OtherFocusReason)
        if tool != "select":
            self._set_items_movable(False)
        if tool != "select":
            self.set_edit_mode("points")

    def set_edit_mode(self, mode: str) -> None:
        if mode not in ("points", "scale", "rotate"):
            mode = "points"
        if self._edit_mode == mode:
            return
        self._edit_mode = mode
        item = self._current_selected_item()
        if item and mode == "points" and isinstance(item, CircleItem):
            self._ensure_circle_anchors(item.model)
        if item:
            self._set_handles_for_item(item)
        self.edit_mode_changed.emit(self._edit_mode)

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
        if isinstance(shape, PolygonShape):
            item = PolygonItem(shape, on_moved=self._on_shape_moved)
            item.setVisible(shape.visible)
            item.setFlag(QGraphicsItem.ItemIsMovable, self._items_movable)
            self._create_point_handles(item)
            return item
        if isinstance(shape, CircleShape):
            item = CircleItem(shape, on_moved=self._on_shape_moved)
            item.setVisible(shape.visible)
            item.setFlag(QGraphicsItem.ItemIsMovable, self._items_movable)
            self._create_circle_point_handles(item)
            return item
        raise ValueError("Shape desconhecido")

    def _update_item(self, item, shape: Shape) -> None:
        if isinstance(item, PolygonItem):
            item.update_path()
            item.sync_style()
            item.setVisible(shape.visible)
            item.setFlag(QGraphicsItem.ItemIsMovable, self._items_movable)
            self._update_mode_handles(item)
        elif isinstance(item, CircleItem):
            item.update_rect()
            item.sync_style()
            item.setVisible(shape.visible)
            item.setFlag(QGraphicsItem.ItemIsMovable, self._items_movable)
            self._update_mode_handles(item)

    def _clear_handles(self, item) -> None:
        for handle in getattr(item, "handles", []):
            handle.setParentItem(None)
            self.scene.removeItem(handle)
        item.handles = []

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
        visible = item.isSelected()
        for handle in item.handles:
            handle.setVisible(visible)

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
        visible = item.isSelected()
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

    def _create_scale_handles(self, item: PolygonItem) -> None:
        self._clear_handles(item)
        for idx in range(4):
            handle = VertexHandle(item, idx, self._on_scale_handle_moved, None, self._on_scale_handle_pressed)
            handle.setParentItem(item)
            handle.setVisible(False)
            item.handles.append(handle)
        self._update_scale_handles(item)

    def _update_scale_handles(self, item: PolygonItem) -> None:
        points = item.model.points
        if not points:
            return
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        minx, maxx = min(xs), max(xs)
        miny, maxy = min(ys), max(ys)
        positions = [(minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy)]
        for handle, pos in zip(item.handles, positions):
            handle.set_pos_silent(pos[0], pos[1])
        visible = item.isSelected()
        for handle in item.handles:
            handle.setVisible(visible)

    def _create_circle_scale_handles(self, item: CircleItem) -> None:
        self._clear_handles(item)
        count = max(4, int(getattr(item.model, "control_points", 4)))
        if count % 2 != 0:
            count += 1
        for idx in range(count):
            handle = VertexHandle(item, idx, self._on_circle_scale_handle_moved, None, self._on_circle_scale_handle_pressed)
            handle.setParentItem(item)
            handle.setVisible(False)
            item.handles.append(handle)
        self._update_circle_scale_handles(item)

    def _update_circle_scale_handles(self, item: CircleItem) -> None:
        count = max(4, int(getattr(item.model, "control_points", 4)))
        if count % 2 != 0:
            count += 1
        if len(item.handles) != count:
            self._create_circle_scale_handles(item)
            return
        cx, cy = item.model.center
        rx = max(item.model.radius_x, 1.0)
        ry = max(item.model.radius_y, 1.0)
        for idx, handle in enumerate(item.handles):
            angle = (idx / count) * (2.0 * 3.141592653589793)
            x = cx + rx * math.cos(angle)
            y = cy + ry * math.sin(angle)
            handle.set_pos_silent(float(x), float(y))
        visible = item.isSelected()
        for handle in item.handles:
            handle.setVisible(visible)

    def _create_rotate_handle(self, item) -> None:
        self._clear_handles(item)
        handle = VertexHandle(
            item,
            0,
            self._on_rotate_handle_moved,
            lambda p, o=item: self._rotate_snap(o, p),
            self._on_rotate_handle_pressed,
        )
        handle.setParentItem(item)
        handle.setVisible(False)
        item.handles.append(handle)
        self._update_rotate_handle(item)

    def _update_rotate_handle(self, item) -> None:
        if not item.handles:
            return
        pos = self._rotate_snap(item, item.handles[0].pos())
        item.handles[0].set_pos_silent(pos.x(), pos.y())
        visible = item.isSelected()
        for handle in item.handles:
            handle.setVisible(visible)

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


    def _rotate_snap(self, owner, pos: QPointF) -> QPointF:
        if isinstance(owner, PolygonItem):
            points = owner.model.points
            if not points:
                return pos
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            minx, maxx = min(xs), max(xs)
            miny, maxy = min(ys), max(ys)
            cx = (minx + maxx) / 2.0
            cy = (miny + maxy) / 2.0
            radius = max((maxy - miny) / 2.0, 1.0) + 30.0
        elif isinstance(owner, CircleItem):
            cx, cy = owner.model.center
            radius = max(owner.model.radius_y, 1.0) + 30.0
        else:
            return pos
        angle = math.atan2(pos.y() - cy, pos.x() - cx)
        return QPointF(cx + math.cos(angle) * radius, cy + math.sin(angle) * radius)

    def _on_scale_handle_pressed(self, owner: PolygonItem, index: int, pos: QPointF) -> None:
        points = list(owner.model.points)
        if not points:
            return
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        center = ((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0)
        scene_pos = owner.mapToScene(pos)
        sx = scene_pos.x() - center[0]
        sy = scene_pos.y() - center[1]
        self._scale_state = {
            "owner": owner,
            "points": points,
            "center": center,
            "start_vec": (sx, sy),
        }

    def _on_scale_handle_moved(self, owner: PolygonItem, index: int, pos: QPointF) -> None:
        state = self._scale_state
        if not state or state.get("owner") != owner:
            return
        cx, cy = state["center"]
        sx, sy = state["start_vec"]
        scene_pos = owner.mapToScene(pos)
        nx = scene_pos.x() - cx
        ny = scene_pos.y() - cy
        EPSILON = 1e-4
        scale_x = nx / sx if abs(sx) > EPSILON else 1.0
        scale_y = ny / sy if abs(sy) > EPSILON else 1.0
        scale_x = max(0.1, abs(scale_x))
        scale_y = max(0.1, abs(scale_y))
        new_points = []
        for px, py in state["points"]:
            new_x = cx + (px - cx) * scale_x
            new_y = cy + (py - cy) * scale_y
            new_points.append((new_x, new_y))
        owner.model.points = new_points
        owner.update_path()
        self._update_scale_handles(owner)
        self.project.touch()

    def _on_circle_scale_handle_pressed(self, owner: CircleItem, index: int, pos: QPointF) -> None:
        cx, cy = owner.model.center
        scene_pos = owner.mapToScene(pos)
        sx = scene_pos.x() - cx
        sy = scene_pos.y() - cy
        start_len = (sx * sx + sy * sy) ** 0.5
        self._scale_state = {
            "owner": owner,
            "center": (cx, cy),
            "radius": max(owner.model.radius_x, owner.model.radius_y, 1.0),
            "start_len": start_len,
        }

    def _on_circle_scale_handle_moved(self, owner: CircleItem, index: int, pos: QPointF) -> None:
        state = self._scale_state
        if not state or state.get("owner") != owner:
            return
        cx, cy = state["center"]
        scene_pos = owner.mapToScene(pos)
        nx = scene_pos.x() - cx
        ny = scene_pos.y() - cy
        new_len = (nx * nx + ny * ny) ** 0.5
        start_len = state.get("start_len", 0.0)
        scale = new_len / start_len if start_len > 1e-4 else 1.0
        scale = max(0.1, abs(scale))
        radius = max(1.0, state["radius"] * scale)
        owner.model.radius_x = radius
        owner.model.radius_y = radius
        owner.update_rect()
        self._update_circle_scale_handles(owner)
        self._update_circle_point_handles(owner)
        self.project.touch()

    def _on_rotate_handle_pressed(self, owner, index: int, pos: QPointF) -> None:
        if isinstance(owner, PolygonItem):
            points = list(owner.model.points)
            if not points:
                return
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            center = ((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0)
            scene_pos = owner.mapToScene(pos)
            angle = math.atan2(scene_pos.y() - center[1], scene_pos.x() - center[0])
            self._rotate_state = {
                "owner": owner,
                "points": points,
                "center": center,
                "start_angle": angle,
            }
        elif isinstance(owner, CircleItem):
            cx, cy = owner.model.center
            scene_pos = owner.mapToScene(pos)
            angle = math.atan2(scene_pos.y() - cy, scene_pos.x() - cx)
            start_rot = 0.0
            if owner.model.media:
                start_rot = float(owner.model.media.transform.rotation)
            self._rotate_state = {
                "owner": owner,
                "center": (cx, cy),
                "start_angle": angle,
                "start_rotation": start_rot,
                "start_handle_angle": getattr(owner, "handle_angle", -math.pi / 2.0),
            }

    def _on_rotate_handle_moved(self, owner, index: int, pos: QPointF) -> None:
        state = self._rotate_state
        if not state or state.get("owner") != owner:
            return
        cx, cy = state["center"]
        scene_pos = owner.mapToScene(pos)
        angle = math.atan2(scene_pos.y() - cy, scene_pos.x() - cx)
        delta = angle - state["start_angle"]
        if isinstance(owner, PolygonItem):
            cos_a = math.cos(delta)
            sin_a = math.sin(delta)
            new_points = []
            for px, py in state["points"]:
                dx = px - cx
                dy = py - cy
                new_x = cx + (dx * cos_a - dy * sin_a)
                new_y = cy + (dx * sin_a + dy * cos_a)
                new_points.append((new_x, new_y))
            owner.model.points = new_points
            owner.update_path()
            self.project.touch()
        elif isinstance(owner, CircleItem):
            owner.handle_angle = state.get("start_handle_angle", -math.pi / 2.0) + delta
            owner.update()
            self._update_circle_point_handles(owner)
            if owner.model.media:
                owner.model.media.transform.rotation = state["start_rotation"] + math.degrees(delta)
            self.project.touch()
        self._update_rotate_handle(owner)

    def _on_shape_moved(self) -> None:
        item = self._current_polygon_item()
        if item:
            self._update_mode_handles(item)
        circle_item = self._current_circle_item()
        if circle_item:
            self._update_mode_handles(circle_item)
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

    def _current_circle_item(self) -> Optional[CircleItem]:
        for item in self.scene.selectedItems():
            if isinstance(item, CircleItem):
                return item
        return None

    def select_shape(self, shape_id: Optional[str]) -> None:
        for item in self.scene.selectedItems():
            item.setSelected(False)
        if not shape_id:
            return
        item = self.items_by_id.get(shape_id)
        if item:
            item.setSelected(True)

    def _set_items_movable(self, enabled: bool) -> None:
        self._items_movable = enabled
        for item in self.items_by_id.values():
            if isinstance(item, (PolygonItem, CircleItem)):
                item.setFlag(QGraphicsItem.ItemIsMovable, enabled)

    def set_shape_visibility(self, shape_id: str, visible: bool) -> None:
        item = self.items_by_id.get(shape_id)
        if item:
            item.setVisible(visible)

    def mousePressEvent(self, event) -> None:
        if self.tool == "select" and event.button() == Qt.LeftButton:
            hit_item = self.itemAt(event.position().toPoint())
            if event.modifiers() & Qt.ShiftModifier:
                self._set_items_movable(True)
                self.setDragMode(QGraphicsView.NoDrag)
                self._begin_edit_for(hit_item)
                super().mousePressEvent(event)
                return
            if isinstance(hit_item, VertexHandle) or \
               isinstance(hit_item, (PolygonItem, CircleItem)) or (
                hasattr(hit_item, "parentItem") and isinstance(hit_item.parentItem(), (PolygonItem, CircleItem))
            ):
                self._set_items_movable(False)
                self.setDragMode(QGraphicsView.NoDrag)
                # Snapshot before Qt starts delivering move events.
                self._begin_edit_for(hit_item)
                if isinstance(hit_item, VertexHandle):
                    self._active_vertex = (hit_item.owner, hit_item.index)
                else:
                    self._active_vertex = None
            else:
                self._set_items_movable(False)
                self._panning = True
                self._pan_last = event.position()
                self.setDragMode(QGraphicsView.NoDrag)
        if event.button() == Qt.LeftButton and self.tool in ("polygon", "circle"):
            scene_pos = self._snap_point(self.mapToScene(event.position().toPoint()))
            if self.tool == "polygon":
                shape = self._create_default_polygon(scene_pos, 120.0, "Polígono")
            else:
                shape = circle_from_center((scene_pos.x(), scene_pos.y()), 60.0, name="Círculo")
            if self.undo_stack is not None:
                label = "Add Polygon" if self.tool == "polygon" else "Add Circle"
                self.undo_stack.push(AddShapeCommand(self.project, shape, label))
            else:
                self.project.add_shape(shape)
            self._sync_items()
            self.select_shape(shape.id)
            self.set_tool("select")
            self._edit_mode = "points"
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
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
        if self.tool == "select" and self._edit_mode == "points":
            scene_pos = self._snap_point(self.mapToScene(event.position().toPoint()))
            item = self._polygon_item_at(event.position().toPoint())
            if item:
                if self._session is not None:
                    self._session.begin(item.model)
                if self._insert_vertex(item, scene_pos):
                    if self._session is not None:
                        self._session.commit(self.project, "Insert Vertex")
                    return
                if self._session is not None:
                    self._session.cancel()
        super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._panning and event.button() == Qt.LeftButton:
            self._panning = False
            self._pan_last = None
        if self.tool == "select" and event.button() == Qt.LeftButton:
            self._set_items_movable(False)
            self.setDragMode(QGraphicsView.NoDrag)
            self._reset_item_drag()
            self._scale_state = {}
            self._rotate_state = {}
            self._circle_drag_state = {}
            self._clear_snap_marker()
            self._commit_edit()
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
        if isinstance(shape, PolygonShape):
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

    def _create_default_circle_poly(self, center: QPointF, size: float, name: str) -> PolygonShape:
        half = size / 2.0
        points = [
            (center.x(), center.y() - half),
            (center.x() + half, center.y()),
            (center.x(), center.y() + half),
            (center.x() - half, center.y()),
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
            if isinstance(item, (PolygonItem, CircleItem)):
                item.set_handles_visible(False)
        selected = self.scene.selectedItems()
        # An armed vertex only makes sense while its own shape stays selected.
        if self._active_vertex is not None:
            if not selected or selected[0] is not self._active_vertex[0]:
                self._active_vertex = None
        if selected:
            item = selected[0]
            if isinstance(item, (PolygonItem, CircleItem)):
                self._set_handles_for_item(item)
                item.set_handles_visible(True)
                self.selection_changed.emit(item.model)
                return
        self.selection_changed.emit(None)

    def _current_selected_item(self):
        items = self.scene.selectedItems()
        return items[0] if items else None

    def _set_handles_for_item(self, item) -> None:
        if self._edit_mode == "points":
            if isinstance(item, PolygonItem):
                self._create_point_handles(item)
                self._update_point_handles(item)
            elif isinstance(item, CircleItem):
                self._create_circle_point_handles(item)
                self._update_circle_point_handles(item)
        elif self._edit_mode == "scale":
            if isinstance(item, PolygonItem):
                self._create_scale_handles(item)
            elif isinstance(item, CircleItem):
                self._create_circle_scale_handles(item)
        elif self._edit_mode == "rotate":
            self._create_rotate_handle(item)
        if item.isSelected():
            for handle in item.handles:
                handle.setVisible(True)

    def _update_mode_handles(self, item) -> None:
        if not hasattr(item, "handles"):
            return
        if self._edit_mode == "points":
            if isinstance(item, PolygonItem):
                self._update_point_handles(item)
            elif isinstance(item, CircleItem):
                self._update_circle_point_handles(item)
        elif self._edit_mode == "scale":
            if isinstance(item, PolygonItem):
                self._update_scale_handles(item)
            elif isinstance(item, CircleItem):
                self._update_circle_scale_handles(item)
        elif self._edit_mode == "rotate":
            self._update_rotate_handle(item)

    def _cycle_edit_mode(self) -> None:
        order = ["points", "scale", "rotate"]
        idx = order.index(self._edit_mode) if self._edit_mode in order else 0
        self.set_edit_mode(order[(idx + 1) % len(order)])

    def _reset_item_drag(self) -> None:
        for item in self.items_by_id.values():
            if hasattr(item, "reset_drag"):
                item.reset_drag()

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

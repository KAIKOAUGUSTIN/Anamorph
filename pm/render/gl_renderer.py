from __future__ import annotations

import math
import time
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image
from PySide6.QtCore import QPointF, QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QTransform
from PySide6.QtWidgets import QWidget

from pm.media.video_player import VideoPlayer
from pm.model.media import MediaRef
from pm.model.project import Project
from pm.model.shapes import CircleShape, PolygonShape, Shape
from pm.render.mesh import triangulate_circle, triangulate_polygon


class GLRenderer(QWidget):
    def __init__(self, project: Project, parent=None) -> None:
        super().__init__(parent)
        self.project = project
        self._start_time = time.perf_counter()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)
        self._timer.start(16)
        self.project.changed.connect(self.update)

        self._image_cache: Dict[str, QImage] = {}
        self._video_players: Dict[str, VideoPlayer] = {}

    def cleanup(self) -> None:
        for player in self._video_players.values():
            player.stop()
        self._video_players.clear()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        if not painter.isActive():
            return
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

            canvas_w = max(self.project.canvas.width, 1)
            canvas_h = max(self.project.canvas.height, 1)
            scale_x = self.width() / canvas_w
            scale_y = self.height() / canvas_h
            painter.scale(scale_x, scale_y)

            bg = QColor(*self.project.canvas.background_color)
            painter.fillRect(QRectF(0, 0, canvas_w, canvas_h), bg)

            now = time.perf_counter() - self._start_time

            for shape in self.project.shapes:
                if not shape.visible:
                    continue
                points, indices = self._shape_geometry(shape)
                if not points or not indices:
                    continue

                minx, miny, maxx, maxy = self._bounding_box(points)
                bbox = QRectF(minx, miny, maxx - minx, maxy - miny)

                pulse_factor = 1.0
                if shape.effects.pulse.enabled:
                    pulse_factor = 1.0 + math.sin(now * shape.effects.pulse.speed) * shape.effects.pulse.amount
                strobe_factor = 1.0
                if shape.effects.strobe.enabled:
                    phase = math.sin(now * shape.effects.strobe.hz * 6.28318)
                    strobe_factor = 1.0 if phase >= 0 else 0.0
                if strobe_factor <= 0.0:
                    continue
                opacity = max(0.0, shape.opacity * pulse_factor * strobe_factor)

                painter.save()
                painter.setOpacity(opacity)

                media_image = self._get_media_image(shape.media)
                if media_image:
                    uvs = self._compute_uvs(points, bbox, media_image, shape.media)
                    self._draw_media_mapped(painter, media_image, points, uvs, indices, shape, now)
                else:
                    path = self._path_from_points(points)
                    fill = self._apply_rgb_shift_color(QColor(*shape.fill_color), shape, now)
                    painter.fillPath(path, fill)

                painter.restore()

            self._draw_strokes(painter)

            if self.project.ui_state.get("test_mode"):
                pen = QPen(QColor(0, 212, 170), 4)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(0, 0, canvas_w, canvas_h)
                # Corner markers for test mode
                marker_size = min(canvas_w, canvas_h) // 10
                painter.drawLine(0, 0, marker_size, 0)
                painter.drawLine(0, 0, 0, marker_size)
                painter.drawLine(canvas_w - marker_size, 0, canvas_w, 0)
                painter.drawLine(canvas_w, 0, canvas_w, marker_size)
                painter.drawLine(0, canvas_h - marker_size, 0, canvas_h)
                painter.drawLine(0, canvas_h, marker_size, canvas_h)
                painter.drawLine(canvas_w - marker_size, canvas_h, canvas_w, canvas_h)
                painter.drawLine(canvas_w, canvas_h - marker_size, canvas_w, canvas_h)
        finally:
            painter.end()

    def _shape_geometry(self, shape: Shape) -> Tuple[List[Tuple[float, float]], List[int]]:
        if isinstance(shape, PolygonShape):
            points = list(shape.points)
            indices = triangulate_polygon(points)
            return points, indices
        if isinstance(shape, CircleShape):
            points, indices = triangulate_circle(shape.center, shape.radius_x, shape.radius_y, 48)
            return points, indices
        return [], []

    def _path_from_points(self, points: List[Tuple[float, float]]) -> QPainterPath:
        path = QPainterPath()
        if points:
            path.moveTo(QPointF(*points[0]))
            for pt in points[1:]:
                path.lineTo(QPointF(*pt))
            path.closeSubpath()
        return path

    def _bounding_box(self, points: List[Tuple[float, float]]) -> Tuple[float, float, float, float]:
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return min(xs), min(ys), max(xs), max(ys)

    def _compute_uvs(
        self,
        points: List[Tuple[float, float]],
        bbox: QRectF,
        image: QImage,
        media: MediaRef,
    ) -> List[Tuple[float, float]]:
        minx = bbox.left()
        miny = bbox.top()
        maxx = bbox.right()
        maxy = bbox.bottom()
        box_w = max(maxx - minx, 1e-5)
        box_h = max(maxy - miny, 1e-5)
        media_w = max(image.width(), 1)
        media_h = max(image.height(), 1)
        mode = (media.fit_mode or "stretch").lower()
        if mode == "stretch":
            content_w, content_h = box_w, box_h
        else:
            if mode == "contain":
                scale = min(box_w / media_w, box_h / media_h)
            else:
                scale = max(box_w / media_w, box_h / media_h)
            content_w = media_w * scale
            content_h = media_h * scale
            offset_x = (box_w - content_w) / 2.0
            offset_y = (box_h - content_h) / 2.0
            if content_w <= 0 or content_h <= 0:
                content_w, content_h = box_w, box_h

        uvs: List[Tuple[float, float]] = []
        for x, y in points:
            u = (x - minx - offset_x) / content_w
            v = (y - miny - offset_y) / content_h
            uvs.append((u, v))

        if media and media.transform:
            uvs = self._apply_uv_transform(uvs, media.transform, content_w, content_h)
        return uvs

    def _apply_uv_transform(
        self,
        uvs: List[Tuple[float, float]],
        transform,
        content_w: float,
        content_h: float,
    ) -> List[Tuple[float, float]]:
        if content_w <= 0 or content_h <= 0:
            return uvs
        dx = transform.offset_x / content_w
        dy = transform.offset_y / content_h
        angle = math.radians(transform.rotation)
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        transformed: List[Tuple[float, float]] = []
        for u, v in uvs:
            u += dx
            v += dy
            if abs(angle) > 1e-9:
                x = u - 0.5
                y = v - 0.5
                u = (x * cos_a - y * sin_a) + 0.5
                v = (x * sin_a + y * cos_a) + 0.5
            transformed.append((u, v))
        return transformed

    def _draw_media_mapped(
        self,
        painter: QPainter,
        image: QImage,
        points: List[Tuple[float, float]],
        uvs: List[Tuple[float, float]],
        indices: List[int],
        shape: Shape,
        now: float,
    ) -> None:
        img_w = image.width()
        img_h = image.height()

        rgb = shape.effects.rgb_shift
        shift = 0.0
        if rgb.enabled:
            shift = rgb.amount * 4.0 * math.sin(now * rgb.speed)

        for i in range(0, len(indices), 3):
            i1, i2, i3 = indices[i], indices[i + 1], indices[i + 2]
            dst = [points[i1], points[i2], points[i3]]
            src = [
                (uvs[i1][0] * img_w, uvs[i1][1] * img_h),
                (uvs[i2][0] * img_w, uvs[i2][1] * img_h),
                (uvs[i3][0] * img_w, uvs[i3][1] * img_h),
            ]
            transform = _affine_from_triangles(src, dst)
            if transform is None:
                continue

            if rgb.enabled and abs(shift) > 0.001:
                painter.save()
                painter.setCompositionMode(QPainter.CompositionMode_Plus)
                self._draw_triangle_image(painter, image, src, transform.translated(shift, 0), QColor(255, 0, 0))
                self._draw_triangle_image(painter, image, src, transform.translated(0, shift), QColor(0, 255, 0))
                self._draw_triangle_image(painter, image, src, transform.translated(-shift, 0), QColor(0, 0, 255))
                painter.restore()
            else:
                self._draw_triangle_image(painter, image, src, transform, None)

    def _draw_triangle_image(
        self,
        painter: QPainter,
        image: QImage,
        src_tri: List[Tuple[float, float]],
        transform: QTransform,
        tint: Optional[QColor],
    ) -> None:
        painter.save()
        painter.setTransform(transform, True)
        path = QPainterPath()
        path.moveTo(QPointF(*src_tri[0]))
        path.lineTo(QPointF(*src_tri[1]))
        path.lineTo(QPointF(*src_tri[2]))
        path.closeSubpath()
        painter.setClipPath(path)
        painter.drawImage(0, 0, image)
        if tint:
            painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
            painter.fillRect(QRectF(0, 0, image.width(), image.height()), tint)
        painter.restore()

    def _draw_strokes(self, painter: QPainter) -> None:
        for shape in self.project.shapes:
            if not shape.visible:
                continue
            color = QColor(*shape.stroke_color)
            alpha = int(color.alpha() * shape.opacity)
            color.setAlpha(max(0, min(alpha, 255)))
            pen = QPen(color)
            pen.setWidthF(max(shape.stroke_width, 0.5))
            painter.setPen(pen)
            if isinstance(shape, PolygonShape):
                shape.ensure_edges()
                points = shape.points
                for idx, edge in enumerate(shape.edges):
                    if not edge.visible:
                        continue
                    p1 = points[idx]
                    p2 = points[(idx + 1) % len(points)]
                    if edge.percent < 1.0:
                        dx = (p2[0] - p1[0]) * edge.percent
                        dy = (p2[1] - p1[1]) * edge.percent
                        p2 = (p1[0] + dx, p1[1] + dy)
                    painter.drawLine(p1[0], p1[1], p2[0], p2[1])
            elif isinstance(shape, CircleShape):
                cx, cy = shape.center
                rx = max(shape.radius_x, 1.0)
                ry = max(shape.radius_y, 1.0)
                painter.drawEllipse(cx - rx, cy - ry, rx * 2, ry * 2)

    def _get_media_image(self, media: MediaRef) -> Optional[QImage]:
        if not media or not media.kind or not media.path:
            return None
        if media.kind == "image":
            cached = self._image_cache.get(media.path)
            if cached:
                return cached
            image = self._load_image(media.path)
            if image:
                self._image_cache[media.path] = image
            return image
        if media.kind == "video":
            player = self._video_players.get(media.path)
            if not player:
                player = VideoPlayer(media.path)
                player.start()
                self._video_players[media.path] = player
            frame, _size = player.get_frame()
            if frame is None:
                return None
            qimg = QImage(frame.data, frame.shape[1], frame.shape[0], frame.strides[0], QImage.Format_RGB888).copy()
            return qimg.convertToFormat(QImage.Format_ARGB32)
        return None

    def _load_image(self, path: str) -> Optional[QImage]:
        try:
            img = Image.open(path).convert("RGBA")
            data = img.tobytes("raw", "RGBA")
            qimg = QImage(data, img.width, img.height, QImage.Format_RGBA8888)
            return qimg.copy()
        except Exception:
            return None

    def _apply_rgb_shift_color(self, color: QColor, shape: Shape, now: float) -> QColor:
        if not shape.effects.rgb_shift.enabled:
            return color
        shift = shape.effects.rgb_shift.amount * 25.0 * math.sin(now * shape.effects.rgb_shift.speed)
        r = max(0, min(255, int(color.red() + shift)))
        g = max(0, min(255, int(color.green() - shift)))
        b = max(0, min(255, int(color.blue() + shift)))
        return QColor(r, g, b, color.alpha())


def _affine_from_triangles(
    src: List[Tuple[float, float]],
    dst: List[Tuple[float, float]],
) -> Optional[QTransform]:
    try:
        sx1, sy1 = src[0]
        sx2, sy2 = src[1]
        sx3, sy3 = src[2]
        dx1, dy1 = dst[0]
        dx2, dy2 = dst[1]
        dx3, dy3 = dst[2]
        A = np.array(
            [
                [sx1, sy1, 1, 0, 0, 0],
                [sx2, sy2, 1, 0, 0, 0],
                [sx3, sy3, 1, 0, 0, 0],
                [0, 0, 0, sx1, sy1, 1],
                [0, 0, 0, sx2, sy2, 1],
                [0, 0, 0, sx3, sy3, 1],
            ],
            dtype=float,
        )
        B = np.array([dx1, dx2, dx3, dy1, dy2, dy3], dtype=float)
        a, b, c, d, e, f = np.linalg.solve(A, B)
    except Exception:
        return None
    return QTransform(a, d, 0.0, b, e, 0.0, c, f, 1.0)

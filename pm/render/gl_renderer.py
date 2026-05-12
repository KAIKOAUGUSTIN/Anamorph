"""OpenGL-based renderer using PyOpenGL and QOpenGLWidget."""

from __future__ import annotations

import ctypes
import logging
import math
import time
from typing import Dict, List, Optional, Tuple

import numpy as np
from OpenGL.GL import (
    GL_ARRAY_BUFFER, GL_BLEND, GL_COLOR_BUFFER_BIT, GL_COMPILE_STATUS,
    GL_DYNAMIC_DRAW, GL_ELEMENT_ARRAY_BUFFER, GL_FLOAT, GL_FRAGMENT_SHADER,
    GL_LINEAR, GL_LINES, GL_LINK_STATUS, GL_NO_ERROR,
    GL_POSITION, GL_REPEAT, GL_RGBA, GL_SRC_ALPHA, GL_STATIC_DRAW,
    GL_TEXTURE0, GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER,
    GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T, GL_TRIANGLES, GL_UNSIGNED_INT,
    GL_VERTEX_SHADER, GL_ONE_MINUS_SRC_ALPHA,
    glActiveTexture, glAttachShader, glBindBuffer, glBindTexture,
    glBindVertexArray, glBlendFunc, glBufferData, glClear, glClearColor,
    glCompileShader, glCreateProgram, glCreateShader, glDeleteBuffers,
    glDeleteProgram, glDeleteShader, glDeleteTextures, glDeleteVertexArrays,
    glDisableVertexAttribArray, glDrawElements, glEnable, glEnableVertexAttribArray,
    glGenBuffers, glGenTextures, glGenVertexArrays, glGetAttribLocation,
    glGetError, glGetProgramInfoLog, glGetProgramiv, glGetShaderInfoLog,
    glGetShaderiv, glGetUniformLocation, glLinkProgram, glShaderSource,
    glTexImage2D, glTexParameteri, glUniform1f, glUniform1i, glUniform2f,
    glUniform3f, glUniform4f, glUniformMatrix4fv, glUseProgram,
    glVertexAttribPointer, glViewport,
)
from OpenGL.GL import shaders as gl_shaders
from PIL import Image
from PySide6.QtCore import QTimer
from PySide6.QtGui import QImage
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QWidget

from pm.media.video_player import VideoPlayer
from pm.model.media import MediaRef
from pm.model.project import Project
from pm.model.shapes import CircleShape, PolygonShape, Shape
from pm.render.mesh import triangulate_circle, triangulate_polygon
from pm.render.shaders import (
    FRAGMENT_SHADER_SOLID, FRAGMENT_SHADER_STROKE, FRAGMENT_SHADER_TEXTURE,
    VERTEX_SHADER,
)

logger = logging.getLogger(__name__)


class GLRenderer(QOpenGLWidget):
    """OpenGL-accelerated renderer for projection mapping."""

    def __init__(self, project: Project, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.project = project
        self._start_time = time.perf_counter()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)
        self._timer.start(16)
        self.project.changed.connect(self.update)

        # OpenGL resources
        self._program_texture = None
        self._program_solid = None
        self._program_stroke = None
        self._vao = None
        self._vbo = None
        self._ebo = None

        # Texture cache
        self._image_cache: Dict[str, int] = {}  # path -> texture ID
        self._video_players: Dict[str, VideoPlayer] = {}
        self._video_textures: Dict[str, int] = {}  # path -> texture ID

        # Track initialization
        self._gl_initialized = False

    def cleanup(self) -> None:
        """Clean up OpenGL resources."""
        for player in self._video_players.values():
            player.stop()
        self._video_players.clear()
        self._video_textures.clear()

        if self._gl_initialized and self.context():
            self.makeCurrent()
            self._cleanup_textures()
            self._cleanup_buffers()
            self._cleanup_programs()

    def _cleanup_textures(self) -> None:
        for tex_id in self._image_cache.values():
            glDeleteTextures(1, [tex_id])
        for tex_id in self._video_textures.values():
            glDeleteTextures(1, [tex_id])
        self._image_cache.clear()

    def _cleanup_buffers(self) -> None:
        if self._vbo:
            glDeleteBuffers(1, [self._vbo])
        if self._ebo:
            glDeleteBuffers(1, [self._ebo])
        if self._vao:
            glDeleteVertexArrays(1, [self._vao])

    def _cleanup_programs(self) -> None:
        if self._program_texture:
            glDeleteProgram(self._program_texture)
        if self._program_solid:
            glDeleteProgram(self._program_solid)
        if self._program_stroke:
            glDeleteProgram(self._program_stroke)

    def initializeGL(self) -> None:
        """Initialize OpenGL resources."""
        try:
            # Compile shaders
            vertex_shader = self._compile_shader(VERTEX_SHADER, GL_VERTEX_SHADER)

            frag_texture = self._compile_shader(FRAGMENT_SHADER_TEXTURE, GL_FRAGMENT_SHADER)
            frag_solid = self._compile_shader(FRAGMENT_SHADER_SOLID, GL_FRAGMENT_SHADER)
            frag_stroke = self._compile_shader(FRAGMENT_SHADER_STROKE, GL_FRAGMENT_SHADER)

            self._program_texture = self._link_program(vertex_shader, frag_texture)
            self._program_solid = self._link_program(vertex_shader, frag_solid)
            self._program_stroke = self._link_program(vertex_shader, frag_stroke)

            glDeleteShader(vertex_shader)
            glDeleteShader(frag_texture)
            glDeleteShader(frag_solid)
            glDeleteShader(frag_stroke)

            # Create VAO
            self._vao = glGenVertexArrays(1)
            glBindVertexArray(self._vao)

            # Create VBO for vertex data (position + UV)
            self._vbo = glGenBuffers(1)
            glBindBuffer(GL_ARRAY_BUFFER, self._vbo)

            # Create EBO for indices
            self._ebo = glGenBuffers(1)
            glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self._ebo)

            # Setup vertex attributes
            # Position attribute (location = 0)
            glEnableVertexAttribArray(0)
            glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 16, ctypes.c_void_p(0))

            # UV attribute (location = 1)
            glEnableVertexAttribArray(1)
            glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 16, ctypes.c_void_p(8))

            glBindVertexArray(0)

            # Enable blending
            glEnable(GL_BLEND)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

            self._gl_initialized = True

        except Exception as e:
            logger.error("OpenGL initialization error: %s", e)

    def resizeGL(self, w: int, h: int) -> None:
        """Handle resize."""
        glViewport(0, 0, w, h)

    def paintGL(self) -> None:
        """Render the scene."""
        if not self._gl_initialized:
            return

        try:
            # Clear with background color
            bg = self.project.canvas.background_color
            glClearColor(bg[0] / 255.0, bg[1] / 255.0, bg[2] / 255.0, 1.0)
            glClear(GL_COLOR_BUFFER_BIT)

            canvas_w = max(self.project.canvas.width, 1)
            canvas_h = max(self.project.canvas.height, 1)

            now = time.perf_counter() - self._start_time

            # Render shapes
            for shape in self.project.shapes:
                if not shape.visible:
                    continue
                self._render_shape(shape, canvas_w, canvas_h, now)

            # Render strokes
            self._render_strokes(canvas_w, canvas_h)

        except Exception as e:
            logger.error("Render error: %s", e)

    def _render_shape(self, shape: Shape, canvas_w: float, canvas_h: float, now: float) -> None:
        """Render a single shape."""
        points, indices = self._shape_geometry(shape)
        if not points or not indices:
            return

        # Calculate effects
        pulse_factor = 1.0
        if shape.effects.pulse.enabled:
            pulse_factor = 1.0 + math.sin(now * shape.effects.pulse.speed) * shape.effects.pulse.amount

        strobe_factor = 1.0
        if shape.effects.strobe.enabled:
            phase = math.sin(now * shape.effects.strobe.hz * 6.28318)
            strobe_factor = 1.0 if phase >= 0 else 0.0
        if strobe_factor <= 0.0:
            return

        opacity = max(0.0, min(1.0, shape.opacity * pulse_factor * strobe_factor))

        # Get media texture or render solid
        tex_id, tex_size = self._get_or_create_texture(shape.media)
        if tex_id:
            uvs = self._compute_uvs_from_size(points, tex_size, shape.media)
            self._draw_textured_shape(points, uvs, indices, tex_id, opacity, shape, now, canvas_w, canvas_h)
        else:
            # Solid color fill
            fill = shape.fill_color
            self._draw_solid_shape(points, indices, fill, opacity, shape, now, canvas_w, canvas_h)

    def _draw_textured_shape(
        self,
        points: List[Tuple[float, float]],
        uvs: List[Tuple[float, float]],
        indices: List[int],
        texture_id: int,
        opacity: float,
        shape: Shape,
        now: float,
        canvas_w: float,
        canvas_h: float,
    ) -> None:
        """Draw a shape with texture."""
        glUseProgram(self._program_texture)

        # Build vertex buffer: x, y, u, v
        vertices = []
        for i, (x, y) in enumerate(points):
            u, v = uvs[i] if i < len(uvs) else (0.0, 0.0)
            vertices.extend([x, y, u, v])

        # Upload vertex data
        glBindBuffer(GL_ARRAY_BUFFER, self._vbo)
        glBufferData(GL_ARRAY_BUFFER, len(vertices) * 4, np.array(vertices, dtype=np.float32), GL_DYNAMIC_DRAW)

        # Upload indices
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self._ebo)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, len(indices) * 4, np.array(indices, dtype=np.uint32), GL_DYNAMIC_DRAW)

        # Set uniforms
        loc = glGetUniformLocation(self._program_texture, "u_canvas_size")
        glUniform2f(loc, canvas_w, canvas_h)

        loc = glGetUniformLocation(self._program_texture, "u_opacity")
        glUniform1f(loc, opacity)

        loc = glGetUniformLocation(self._program_texture, "u_time")
        glUniform1f(loc, now)

        # RGB shift effect
        rgb = shape.effects.rgb_shift
        loc = glGetUniformLocation(self._program_texture, "u_rgb_shift")
        if rgb.enabled:
            glUniform3f(loc, rgb.amount, rgb.speed, 0.0)
        else:
            glUniform3f(loc, 0.0, 0.0, 0.0)

        # Bind texture
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, texture_id)
        loc = glGetUniformLocation(self._program_texture, "u_texture")
        glUniform1i(loc, 0)

        # Draw
        glBindVertexArray(self._vao)
        glDrawElements(GL_TRIANGLES, len(indices), GL_UNSIGNED_INT, None)

    def _draw_solid_shape(
        self,
        points: List[Tuple[float, float]],
        indices: List[int],
        color: List[int],
        opacity: float,
        shape: Shape,
        now: float,
        canvas_w: float,
        canvas_h: float,
    ) -> None:
        """Draw a shape with solid color."""
        glUseProgram(self._program_solid)

        # Build vertex buffer (UV not used but needed for attribute)
        vertices = []
        for x, y in points:
            vertices.extend([x, y, 0.0, 0.0])

        glBindBuffer(GL_ARRAY_BUFFER, self._vbo)
        glBufferData(GL_ARRAY_BUFFER, len(vertices) * 4, np.array(vertices, dtype=np.float32), GL_DYNAMIC_DRAW)

        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self._ebo)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, len(indices) * 4, np.array(indices, dtype=np.uint32), GL_DYNAMIC_DRAW)

        # Set uniforms
        loc = glGetUniformLocation(self._program_solid, "u_canvas_size")
        glUniform2f(loc, canvas_w, canvas_h)

        loc = glGetUniformLocation(self._program_solid, "u_opacity")
        glUniform1f(loc, opacity)

        loc = glGetUniformLocation(self._program_solid, "u_time")
        glUniform1f(loc, now)

        loc = glGetUniformLocation(self._program_solid, "u_color")
        glUniform4f(loc, color[0] / 255.0, color[1] / 255.0, color[2] / 255.0, color[3] / 255.0 if len(color) > 3 else 1.0)

        rgb = shape.effects.rgb_shift
        loc = glGetUniformLocation(self._program_solid, "u_rgb_shift")
        if rgb.enabled:
            glUniform3f(loc, rgb.amount, rgb.speed, 0.0)
        else:
            glUniform3f(loc, 0.0, 0.0, 0.0)

        glBindVertexArray(self._vao)
        glDrawElements(GL_TRIANGLES, len(indices), GL_UNSIGNED_INT, None)

    def _render_strokes(self, canvas_w: float, canvas_h: float) -> None:
        """Render shape strokes."""
        for shape in self.project.shapes:
            if not shape.visible:
                continue

            alpha = self._stroke_alpha(shape)
            if isinstance(shape, PolygonShape):
                self._render_polygon_stroke(shape, alpha, canvas_w, canvas_h)
            elif isinstance(shape, CircleShape):
                self._render_circle_stroke(shape, alpha, canvas_w, canvas_h)

    def _stroke_alpha(self, shape: Shape) -> float:
        color = shape.stroke_color
        return (color[3] / 255.0 * shape.opacity) if len(color) > 3 else shape.opacity

    def _render_polygon_stroke(self, shape: PolygonShape, alpha: float, canvas_w: float, canvas_h: float) -> None:
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
            self._draw_line(p1, p2, shape.stroke_color[:3], alpha, shape.stroke_width, canvas_w, canvas_h)

    def _render_circle_stroke(self, shape: CircleShape, alpha: float, canvas_w: float, canvas_h: float) -> None:
        cx, cy = shape.center
        rx = max(shape.radius_x, 1.0)
        ry = max(shape.radius_y, 1.0)
        segments = 48
        for i in range(segments):
            a1 = i * 2 * math.pi / segments
            a2 = (i + 1) * 2 * math.pi / segments
            p1 = (cx + rx * math.cos(a1), cy + ry * math.sin(a1))
            p2 = (cx + rx * math.cos(a2), cy + ry * math.sin(a2))
            self._draw_line(p1, p2, shape.stroke_color[:3], alpha, shape.stroke_width, canvas_w, canvas_h)

    def _draw_line(
        self,
        p1: Tuple[float, float],
        p2: Tuple[float, float],
        color: List[int],
        alpha: float,
        width: float,
        canvas_w: float,
        canvas_h: float,
    ) -> None:
        """Draw a line segment."""
        glUseProgram(self._program_stroke)

        # Simple 2-vertex line
        vertices = [p1[0], p1[1], 0.0, 0.0, p2[0], p2[1], 0.0, 0.0]
        indices = [0, 1]

        glBindBuffer(GL_ARRAY_BUFFER, self._vbo)
        glBufferData(GL_ARRAY_BUFFER, len(vertices) * 4, np.array(vertices, dtype=np.float32), GL_DYNAMIC_DRAW)

        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self._ebo)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, len(indices) * 4, np.array(indices, dtype=np.uint32), GL_DYNAMIC_DRAW)

        loc = glGetUniformLocation(self._program_stroke, "u_canvas_size")
        glUniform2f(loc, canvas_w, canvas_h)

        loc = glGetUniformLocation(self._program_stroke, "u_color")
        glUniform4f(loc, color[0] / 255.0, color[1] / 255.0, color[2] / 255.0, alpha)

        glBindVertexArray(self._vao)
        glDrawElements(GL_LINES, 2, GL_UNSIGNED_INT, None)

    def _shape_geometry(self, shape: Shape) -> Tuple[List[Tuple[float, float]], List[int]]:
        """Get triangulated geometry for a shape."""
        if isinstance(shape, PolygonShape):
            points = list(shape.points)
            indices = triangulate_polygon(points)
            return points, indices
        if isinstance(shape, CircleShape):
            points, indices = triangulate_circle(shape.center, shape.radius_x, shape.radius_y, 48)
            return points, indices
        return [], []

    def _compute_uvs(
        self,
        points: List[Tuple[float, float]],
        image: QImage,
        media: MediaRef,
    ) -> List[Tuple[float, float]]:
        """Compute UV coordinates for shape vertices."""
        if not points:
            return []

        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        minx, miny, maxx, maxy = min(xs), min(ys), max(xs), max(ys)
        box_w = max(maxx - minx, 1e-5)
        box_h = max(maxy - miny, 1e-5)

        media_w = max(image.width(), 1)
        media_h = max(image.height(), 1)
        mode = (media.fit_mode or "stretch").lower()

        # Warp mode
        if mode == "warp":
            return self._compute_warp_uvs(points, minx, miny, box_w, box_h)

        if mode == "stretch":
            content_w, content_h = box_w, box_h
            offset_x, offset_y = 0.0, 0.0
        else:
            if mode == "contain":
                scale = min(box_w / media_w, box_h / media_h)
            else:  # cover
                scale = max(box_w / media_w, box_h / media_h)
            content_w = media_w * scale
            content_h = media_h * scale
            offset_x = (box_w - content_w) / 2.0
            offset_y = (box_h - content_h) / 2.0

        uvs: List[Tuple[float, float]] = []
        for x, y in points:
            u = (x - minx - offset_x) / content_w if content_w > 0 else 0.0
            v = (y - miny - offset_y) / content_h if content_h > 0 else 0.0
            uvs.append((max(0.0, min(1.0, u)), max(0.0, min(1.0, v))))

        return uvs

    def _compute_warp_uvs(
        self,
        points: List[Tuple[float, float]],
        minx: float,
        miny: float,
        box_w: float,
        box_h: float,
    ) -> List[Tuple[float, float]]:
        """Compute UVs for warp mode."""
        if len(points) == 4:
            maxx = minx + box_w
            maxy = miny + box_h
            corners = [(minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy)]
            corner_uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]

            distances = []
            for i, (px, py) in enumerate(points):
                for j, (cx, cy) in enumerate(corners):
                    dist = (px - cx) ** 2 + (py - cy) ** 2
                    distances.append((dist, i, j))
            distances.sort()

            uvs = [(0.0, 0.0)] * 4
            used_corners = set()
            assigned_points = set()
            for _, point_idx, corner_idx in distances:
                if point_idx not in assigned_points and corner_idx not in used_corners:
                    uvs[point_idx] = corner_uvs[corner_idx]
                    assigned_points.add(point_idx)
                    used_corners.add(corner_idx)
            return uvs

        return [((x - minx) / box_w, (y - miny) / box_h) for x, y in points]

    def _get_or_create_texture(self, media: MediaRef) -> Tuple[Optional[int], Tuple[int, int]]:
        """Get or create a texture for media.

        Returns:
            Tuple of (texture_id, (width, height)) or (None, (0, 0)) if no media.
        """
        if not media or not media.kind or not media.path:
            return None, (0, 0)

        if media.kind == "image":
            return self._get_image_texture(media)
        elif media.kind == "video":
            return self._get_video_texture(media)

        return None, (0, 0)

    def _get_image_texture(self, media: MediaRef) -> Tuple[Optional[int], Tuple[int, int]]:
        cached_tex = self._image_cache.get(media.path)
        if cached_tex:
            img = self._load_image(media.path)
            if img:
                return cached_tex, (img.width(), img.height())
            return cached_tex, (1, 1)

        img = self._load_image(media.path)
        if not img:
            return None, (0, 0)

        tex_id = self._create_texture_from_qimage(img)
        if tex_id:
            self._image_cache[media.path] = tex_id
            return tex_id, (img.width(), img.height())
        return None, (0, 0)

    def _get_video_texture(self, media: MediaRef) -> Tuple[Optional[int], Tuple[int, int]]:
        player = self._video_players.get(media.path)
        if not player:
            player = VideoPlayer(media.path)
            player.start()
            self._video_players[media.path] = player

        frame, size = player.get_frame()
        if frame is None:
            return None, (0, 0)
        qimg = QImage(frame.data, frame.shape[1], frame.shape[0], frame.strides[0], QImage.Format_RGB888).copy()
        qimg = qimg.convertToFormat(QImage.Format_RGBA8888)
        tex_id = self._create_texture_from_qimage(qimg)
        return (tex_id, size) if tex_id else (None, (0, 0))

    def _create_texture_from_qimage(self, image: QImage) -> Optional[int]:
        """Create an OpenGL texture from a QImage."""
        ptr = image.constBits()
        ptr.setsize(image.sizeInBytes())

        tex_id = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, tex_id)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, image.width(), image.height(), 0, GL_RGBA, GL_UNSIGNED_BYTE, ptr)

        return tex_id

    def _compute_uvs_from_size(
        self,
        points: List[Tuple[float, float]],
        tex_size: Tuple[int, int],
        media: MediaRef,
    ) -> List[Tuple[float, float]]:
        """Compute UV coordinates based on texture size."""
        if not points:
            return []

        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        minx, miny, maxx, maxy = min(xs), min(ys), max(xs), max(ys)
        box_w = max(maxx - minx, 1e-5)
        box_h = max(maxy - miny, 1e-5)

        media_w = max(tex_size[0], 1)
        media_h = max(tex_size[1], 1)
        mode = (media.fit_mode or "stretch").lower()

        if mode == "warp":
            return self._compute_warp_uvs(points, minx, miny, box_w, box_h)

        if mode == "stretch":
            content_w, content_h = box_w, box_h
            offset_x, offset_y = 0.0, 0.0
        else:
            if mode == "contain":
                scale = min(box_w / media_w, box_h / media_h)
            else:  # cover
                scale = max(box_w / media_w, box_h / media_h)
            content_w = media_w * scale
            content_h = media_h * scale
            offset_x = (box_w - content_w) / 2.0
            offset_y = (box_h - content_h) / 2.0

        uvs: List[Tuple[float, float]] = []
        for x, y in points:
            u = (x - minx - offset_x) / content_w if content_w > 0 else 0.0
            v = (y - miny - offset_y) / content_h if content_h > 0 else 0.0
            uvs.append((max(0.0, min(1.0, u)), max(0.0, min(1.0, v))))

        return uvs

    def _load_image(self, path: str) -> Optional[QImage]:
        """Load an image file."""
        try:
            img = Image.open(path).convert("RGBA")
            data = img.tobytes("raw", "RGBA")
            qimg = QImage(data, img.width, img.height, QImage.Format_RGBA8888)
            return qimg.copy()
        except Exception:
            return None

    def _compile_shader(self, source: str, shader_type: int) -> int:
        """Compile a shader from source.

        Args:
            source: GLSL source code
            shader_type: GL_VERTEX_SHADER or GL_FRAGMENT_SHADER
        """
        shader = glCreateShader(shader_type)
        glShaderSource(shader, source)
        glCompileShader(shader)

        result = ctypes.c_int()
        glGetShaderiv(shader, GL_COMPILE_STATUS, result)
        if not result.value:
            error = glGetShaderInfoLog(shader).decode()
            raise RuntimeError(f"Shader compilation error: {error}")

        return shader

    def _link_program(self, vertex_shader: int, fragment_shader: int) -> int:
        """Link shaders into a program."""
        program = glCreateProgram()
        glAttachShader(program, vertex_shader)
        glAttachShader(program, fragment_shader)
        glLinkProgram(program)

        result = ctypes.c_int()
        glGetProgramiv(program, GL_LINK_STATUS, result)
        if not result.value:
            error = glGetProgramInfoLog(program).decode()
            raise RuntimeError(f"Program link error: {error}")

        return program

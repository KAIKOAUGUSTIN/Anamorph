"""OpenGL-based renderer using PyOpenGL and QOpenGLWidget."""

from __future__ import annotations

import ctypes
import logging
import math
import time
from typing import Dict, List, Optional, Tuple

import numpy as np
from OpenGL.GL import (
    GL_ARRAY_BUFFER, GL_BLEND, GL_CLAMP_TO_EDGE, GL_COLOR_BUFFER_BIT,
    GL_FRAMEBUFFER, glBindFramebuffer,
    GL_COMPILE_STATUS, GL_DYNAMIC_DRAW, GL_ELEMENT_ARRAY_BUFFER, GL_FALSE,
    GL_FLOAT, GL_FRAGMENT_SHADER, GL_LINEAR, GL_LINK_STATUS,
    GL_RGBA, GL_SRC_ALPHA,
    GL_TEXTURE0, GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER,
    GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T, GL_TRIANGLES, GL_TRUE,
    GL_UNSIGNED_BYTE, GL_UNSIGNED_INT,
    GL_VERTEX_SHADER, GL_ONE_MINUS_SRC_ALPHA,
    glActiveTexture, glAttachShader, glBindBuffer, glBindTexture,
    glBindVertexArray, glBlendFunc, glBufferData, glClear, glClearColor,
    glCompileShader, glCreateProgram, glCreateShader, glDeleteBuffers,
    glDeleteProgram, glDeleteShader, glDeleteTextures, glDeleteVertexArrays,
    glDrawElements, glEnable, glEnableVertexAttribArray,
    glGenBuffers, glGenTextures, glGenVertexArrays,
    glGetProgramInfoLog, glGetProgramiv, glGetShaderInfoLog,
    glGetShaderiv, glGetUniformLocation, glLinkProgram, glShaderSource,
    glTexImage2D, glTexParameteri, glTexSubImage2D, glUniform1f, glUniform1i,
    glUniform2f, glUniform3f, glUniform4f, glUniformMatrix3fv, glUseProgram,
    glVertexAttribPointer, glViewport,
)
from PIL import Image
from PySide6.QtCore import QTimer
from PySide6.QtGui import QImage
from PySide6.QtOpenGL import QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QWidget

from pm.media.video_player import VideoPlayer
from pm.model.media import MediaRef
from pm.model.project import Project
from pm.model.shapes import CircleShape, MeshShape, PolygonShape, Shape, active_masks
from pm.model.output import Output
from pm.render.fit import content_rect, leaves_unit_square
from pm.render.homography import canvas_to_uv_matrix, corner_uv_assignment
from pm.render.mesh import (
    bezier_control_points,
    circle_ring,
    cubic_point,
    edge_samples,
    mesh_outline,
    tessellate_mesh,
    triangulate_circle,
    triangulate_polygon,
    triangulate_with_holes,
)
from pm.render.test_pattern import GRID, render_test_pattern
from pm.render.shaders import (
    FRAGMENT_SHADER_OUTPUT, FRAGMENT_SHADER_SOLID, FRAGMENT_SHADER_STROKE,
    FRAGMENT_SHADER_TEXTURE, VERTEX_SHADER, VERTEX_SHADER_OUTPUT,
)

logger = logging.getLogger(__name__)


class GLRenderer(QOpenGLWidget):
    """OpenGL-accelerated renderer for projection mapping."""

    def __init__(
        self,
        project: Project,
        parent: Optional[QWidget] = None,
        output: Optional[Output] = None,
    ) -> None:
        super().__init__(parent)
        self.project = project
        # An identity output is the whole canvas with no corrections, which is
        # what the editor preview and a single-projector rig both want.
        self.output = output or Output(name="Preview")
        self._start_time = time.perf_counter()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)
        self._timer.start(16)
        self.project.changed.connect(self.update)

        # OpenGL resources
        self._program_texture = None
        self._program_solid = None
        self._program_stroke = None
        self._program_output = None
        self._canvas_fbo: Optional[QOpenGLFramebufferObject] = None
        self._canvas_fbo_size: Tuple[int, int] = (0, 0)
        self._vao = None
        self._vbo = None
        self._ebo = None

        # Texture cache. Sizes are cached alongside the texture so a frame
        # never has to touch the source file again.
        self._image_cache: Dict[str, Tuple[int, Tuple[int, int]]] = {}
        self._video_players: Dict[str, VideoPlayer] = {}
        self._video_textures: Dict[str, Tuple[int, Tuple[int, int]]] = {}
        self._test_pattern_texture_id: Optional[int] = None
        self._test_pattern_key: Optional[Tuple] = None

        # Track initialization
        self._gl_initialized = False

    def cleanup(self) -> None:
        """Clean up OpenGL resources."""
        # Stop the repaint timer first: it fires every 16ms, and a paint after
        # the programs are deleted uses handles that no longer exist.
        self._timer.stop()
        for player in self._video_players.values():
            player.stop()
        self._video_players.clear()

        # _video_textures is cleared by _cleanup_textures, after the GL
        # objects it names have actually been deleted.
        if self._gl_initialized and self.context():
            self.makeCurrent()
            self._cleanup_textures()
            self._cleanup_buffers()
            self._cleanup_programs()
            self._canvas_fbo = None
            self._canvas_fbo_size = (0, 0)

    def _cleanup_textures(self) -> None:
        for tex_id, _ in self._image_cache.values():
            glDeleteTextures(1, [tex_id])
        for tex_id, _ in self._video_textures.values():
            glDeleteTextures(1, [tex_id])
        if self._test_pattern_texture_id:
            glDeleteTextures(1, [self._test_pattern_texture_id])
            self._test_pattern_texture_id = None
            self._test_pattern_key = None
        self._image_cache.clear()
        self._video_textures.clear()

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
        if self._program_output:
            glDeleteProgram(self._program_output)

    def initializeGL(self) -> None:
        """Initialize OpenGL resources."""
        try:
            # Compile shaders
            vertex_shader = self._compile_shader(VERTEX_SHADER, GL_VERTEX_SHADER)

            frag_texture = self._compile_shader(FRAGMENT_SHADER_TEXTURE, GL_FRAGMENT_SHADER)
            frag_solid = self._compile_shader(FRAGMENT_SHADER_SOLID, GL_FRAGMENT_SHADER)
            frag_stroke = self._compile_shader(FRAGMENT_SHADER_STROKE, GL_FRAGMENT_SHADER)

            vertex_output = self._compile_shader(VERTEX_SHADER_OUTPUT, GL_VERTEX_SHADER)
            frag_output = self._compile_shader(FRAGMENT_SHADER_OUTPUT, GL_FRAGMENT_SHADER)

            self._program_texture = self._link_program(vertex_shader, frag_texture)
            self._program_solid = self._link_program(vertex_shader, frag_solid)
            self._program_stroke = self._link_program(vertex_shader, frag_stroke)
            self._program_output = self._link_program(vertex_output, frag_output)

            glDeleteShader(vertex_shader)
            glDeleteShader(frag_texture)
            glDeleteShader(frag_solid)
            glDeleteShader(frag_stroke)
            glDeleteShader(vertex_output)
            glDeleteShader(frag_output)

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
            logger.exception("OpenGL initialization error: %s", e)

    def resizeGL(self, w: int, h: int) -> None:
        """Handle resize."""
        glViewport(0, 0, w, h)

    def paintGL(self) -> None:
        """Composite the canvas once, then show this projector's view of it.

        Two passes, not one. Edge blending has to attenuate the *finished*
        image: applied per shape, two surfaces overlapping inside the blend
        strip would each be darkened, and the seam would show as a dark
        patch instead of disappearing.
        """
        if not self._gl_initialized:
            return

        try:
            canvas_w = max(self.project.canvas.width, 1)
            canvas_h = max(self.project.canvas.height, 1)

            if not self._ensure_canvas_target(canvas_w, canvas_h):
                # No framebuffer to composite into; draw straight to the
                # widget so the editor preview still shows something.
                self._render_canvas(canvas_w, canvas_h)
                return

            self._canvas_fbo.bind()
            glViewport(0, 0, canvas_w, canvas_h)
            self._render_canvas(canvas_w, canvas_h)
            self._canvas_fbo.release()

            # release() binds framebuffer 0, which is not this widget's
            # target - QOpenGLWidget renders into one of its own.
            glBindFramebuffer(GL_FRAMEBUFFER, self.defaultFramebufferObject())
            ratio = self.devicePixelRatio()
            glViewport(0, 0, int(self.width() * ratio), int(self.height() * ratio))
            self._draw_output(self._canvas_fbo.texture())

        except Exception as e:
            logger.exception("Render error: %s", e)

    def _render_canvas(self, canvas_w: int, canvas_h: int) -> None:
        """Everything the artwork consists of, in canvas coordinates."""
        bg = self.project.canvas.background_color
        glClearColor(bg[0] / 255.0, bg[1] / 255.0, bg[2] / 255.0, 1.0)
        glClear(GL_COLOR_BUFFER_BIT)

        # Calibration replaces the scene rather than overlaying it: the point
        # is to align the projector against known geometry, with nothing else
        # on screen to confuse the eye.
        if self.project.ui_state.get("test_mode"):
            self._draw_test_pattern(canvas_w, canvas_h)
            return

        now = time.perf_counter() - self._start_time
        for shape in self.project.shapes:
            if not shape.visible:
                continue
            self._render_shape(shape, canvas_w, canvas_h, now)

        self._render_strokes(canvas_w, canvas_h)

    def _ensure_canvas_target(self, canvas_w: int, canvas_h: int) -> bool:
        if self._canvas_fbo is not None and self._canvas_fbo_size == (canvas_w, canvas_h):
            return True
        if self._canvas_fbo is not None:
            self._canvas_fbo = None

        try:
            fmt = QOpenGLFramebufferObjectFormat()
            fmt.setAttachment(QOpenGLFramebufferObject.NoAttachment)
            fbo = QOpenGLFramebufferObject(canvas_w, canvas_h, fmt)
        except Exception as exc:  # pragma: no cover - driver dependent
            logger.warning("Could not create canvas framebuffer: %s", exc)
            return False

        if not fbo.isValid():
            logger.warning("Canvas framebuffer is not valid at %dx%d", canvas_w, canvas_h)
            return False

        self._canvas_fbo = fbo
        self._canvas_fbo_size = (canvas_w, canvas_h)
        return True

    def _draw_output(self, canvas_texture: int) -> None:
        """Draw the composited canvas through this projector's corrections."""
        output = self.output
        region = output.region.normalised()
        blend = output.blend.normalised()
        color = output.color.normalised()

        glUseProgram(self._program_output)

        # A quad covering the projector's whole frame, in 0..1.
        vertices = [
            0.0, 0.0, 0.0, 0.0,
            1.0, 0.0, 0.0, 0.0,
            1.0, 1.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
        ]
        indices = [0, 1, 2, 0, 2, 3]

        glBindBuffer(GL_ARRAY_BUFFER, self._vbo)
        glBufferData(GL_ARRAY_BUFFER, len(vertices) * 4, np.array(vertices, dtype=np.float32), GL_DYNAMIC_DRAW)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self._ebo)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, len(indices) * 4, np.array(indices, dtype=np.uint32), GL_DYNAMIC_DRAW)

        def loc(name):
            return glGetUniformLocation(self._program_output, name)

        glUniform4f(loc("u_region"), region.u0, region.v0, region.width, region.height)

        # Keystone reuses the corner-pin solver: the projector's warped frame
        # maps back to the square the canvas was composited into.
        matrix = canvas_to_uv_matrix(output.corners) if output.has_keystone() else None
        if matrix is not None:
            glUniform1i(loc("u_has_keystone"), 1)
            glUniformMatrix3fv(loc("u_keystone"), 1, GL_TRUE, matrix.astype(np.float32))
        else:
            glUniform1i(loc("u_has_keystone"), 0)

        glUniform4f(loc("u_blend"), blend.left, blend.right, blend.top, blend.bottom)
        glUniform1f(loc("u_blend_gamma"), blend.gamma)

        glUniform1f(loc("u_brightness"), color.brightness)
        glUniform1f(loc("u_contrast"), color.contrast)
        glUniform1f(loc("u_gamma"), color.gamma)
        glUniform3f(loc("u_gain"), color.gain_r, color.gain_g, color.gain_b)

        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, canvas_texture)
        glUniform1i(loc("u_canvas"), 0)

        glBindVertexArray(self._vao)
        glDrawElements(GL_TRIANGLES, len(indices), GL_UNSIGNED_INT, None)

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
            # Aspect ratio and pixel offsets are relative to the region that
            # actually feeds this surface, not to the whole file - taking the
            # left third of a 16:9 clip gives a 16:27 image to fit.
            region = shape.media.source_rect.normalised()
            fit_size = (
                max(tex_size[0] * region.width, 1.0),
                max(tex_size[1] * region.height, 1.0),
            )
            if isinstance(shape, MeshShape):
                uvs = self._mesh_uvs(shape)
            else:
                uvs = self._compute_uvs_from_size(points, fit_size, shape.media)
            uv_matrix = self._warp_matrix(shape)
            self._draw_textured_shape(
                points, uvs, indices, tex_id, opacity, shape, now,
                canvas_w, canvas_h, uv_matrix, fit_size,
            )
        else:
            # Solid color fill
            fill = shape.fill_color
            self._draw_solid_shape(points, indices, fill, opacity, shape, now, canvas_w, canvas_h)

    def _test_pattern_texture(self, canvas_w: float, canvas_h: float) -> Optional[int]:
        """Texture for the current calibration pattern, regenerated only when
        the resolution, pattern or screen label actually changes."""
        kind = self.project.ui_state.get("test_pattern", GRID)
        label = self.project.name or ""
        key = (int(canvas_w), int(canvas_h), kind, label)
        if self._test_pattern_key == key and self._test_pattern_texture_id:
            return self._test_pattern_texture_id

        image = render_test_pattern(int(canvas_w), int(canvas_h), kind, label)
        if self._test_pattern_texture_id:
            glDeleteTextures(1, [self._test_pattern_texture_id])
            self._test_pattern_texture_id = None

        tex_id = self._create_texture_from_qimage(image)
        if not tex_id:
            return None
        self._test_pattern_texture_id = tex_id
        self._test_pattern_key = key
        return tex_id

    def _draw_test_pattern(self, canvas_w: float, canvas_h: float) -> None:
        tex_id = self._test_pattern_texture(canvas_w, canvas_h)
        if not tex_id:
            return

        glUseProgram(self._program_texture)

        vertices = [
            0.0, 0.0, 0.0, 0.0,
            canvas_w, 0.0, 1.0, 0.0,
            canvas_w, canvas_h, 1.0, 1.0,
            0.0, canvas_h, 0.0, 1.0,
        ]
        indices = [0, 1, 2, 0, 2, 3]

        glBindBuffer(GL_ARRAY_BUFFER, self._vbo)
        glBufferData(GL_ARRAY_BUFFER, len(vertices) * 4, np.array(vertices, dtype=np.float32), GL_DYNAMIC_DRAW)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self._ebo)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, len(indices) * 4, np.array(indices, dtype=np.uint32), GL_DYNAMIC_DRAW)

        # Every uniform the texture program reads has to be set explicitly:
        # whatever a previous frame left behind is still bound.
        glUniform2f(glGetUniformLocation(self._program_texture, "u_canvas_size"), canvas_w, canvas_h)
        glUniform1f(glGetUniformLocation(self._program_texture, "u_opacity"), 1.0)
        glUniform1f(glGetUniformLocation(self._program_texture, "u_time"), 0.0)
        glUniform3f(glGetUniformLocation(self._program_texture, "u_rgb_shift"), 0.0, 0.0, 0.0)
        glUniform1i(glGetUniformLocation(self._program_texture, "u_uv_projective"), 0)
        glUniform2f(glGetUniformLocation(self._program_texture, "u_media_offset"), 0.0, 0.0)
        glUniform1f(glGetUniformLocation(self._program_texture, "u_media_rotation"), 0.0)
        glUniform1i(glGetUniformLocation(self._program_texture, "u_uv_clip"), 0)
        glUniform4f(glGetUniformLocation(self._program_texture, "u_source_rect"), 0.0, 0.0, 1.0, 1.0)

        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, tex_id)
        glUniform1i(glGetUniformLocation(self._program_texture, "u_texture"), 0)

        glBindVertexArray(self._vao)
        glDrawElements(GL_TRIANGLES, len(indices), GL_UNSIGNED_INT, None)

    def _warp_matrix(self, shape: Shape) -> Optional[np.ndarray]:
        """Homography for a corner-pinned surface, or None for every other case.

        Built from the shape's four *anchors*, never from the drawn outline: a
        curved edge samples into a long point list, and a corner pin is still
        pinned to the corners. A bulge past a corner reads outside the media
        and is clipped, which is what "pinned to those four points" means.
        """
        if (shape.media.fit_mode or "").lower() != "warp":
            return None
        if not isinstance(shape, PolygonShape) or len(shape.points) != 4:
            return None
        return canvas_to_uv_matrix(shape.points)

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
        uv_matrix: Optional[np.ndarray] = None,
        media_size: Tuple[int, int] = (1, 1),
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

        # Corner pin. The flag must be written on every draw - uniforms persist
        # on the program, so skipping the else branch would leak the previous
        # shape's matrix onto this one.
        loc = glGetUniformLocation(self._program_texture, "u_uv_projective")
        if uv_matrix is not None:
            glUniform1i(loc, 1)
            loc = glGetUniformLocation(self._program_texture, "u_uv_matrix")
            # GL_TRUE transposes: numpy is row-major, GLSL mat3 is column-major.
            glUniformMatrix3fv(loc, 1, GL_TRUE, uv_matrix.astype(np.float32))
        else:
            glUniform1i(loc, 0)

        # Media pan/rotate. The panel edits offsets in source pixels, which
        # only become UV units once the media's own size is known.
        transform = shape.media.transform
        loc = glGetUniformLocation(self._program_texture, "u_media_offset")
        glUniform2f(
            loc,
            transform.offset_x / max(media_size[0], 1),
            transform.offset_y / max(media_size[1], 1),
        )
        loc = glGetUniformLocation(self._program_texture, "u_media_rotation")
        glUniform1f(loc, math.radians(transform.rotation))

        # Clip whenever the UVs can leave the media: the bars of a `contain`
        # fit, or the gap a pan opens up.
        panned = transform.offset_x != 0.0 or transform.offset_y != 0.0
        # A curved edge that bulges past its corners leaves the pinned quad
        # too, and without the clip it would drag the media's edge texel out
        # with it.
        curved = isinstance(shape, PolygonShape) and shape.has_curves
        clip = leaves_unit_square(shape.media.fit_mode) or panned or curved or transform.rotation != 0.0
        glUniform1i(glGetUniformLocation(self._program_texture, "u_uv_clip"), 1 if clip else 0)

        region = shape.media.source_rect.normalised()
        glUniform4f(
            glGetUniformLocation(self._program_texture, "u_source_rect"),
            region.u0, region.v0, region.width, region.height,
        )

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
            if isinstance(shape, MeshShape):
                self._render_mesh_stroke(shape, alpha, canvas_w, canvas_h)
            elif isinstance(shape, PolygonShape):
                self._render_polygon_stroke(shape, alpha, canvas_w, canvas_h)
            elif isinstance(shape, CircleShape):
                self._render_circle_stroke(shape, alpha, canvas_w, canvas_h)

    def _stroke_alpha(self, shape: Shape) -> float:
        color = shape.stroke_color
        return (color[3] / 255.0 * shape.opacity) if len(color) > 3 else shape.opacity

    def _render_polygon_stroke(self, shape: PolygonShape, alpha: float, canvas_w: float, canvas_h: float) -> None:
        shape.ensure_edges()
        points = shape.points
        segments: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
        for idx, edge in enumerate(shape.edges):
            if not edge.visible:
                continue
            p1 = points[idx]
            p2 = points[(idx + 1) % len(points)]
            if edge.curved:
                # `percent` on a curve is measured along the arc, so the
                # sampler truncates it rather than the chord.
                walk = edge_samples(p1, p2, edge.curve1, edge.curve2, 16, edge.percent)
                walk.append(cubic_point(
                    p1, *bezier_control_points(p1, p2, edge.curve1, edge.curve2), p2, edge.percent
                ))
                segments.extend((walk[i], walk[i + 1]) for i in range(len(walk) - 1))
                continue
            if edge.percent < 1.0:
                dx = (p2[0] - p1[0]) * edge.percent
                dy = (p2[1] - p1[1]) * edge.percent
                p2 = (p1[0] + dx, p1[1] + dy)
            segments.append((p1, p2))
        self._draw_segments(segments, shape.stroke_color[:3], alpha, shape.stroke_width, canvas_w, canvas_h)

    def _render_mesh_stroke(self, shape: MeshShape, alpha: float, canvas_w: float, canvas_h: float) -> None:
        outline = mesh_outline(shape.points, shape.rows, shape.cols)
        if len(outline) < 2:
            return
        segments = [(outline[i], outline[(i + 1) % len(outline)]) for i in range(len(outline))]
        self._draw_segments(segments, shape.stroke_color[:3], alpha, shape.stroke_width, canvas_w, canvas_h)

    def _render_circle_stroke(self, shape: CircleShape, alpha: float, canvas_w: float, canvas_h: float) -> None:
        cx, cy = shape.center
        rx = max(shape.radius_x, 1.0)
        ry = max(shape.radius_y, 1.0)
        steps = 48
        segments = []
        for i in range(steps):
            a1 = i * 2 * math.pi / steps
            a2 = (i + 1) * 2 * math.pi / steps
            segments.append((
                (cx + rx * math.cos(a1), cy + ry * math.sin(a1)),
                (cx + rx * math.cos(a2), cy + ry * math.sin(a2)),
            ))
        self._draw_segments(segments, shape.stroke_color[:3], alpha, shape.stroke_width, canvas_w, canvas_h)

    def _draw_segments(
        self,
        segments: List[Tuple[Tuple[float, float], Tuple[float, float]]],
        color: List[int],
        alpha: float,
        width: float,
        canvas_w: float,
        canvas_h: float,
    ) -> None:
        """Draw stroke segments as quads, in one call.

        Not GL_LINES: the line width was accepted as an argument and silently
        ignored, so every stroke came out one pixel wide however thick the
        editor drew it. glLineWidth would not have helped either - the core
        profile is free to clamp it to 1.0, and most drivers do.

        Expanding each segment along its perpendicular gives real width, and
        batching the whole outline into a single draw also retires the 48
        draw calls a circle used to cost.

        Joins are butt caps. At stroke widths that read as an outline the
        notch at a corner is invisible; mitring them would need adjacency
        information this does not carry.
        """
        if not segments or width <= 0.0 or alpha <= 0.0:
            return

        half = max(width, 0.5) / 2.0
        vertices: List[float] = []
        indices: List[int] = []
        for (x1, y1), (x2, y2) in segments:
            dx, dy = x2 - x1, y2 - y1
            length = math.hypot(dx, dy)
            if length < 1e-9:
                continue
            # Perpendicular, scaled to half the stroke width.
            nx, ny = -dy / length * half, dx / length * half

            base = len(vertices) // 4
            for px, py in (
                (x1 + nx, y1 + ny),
                (x2 + nx, y2 + ny),
                (x2 - nx, y2 - ny),
                (x1 - nx, y1 - ny),
            ):
                vertices.extend([px, py, 0.0, 0.0])
            indices.extend([base, base + 1, base + 2, base, base + 2, base + 3])

        if not indices:
            return

        glUseProgram(self._program_stroke)

        glBindBuffer(GL_ARRAY_BUFFER, self._vbo)
        glBufferData(GL_ARRAY_BUFFER, len(vertices) * 4, np.array(vertices, dtype=np.float32), GL_DYNAMIC_DRAW)

        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self._ebo)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, len(indices) * 4, np.array(indices, dtype=np.uint32), GL_DYNAMIC_DRAW)

        loc = glGetUniformLocation(self._program_stroke, "u_canvas_size")
        glUniform2f(loc, canvas_w, canvas_h)

        loc = glGetUniformLocation(self._program_stroke, "u_color")
        glUniform4f(loc, color[0] / 255.0, color[1] / 255.0, color[2] / 255.0, alpha)

        glBindVertexArray(self._vao)
        glDrawElements(GL_TRIANGLES, len(indices), GL_UNSIGNED_INT, None)

    def _shape_geometry(self, shape: Shape) -> Tuple[List[Tuple[float, float]], List[int]]:
        """Get triangulated geometry for a shape."""
        if isinstance(shape, MeshShape):
            positions, _uvs, indices = tessellate_mesh(shape.points, shape.rows, shape.cols)
            return positions, indices
        holes = active_masks(shape)
        if isinstance(shape, PolygonShape):
            # The curved boundary, when there is one: the fill has to follow
            # the same edge the stroke draws, or the media spills past it.
            return triangulate_with_holes(shape.outline(), holes)
        if isinstance(shape, CircleShape):
            if holes:
                # The ring on its own, not the centre fan: earcut wants a
                # simple boundary to cut the holes out of.
                return triangulate_with_holes(circle_ring(shape.center, shape.radius_x, shape.radius_y), holes)
            points, indices = triangulate_circle(shape.center, shape.radius_x, shape.radius_y, 48)
            return points, indices
        return [], []

    def _mesh_uvs(self, shape: MeshShape) -> List[Tuple[float, float]]:
        """UVs straight from the grid's parametric position.

        A bounding-box fit cannot describe a bent surface: the media has to
        flow *along* the mesh, not across the rectangle it happens to occupy.
        """
        _positions, uvs, _indices = tessellate_mesh(shape.points, shape.rows, shape.cols)
        return uvs

    def _compute_uvs(
        self,
        points: List[Tuple[float, float]],
        image: QImage,
        media: MediaRef,
    ) -> List[Tuple[float, float]]:
        """Compute UV coordinates for shape vertices."""
        return self._compute_fit_uvs(points, image.width(), image.height(), media)

    def _compute_fit_uvs(
        self,
        points: List[Tuple[float, float]],
        media_w: int,
        media_h: int,
        media: MediaRef,
    ) -> List[Tuple[float, float]]:
        """Core UV computation shared by _compute_uvs and _compute_uvs_from_size."""
        if not points:
            return []

        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        minx, miny, maxx, maxy = min(xs), min(ys), max(xs), max(ys)
        box_w = max(maxx - minx, 1e-5)
        box_h = max(maxy - miny, 1e-5)

        mode = (media.fit_mode or "stretch").lower()
        if mode == "warp":
            return self._compute_warp_uvs(points, minx, miny, box_w, box_h)

        offset_x, offset_y, content_w, content_h = content_rect(
            box_w, box_h, media_w, media_h, mode
        )

        # Deliberately unclamped. In `contain` the bars really are outside the
        # media, and clamping here would stretch the edge column of pixels
        # across them instead of leaving them empty; the fragment shader
        # discards those samples rather than hiding them.
        uvs: List[Tuple[float, float]] = []
        for x, y in points:
            uvs.append((
                (x - minx - offset_x) / content_w,
                (y - miny - offset_y) / content_h,
            ))

        return uvs
    def _compute_warp_uvs(
        self,
        points: List[Tuple[float, float]],
        minx: float,
        miny: float,
        box_w: float,
        box_h: float,
    ) -> List[Tuple[float, float]]:
        """Per-vertex UVs for warp mode.

        These are the fallback the fragment shader uses when the homography
        cannot be built (degenerate quad, or a shape that is not a quad at
        all). When it can, `_warp_matrix` supersedes them.
        """
        uvs = corner_uv_assignment(points)
        if uvs is not None:
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
        cached = self._image_cache.get(media.path)
        if cached:
            return cached

        img = self._load_image(media.path)
        if not img:
            return None, (0, 0)

        tex_id = self._create_texture_from_qimage(img)
        if tex_id:
            entry = (tex_id, (img.width(), img.height()))
            self._image_cache[media.path] = entry
            return entry
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

        # One texture per clip, refilled in place. Allocating a fresh texture
        # every frame - and never deleting it - exhausts GPU memory within
        # minutes of playback.
        frame_size = (qimg.width(), qimg.height())
        cached = self._video_textures.get(media.path)
        if cached and cached[1] == frame_size:
            tex_id = cached[0]
            ptr = self._image_bytes(qimg)
            glBindTexture(GL_TEXTURE_2D, tex_id)
            glTexSubImage2D(
                GL_TEXTURE_2D, 0, 0, 0, frame_size[0], frame_size[1],
                GL_RGBA, GL_UNSIGNED_BYTE, ptr,
            )
            return tex_id, size

        if cached:
            glDeleteTextures(1, [cached[0]])

        tex_id = self._create_texture_from_qimage(qimg)
        if not tex_id:
            return None, (0, 0)
        self._video_textures[media.path] = (tex_id, frame_size)
        return tex_id, size

    @staticmethod
    def _image_bytes(image: QImage) -> bytes:
        """Raw pixels of a QImage, ready for glTex*Image2D.

        PySide6 hands back a correctly sized memoryview; the older
        `setsize()` dance belongs to PyQt5's sip pointers and raises here.
        """
        return bytes(image.constBits())

    def _create_texture_from_qimage(self, image: QImage) -> Optional[int]:
        """Create an OpenGL texture from a QImage."""
        ptr = self._image_bytes(image)

        tex_id = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, tex_id)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        # Clamped, not repeated: rounding in the corner-pin divide can push a
        # UV a hair outside [0, 1] at the surface edge, and REPEAT turns that
        # into a strip of the opposite edge stitched along the border.
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, image.width(), image.height(), 0, GL_RGBA, GL_UNSIGNED_BYTE, ptr)

        return tex_id

    def _compute_uvs_from_size(
        self,
        points: List[Tuple[float, float]],
        tex_size: Tuple[int, int],
        media: MediaRef,
    ) -> List[Tuple[float, float]]:
        """Compute UV coordinates based on texture size."""
        return self._compute_fit_uvs(points, tex_size[0], tex_size[1], media)
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

# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pixel tests: what actually lands on the projector.

Everything else in this suite checks the numbers that feed the renderer. These
check the frame that comes out, because the failures that cost a show live in
the gap between the two - a Y flip, a stroke that renders one pixel wide, a
mask that is cut out of the geometry but not out of the image.

They need a real GL context, which the `offscreen` platform cannot give, so
they skip by default and run for real under:

    xvfb-run -a env QT_QPA_PLATFORM=xcb LIBGL_ALWAYS_SOFTWARE=1 pytest tests/test_render_gl.py
"""

import os

import pytest
from PySide6.QtCore import QRectF, QTimer
from PySide6.QtGui import QColor, QImage, QPainter

from pm.model.output import Output
from pm.model.project import Project
from pm.model.shapes import (
    circle_from_center,
    mask_from_rect,
    mesh_from_rect,
    polygon_from_points,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("QT_QPA_PLATFORM", "offscreen") == "offscreen",
    reason="QOpenGLWidget cannot create a context on the offscreen platform",
)

WIDTH, HEIGHT = 320, 240


@pytest.fixture
def project():
    project = Project()
    project.canvas.width, project.canvas.height = WIDTH, HEIGHT
    project.outputs = [Output(name="Preview")]
    return project


def _grab(project, output=None, size=(WIDTH, HEIGHT)) -> QImage:
    """One frame of `project` through `output`, as an image.

    The renderer paints on a timer, so the widget is shown and pumped rather
    than asked to paint directly: `grabFramebuffer` on a widget that has never
    been composited comes back empty.
    """
    from PySide6.QtWidgets import QApplication

    from pm.render.gl_renderer import GLRenderer

    app = QApplication.instance()
    renderer = GLRenderer(project, output=output or project.outputs[0])
    renderer.resize(*size)
    renderer.show()
    for _ in range(6):
        app.processEvents()
    renderer.repaint()
    app.processEvents()
    image = renderer.grabFramebuffer()
    renderer.cleanup()
    renderer.close()
    renderer.deleteLater()
    app.processEvents()
    return image


def _at(image: QImage, x: float, y: float):
    """Colour at a canvas coordinate, as (r, g, b)."""
    px = int(x / WIDTH * image.width())
    py = int(y / HEIGHT * image.height())
    px = max(0, min(image.width() - 1, px))
    py = max(0, min(image.height() - 1, py))
    colour = image.pixelColor(px, py)
    return (colour.red(), colour.green(), colour.blue())


def _is_dark(rgb, threshold=40) -> bool:
    return max(rgb) <= threshold


def _checkerboard(path, w=128, h=128, cell=32):
    image = QImage(w, h, QImage.Format_RGB32)
    painter = QPainter(image)
    for y in range(0, h, cell):
        for x in range(0, w, cell):
            on = ((x // cell) + (y // cell)) % 2 == 0
            painter.fillRect(x, y, cell, cell, QColor(240, 60, 40) if on else QColor(20, 30, 90))
    # A marker in the top-left quarter, so a vertical flip is visible.
    painter.fillRect(0, 0, cell // 2, cell // 2, QColor(255, 255, 255))
    painter.end()
    image.save(path)
    return path


# --- the basics -------------------------------------------------------------

def test_a_solid_surface_lands_where_the_canvas_says(project, qapp):
    shape = polygon_from_points(
        [(80.0, 60.0), (240.0, 60.0), (240.0, 180.0), (80.0, 180.0)], name="wall"
    )
    shape.fill_color = [255, 0, 0, 255]
    shape.stroke_width = 0.0
    project.add_shape(shape)

    image = _grab(project)

    assert _at(image, 160, 120)[0] > 180, "the middle of the surface is filled"
    assert _is_dark(_at(image, 20, 20)), "outside it is background"
    assert _is_dark(_at(image, 300, 220))


def test_the_canvas_is_not_flipped_vertically(project, qapp):
    """Canvas Y grows down; NDC grows up. Getting this wrong mirrors the show
    against what the operator is editing, and a symmetric test pattern hides it."""
    top = polygon_from_points([(20.0, 10.0), (300.0, 10.0), (300.0, 60.0), (20.0, 60.0)])
    top.fill_color = [255, 0, 0, 255]
    top.stroke_width = 0.0
    bottom = polygon_from_points([(20.0, 180.0), (300.0, 180.0), (300.0, 230.0), (20.0, 230.0)])
    bottom.fill_color = [0, 0, 255, 255]
    bottom.stroke_width = 0.0
    project.add_shape(top)
    project.add_shape(bottom)

    image = _grab(project)

    assert _at(image, 160, 35)[0] > 180, "red belongs at the top"
    assert _at(image, 160, 205)[2] > 180, "blue belongs at the bottom"


def test_a_hidden_surface_is_not_drawn(project, qapp):
    shape = polygon_from_points([(80.0, 60.0), (240.0, 60.0), (240.0, 180.0), (80.0, 180.0)])
    shape.fill_color = [255, 0, 0, 255]
    shape.visible = False
    project.add_shape(shape)

    assert _is_dark(_at(_grab(project), 160, 120))


def test_opacity_reaches_the_output(project, qapp):
    shape = polygon_from_points([(80.0, 60.0), (240.0, 60.0), (240.0, 180.0), (80.0, 180.0)])
    shape.fill_color = [255, 255, 255, 255]
    shape.stroke_width = 0.0
    shape.opacity = 0.25
    project.add_shape(shape)

    assert 20 < _at(_grab(project), 160, 120)[0] < 160


# --- strokes ----------------------------------------------------------------

def test_a_thick_stroke_is_actually_thick(project, qapp):
    """`_draw_line` took a width and never used it, so every stroke came out
    one pixel wide on the projector while the editor drew it correctly."""
    shape = polygon_from_points(
        [(80.0, 60.0), (240.0, 60.0), (240.0, 180.0), (80.0, 180.0)], name="wall"
    )
    shape.fill_color = [0, 0, 0, 0]
    shape.stroke_color = [0, 255, 0, 255]
    shape.stroke_width = 10.0
    project.add_shape(shape)

    image = _grab(project)

    # Walk down the left edge's normal: a 10-unit stroke straddles the edge.
    lit = [x for x in range(70, 92) if _at(image, x, 120)[1] > 120]
    assert len(lit) >= 6, f"stroke covered only {len(lit)} columns"


# --- masks ------------------------------------------------------------------

def test_a_mask_is_a_hole_in_the_projected_image(project, qapp):
    shape = polygon_from_points(
        [(60.0, 40.0), (260.0, 40.0), (260.0, 200.0), (60.0, 200.0)], name="wall"
    )
    shape.fill_color = [255, 255, 255, 255]
    shape.stroke_width = 0.0
    shape.masks = [mask_from_rect((160.0, 120.0), 80.0, 60.0)]
    project.add_shape(shape)

    image = _grab(project)

    assert _at(image, 160, 120) == pytest.approx((0, 0, 0), abs=12), "the window is dark"
    assert _at(image, 90, 120)[0] > 180, "the wall around it is not"


# --- circles and meshes -----------------------------------------------------

def test_a_circle_closes_all_the_way_round(project, qapp):
    """The fan used to stop one wedge short, leaving a slice unlit."""
    circle = circle_from_center((160.0, 120.0), 80.0, name="dot")
    circle.fill_color = [255, 255, 255, 255]
    circle.stroke_width = 0.0
    project.add_shape(circle)

    image = _grab(project)

    import math

    for degrees in range(0, 360, 15):
        angle = math.radians(degrees)
        x = 160.0 + math.cos(angle) * 60.0
        y = 120.0 + math.sin(angle) * 60.0
        assert _at(image, x, y)[0] > 180, f"unlit wedge at {degrees} degrees"


def test_a_mesh_fills_its_patch(project, qapp):
    mesh = mesh_from_rect((160.0, 120.0), 140.0, rows=2, cols=2, name="column")
    mesh.fill_color = [255, 255, 255, 255]
    mesh.stroke_width = 0.0
    project.add_shape(mesh)

    image = _grab(project)

    assert _at(image, 160, 120)[0] > 180
    assert _is_dark(_at(image, 20, 20))


# --- media ------------------------------------------------------------------

def test_media_is_drawn_the_right_way_up(project, tmp_path, qapp):
    path = _checkerboard(str(tmp_path / "checker.png"))
    shape = polygon_from_points(
        [(60.0, 40.0), (260.0, 40.0), (260.0, 200.0), (60.0, 200.0)], name="wall"
    )
    shape.media.kind = "image"
    shape.media.path = path
    shape.media.fit_mode = "stretch"
    shape.stroke_width = 0.0
    project.add_shape(shape)

    image = _grab(project)

    # The white marker occupies the top-left eighth of the media.
    top_left = _at(image, 66, 46)
    assert min(top_left) > 180, f"the marker is not at the top left: {top_left}"


def test_contain_letterboxes_instead_of_smearing(project, tmp_path, qapp):
    """Clamped UVs used to stretch the media's edge pixels across the bars."""
    path = _checkerboard(str(tmp_path / "checker.png"), w=128, h=128)
    shape = polygon_from_points(
        [(20.0, 60.0), (300.0, 60.0), (300.0, 180.0), (20.0, 180.0)], name="wide"
    )
    shape.media.kind = "image"
    shape.media.path = path
    shape.media.fit_mode = "contain"
    shape.fill_color = [0, 0, 0, 0]
    shape.stroke_width = 0.0
    project.add_shape(shape)

    image = _grab(project)

    assert _is_dark(_at(image, 30, 120)), "the left bar is empty, not smeared"
    assert _is_dark(_at(image, 290, 120)), "and so is the right one"
    assert not _is_dark(_at(image, 160, 120)), "the media itself is in the middle"


# --- the output pass --------------------------------------------------------

def test_an_output_region_crops_to_its_share_of_the_canvas(project, qapp):
    left = polygon_from_points([(10.0, 100.0), (150.0, 100.0), (150.0, 140.0), (10.0, 140.0)])
    left.fill_color = [255, 0, 0, 255]
    left.stroke_width = 0.0
    right = polygon_from_points([(170.0, 100.0), (310.0, 100.0), (310.0, 140.0), (170.0, 140.0)])
    right.fill_color = [0, 0, 255, 255]
    right.stroke_width = 0.0
    project.add_shape(left)
    project.add_shape(right)

    output = Output(name="Left half")
    output.region.u1 = 0.5

    image = _grab(project, output=output)

    # The left half of the canvas now fills the whole frame: red spans it and
    # the blue surface is off-screen entirely.
    assert _at(image, 160, 120)[0] > 150
    assert all(
        _at(image, x, 120)[2] < 150 for x in range(20, 300, 40)
    ), "the right half must not be in this projector's frame"


def test_a_blend_ramp_darkens_the_edge_it_is_on(project, qapp):
    shape = polygon_from_points([(0.0, 0.0), (320.0, 0.0), (320.0, 240.0), (0.0, 240.0)])
    shape.fill_color = [255, 255, 255, 255]
    shape.stroke_width = 0.0
    project.add_shape(shape)

    output = Output(name="Left projector")
    output.blend.right = 0.3

    image = _grab(project, output=output)

    middle = _at(image, 40, 120)[0]
    edge = _at(image, 315, 120)[0]
    assert middle > 200, "away from the seam the image is untouched"
    assert edge < 60, "the outer end of the ramp is nearly black"
    assert edge < middle


def test_colour_correction_reaches_the_frame(project, qapp):
    shape = polygon_from_points([(0.0, 0.0), (320.0, 0.0), (320.0, 240.0), (0.0, 240.0)])
    shape.fill_color = [200, 200, 200, 255]
    shape.stroke_width = 0.0
    project.add_shape(shape)

    plain = _at(_grab(project), 160, 120)

    output = Output(name="Dim")
    output.color.brightness = -0.4
    dimmed = _at(_grab(project, output=output), 160, 120)

    assert dimmed[0] < plain[0] - 40


def test_a_gain_shifts_only_its_own_channel(project, qapp):
    shape = polygon_from_points([(0.0, 0.0), (320.0, 0.0), (320.0, 240.0), (0.0, 240.0)])
    shape.fill_color = [200, 200, 200, 255]
    shape.stroke_width = 0.0
    project.add_shape(shape)

    output = Output(name="Warm")
    output.color.gain_b = 0.3

    r, g, b = _at(_grab(project, output=output), 160, 120)

    assert b < r - 40 and b < g - 40


# --- the test pattern -------------------------------------------------------

def test_test_mode_replaces_the_artwork(project, qapp):
    shape = polygon_from_points([(80.0, 60.0), (240.0, 60.0), (240.0, 180.0), (80.0, 180.0)])
    shape.fill_color = [255, 0, 0, 255]
    project.add_shape(shape)
    project.ui_state["test_mode"] = True
    project.ui_state["test_pattern"] = "checkerboard"

    image = _grab(project)

    # No red anywhere: the pattern is greyscale and covers the whole canvas.
    reds = [_at(image, x, y) for x in (40, 160, 280) for y in (40, 120, 200)]
    assert all(abs(r - g) < 60 for r, g, _b in reds), f"artwork leaked into test mode: {reds}"


# --- blend modes ------------------------------------------------------------

def _stacked(project, mode, under=(80, 80, 80), over=(80, 80, 80)):
    from pm.model.shapes import polygon_from_points

    base = polygon_from_points([(0.0, 0.0), (320.0, 0.0), (320.0, 240.0), (0.0, 240.0)])
    base.fill_color = [*under, 255]
    base.stroke_width = 0.0
    top = polygon_from_points([(80.0, 60.0), (240.0, 60.0), (240.0, 180.0), (80.0, 180.0)])
    top.fill_color = [*over, 255]
    top.stroke_width = 0.0
    top.blend_mode = mode
    project.add_shape(base)
    project.add_shape(top)
    return _grab(project)


def test_normal_blending_covers_what_is_under_it(project, qapp):
    image = _stacked(project, "normal", under=(200, 0, 0), over=(0, 0, 200))
    assert _at(image, 160, 120)[2] > 150
    assert _at(image, 160, 120)[0] < 80


def test_add_brightens_instead_of_replacing(project, qapp):
    """Two beams on the same wall sum; one does not delete the other."""
    plain = _at(_stacked(project, "normal"), 160, 120)[0]

    fresh = Project()
    fresh.canvas.width, fresh.canvas.height = WIDTH, HEIGHT
    fresh.outputs = [Output(name="Preview")]
    added = _at(_stacked(fresh, "add"), 160, 120)[0]

    assert added > plain + 40, f"add gave {added}, normal gave {plain}"


def test_multiply_darkens(project, qapp):
    image = _stacked(project, "multiply", under=(200, 200, 200), over=(120, 120, 120))
    inside = _at(image, 160, 120)[0]
    outside = _at(image, 20, 20)[0]

    assert inside < outside - 40, f"multiply gave {inside} against {outside}"


def test_screen_never_darkens(project, qapp):
    image = _stacked(project, "screen", under=(120, 120, 120), over=(120, 120, 120))
    inside = _at(image, 160, 120)[0]
    outside = _at(image, 20, 20)[0]

    assert inside > outside + 30


def test_a_blend_mode_does_not_leak_into_the_next_surface(project, qapp):
    """The mode is per surface; leaving it set would tint everything after."""
    from pm.model.shapes import polygon_from_points

    glow = polygon_from_points([(10.0, 10.0), (100.0, 10.0), (100.0, 100.0), (10.0, 100.0)])
    glow.fill_color = [200, 200, 200, 255]
    glow.blend_mode = "add"
    glow.stroke_width = 0.0
    plain = polygon_from_points([(150.0, 120.0), (300.0, 120.0), (300.0, 220.0), (150.0, 220.0)])
    plain.fill_color = [0, 0, 200, 255]
    plain.stroke_width = 0.0
    project.add_shape(glow)
    project.add_shape(plain)

    image = _grab(project)

    r, _g, b = _at(image, 220, 170)
    assert b > 150 and r < 80, "the plain surface composited normally"


# --- blackout ---------------------------------------------------------------

def test_blackout_kills_the_frame(project, qapp):
    """The panic button. Nothing downstream runs, so nothing can leak."""
    shape = polygon_from_points([(0.0, 0.0), (320.0, 0.0), (320.0, 240.0), (0.0, 240.0)])
    shape.fill_color = [255, 255, 255, 255]
    shape.stroke_width = 0.0
    project.add_shape(shape)

    lit = _at(_grab(project), 160, 120)
    assert lit[0] > 200

    project.set_blackout(True)
    dark = _grab(project)

    for x, y in ((10, 10), (160, 120), (310, 230)):
        assert _is_dark(_at(dark, x, y), threshold=8), f"light left at {x},{y}"


def test_blackout_beats_test_mode(project, qapp):
    """Test mode replaces the artwork; blackout replaces everything."""
    project.ui_state["test_mode"] = True
    project.set_blackout(True)

    image = _grab(project)

    assert _is_dark(_at(image, 160, 120), threshold=8)


def test_clearing_the_blackout_brings_the_show_back(project, qapp):
    shape = polygon_from_points([(0.0, 0.0), (320.0, 0.0), (320.0, 240.0), (0.0, 240.0)])
    shape.fill_color = [255, 255, 255, 255]
    shape.stroke_width = 0.0
    project.add_shape(shape)
    project.set_blackout(True)

    project.set_blackout(False)

    assert _at(_grab(project), 160, 120)[0] > 200

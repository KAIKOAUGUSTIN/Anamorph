import pytest

from pm.io.project_io import load_project, save_project
from pm.model.media import SourceRect
from pm.model.output import (
    ColorCorrection,
    EdgeBlend,
    IDENTITY_CORNERS,
    Output,
    split_outputs,
)
from pm.model.project import Project
from pm.model.shapes import polygon_from_points


# --- the blend curve --------------------------------------------------------
#
# Mirrors the GLSL in FRAGMENT_SHADER_OUTPUT. The property it has to satisfy is
# the whole point of edge blending, and it is far cheaper to pin down here than
# by sampling a framebuffer.

def blend_curve(t: float, exponent: float) -> float:
    t = max(0.0, min(1.0, t))
    if t < 0.5:
        return 0.5 * (2.0 * t) ** exponent
    return 1.0 - 0.5 * (2.0 * (1.0 - t)) ** exponent


@pytest.mark.parametrize("exponent", [1.0, 1.8, 2.2, 3.0])
@pytest.mark.parametrize("t", [0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0])
def test_facing_projectors_always_sum_to_one(t, exponent):
    """Two projectors across an overlap see t and 1-t.

    If the pair does not sum to exactly 1, the middle of the seam comes out
    brighter or darker than the rest of the wall - which is the artefact edge
    blending exists to remove. A plain pow() curve fails this.
    """
    assert blend_curve(t, exponent) + blend_curve(1.0 - t, exponent) == pytest.approx(1.0)


def test_a_naive_power_curve_would_not_sum_to_one():
    """Guards the reasoning above, so the S-curve is not 'simplified' away."""
    t, exponent = 0.5, 2.2
    naive = t ** (1.0 / exponent)
    assert naive + (1.0 - t) ** (1.0 / exponent) != pytest.approx(1.0)


def test_the_curve_reaches_both_ends():
    assert blend_curve(0.0, 2.2) == pytest.approx(0.0)
    assert blend_curve(1.0, 2.2) == pytest.approx(1.0)


# --- tiling -----------------------------------------------------------------

def test_a_single_output_covers_everything_with_no_ramp():
    outputs = split_outputs(1)
    assert len(outputs) == 1
    assert outputs[0].region.is_full_frame()
    assert not outputs[0].blend.is_active()


def test_two_outputs_overlap_in_the_middle():
    left, right = split_outputs(2, overlap=0.25)
    assert left.region.u0 == 0.0
    assert right.region.u1 == 1.0
    assert left.region.u1 > right.region.u0, "the projectors must share a strip"


def test_ramps_span_the_whole_shared_strip():
    """Each neighbour reaches back past the boundary, so the overlap is twice
    the reach. Covering only half leaves both projectors at full brightness
    across the rest and the seam comes out doubled."""
    left, right = split_outputs(2, overlap=0.25)

    overlap_width = left.region.u1 - right.region.u0
    assert left.blend.right == pytest.approx(overlap_width / left.region.width)
    assert right.blend.left == pytest.approx(overlap_width / right.region.width)


def test_only_the_edges_that_meet_a_neighbour_ramp():
    left, middle, right = split_outputs(3, overlap=0.2)

    assert left.blend.left == 0.0 and left.blend.right > 0.0
    assert middle.blend.left > 0.0 and middle.blend.right > 0.0
    assert right.blend.left > 0.0 and right.blend.right == 0.0


def test_vertical_tiling_ramps_the_other_axis():
    top, bottom = split_outputs(2, overlap=0.2, horizontal=False)
    assert top.blend.bottom > 0.0 and top.blend.right == 0.0
    assert bottom.blend.top > 0.0 and bottom.blend.left == 0.0
    assert top.region.v1 > bottom.region.v0


def test_tiled_outputs_cover_the_canvas_end_to_end():
    outputs = split_outputs(4, overlap=0.15)
    assert outputs[0].region.u0 == 0.0
    assert outputs[-1].region.u1 == 1.0
    for a, b in zip(outputs, outputs[1:]):
        assert b.region.u0 < a.region.u1, "a gap between projectors is a dark stripe"


# --- clamping ---------------------------------------------------------------

def test_opposing_ramps_cannot_meet_in_the_middle():
    """Wider than half and the centre of the output would be attenuated from
    both sides at once."""
    blend = EdgeBlend(left=0.9, right=0.9).normalised()
    assert blend.left <= 0.5 and blend.right <= 0.5


def test_blend_exponent_stays_usable():
    assert EdgeBlend(gamma=0.0).normalised().gamma > 0.0


def test_colour_is_clamped_to_sane_ranges():
    color = ColorCorrection(brightness=9.0, contrast=-4.0, gamma=0.0, gain_r=99.0).normalised()
    assert color.brightness == 1.0
    assert color.contrast == 0.0
    assert color.gamma > 0.0
    assert color.gain_r == 4.0


def test_identity_colour_is_recognised():
    assert ColorCorrection().is_identity()
    assert not ColorCorrection(brightness=0.01).is_identity()


def test_keystone_starts_as_the_identity_frame():
    output = Output()
    assert not output.has_keystone()

    output.corners = [(0.2, 0.0), (0.8, 0.0), (1.0, 1.0), (0.0, 1.0)]
    assert output.has_keystone()

    output.reset_keystone()
    assert output.corners == IDENTITY_CORNERS


# --- persistence ------------------------------------------------------------

def test_outputs_survive_a_save_load_round_trip(tmp_path):
    project = Project()
    project.add_shape(polygon_from_points([(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]))
    project.outputs = split_outputs(2, overlap=0.2)
    project.outputs[0].screen_id = "screen_1"
    project.outputs[0].corners = [(0.1, 0.0), (0.9, 0.0), (1.0, 1.0), (0.0, 1.0)]
    project.outputs[1].color = ColorCorrection(brightness=-0.2, gain_b=0.8)

    path = str(tmp_path / "p.pmap.json")
    save_project(project, path)
    reloaded = load_project(path)

    assert len(reloaded.outputs) == 2
    assert reloaded.outputs[0].screen_id == "screen_1"
    assert reloaded.outputs[0].corners[0] == (0.1, 0.0)
    assert reloaded.outputs[1].color.gain_b == pytest.approx(0.8)
    assert reloaded.outputs[0].blend.right > 0.0


def test_a_project_without_outputs_gets_one():
    """Files written before outputs existed described a single projector by
    the screen id in ui_state."""
    project = Project.from_dict(
        {"name": "old", "canvas": {}, "shapes": [], "ui": {"last_projection_screen_id": "screen_2"}}
    )

    assert len(project.outputs) == 1
    assert project.outputs[0].screen_id == "screen_2"
    assert project.outputs[0].region.is_full_frame()
    assert not project.outputs[0].has_keystone()


def test_a_legacy_project_with_no_screen_still_gets_an_output():
    project = Project.from_dict({"name": "old", "shapes": []})
    assert len(project.outputs) == 1
    assert project.outputs[0].screen_id is None


def test_malformed_corners_fall_back_to_the_identity():
    output = Output.from_dict({"corners": [{"x": 0.0, "y": 0.0}]})
    assert output.corners == IDENTITY_CORNERS


# --- project wiring ---------------------------------------------------------

def test_outputs_can_be_added_and_removed(qapp):
    project = Project()
    project.outputs = []
    output = Output(name="Projector 1")

    project.add_output(output)
    assert project.get_output(output.id) is output

    project.remove_output(output.id)
    assert project.outputs == []
    assert project.get_output(output.id) is None


def test_changing_outputs_marks_the_project_dirty(qapp):
    project = Project()
    project.mark_saved()

    project.add_output(Output())

    assert project.dirty

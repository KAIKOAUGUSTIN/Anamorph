# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest

from render.fit import COVER, CONTAIN, STRETCH, WARP, content_rect, leaves_unit_square


def test_stretch_fills_the_box():
    assert content_rect(400, 200, 100, 100, STRETCH) == (0.0, 0.0, 400.0, 200.0)


def test_contain_letterboxes_a_tall_media_in_a_wide_box():
    offset_x, offset_y, w, h = content_rect(400, 200, 100, 200, CONTAIN)
    # Media is 1:2, box is 2:1 -> height binds, leaving pillars either side.
    assert (w, h) == (100.0, 200.0)
    assert offset_x == pytest.approx(150.0)
    assert offset_y == pytest.approx(0.0)


def test_contain_letterboxes_a_wide_media_in_a_tall_box():
    offset_x, offset_y, w, h = content_rect(200, 400, 200, 100, CONTAIN)
    assert (w, h) == (200.0, 100.0)
    assert offset_x == pytest.approx(0.0)
    assert offset_y == pytest.approx(150.0)


def test_contain_never_overflows():
    offset_x, offset_y, w, h = content_rect(400, 200, 100, 200, CONTAIN)
    assert w <= 400 and h <= 200
    assert offset_x >= 0 and offset_y >= 0


def test_cover_overflows_and_centres():
    offset_x, offset_y, w, h = content_rect(400, 200, 100, 200, COVER)
    # Width binds now, so the media runs off the top and bottom.
    assert (w, h) == (400.0, 800.0)
    assert offset_x == pytest.approx(0.0)
    assert offset_y == pytest.approx(-300.0)


def test_cover_always_reaches_every_edge():
    offset_x, offset_y, w, h = content_rect(400, 200, 100, 200, COVER)
    assert offset_x <= 0 and offset_y <= 0
    assert offset_x + w >= 400 and offset_y + h >= 200


def test_matching_aspect_ratios_agree_across_modes():
    box = (400, 200)
    media = (200, 100)
    assert content_rect(*box, *media, CONTAIN) == content_rect(*box, *media, COVER)
    assert content_rect(*box, *media, CONTAIN) == content_rect(*box, *media, STRETCH)


def test_warp_falls_back_to_stretch():
    """warp is a homography, not a fit; callers branch before reaching here."""
    assert content_rect(400, 200, 100, 100, WARP) == content_rect(400, 200, 100, 100, STRETCH)


def test_unknown_mode_falls_back_to_stretch():
    assert content_rect(400, 200, 100, 100, "nonsense") == (0.0, 0.0, 400.0, 200.0)


@pytest.mark.parametrize("mode", [STRETCH, CONTAIN, COVER])
def test_degenerate_inputs_do_not_divide_by_zero(mode):
    offset_x, offset_y, w, h = content_rect(0, 0, 0, 0, mode)
    assert w > 0 and h > 0
    assert all(v == v for v in (offset_x, offset_y, w, h))  # no NaN


def test_only_contain_leaves_the_unit_square():
    assert leaves_unit_square(CONTAIN)
    assert not leaves_unit_square(COVER)
    assert not leaves_unit_square(STRETCH)
    assert not leaves_unit_square(WARP)


def test_uvs_derived_from_contain_fall_outside_the_unit_square():
    """The bars are outside the media - which is exactly why the renderer has
    to discard those samples rather than clamp them to the edge pixel."""
    box_w, box_h = 400.0, 200.0
    offset_x, _, content_w, _ = content_rect(box_w, box_h, 100, 200, CONTAIN)

    u_left = (0.0 - offset_x) / content_w
    u_right = (box_w - offset_x) / content_w
    assert u_left < 0.0
    assert u_right > 1.0

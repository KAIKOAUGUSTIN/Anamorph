# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""How media is placed inside a surface's bounding box.

This lives on its own because two places need the answer and they must never
disagree: the OpenGL renderer turns it into UVs, and the editor viewport turns
it into a destination rectangle for QPainter. When the two drifted apart, the
canvas showed one framing and the projector showed another - the worst kind of
bug in a mapping tool, because the operator calibrates against the lie.

Pure arithmetic: no Qt, no GL.
"""

from __future__ import annotations

from typing import Tuple

STRETCH = "stretch"
CONTAIN = "contain"
COVER = "cover"
WARP = "warp"

# Boxes and media can both collapse to nothing mid-drag; clamp rather than
# divide by zero.
_MIN_EXTENT = 1e-5


def content_rect(
    box_w: float,
    box_h: float,
    media_w: float,
    media_h: float,
    mode: str,
) -> Tuple[float, float, float, float]:
    """Where the media sits inside the box.

    Returns ``(offset_x, offset_y, content_w, content_h)`` in box units, with
    the offset measured from the box's top-left corner.

    - ``stretch`` fills the box, ignoring the media's aspect ratio.
    - ``contain`` fits the whole media inside, leaving bars: the content is
      smaller than the box, so the offsets are positive.
    - ``cover`` fills the box and overflows: the content is larger, so the
      offsets are negative and the caller clips.

    ``warp`` has no meaningful rectangle - it is a homography, not a fit - and
    is treated as ``stretch`` so callers that forget to branch still get
    something sane rather than a crash.
    """
    box_w = max(float(box_w), _MIN_EXTENT)
    box_h = max(float(box_h), _MIN_EXTENT)
    media_w = max(float(media_w), _MIN_EXTENT)
    media_h = max(float(media_h), _MIN_EXTENT)

    mode = (mode or STRETCH).lower()
    if mode == CONTAIN:
        scale = min(box_w / media_w, box_h / media_h)
    elif mode == COVER:
        scale = max(box_w / media_w, box_h / media_h)
    else:  # stretch, warp, and anything unrecognised
        return (0.0, 0.0, box_w, box_h)

    content_w = media_w * scale
    content_h = media_h * scale
    return (
        (box_w - content_w) / 2.0,
        (box_h - content_h) / 2.0,
        content_w,
        content_h,
    )


def leaves_unit_square(mode: str) -> bool:
    """True when UVs computed from this mode can fall outside [0, 1].

    Only ``contain`` does, and only because the bars are genuinely outside the
    media. The renderer uses this to decide whether those fragments have to be
    discarded instead of clamped to the edge pixel.
    """
    return (mode or STRETCH).lower() == CONTAIN

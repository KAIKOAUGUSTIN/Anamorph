# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Projector outputs onto a single shared canvas.

The canvas is the artwork; an output is one projector's view of part of it.
Several projectors can cover the same canvas, overlapping where they meet, and
each carries the corrections that make a physical rig agree with itself:

- **region** - which slice of the canvas this projector is responsible for.
- **corners** - keystone. Squaring the projector against the surface, above
  and beyond the per-surface corner pin.
- **blend** - the ramps that make an overlap between two projectors invisible.
- **colour** - two projectors never match out of the box; one runs warmer or
  dimmer than the other and has to be pulled into line.

This is the piece that made soft-edge impossible before: every screen used to
own a whole separate project, so two projectors could never be looking at one
canvas in the first place.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from model.media import SourceRect

Point = Tuple[float, float]

# The output's own frame, normalised. Keystone corners start here, meaning
# "fill the projector exactly".
IDENTITY_CORNERS: List[Point] = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]


def new_output_id() -> str:
    return uuid.uuid4().hex[:8]


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


@dataclass
class EdgeBlend:
    """Soft-edge ramps, as a fraction of the output's width or height.

    Where two projectors overlap, each fades out across the shared strip so
    the seam disappears. `gamma` shapes the ramp: projectors are not linear,
    and a straight fade leaves a visible bright or dark band down the middle
    of the overlap. 2.2 is the usual starting point, tuned by eye.
    """

    left: float = 0.0
    right: float = 0.0
    top: float = 0.0
    bottom: float = 0.0
    gamma: float = 2.2

    def is_active(self) -> bool:
        return any(v > 0.0 for v in (self.left, self.right, self.top, self.bottom))

    def normalised(self) -> "EdgeBlend":
        # Opposing ramps must not overlap, or the middle of the output would
        # be attenuated from both sides at once.
        left = _clamp(self.left, 0.0, 0.5)
        right = _clamp(self.right, 0.0, 0.5)
        top = _clamp(self.top, 0.0, 0.5)
        bottom = _clamp(self.bottom, 0.0, 0.5)
        return EdgeBlend(left, right, top, bottom, max(0.1, float(self.gamma)))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "left": float(self.left),
            "right": float(self.right),
            "top": float(self.top),
            "bottom": float(self.bottom),
            "gamma": float(self.gamma),
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "EdgeBlend":
        if not data:
            return EdgeBlend()
        return EdgeBlend(
            left=float(data.get("left", 0.0)),
            right=float(data.get("right", 0.0)),
            top=float(data.get("top", 0.0)),
            bottom=float(data.get("bottom", 0.0)),
            gamma=float(data.get("gamma", 2.2)),
        )


@dataclass
class ColorCorrection:
    """Per-projector colour, for pulling a mismatched rig into agreement."""

    brightness: float = 0.0   # added, -1..1
    contrast: float = 1.0     # multiplied about mid grey
    gamma: float = 1.0
    gain_r: float = 1.0
    gain_g: float = 1.0
    gain_b: float = 1.0

    def is_identity(self) -> bool:
        return (
            self.brightness == 0.0
            and self.contrast == 1.0
            and self.gamma == 1.0
            and self.gain_r == self.gain_g == self.gain_b == 1.0
        )

    def normalised(self) -> "ColorCorrection":
        return ColorCorrection(
            brightness=_clamp(self.brightness, -1.0, 1.0),
            contrast=_clamp(self.contrast, 0.0, 4.0),
            gamma=_clamp(self.gamma, 0.1, 4.0),
            gain_r=_clamp(self.gain_r, 0.0, 4.0),
            gain_g=_clamp(self.gain_g, 0.0, 4.0),
            gain_b=_clamp(self.gain_b, 0.0, 4.0),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "brightness": float(self.brightness),
            "contrast": float(self.contrast),
            "gamma": float(self.gamma),
            "gain_r": float(self.gain_r),
            "gain_g": float(self.gain_g),
            "gain_b": float(self.gain_b),
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "ColorCorrection":
        if not data:
            return ColorCorrection()
        return ColorCorrection(
            brightness=float(data.get("brightness", 0.0)),
            contrast=float(data.get("contrast", 1.0)),
            gamma=float(data.get("gamma", 1.0)),
            gain_r=float(data.get("gain_r", 1.0)),
            gain_g=float(data.get("gain_g", 1.0)),
            gain_b=float(data.get("gain_b", 1.0)),
        )


@dataclass
class Output:
    id: str = field(default_factory=new_output_id)
    name: str = "Output"
    screen_id: Optional[str] = None
    enabled: bool = True
    # Which part of the shared canvas this projector shows. Two projectors
    # covering one wall take overlapping regions and blend the seam.
    region: SourceRect = field(default_factory=SourceRect)
    # Keystone, in the output's own normalised frame.
    corners: List[Point] = field(default_factory=lambda: list(IDENTITY_CORNERS))
    blend: EdgeBlend = field(default_factory=EdgeBlend)
    color: ColorCorrection = field(default_factory=ColorCorrection)

    def has_keystone(self) -> bool:
        return [tuple(c) for c in self.corners] != IDENTITY_CORNERS

    def reset_keystone(self) -> None:
        self.corners = list(IDENTITY_CORNERS)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "screen_id": self.screen_id,
            "enabled": bool(self.enabled),
            "region": self.region.to_dict(),
            "corners": [{"x": float(x), "y": float(y)} for x, y in self.corners],
            "blend": self.blend.to_dict(),
            "color": self.color.to_dict(),
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "Output":
        corners = [
            (float(p.get("x", 0.0)), float(p.get("y", 0.0)))
            for p in data.get("corners", [])
        ]
        if len(corners) != 4:
            corners = list(IDENTITY_CORNERS)
        return Output(
            id=data.get("id") or new_output_id(),
            name=data.get("name", "Output"),
            screen_id=data.get("screen_id"),
            enabled=bool(data.get("enabled", True)),
            region=SourceRect.from_dict(data.get("region", {})),
            corners=corners,
            blend=EdgeBlend.from_dict(data.get("blend", {})),
            color=ColorCorrection.from_dict(data.get("color", {})),
        )


def split_outputs(count: int, overlap: float = 0.1, horizontal: bool = True) -> List[Output]:
    """`count` projectors tiled across the canvas, overlapping by `overlap`.

    The starting point for an edge-blended rig: the regions already overlap by
    the right amount and the facing edges already carry matching ramps, so the
    operator tunes rather than derives.
    """
    count = max(1, int(count))
    overlap = _clamp(overlap, 0.0, 0.5)
    outputs: List[Output] = []

    span = 1.0 / count
    for index in range(count):
        start = max(0.0, index * span - (overlap * span if index > 0 else 0.0))
        end = min(1.0, (index + 1) * span + (overlap * span if index < count - 1 else 0.0))

        blend = EdgeBlend()
        # Only the edges that actually meet a neighbour get a ramp, and the
        # ramp has to span the *whole* overlap. Both neighbours reach back by
        # `overlap * span` past the boundary, so the shared strip is twice
        # that - covering only half of it leaves each projector at full
        # brightness across the rest and the seam comes out doubled.
        if count > 1:
            ramp = (2.0 * overlap * span) / max(end - start, 1e-6)
            if index > 0:
                setattr(blend, "left" if horizontal else "top", ramp)
            if index < count - 1:
                setattr(blend, "right" if horizontal else "bottom", ramp)

        region = (
            SourceRect(start, 0.0, end, 1.0) if horizontal else SourceRect(0.0, start, 1.0, end)
        )
        outputs.append(
            Output(name=f"Projector {index + 1}", region=region, blend=blend)
        )

    return outputs

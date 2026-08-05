from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class MediaTransform:
    offset_x: float = 0.0
    offset_y: float = 0.0
    rotation: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "offset_x": float(self.offset_x),
            "offset_y": float(self.offset_y),
            "rotation": float(self.rotation),
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "MediaTransform":
        if not data:
            return MediaTransform()
        return MediaTransform(
            offset_x=float(data.get("offset_x", 0.0)),
            offset_y=float(data.get("offset_y", 0.0)),
            rotation=float(data.get("rotation", 0.0)),
        )


@dataclass
class SourceRect:
    """Which part of the media feeds a surface, in normalised coordinates.

    The whole point of separating input space from output space: where a
    surface *is* on the wall has nothing to do with which slice of the video
    it shows. One clip can drive six surfaces, each taking a different region,
    without six copies of the file.

    Axis-aligned on purpose. A free quad here would be a second homography
    layered on the corner pin, and the real need - "this wall shows the left
    third" - is a rectangle.
    """

    u0: float = 0.0
    v0: float = 0.0
    u1: float = 1.0
    v1: float = 1.0

    # A region has to keep some area or the surface samples a single pixel.
    MIN_SIZE = 0.01

    def normalised(self) -> "SourceRect":
        """A copy with the corners ordered and clamped into the unit square."""
        u0, u1 = sorted((_clamp01(self.u0), _clamp01(self.u1)))
        v0, v1 = sorted((_clamp01(self.v0), _clamp01(self.v1)))
        if u1 - u0 < self.MIN_SIZE:
            u1 = min(1.0, u0 + self.MIN_SIZE)
            u0 = max(0.0, u1 - self.MIN_SIZE)
        if v1 - v0 < self.MIN_SIZE:
            v1 = min(1.0, v0 + self.MIN_SIZE)
            v0 = max(0.0, v1 - self.MIN_SIZE)
        return SourceRect(u0, v0, u1, v1)

    @property
    def width(self) -> float:
        return self.u1 - self.u0

    @property
    def height(self) -> float:
        return self.v1 - self.v0

    def is_full_frame(self) -> bool:
        return (self.u0, self.v0, self.u1, self.v1) == (0.0, 0.0, 1.0, 1.0)

    def to_dict(self) -> Dict[str, Any]:
        return {"u0": float(self.u0), "v0": float(self.v0), "u1": float(self.u1), "v1": float(self.v1)}

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "SourceRect":
        if not data:
            return SourceRect()
        return SourceRect(
            u0=float(data.get("u0", 0.0)),
            v0=float(data.get("v0", 0.0)),
            u1=float(data.get("u1", 1.0)),
            v1=float(data.get("v1", 1.0)),
        )


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


@dataclass
class MediaRef:
    kind: Optional[str] = None  # "image", "video", or None
    path: str = ""
    fit_mode: str = "stretch"  # "stretch", "contain", "cover", "warp"
    transform: MediaTransform = field(default_factory=MediaTransform)
    source_rect: SourceRect = field(default_factory=SourceRect)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "path": self.path,
            "fit_mode": self.fit_mode,
            "transform": self.transform.to_dict(),
            "source_rect": self.source_rect.to_dict(),
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "MediaRef":
        if not data:
            return MediaRef()
        return MediaRef(
            kind=data.get("kind"),
            path=data.get("path", ""),
            fit_mode=data.get("fit_mode", "stretch"),
            transform=MediaTransform.from_dict(data.get("transform", {})),
            # Absent in files written before source regions existed, which
            # is exactly the full frame.
            source_rect=SourceRect.from_dict(data.get("source_rect", {})),
        )

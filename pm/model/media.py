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
class MediaRef:
    kind: Optional[str] = None  # "image", "video", or None
    path: str = ""
    fit_mode: str = "stretch"  # "stretch", "contain", "cover"
    transform: MediaTransform = field(default_factory=MediaTransform)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "path": self.path,
            "fit_mode": self.fit_mode,
            "transform": self.transform.to_dict(),
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
        )

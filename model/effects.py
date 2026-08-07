# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class EffectParam:
    enabled: bool = False
    amount: float = 0.0
    speed: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "amount": float(self.amount),
            "speed": float(self.speed),
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "EffectParam":
        if not data:
            return EffectParam()
        return EffectParam(
            enabled=bool(data.get("enabled", False)),
            amount=float(data.get("amount", 0.0)),
            speed=float(data.get("speed", 1.0)),
        )


@dataclass
class StrobeParam:
    enabled: bool = False
    hz: float = 2.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "hz": float(self.hz),
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "StrobeParam":
        if not data:
            return StrobeParam()
        return StrobeParam(
            enabled=bool(data.get("enabled", False)),
            hz=float(data.get("hz", 2.0)),
        )


@dataclass
class Effects:
    rgb_shift: EffectParam = field(default_factory=EffectParam)
    pulse: EffectParam = field(default_factory=EffectParam)
    strobe: StrobeParam = field(default_factory=StrobeParam)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rgb_shift": self.rgb_shift.to_dict(),
            "pulse": self.pulse.to_dict(),
            "strobe": self.strobe.to_dict(),
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "Effects":
        if not data:
            return Effects()
        return Effects(
            rgb_shift=EffectParam.from_dict(data.get("rgb_shift", {})),
            pulse=EffectParam.from_dict(data.get("pulse", {})),
            strobe=StrobeParam.from_dict(data.get("strobe", {})),
        )

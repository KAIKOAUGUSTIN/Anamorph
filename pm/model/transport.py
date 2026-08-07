"""The show clock.

Every clip in the project reads its position from here rather than from its
own decoder's idea of "now". That is what makes two surfaces showing the same
file frame-accurate against each other, and what lets one button stop the
whole show instead of stopping it one surface at a time.

The clock is monotonic wall time, scaled by `speed`. It is deliberately not
tied to any decoder: a stalled file must not drag the rest of the show back
with it, and a projector that drops frames must not fall behind the others.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict

# Playing fast enough to be useful for previewing, slow enough to be useful
# for setting a cue. Outside this and a decoder cannot keep up anyway.
MIN_SPEED = 0.05
MAX_SPEED = 4.0


@dataclass
class Transport:
    """Show time: where the whole project is, and whether it is moving."""

    playing: bool = True
    speed: float = 1.0

    def __post_init__(self) -> None:
        self._anchor_show = 0.0
        self._anchor_wall = time.monotonic()

    # --- reading ---------------------------------------------------------

    def position(self) -> float:
        """Show time in seconds.

        Held at the anchor while paused, which is what makes a paused show
        freeze rather than jump forward when it resumes.
        """
        if not self.playing:
            return self._anchor_show
        return self._anchor_show + (time.monotonic() - self._anchor_wall) * self.speed

    # --- writing ---------------------------------------------------------

    def play(self) -> None:
        if self.playing:
            return
        self._reanchor(self._anchor_show)
        self.playing = True

    def pause(self) -> None:
        if not self.playing:
            return
        self._anchor_show = self.position()
        self.playing = False

    def toggle(self) -> None:
        self.pause() if self.playing else self.play()

    def seek(self, seconds: float) -> None:
        self._reanchor(max(0.0, float(seconds)))

    def restart(self) -> None:
        self.seek(0.0)

    def set_speed(self, speed: float) -> None:
        """Change the rate without moving the playhead.

        Re-anchoring first is the whole trick: without it the elapsed wall
        time since the last anchor is suddenly reinterpreted at the new rate
        and the show jumps.
        """
        speed = max(MIN_SPEED, min(MAX_SPEED, float(speed)))
        if speed == self.speed:
            return
        self._reanchor(self.position())
        self.speed = speed

    def _reanchor(self, show_time: float) -> None:
        self._anchor_show = show_time
        self._anchor_wall = time.monotonic()

    # --- persistence -----------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        # Position is not saved: a show opens at the top, not wherever the
        # operator happened to leave it yesterday.
        return {"playing": bool(self.playing), "speed": float(self.speed)}

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "Transport":
        if not data:
            return Transport()
        return Transport(
            playing=bool(data.get("playing", True)),
            speed=max(MIN_SPEED, min(MAX_SPEED, float(data.get("speed", 1.0)))),
        )

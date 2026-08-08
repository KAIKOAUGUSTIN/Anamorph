# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Decoders, shared, driven by the show clock.

Two things this fixes at once.

**Synchronisation.** A clip used to free-run on its own thread from the moment
it was opened, so two surfaces showing the same file drifted apart by however
long apart they were loaded - and there was no way to bring them back. A clip
is now keyed by *what it is playing and how*, so two surfaces with the same
file and the same playback settings share one decoder and are frame-accurate
against each other by construction. Different settings get their own decoder,
which is the only honest answer when one is at half speed.

**Cost.** The renderer opened a decoder per path per renderer; the editor
opened none at all, which is why video could not be previewed. One pool serves
the editor, the preview and every projection window, so previewing a clip is
free once something else is already playing it.

The decode thread never seeks unless the show clock has moved somewhere it
cannot reach by reading forward. Seeking a compressed video is expensive and
inexact, so the common case - playing forward at normal speed - never does it.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Dict, Optional, Tuple

import cv2
import numpy as np

from model.media import MediaRef, Playback

logger = logging.getLogger(__name__)

Frame = Tuple[Optional[np.ndarray], Tuple[int, int]]
EMPTY: Frame = (None, (0, 0))

# How far the decoder may be behind the requested time before it gives up on
# reading forward and seeks. One frame of slack at 30fps is not enough - a
# decode hiccup would send it seeking, which costs more than it saves.
SEEK_THRESHOLD_SECONDS = 0.35

# A clip nobody has asked about for this long is closed. Deleting a surface,
# or pointing it at another file, should not leave a decode thread running for
# the rest of the show.
IDLE_TIMEOUT_SECONDS = 5.0


def clip_key(media: MediaRef) -> Optional[Tuple]:
    """What makes two surfaces able to share a decoder.

    Rounding is what makes sharing actually happen: two surfaces typed to the
    same speed through a spin box must not miss each other by 1e-15.
    """
    if not media or not media.path or media.kind not in ("video", "camera"):
        return None
    if media.kind == "camera":
        return ("camera", media.path)
    playback = media.playback.normalised()
    return (
        "video",
        media.path,
        round(playback.speed, 4),
        bool(playback.loop),
        round(playback.start, 3),
        bool(playback.hold_last),
    )


class Clip:
    """One decoder, following the show clock."""

    def __init__(self, path: str, playback: Playback, live: bool = False) -> None:
        self.path = path
        self.playback = playback.normalised()
        self.live = live
        self._capture = cv2.VideoCapture(int(path) if live else path)
        if not self._capture.isOpened():
            self._capture.release()
            raise IOError(f"Could not open media: {path}")

        fps = float(self._capture.get(cv2.CAP_PROP_FPS) or 0.0)
        self.fps = fps if fps > 0 else 30.0
        frames = float(self._capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
        self.duration = frames / self.fps if frames > 0 else 0.0

        self._frame: Optional[np.ndarray] = None
        self._frame_time = 0.0
        self._lock = threading.Lock()
        self._wanted = 0.0
        self._exhausted = False
        self._running = True
        self._touched = time.monotonic()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    # --- the public face -------------------------------------------------

    def frame_at(self, show_time: float) -> Frame:
        """The frame this clip should be showing at `show_time`."""
        with self._lock:
            self._wanted = self._clip_time(show_time)
            self._touched = time.monotonic()
            frame = self._frame
        if frame is None:
            return EMPTY
        height, width = frame.shape[:2]
        return frame, (width, height)

    def _clip_time(self, show_time: float) -> float:
        """Show time -> position inside this clip."""
        if self.live:
            return 0.0
        local = (show_time - self.playback.start) * self.playback.speed
        if local < 0.0:
            return 0.0
        if self.duration <= 0.0:
            return local
        if self.playback.loop:
            return local % self.duration
        # Past the end: hold the last frame rather than going black mid-show.
        return min(local, max(self.duration - 1.0 / self.fps, 0.0))

    def idle_for(self) -> float:
        with self._lock:
            return time.monotonic() - self._touched

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            # The capture is released by the decode thread's own finally: this
            # side must never close it while that one might be inside read().
            self._thread.join(timeout=5.0)
            self._thread = None

    # --- the decode thread -----------------------------------------------

    def _run(self) -> None:
        try:
            position = 0.0
            frame_time = 1.0 / self.fps
            while self._running:
                with self._lock:
                    wanted = self._wanted

                if self.live:
                    ok, frame = self._capture.read()
                    if ok and frame is not None:
                        self._publish(frame, 0.0)
                    else:
                        time.sleep(frame_time)
                    continue

                behind = wanted - position
                if behind < -frame_time or behind > SEEK_THRESHOLD_SECONDS:
                    # The show jumped - a seek, a loop wrap, or a stall long
                    # enough that reading forward would take longer than
                    # seeking. Anything smaller is caught up by decoding on.
                    self._capture.set(cv2.CAP_PROP_POS_MSEC, max(wanted, 0.0) * 1000.0)
                    position = wanted
                    behind = 0.0

                if behind < 0.0:
                    # Ahead of the show - paused, or playing slower than real
                    # time. Wait rather than burn a core decoding frames that
                    # will be thrown away.
                    time.sleep(min(-behind, 0.05))
                    continue

                ok, frame = self._capture.read()
                if not ok or frame is None:
                    if self.playback.loop or self.duration <= 0.0:
                        self._capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        position = 0.0
                        ok, frame = self._capture.read()
                        if not ok or frame is None:
                            time.sleep(0.05)
                            continue
                    else:
                        # Out of frames and not looping: the last published
                        # frame stays up, and the thread stops spinning.
                        time.sleep(0.05)
                        continue

                position += frame_time
                self._publish(frame, position)
        except Exception as exc:  # pragma: no cover - decoder / driver specific
            logger.warning("Decoding %s stopped: %s", self.path, exc)
        finally:
            if self._capture is not None:
                self._capture.release()

    def _publish(self, frame: np.ndarray, position: float) -> None:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        with self._lock:
            self._frame = rgb
            self._frame_time = position


class ClipPool:
    """Every open decoder in the app, keyed by what it is playing.

    One pool per process, reached through `clip_pool()`. The editor, the
    output preview and every projection window ask the same pool, so a clip is
    decoded once no matter how many things are looking at it.
    """

    def __init__(self) -> None:
        self._clips: Dict[Tuple, Clip] = {}
        self._failed: Dict[Tuple, float] = {}
        self._lock = threading.Lock()

    def frame(self, media: MediaRef, show_time: float) -> Frame:
        """The frame `media` should be showing, opening a decoder if needed."""
        key = clip_key(media)
        if key is None:
            return EMPTY
        clip = self._clip_for(key, media)
        if clip is None:
            return EMPTY
        return clip.frame_at(show_time)

    def size_of(self, media: MediaRef) -> Tuple[int, int]:
        _frame, size = self.frame(media, 0.0)
        return size

    def _clip_for(self, key: Tuple, media: MediaRef) -> Optional[Clip]:
        with self._lock:
            clip = self._clips.get(key)
            if clip is not None:
                return clip
            # A file that cannot be opened must not be retried sixty times a
            # second; the log would drown and so would the frame rate.
            failed_at = self._failed.get(key)
            if failed_at is not None and time.monotonic() - failed_at < 2.0:
                return None
        try:
            clip = Clip(media.path, media.playback, live=media.is_live)
        except Exception as exc:
            logger.warning("Could not open %s: %s", media.path, exc)
            with self._lock:
                self._failed[key] = time.monotonic()
            return None
        with self._lock:
            existing = self._clips.get(key)
            if existing is not None:
                # Another thread got there first while this one was opening.
                clip.stop()
                return existing
            self._clips[key] = clip
            self._failed.pop(key, None)
            return clip

    def reap_idle(self, timeout: float = IDLE_TIMEOUT_SECONDS) -> int:
        """Close decoders nobody has asked about. Returns how many went."""
        with self._lock:
            stale = [key for key, clip in self._clips.items() if clip.idle_for() > timeout]
            clips = [self._clips.pop(key) for key in stale]
        for clip in clips:
            clip.stop()
        return len(clips)

    def stop_all(self) -> None:
        with self._lock:
            clips = list(self._clips.values())
            self._clips.clear()
            self._failed.clear()
        for clip in clips:
            clip.stop()

    def __len__(self) -> int:
        with self._lock:
            return len(self._clips)


_POOL: Optional[ClipPool] = None


def clip_pool() -> ClipPool:
    global _POOL
    if _POOL is None:
        _POOL = ClipPool()
    return _POOL


def reset_clip_pool() -> None:
    """Drop every decoder. For shutdown, and for tests."""
    global _POOL
    if _POOL is not None:
        _POOL.stop_all()
    _POOL = None

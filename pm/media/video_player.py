from __future__ import annotations

import threading
import time
from typing import Optional, Tuple

import cv2
import numpy as np


class VideoPlayer:
    def __init__(self, path: str) -> None:
        self.path = path
        self.cap = cv2.VideoCapture(path)
        if not self.cap.isOpened():
            raise IOError(f"Não foi possível abrir o vídeo: {path}")
        self.fps = float(self.cap.get(cv2.CAP_PROP_FPS) or 30.0)
        if self.fps <= 0:
            self.fps = 30.0
        self._frame: Optional[np.ndarray] = None
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            # No release here: the capture is closed by the decode thread's
            # own finally. Releasing from this side while that thread sat
            # inside cap.read() was a use-after-free waiting to happen, and a
            # 1s join is exactly long enough for a slow seek to lose the race.
            # The timeout only stops a wedged decoder from hanging shutdown -
            # the thread still releases whenever it does come back.
            self._thread.join(timeout=5.0)
            self._thread = None

    def _run(self) -> None:
        frame_delay = 1.0 / self.fps
        try:
            # Aim at a wall-clock deadline instead of sleeping a full frame
            # after each decode. Sleeping the whole interval on top of decode
            # time meant a 30fps clip actually played slower than 30fps, and
            # drifted further behind the longer it ran.
            next_at = time.perf_counter()
            while self._running:
                ok, frame = self.cap.read()
                if not ok:
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ok, frame = self.cap.read()
                if ok and frame is not None:
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    with self._lock:
                        self._frame = frame

                next_at += frame_delay
                remaining = next_at - time.perf_counter()
                if remaining > 0:
                    time.sleep(remaining)
                else:
                    # Decoding fell behind; give up the lost time rather than
                    # racing to catch up on every subsequent frame.
                    next_at = time.perf_counter()
        finally:
            if self.cap:
                self.cap.release()

    def get_frame(self) -> Tuple[Optional[np.ndarray], Tuple[int, int]]:
        with self._lock:
            frame = None if self._frame is None else self._frame.copy()
        if frame is None:
            return None, (0, 0)
        height, width, _ = frame.shape
        return frame, (width, height)

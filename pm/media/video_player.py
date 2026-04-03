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
            self._thread.join(timeout=1.0)
            self._thread = None
        if self.cap:
            self.cap.release()

    def _run(self) -> None:
        frame_delay = 1.0 / self.fps
        while self._running:
            ok, frame = self.cap.read()
            if not ok:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = self.cap.read()
            if ok and frame is not None:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                with self._lock:
                    self._frame = frame
            time.sleep(frame_delay)

    def get_frame(self) -> Tuple[Optional[np.ndarray], Tuple[int, int]]:
        with self._lock:
            frame = None if self._frame is None else self._frame.copy()
        if frame is None:
            return None, (0, 0)
        height, width, _ = frame.shape
        return frame, (width, height)

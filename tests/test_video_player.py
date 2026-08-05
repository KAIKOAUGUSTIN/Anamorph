import time

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from pm.media.video_player import VideoPlayer

FPS = 30.0
FRAMES = 90  # three seconds of source, so looping is not in play
SIZE = (64, 48)


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("video") / "clip.mp4")
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), FPS, SIZE)
    if not writer.isOpened():
        pytest.skip("no mp4 encoder available in this build of OpenCV")
    for i in range(FRAMES):
        frame = np.full((SIZE[1], SIZE[0], 3), i * 2 % 256, dtype=np.uint8)
        writer.write(frame)
    writer.release()
    return path


def test_player_produces_frames(clip):
    player = VideoPlayer(clip)
    player.start()
    try:
        deadline = time.perf_counter() + 2.0
        frame, size = None, (0, 0)
        while frame is None and time.perf_counter() < deadline:
            frame, size = player.get_frame()
            time.sleep(0.01)
        assert frame is not None, "decoder never produced a frame"
        assert size == SIZE
    finally:
        player.stop()


class _SlowCapture:
    """A VideoCapture that costs a known amount of time to read from.

    cv2.VideoCapture attributes are read-only, so the capture is wrapped
    rather than patched.
    """

    def __init__(self, capture, delay):
        self._capture = capture
        self._delay = delay

    def read(self):
        time.sleep(self._delay)
        return self._capture.read()

    def set(self, *args):
        return self._capture.set(*args)

    def release(self):
        return self._capture.release()

    def isOpened(self):
        return self._capture.isOpened()


def _count_frames_per_second(player, window=1.0):
    """Distinct frames observed over `window`, sampling faster than playback."""
    time.sleep(0.3)  # let the loop settle
    seen = set()
    started = time.perf_counter()
    while time.perf_counter() - started < window:
        frame, _ = player.get_frame()
        if frame is not None:
            seen.add(int(frame[0, 0, 0]))
        time.sleep(1.0 / 480.0)
    return len(seen)


def test_playback_absorbs_decode_time_instead_of_adding_to_it(clip):
    """The pacing fix, isolated.

    Sleeping a full frame interval *after* decoding meant the real period was
    decode + interval, so playback ran slower than the source and drifted
    further behind the longer it went. A 64x48 test clip decodes too fast for
    that to show, so decode cost is injected: 20ms of work inside a 33ms
    budget must still yield ~30fps, not ~19fps.
    """
    player = VideoPlayer(clip)
    player.cap = _SlowCapture(player.cap, 0.020)
    player.start()
    try:
        rate = _count_frames_per_second(player)
    finally:
        player.stop()

    # Old behaviour lands near 1 / (0.020 + 0.0333) = 19fps.
    assert rate >= 25, f"only {rate} frames in a second with a 20ms decode"


def test_playback_matches_the_source_rate(clip):
    player = VideoPlayer(clip)
    player.start()
    try:
        rate = _count_frames_per_second(player)
    finally:
        player.stop()

    assert 24 <= rate <= 36, f"{rate}fps for a {FPS:.0f}fps clip"


def test_stop_is_safe_while_decoding(clip):
    """stop() used to release the capture from the caller's thread while the
    decoder could still be inside cap.read()."""
    for _ in range(5):
        player = VideoPlayer(clip)
        player.start()
        time.sleep(0.02)
        player.stop()
        assert player._thread is None


def test_stop_is_idempotent(clip):
    player = VideoPlayer(clip)
    player.start()
    player.stop()
    player.stop()


def test_missing_file_raises_rather_than_silently_doing_nothing():
    with pytest.raises(IOError):
        VideoPlayer("/no/such/clip.mp4")

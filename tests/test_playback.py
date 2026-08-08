# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Media that plays, on a clock the whole show shares.

Before this a clip started free-running the moment it was loaded and never
stopped: no pause, no seek, no rate, and two surfaces on the same file drifted
apart by however long apart they were opened, with no way to bring them back.
"""

import os
import time

import numpy as np
import pytest

from media.clip_pool import Clip, ClipPool, clip_key, reset_clip_pool
from model.media import MediaRef, Playback
from model.project import Project
from model.shapes import polygon_from_points, shape_from_dict, shape_to_dict
from model.transport import MAX_SPEED, MIN_SPEED, Transport

QUAD = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]


@pytest.fixture
def clip_file(tmp_path):
    """A real 3-second clip, because a fake one proves nothing about seeking."""
    import cv2

    path = str(tmp_path / "clip.mp4")
    fps, width, height = 20, 64, 48
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    if not writer.isOpened():
        pytest.skip("no mp4 encoder in this OpenCV build")
    for index in range(fps * 3):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        # Brightness ramps with time, so a frame's value says when it is from.
        frame[:, :] = (index * 4) % 256
        writer.write(frame)
    writer.release()
    return path


@pytest.fixture(autouse=True)
def _clean_pool():
    reset_clip_pool()
    yield
    reset_clip_pool()


# --- the show clock ---------------------------------------------------------

def test_a_new_transport_is_running_from_zero():
    transport = Transport()
    assert transport.playing
    assert transport.position() < 0.1


def test_pausing_freezes_the_playhead():
    transport = Transport()
    time.sleep(0.05)
    transport.pause()
    held = transport.position()
    time.sleep(0.05)

    assert transport.position() == held


def test_resuming_carries_on_from_where_it_stopped():
    """Not from where it would have been had it never stopped."""
    transport = Transport()
    time.sleep(0.05)
    transport.pause()
    held = transport.position()
    time.sleep(0.2)
    transport.play()

    assert transport.position() == pytest.approx(held, abs=0.05)


def test_seeking_moves_the_playhead():
    transport = Transport()
    transport.seek(42.0)
    assert transport.position() == pytest.approx(42.0, abs=0.05)


def test_seeking_before_zero_is_clamped():
    transport = Transport()
    transport.seek(-10.0)
    assert transport.position() >= 0.0


def test_restart_goes_back_to_the_top():
    transport = Transport()
    transport.seek(30.0)
    transport.restart()
    assert transport.position() < 0.1


def test_changing_speed_does_not_jump_the_playhead():
    """Re-anchoring first is the trick: without it the elapsed wall time is
    suddenly reinterpreted at the new rate and the show lurches."""
    transport = Transport()
    time.sleep(0.1)
    before = transport.position()

    transport.set_speed(4.0)

    assert transport.position() == pytest.approx(before, abs=0.05)


def test_speed_actually_scales_time():
    fast = Transport(speed=4.0)
    slow = Transport(speed=0.25)
    time.sleep(0.1)

    assert fast.position() > slow.position() * 4


def test_speed_is_clamped_to_what_a_decoder_can_follow():
    transport = Transport()
    transport.set_speed(1000.0)
    assert transport.speed == MAX_SPEED
    transport.set_speed(0.0)
    assert transport.speed == MIN_SPEED


def test_toggle_flips_the_state():
    transport = Transport()
    transport.toggle()
    assert not transport.playing
    transport.toggle()
    assert transport.playing


def test_the_transport_survives_a_round_trip():
    transport = Transport(playing=False, speed=0.5)
    restored = Transport.from_dict(transport.to_dict())
    assert restored.playing is False and restored.speed == 0.5


def test_position_is_not_saved():
    """A show opens at the top, not wherever it was left yesterday."""
    transport = Transport()
    transport.seek(90.0)
    assert "position" not in transport.to_dict()
    assert Transport.from_dict(transport.to_dict()).position() < 0.1


def test_a_project_carries_a_transport():
    project = Project()
    project.transport.set_speed(2.0)

    restored = Project.from_dict(project.to_dict())

    assert restored.transport.speed == 2.0


# --- playback settings ------------------------------------------------------

def test_playback_defaults_to_a_looping_clip_at_normal_speed():
    playback = Playback()
    assert playback.loop and playback.speed == 1.0 and playback.start == 0.0
    assert playback.hold_last, "going black when a clip ends is a failure the audience sees"
    assert playback.is_default()


def test_default_playback_writes_nothing_to_the_file():
    media = MediaRef(kind="video", path="/tmp/x.mp4")
    assert "playback" not in media.to_dict()


def test_playback_survives_a_round_trip():
    media = MediaRef(kind="video", path="/tmp/x.mp4")
    media.playback = Playback(loop=False, speed=0.5, start=-2.0, hold_last=False)

    restored = MediaRef.from_dict(media.to_dict())

    assert restored.playback == media.playback


def test_a_file_from_before_playback_existed_loads_with_defaults():
    restored = MediaRef.from_dict({"kind": "video", "path": "/tmp/x.mp4"})
    assert restored.playback.is_default()


def test_playback_travels_with_a_duplicated_surface():
    from model.commands import duplicate_shape

    shape = polygon_from_points(list(QUAD))
    shape.media.kind = "video"
    shape.media.playback.speed = 0.5

    assert duplicate_shape(shape).media.playback.speed == 0.5


def test_only_video_answers_to_the_clock():
    assert MediaRef(kind="video").is_timed
    assert not MediaRef(kind="image").is_timed
    assert not MediaRef(kind="camera").is_timed
    assert MediaRef(kind="camera").is_live


# --- sharing, which is what synchronisation means here ----------------------

def test_two_surfaces_with_the_same_settings_share_a_decoder():
    """That sharing *is* the synchronisation: one decoder cannot drift from
    itself."""
    first = MediaRef(kind="video", path="/tmp/x.mp4")
    second = MediaRef(kind="video", path="/tmp/x.mp4")

    assert clip_key(first) == clip_key(second)


def test_different_speeds_get_their_own_decoder():
    first = MediaRef(kind="video", path="/tmp/x.mp4")
    second = MediaRef(kind="video", path="/tmp/x.mp4")
    second.playback.speed = 0.5

    assert clip_key(first) != clip_key(second)


def test_a_typed_speed_still_matches():
    """Rounding is what makes sharing actually happen between two spin boxes."""
    first = MediaRef(kind="video", path="/tmp/x.mp4")
    second = MediaRef(kind="video", path="/tmp/x.mp4")
    second.playback.speed = 1.0 + 1e-12

    assert clip_key(first) == clip_key(second)


def test_a_still_has_no_decoder_key():
    assert clip_key(MediaRef(kind="image", path="/tmp/x.png")) is None
    assert clip_key(MediaRef()) is None


def test_a_camera_is_keyed_on_its_device():
    assert clip_key(MediaRef(kind="camera", path="0")) == ("camera", "0")


# --- the decoder ------------------------------------------------------------

def test_a_clip_reports_its_length_and_rate(clip_file):
    clip = Clip(clip_file, Playback())
    try:
        assert clip.fps == pytest.approx(20.0, abs=1.0)
        assert clip.duration == pytest.approx(3.0, abs=0.3)
    finally:
        clip.stop()


def test_a_missing_file_raises_rather_than_silently_doing_nothing():
    with pytest.raises(IOError):
        Clip("/nonexistent/clip.mp4", Playback())


def test_show_time_maps_into_the_clip(clip_file):
    clip = Clip(clip_file, Playback())
    try:
        assert clip._clip_time(0.0) == pytest.approx(0.0)
        assert clip._clip_time(1.5) == pytest.approx(1.5, abs=0.01)
    finally:
        clip.stop()


def test_a_looping_clip_wraps_around(clip_file):
    clip = Clip(clip_file, Playback(loop=True))
    try:
        # Four seconds into a three second clip is one second in.
        assert clip._clip_time(4.0) == pytest.approx(1.0, abs=0.2)
    finally:
        clip.stop()


def test_a_one_shot_clip_holds_its_last_frame(clip_file):
    clip = Clip(clip_file, Playback(loop=False))
    try:
        held = clip._clip_time(30.0)
        assert held == pytest.approx(clip.duration, abs=0.1)
        assert held <= clip.duration
    finally:
        clip.stop()


def test_an_offset_delays_or_skips_into_the_clip(clip_file):
    delayed = Clip(clip_file, Playback(start=2.0))
    try:
        assert delayed._clip_time(0.0) == 0.0, "not started yet at show zero"
        assert delayed._clip_time(3.0) == pytest.approx(1.0, abs=0.01)
    finally:
        delayed.stop()


def test_clip_speed_scales_its_own_timeline(clip_file):
    clip = Clip(clip_file, Playback(speed=2.0))
    try:
        assert clip._clip_time(1.0) == pytest.approx(2.0, abs=0.01)
    finally:
        clip.stop()


def test_a_clip_actually_produces_frames(clip_file):
    clip = Clip(clip_file, Playback())
    try:
        deadline = time.monotonic() + 5.0
        frame, size = None, (0, 0)
        while time.monotonic() < deadline and frame is None:
            frame, size = clip.frame_at(0.5)
            if frame is None:
                time.sleep(0.02)
        assert frame is not None, "no frame decoded in five seconds"
        assert size == (64, 48)
        assert frame.shape == (48, 64, 3)
    finally:
        clip.stop()


def test_a_paused_show_stops_advancing_the_clip(clip_file):
    """The decoder waits rather than burning a core on frames nobody wants."""
    clip = Clip(clip_file, Playback())
    try:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and clip.frame_at(0.2)[0] is None:
            time.sleep(0.02)
        first = clip.frame_at(0.2)[0]
        time.sleep(0.3)
        second = clip.frame_at(0.2)[0]

        assert first is not None and second is not None
        assert np.array_equal(first, second), "a held show time held the frame"
    finally:
        clip.stop()


# --- the pool ---------------------------------------------------------------

def test_the_pool_opens_one_decoder_per_key(clip_file):
    pool = ClipPool()
    try:
        first = MediaRef(kind="video", path=clip_file)
        second = MediaRef(kind="video", path=clip_file)
        pool.frame(first, 0.0)
        pool.frame(second, 0.0)

        assert len(pool) == 1, "two surfaces on one clip share a decoder"

        second.playback.speed = 0.5
        pool.frame(second, 0.0)
        assert len(pool) == 2, "different settings cannot share"
    finally:
        pool.stop_all()


def test_the_pool_gives_nothing_for_a_still():
    pool = ClipPool()
    frame, size = pool.frame(MediaRef(kind="image", path="/tmp/x.png"), 0.0)
    assert frame is None and size == (0, 0)


def test_an_unopenable_file_is_not_retried_sixty_times_a_second():
    pool = ClipPool()
    media = MediaRef(kind="video", path="/nonexistent/clip.mp4")

    for _ in range(5):
        assert pool.frame(media, 0.0)[0] is None

    assert len(pool) == 0


def test_idle_decoders_are_reaped(clip_file):
    pool = ClipPool()
    try:
        pool.frame(MediaRef(kind="video", path=clip_file), 0.0)
        assert len(pool) == 1

        assert pool.reap_idle(timeout=0.0) == 1
        assert len(pool) == 0
    finally:
        pool.stop_all()


class _ClipIdleFor:
    """A stand-in whose idle time is exact.

    The real `Clip` reads `time.monotonic()`, and that clock's resolution is
    the whole problem: nanoseconds on Linux and macOS, ~15ms on Windows. A
    test built on real elapsed time cannot state where the boundary is, which
    is why the off-by-one in `reap_idle` survived until a Windows runner
    happened to look. This one names the idle time instead of racing for it.
    """

    def __init__(self, idle: float) -> None:
        self._idle = idle
        self.stopped = False

    def idle_for(self) -> float:
        return self._idle

    def stop(self) -> None:
        self.stopped = True


def test_a_clip_idle_for_exactly_the_timeout_is_reaped():
    """`>` here means a decoder is kept on a coarse clock and dropped on a
    fine one - the same call behaving differently per platform."""
    pool = ClipPool()
    clip = _ClipIdleFor(5.0)
    pool._clips[("exactly-at-the-boundary",)] = clip

    assert pool.reap_idle(timeout=5.0) == 1
    assert clip.stopped and len(pool) == 0


def test_a_clip_idle_for_less_than_the_timeout_stays():
    pool = ClipPool()
    clip = _ClipIdleFor(4.999)
    pool._clips[("still-warm",)] = clip

    assert pool.reap_idle(timeout=5.0) == 0
    assert not clip.stopped and len(pool) == 1


def test_a_clip_still_being_watched_is_not_reaped(clip_file):
    pool = ClipPool()
    try:
        media = MediaRef(kind="video", path=clip_file)
        pool.frame(media, 0.0)

        assert pool.reap_idle(timeout=30.0) == 0
        assert len(pool) == 1
    finally:
        pool.stop_all()


def test_stopping_the_pool_closes_everything(clip_file):
    pool = ClipPool()
    pool.frame(MediaRef(kind="video", path=clip_file), 0.0)

    pool.stop_all()

    assert len(pool) == 0


# --- blend modes ------------------------------------------------------------

def test_every_blend_mode_maps_to_a_gl_pair():
    from render.gl_renderer import GLRenderer

    for mode in ("normal", "add", "screen", "multiply"):
        assert mode in GLRenderer.BLEND_MODES


def test_an_unknown_blend_mode_falls_back_to_normal():
    from render.gl_renderer import GLRenderer

    assert GLRenderer.BLEND_MODES.get("nonsense", GLRenderer.BLEND_MODES["normal"]) == (
        GLRenderer.BLEND_MODES["normal"]
    )


def test_blend_mode_round_trips_through_the_file():
    shape = polygon_from_points(list(QUAD))
    shape.blend_mode = "add"
    assert shape_from_dict(shape_to_dict(shape)).blend_mode == "add"


# --- the UI -----------------------------------------------------------------

@pytest.fixture
def panel(qapp):
    from ui.property_panel import PropertyPanel

    project = Project()
    shape = polygon_from_points(list(QUAD), name="wall")
    shape.media.kind = "video"
    shape.media.path = "/tmp/x.mp4"
    project.add_shape(shape)
    from PySide6.QtGui import QUndoStack

    widget = PropertyPanel()
    stack = QUndoStack()
    widget.set_undo_context(project, stack)
    widget.set_shape(shape)
    return widget, project, stack


def test_the_playback_section_is_only_there_for_clips(panel):
    widget, project, _stack = panel
    assert widget.playback_group.isVisibleTo(widget)

    still = polygon_from_points(list(QUAD))
    still.media.kind = "image"
    widget.set_shape(still)

    assert not widget.playback_group.isVisibleTo(widget)


def test_turning_looping_off_reaches_the_model(panel):
    widget, project, _stack = panel

    widget.loop_check.setChecked(False)

    assert project.shapes[0].media.playback.loop is False


def test_a_clip_speed_is_undoable(panel):
    widget, project, stack = panel

    widget.clip_speed.setValue(0.5)
    assert project.shapes[0].media.playback.speed == 0.5

    stack.undo()
    assert project.shapes[0].media.playback.speed == 1.0


def test_the_blend_combo_reaches_the_model(panel):
    widget, project, _stack = panel

    widget.blend_mode.setCurrentIndex(widget.blend_mode.findData("add"))

    assert project.shapes[0].blend_mode == "add"


def test_the_transport_bar_drives_the_project(qapp):
    from ui.transport_bar import TransportBar, format_time

    project = Project()
    bar = TransportBar(project)
    try:
        assert bar.play_button.text() == "Pause"

        bar.toggle()
        assert project.transport.playing is False
        assert bar.play_button.text() == "Play"

        project.transport.seek(65.0)
        bar._refresh_readout()
        assert bar.position_label.text() == format_time(65.0)

        bar.speed_box.setValue(2.0)
        assert project.transport.speed == 2.0

        bar.restart()
        assert project.transport.position() < 0.1
    finally:
        bar.close()


def test_the_clock_reads_like_a_clock():
    from ui.transport_bar import format_time

    assert format_time(0.0) == "0:00.0"
    assert format_time(65.4) == "1:05.4"
    assert format_time(-3.0) == "0:00.0"


def test_space_toggles_the_show(qapp):
    from ui.main_window import MainWindow

    win = MainWindow()
    try:
        assert win.project.transport.playing
        win.action_play_pause.trigger()
        assert not win.project.transport.playing
    finally:
        win.project.mark_saved()
        win.close()


def test_the_canvas_only_ticks_for_moving_media(qapp):
    from ui.canvas_editor import CanvasEditor

    project = Project()
    still = polygon_from_points(list(QUAD))
    still.media.kind = "image"
    project.add_shape(still)
    canvas = CanvasEditor(project)

    # Nothing here moves, so a repaint would be pure waste.
    assert not any(
        s.media.is_timed or s.media.is_live for s in project.shapes if s.visible
    )

    clip = polygon_from_points(list(QUAD))
    clip.media.kind = "video"
    project.add_shape(clip)

    assert any(s.media.is_timed for s in project.shapes if s.visible)
    canvas.close()


def test_the_canvas_hands_its_items_the_show_clock(qapp):
    from ui.canvas_editor import CanvasEditor

    project = Project()
    shape = polygon_from_points(list(QUAD))
    project.add_shape(shape)
    canvas = CanvasEditor(project)
    try:
        item = canvas.items_by_id[shape.id]
        assert item.transport is project.transport
    finally:
        canvas.close()

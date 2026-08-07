# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest
from PySide6.QtGui import QUndoStack

from fileio.project_io import load_project, save_project
from model.media import MediaRef, SourceRect
from model.project import Project
from model.shapes import polygon_from_points, shape_from_dict, shape_to_dict

QUAD = [(0.0, 0.0), (200.0, 0.0), (200.0, 100.0), (0.0, 100.0)]


# --- the value type -------------------------------------------------------

def test_default_is_the_whole_frame():
    region = SourceRect()
    assert (region.u0, region.v0, region.u1, region.v1) == (0.0, 0.0, 1.0, 1.0)
    assert region.is_full_frame()
    assert region.width == 1.0 and region.height == 1.0


def test_dragging_past_a_corner_reorders_rather_than_inverting():
    region = SourceRect(0.8, 0.9, 0.2, 0.1).normalised()
    assert region.u0 < region.u1 and region.v0 < region.v1
    assert (region.u0, region.u1) == (0.2, 0.8)


def test_region_is_clamped_into_the_unit_square():
    region = SourceRect(-3.0, -1.0, 5.0, 2.0).normalised()
    assert (region.u0, region.v0, region.u1, region.v1) == (0.0, 0.0, 1.0, 1.0)


def test_a_collapsed_region_keeps_some_area():
    """Zero area would make the whole surface sample a single pixel."""
    region = SourceRect(0.5, 0.5, 0.5, 0.5).normalised()
    assert region.width >= SourceRect.MIN_SIZE
    assert region.height >= SourceRect.MIN_SIZE


def test_a_collapsed_region_at_the_far_edge_stays_inside():
    region = SourceRect(1.0, 1.0, 1.0, 1.0).normalised()
    assert region.u1 <= 1.0 and region.v1 <= 1.0
    assert region.width >= SourceRect.MIN_SIZE


# --- persistence ----------------------------------------------------------

def test_region_survives_a_save_load_round_trip(tmp_path):
    project = Project()
    shape = polygon_from_points(list(QUAD))
    shape.media.kind = "image"
    shape.media.path = "/tmp/x.png"
    shape.media.source_rect = SourceRect(0.25, 0.0, 0.75, 0.5)
    project.add_shape(shape)

    path = str(tmp_path / "p.pmap.json")
    save_project(project, path)
    reloaded = load_project(path)

    region = reloaded.shapes[0].media.source_rect
    assert (region.u0, region.v0, region.u1, region.v1) == (0.25, 0.0, 0.75, 0.5)


def test_projects_written_before_source_regions_still_load():
    """Absent field means the whole frame - old files must not break."""
    legacy = {
        "id": "abc",
        "type": "polygon",
        "name": "wall",
        "points": [{"x": x, "y": y} for x, y in QUAD],
        "edges": [],
        "media": {"kind": "image", "path": "/tmp/x.png", "fit_mode": "warp"},
    }
    shape = shape_from_dict(legacy)
    assert shape.media.source_rect.is_full_frame()


def test_region_round_trips_through_shape_serialisation():
    shape = polygon_from_points(list(QUAD))
    shape.media = MediaRef(kind="image", path="/tmp/x.png", source_rect=SourceRect(0.1, 0.2, 0.3, 0.4))

    restored = shape_from_dict(shape_to_dict(shape))

    r = restored.media.source_rect
    assert (r.u0, r.v0, r.u1, r.v1) == (0.1, 0.2, 0.3, 0.4)


def test_duplicating_a_shape_carries_the_region():
    from model.commands import duplicate_shape

    shape = polygon_from_points(list(QUAD))
    shape.media.kind = "image"
    shape.media.source_rect = SourceRect(0.5, 0.0, 1.0, 1.0)

    copy = duplicate_shape(shape)

    assert copy.media.source_rect.u0 == 0.5


# --- panel wiring ---------------------------------------------------------

@pytest.fixture
def panel(qapp):
    from ui.property_panel import PropertyPanel

    project = Project()
    widget = PropertyPanel()
    widget.set_undo_context(project, QUndoStack())
    return widget, project


def _with_media(panel):
    widget, project = panel
    shape = polygon_from_points(list(QUAD))
    shape.media.kind = "image"
    shape.media.path = "/tmp/x.png"
    project.add_shape(shape)
    widget.set_shape(shape)
    return widget, shape


def test_panel_shows_the_full_frame_by_default(panel):
    widget, _ = _with_media(panel)
    assert [s.value() for s in widget.source_spins] == [0.0, 0.0, 1.0, 1.0]


def test_typing_a_region_updates_the_shape(panel):
    widget, shape = _with_media(panel)

    widget.source_spins[0].setValue(0.5)

    assert shape.media.source_rect.u0 == pytest.approx(0.5)
    assert shape.media.source_rect.u1 == pytest.approx(1.0)


def test_typed_region_is_undoable(panel):
    widget, shape = _with_media(panel)
    stack = widget._session._stack

    widget.source_spins[0].setValue(0.5)
    stack.undo()

    assert widget._project.shapes[0].media.source_rect.is_full_frame()


def test_dragging_the_picker_commits_once_on_release(panel):
    widget, shape = _with_media(panel)
    stack = widget._session._stack

    # Live updates while the mouse is down...
    for u0 in (0.1, 0.2, 0.3):
        widget._on_source_region_preview(SourceRect(u0, 0.0, 1.0, 1.0))
    assert stack.count() == 0, "a drag in progress must not fill the undo stack"

    widget._on_source_region_committed(SourceRect(0.3, 0.0, 1.0, 1.0))
    assert stack.count() == 1
    assert shape.media.source_rect.u0 == pytest.approx(0.3)


def test_full_frame_button_restores_everything(panel):
    _widget, project = panel
    widget, _shape = _with_media(panel)
    widget.source_spins[0].setValue(0.4)

    widget._on_reset_source_region()

    # Read through the project: every commit swaps in a restored shape, so
    # the object the test started with is an orphan by now.
    assert project.shapes[0].media.source_rect.is_full_frame()


def test_the_picker_previews_video_too(panel):
    """It used to be images only, because previewing video meant a second
    decoder per surface. Decoders are shared now, so the region can be aimed
    by eye instead of typed blind."""
    widget, project = panel
    shape = polygon_from_points(list(QUAD))
    shape.media.kind = "video"
    shape.media.path = "/tmp/x.mp4"
    project.add_shape(shape)

    widget.set_shape(shape)

    assert widget.source_picker.isVisibleTo(widget)


def test_the_picker_is_hidden_with_no_media(panel):
    widget, project = panel
    shape = polygon_from_points(list(QUAD))
    project.add_shape(shape)

    widget.set_shape(shape)

    assert not widget.source_picker.isVisibleTo(widget)

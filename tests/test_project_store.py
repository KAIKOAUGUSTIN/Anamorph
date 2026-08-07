# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-or-later

import json

import pytest

from pm.model.output import Output
from pm.model.project import Project
from pm.model.project_store import LEGACY_WORKSPACE_DIR, PROJECT_FILENAME, ProjectStore
from pm.model.shapes import polygon_from_points

QUAD = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]


@pytest.fixture
def store(qapp, tmp_path):
    s = ProjectStore()
    s.set_base_path(str(tmp_path))
    return s


def _write_legacy(tmp_path, screen_id, shape_names):
    legacy = tmp_path / LEGACY_WORKSPACE_DIR
    legacy.mkdir(parents=True, exist_ok=True)
    project = Project()
    for name in shape_names:
        project.add_shape(polygon_from_points(list(QUAD), name=name))
    with open(legacy / f"{screen_id}.workspace.json", "w", encoding="utf-8") as handle:
        json.dump(project.to_dict(), handle)


def test_a_fresh_store_gives_a_project_with_one_output(store):
    project = store.load()
    assert project.shapes == []
    assert len(project.outputs) == 1


def test_the_session_round_trips(store, tmp_path):
    project = store.load()
    project.add_shape(polygon_from_points(list(QUAD), name="wall"))
    project.outputs[0].name = "House Left"
    store.save()

    reopened = ProjectStore()
    reopened.set_base_path(str(tmp_path))
    restored = reopened.load()

    assert [s.name for s in restored.shapes] == ["wall"]
    assert restored.outputs[0].name == "House Left"


def test_saving_clears_the_dirty_flag(store):
    project = store.load()
    project.add_shape(polygon_from_points(list(QUAD)))
    assert project.dirty

    store.save()
    assert not project.dirty


def test_a_corrupt_session_does_not_stop_the_app(store, tmp_path):
    (tmp_path / PROJECT_FILENAME).write_text("{ not json", encoding="utf-8")

    project = store.load()

    assert isinstance(project, Project)
    assert project.outputs


# --- migration --------------------------------------------------------------

def test_legacy_workspaces_fold_into_one_project(store, tmp_path):
    """Each screen used to own a whole separate project, which is exactly why
    two projectors could never share a canvas."""
    _write_legacy(tmp_path, "screen_0", ["a", "b", "c"])
    _write_legacy(tmp_path, "screen_1", ["x"])

    project = store.load()

    # The workspace that was actually worked on becomes the artwork.
    assert [s.name for s in project.shapes] == ["a", "b", "c"]
    # And every screen that had one becomes an output onto it.
    assert {o.screen_id for o in project.outputs} == {"screen_0", "screen_1"}


def test_migration_puts_the_richest_workspaces_screen_first(store, tmp_path):
    _write_legacy(tmp_path, "screen_0", ["only one"])
    _write_legacy(tmp_path, "screen_1", ["a", "b"])

    project = store.load()

    assert project.outputs[0].screen_id == "screen_1"


def test_migration_leaves_the_old_files_alone(store, tmp_path):
    """A mistaken merge has to be recoverable by hand."""
    _write_legacy(tmp_path, "screen_0", ["a"])

    store.load()

    assert (tmp_path / LEGACY_WORKSPACE_DIR / "screen_0.workspace.json").exists()


def test_a_saved_session_wins_over_legacy_workspaces(store, tmp_path):
    _write_legacy(tmp_path, "screen_0", ["legacy"])
    project = store.load()
    project.shapes = [polygon_from_points(list(QUAD), name="current")]
    store.save()

    reopened = ProjectStore()
    reopened.set_base_path(str(tmp_path))

    assert [s.name for s in reopened.load().shapes] == ["current"]


def test_a_migrated_project_is_dirty(store, tmp_path):
    """It only exists in memory until the user saves it."""
    _write_legacy(tmp_path, "screen_0", ["a"])

    project = store.load()

    assert project.dirty
    assert project.path is None


def test_unreadable_legacy_files_are_skipped(store, tmp_path):
    legacy = tmp_path / LEGACY_WORKSPACE_DIR
    legacy.mkdir(parents=True)
    (legacy / "broken.workspace.json").write_text("nonsense", encoding="utf-8")
    _write_legacy(tmp_path, "screen_1", ["good"])

    project = store.load()

    assert [s.name for s in project.shapes] == ["good"]


def test_set_project_replaces_what_gets_saved(store, tmp_path):
    store.load()
    replacement = Project()
    replacement.name = "Opened"
    replacement.outputs = [Output(name="P1")]

    store.set_project(replacement)
    store.save()

    reopened = ProjectStore()
    reopened.set_base_path(str(tmp_path))
    assert reopened.load().name == "Opened"

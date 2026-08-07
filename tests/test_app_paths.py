# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The session copy surviving the app learning its own name.

Setting `setApplicationName`/`setOrganizationName` moves AppDataLocation, and
the session copy is the only place an hour of unsaved work exists. A rename
that quietly reset it would be a data loss the operator sees exactly once,
with no way to tell it happened.
"""

from pathlib import Path

import pytest
from PySide6.QtCore import QStandardPaths

import app_paths
from about import APP_NAME, ORGANIZATION
from model.project_store import PROJECT_FILENAME


@pytest.fixture
def legacy(tmp_path, monkeypatch):
    """A previous version's app data, with a session in it."""
    old = tmp_path / "python3.12" / app_paths.LEGACY_DIR_NAME
    old.mkdir(parents=True)
    (old / PROJECT_FILENAME).write_text('{"shapes": ["an hour of work"]}')
    monkeypatch.setattr(app_paths, "_legacy_app_data", str(old.parent))
    return old


def test_the_base_path_is_the_app_data_directory(qapp):
    base = Path(app_paths.workspace_base_path())

    assert base.is_dir()
    assert base == Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation))
    assert APP_NAME in str(base) or ORGANIZATION in str(base), (
        "the point of naming the app is that its data is findable by name"
    )


def test_a_previous_version_session_is_carried_across(qapp, legacy):
    base = Path(app_paths.workspace_base_path())

    carried = base / PROJECT_FILENAME
    assert carried.exists(), "the crash net was reset by a rename"
    assert "an hour of work" in carried.read_text()


def test_the_original_is_left_where_it_was(qapp, legacy):
    """Copy, not move: going back to an older build has to still work."""
    app_paths.workspace_base_path()

    assert (legacy / PROJECT_FILENAME).exists()


def test_current_work_is_never_overwritten(qapp, legacy):
    """The second run must not drag a stale session back over a newer one."""
    base = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation))
    base.mkdir(parents=True, exist_ok=True)
    (base / PROJECT_FILENAME).write_text('{"shapes": ["todays work"]}')

    app_paths.workspace_base_path()

    assert "todays work" in (base / PROJECT_FILENAME).read_text()


def test_nothing_happens_when_there_is_no_previous_version(qapp, monkeypatch):
    monkeypatch.setattr(app_paths, "_legacy_app_data", None)

    base = Path(app_paths.workspace_base_path())

    assert base.is_dir()
    assert not (base / PROJECT_FILENAME).exists()


def test_an_unreadable_legacy_folder_is_reported_not_fatal(qapp, legacy, monkeypatch):
    """Losing the previous session is bad; failing to start is worse."""
    import shutil

    from ui.problem_log import ProblemLog

    def refuse(*_args, **_kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(shutil, "copy2", refuse)

    log = ProblemLog()
    log.install()
    try:
        base = Path(app_paths.workspace_base_path())

        assert base.is_dir(), "startup has to survive it"
        assert any("Could not carry" in p.message for p in log.problems())
    finally:
        log.uninstall()


def test_the_window_uses_it(qapp):
    """The path logic lives in one place; the window must not have kept a
    second copy of it."""
    from ui.main_window import MainWindow

    win = MainWindow()
    try:
        assert win._get_workspace_base_path() == app_paths.workspace_base_path()
    finally:
        win.project.mark_saved()
        win.close()

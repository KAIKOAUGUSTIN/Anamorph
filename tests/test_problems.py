# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-only

"""Failures the operator can see.

Everything that was not fatal used to end at `logger.warning` - a codec the
build cannot open, a session that would not parse, a framebuffer the driver
refused. All of it went to a console nobody watches during a show.
"""

import logging

import pytest

from ui.problem_log import MAX_PROBLEMS, ProblemLog


@pytest.fixture
def log():
    log = ProblemLog()
    log.install("app.test")
    yield log
    log.uninstall("app.test")


# --- collection -------------------------------------------------------------

def test_a_warning_from_the_app_is_collected(log):
    logging.getLogger("app.test.decoder").warning("Could not open %s", "/x.mp4")

    assert log.count() == 1
    assert log.latest().message == "Could not open /x.mp4"
    assert log.latest().source == "app.test.decoder"


def test_an_error_is_marked_as_one(log):
    logging.getLogger("app.test").error("gone wrong")
    logging.getLogger("app.test").warning("less wrong")

    assert log.error_count() == 1
    assert log.count() == 2


def test_chatter_below_warning_is_ignored(log):
    logging.getLogger("app.test").info("just so you know")
    logging.getLogger("app.test").debug("noise")

    assert log.count() == 0


def test_a_new_problem_is_announced(log):
    seen = []
    log.problem_added.connect(seen.append)

    logging.getLogger("app.test").warning("something")

    assert len(seen) == 1 and seen[0].message == "something"


def test_the_list_is_capped(log):
    """A decoder failing every frame must not eat the machine."""
    for index in range(MAX_PROBLEMS + 50):
        log.add(logging.WARNING, "app.test", f"problem {index}")

    assert log.count() == MAX_PROBLEMS
    assert log.latest().message == f"problem {MAX_PROBLEMS + 49}"
    assert log.problems()[0].message == "problem 50", "the oldest go, not the newest"


def test_installing_twice_does_not_double_up(log):
    log.install("app.test")

    logging.getLogger("app.test").warning("once")

    assert log.count() == 1


def test_uninstalling_stops_the_collection(log):
    log.uninstall("app.test")

    logging.getLogger("app.test").warning("into the void")

    assert log.count() == 0


def test_a_broken_format_string_does_not_take_the_app_with_it(log):
    """Logging must never raise into whatever was being done at the time.

    Driven through the handler rather than through `logger.warning`, because
    pytest's own logging plugin formats the record too and would raise before
    this handler is reached - which says nothing about this handler.
    """
    record = logging.LogRecord(
        "app.test", logging.WARNING, __file__, 0, "%d items", ("not a number",), None
    )

    log._handler.emit(record)

    assert log.count() == 1
    assert "items" in log.latest().message


def test_clearing_empties_the_list(log):
    logging.getLogger("app.test").warning("something")
    log.clear()
    assert log.count() == 0 and log.latest() is None


def test_a_problem_reads_like_a_line_in_a_list(log):
    problem = log.add(logging.ERROR, "app.test", "the projector is on fire")

    line = problem.line()
    assert "the projector is on fire" in line
    assert line.startswith("✕"), "an error is not a warning"
    assert ":" in problem.clock()


# --- the real call sites reach it ------------------------------------------

def test_a_clip_that_will_not_open_shows_up(tmp_path):
    from media.clip_pool import ClipPool
    from model.media import MediaRef

    log = ProblemLog()
    log.install()
    try:
        ClipPool().frame(MediaRef(kind="video", path=str(tmp_path / "gone.mp4")), 0.0)

        assert log.count() >= 1
        assert "gone.mp4" in log.latest().message
    finally:
        log.uninstall()


def test_a_session_that_will_not_parse_shows_up(tmp_path, qapp):
    from model.project_store import ProjectStore

    log = ProblemLog()
    log.install()
    try:
        store = ProjectStore()
        store.set_base_path(str(tmp_path / "appdata"))
        store.save()
        store.session_path().write_text("{ not json")

        store.load()

        assert any("Could not read" in p.message for p in log.problems())
    finally:
        log.uninstall()


def test_a_backup_that_cannot_be_written_says_so(tmp_path, monkeypatch):
    """A read-only show folder is worth hearing about before the next save
    matters. Losing the safety net must not stop the save itself."""
    import shutil

    from fileio import project_io
    from model.project import Project

    path = tmp_path / "show.pmap.json"
    project_io.save_project(Project(), str(path))

    def refuse(*_args, **_kwargs):
        raise OSError("read-only file system")

    monkeypatch.setattr(shutil, "copy2", refuse)

    log = ProblemLog()
    log.install()
    try:
        project = Project()
        project.name = "saved anyway"
        project_io.save_project(project, str(path))

        assert any("Could not back up" in p.message for p in log.problems())
        assert project_io.load_project(str(path)).name == "saved anyway", (
            "the save still has to happen"
        )
    finally:
        log.uninstall()


# --- the window -------------------------------------------------------------

def test_the_window_collects_problems(qapp):
    from ui.main_window import MainWindow

    win = MainWindow()
    try:
        logging.getLogger("ui.somewhere").warning("a thing went wrong")

        assert win.problem_log.count() >= 1
        assert win.problems_button.isVisibleTo(win)
        assert "problem" in win.problems_button.text()
    finally:
        win.project.mark_saved()
        win.close()


def test_every_module_of_this_app_is_on_the_list(qapp):
    """`PACKAGES` decides whose warnings reach the operator, and a module
    missing from it fails silently - the failure is logged and nobody ever
    sees it. That is how `app_paths` was left off when it was written.
    """
    import subprocess
    from pathlib import Path

    from about import PACKAGES

    root = Path(__file__).resolve().parent.parent
    tracked = subprocess.run(
        ["git", "ls-files", "*.py"],
        cwd=root, capture_output=True, text=True, check=True,
    ).stdout.split()

    importable = set()
    for name in tracked:
        head, _, tail = name.partition("/")
        if head == "tests":
            continue
        if not tail:
            importable.add(head[:-len(".py")])
        elif (root / head / "__init__.py").exists():
            importable.add(head)

    missing = importable - set(PACKAGES)
    assert not missing, f"warnings from {sorted(missing)} would never be shown"


def test_a_dependency_talking_to_itself_is_not_the_operators_problem(qapp):
    """The log listens on the root logger now that the app's modules are
    top-level and share no ancestor. A colour-profile warning from a decoding
    library is not something anyone can act on during a show, and a list full
    of them is a list nobody reads."""
    from ui.main_window import MainWindow

    win = MainWindow()
    try:
        win.problem_log.clear()

        logging.getLogger("PIL.TiffImagePlugin").warning("unknown tag")
        logging.getLogger("some_dependency").error("internal state")

        assert win.problem_log.count() == 0

        logging.getLogger("render.gl_renderer").warning("this one is ours")
        assert win.problem_log.count() == 1
    finally:
        win.project.mark_saved()
        win.close()


def test_the_button_stays_hidden_when_nothing_is_wrong(qapp):
    from ui.main_window import MainWindow

    win = MainWindow()
    try:
        win.problem_log.clear()
        win._refresh_problems_button()

        assert not win.problems_button.isVisible()
    finally:
        win.project.mark_saved()
        win.close()


def test_the_dialog_lists_newest_first(qapp):
    from ui.problem_log import ProblemDialog

    log = ProblemLog()
    log.add(logging.WARNING, "app.test", "first")
    log.add(logging.ERROR, "app.test", "second")
    dialog = ProblemDialog(log)
    try:
        assert dialog.list.count() == 2
        assert "second" in dialog.list.item(0).text()
        assert "first" in dialog.list.item(1).text()
    finally:
        dialog.close()


def test_the_dialog_says_when_nothing_has_gone_wrong(qapp):
    from ui.problem_log import ProblemDialog

    dialog = ProblemDialog(ProblemLog())
    try:
        assert dialog.list.count() == 0
        assert not dialog.clear_button.isEnabled()
    finally:
        dialog.close()


def test_the_dialog_follows_new_problems(qapp):
    from ui.problem_log import ProblemDialog

    log = ProblemLog()
    dialog = ProblemDialog(log)
    try:
        log.add(logging.WARNING, "app.test", "just happened")
        assert dialog.list.count() == 1
    finally:
        dialog.close()


# --- the app agreeing with its own help sheet -------------------------------

def test_the_file_shortcuts_are_actually_bound(qapp):
    """The help sheet promised Ctrl+N/O/S; the actions had no keys behind them."""
    from PySide6.QtGui import QKeySequence
    from ui.main_window import MainWindow

    win = MainWindow()
    try:
        assert win.action_new.shortcut() == QKeySequence(QKeySequence.New)
        assert win.action_open.shortcut() == QKeySequence(QKeySequence.Open)
        assert win.action_save.shortcut() == QKeySequence(QKeySequence.Save)
        assert win.action_save_as.shortcut() == QKeySequence(QKeySequence.SaveAs)
    finally:
        win.project.mark_saved()
        win.close()


def test_every_shortcut_the_help_sheet_names_exists(qapp):
    """The sheet is the manual; a key on it that does nothing is worse than
    no sheet at all."""
    from PySide6.QtGui import QKeySequence
    from ui.help_dialog import SHORTCUTS
    from ui.main_window import MainWindow

    win = MainWindow()
    try:
        bound = {
            QKeySequence(action.shortcut()).toString().lower()
            for action in win.actions()
            if not action.shortcut().isEmpty()
        }
        promised = [
            keys for _section, entries in SHORTCUTS for keys, _meaning in entries
            if keys.replace(" ", "").lower().startswith(("ctrl+", "f1", "b", "space", "delete"))
            and " or " not in keys
            and "/" not in keys
            and "drag" not in keys.lower()
            and "click" not in keys.lower()
        ]
        for keys in promised:
            normalised = QKeySequence(keys.replace(" ", "")).toString().lower()
            assert normalised in bound, f"the sheet promises {keys!r} and nothing answers"
    finally:
        win.project.mark_saved()
        win.close()

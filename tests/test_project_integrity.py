import os
import tempfile

import pytest
from PySide6.QtWidgets import QMessageBox

from pm.io.project_io import load_project, save_project
from pm.model.project import Project
from pm.model.shapes import polygon_from_points

QUAD = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]


class _FakeDialog:
    """Stands in for the modal, so tests can answer it without a human."""

    def __init__(self, answer):
        self._answer = answer

    def exec(self):
        return self._answer


@pytest.fixture
def window(qapp):
    from pm.ui.main_window import MainWindow

    win = MainWindow()
    yield win
    win.project.mark_saved()  # so closing never blocks on the prompt
    win.close()


def _answer_with(monkeypatch, win, answer):
    """Make the next confirmation dialog return `answer`, and count the asks."""
    asked = []

    def fake(_title, _text, _icon, _buttons, _default):
        asked.append(True)
        return _FakeDialog(answer)

    monkeypatch.setattr(win, "_styled_message_box", fake)
    return asked


# --- discard confirmation -------------------------------------------------

def test_clean_project_is_not_questioned(window, monkeypatch):
    asked = _answer_with(monkeypatch, window, QMessageBox.Discard)
    window.project.mark_saved()

    assert window._confirm_discard("Quit anyway?") is True
    assert not asked, "a saved project has nothing to warn about"


def test_dirty_project_asks_and_cancel_stops_the_action(window, monkeypatch):
    asked = _answer_with(monkeypatch, window, QMessageBox.Cancel)
    window.project.touch()

    assert window._confirm_discard("Quit anyway?") is False
    assert asked


def test_discard_lets_the_action_through(window, monkeypatch):
    _answer_with(monkeypatch, window, QMessageBox.Discard)
    window.project.touch()

    assert window._confirm_discard("Quit anyway?") is True


def test_save_only_proceeds_if_the_save_actually_happened(window, monkeypatch):
    _answer_with(monkeypatch, window, QMessageBox.Save)
    window.project.touch()

    # A cancelled Save-As leaves the project dirty; carrying on would discard
    # exactly the work the user just tried to keep.
    monkeypatch.setattr(window, "_save_project", lambda *a, **k: None)
    assert window._confirm_discard("Quit anyway?") is False

    monkeypatch.setattr(window, "_save_project", lambda *a, **k: window.project.mark_saved())
    assert window._confirm_discard("Quit anyway?") is True


def test_new_project_respects_cancel(window, monkeypatch):
    _answer_with(monkeypatch, window, QMessageBox.Cancel)
    window.project.add_shape(polygon_from_points(list(QUAD), name="keep me"))
    before = window.project

    window._new_project()

    assert window.project is before
    assert [s.name for s in window.project.shapes] == ["keep me"]


def test_new_project_replaces_when_confirmed(window, monkeypatch):
    _answer_with(monkeypatch, window, QMessageBox.Discard)
    window.project.add_shape(polygon_from_points(list(QUAD)))

    window._new_project()

    assert window.project.shapes == []
    assert window.project.name == "Untitled"


# --- the workspace the manager actually holds -----------------------------

def test_adopting_a_project_hands_it_to_the_store(window):
    """Swapping the attribute alone let the shutdown save write the previous
    project back over the user's work."""
    adopted = Project()
    adopted.name = "Opened From Disk"

    window._adopt_project(adopted)

    assert window.store.project is adopted
    assert window.project is adopted


def test_opening_a_file_survives_a_shutdown_save(window, monkeypatch, tmp_path):
    on_disk = Project()
    on_disk.name = "From File"
    on_disk.add_shape(polygon_from_points(list(QUAD), name="wall"))
    path = str(tmp_path / "p.pmap.json")
    save_project(on_disk, path)

    monkeypatch.setattr(
        "pm.ui.main_window.QFileDialog.getOpenFileName",
        staticmethod(lambda *a, **k: (path, "")),
    )
    _answer_with(monkeypatch, window, QMessageBox.Discard)
    window._open_project()

    assert window.project.name == "From File"

    # What the shutdown path would persist.
    assert window.store.project is window.project


def test_an_opened_project_always_has_somewhere_to_project(window, monkeypatch, tmp_path):
    """A project with no output cannot show anything at all."""
    bare = Project()
    bare.outputs = []
    path = str(tmp_path / "bare.pmap.json")
    save_project(bare, path)

    monkeypatch.setattr(
        "pm.ui.main_window.QFileDialog.getOpenFileName",
        staticmethod(lambda *a, **k: (path, "")),
    )
    _answer_with(monkeypatch, window, QMessageBox.Discard)
    window._open_project()

    assert window.project.outputs


# --- undoable visibility --------------------------------------------------

def test_hiding_a_shape_is_undoable(window):
    shape = polygon_from_points(list(QUAD), name="wall")
    window.project.add_shape(shape)

    window._on_visibility_change(shape.id, False)
    assert window.project.get_shape(shape.id).visible is False

    window.undo_stack.undo()
    assert window.project.get_shape(shape.id).visible is True


def test_visibility_no_op_adds_nothing_to_the_stack(window):
    shape = polygon_from_points(list(QUAD))
    window.project.add_shape(shape)
    depth = window.undo_stack.count()

    window._on_visibility_change(shape.id, True)  # already visible

    assert window.undo_stack.count() == depth


# --- dirty tracking round trip --------------------------------------------

def test_saving_and_loading_clear_the_dirty_flag(tmp_path):
    project = Project()
    project.add_shape(polygon_from_points(list(QUAD)))
    assert project.dirty

    path = str(tmp_path / "p.pmap.json")
    save_project(project, path)
    assert not project.dirty

    reloaded = load_project(path)
    assert not reloaded.dirty

import pytest
from PySide6.QtGui import QImage, QUndoStack

from pm.render.test_pattern import (
    BORDERS,
    CHECKER,
    GRID,
    PATTERNS,
    available_patterns,
    render_test_pattern,
)


@pytest.mark.parametrize("kind", [GRID, CHECKER, BORDERS])
def test_pattern_fills_the_output_resolution(qapp, kind):
    image = render_test_pattern(800, 600, kind)
    assert (image.width(), image.height()) == (800, 600)
    assert not image.isNull()


@pytest.mark.parametrize("kind", [GRID, CHECKER, BORDERS])
def test_pattern_is_not_blank(qapp, kind):
    """A calibration pattern that renders black is worse than none at all."""
    image = render_test_pattern(400, 300, kind)
    lit = sum(
        1
        for x in range(0, 400, 4)
        for y in range(0, 300, 4)
        if image.pixelColor(x, y).getRgb()[:3] != (0, 0, 0)
    )
    assert lit > 100


@pytest.mark.parametrize("kind", [GRID, CHECKER, BORDERS])
def test_every_edge_is_marked(qapp, kind):
    """The 1px frame is how the operator confirms nothing is being cropped."""
    w, h = 320, 240
    image = render_test_pattern(w, h, kind)
    for point in ((w // 2, 0), (w // 2, h - 1), (0, h // 2), (w - 1, h // 2)):
        assert image.pixelColor(*point).getRgb()[:3] != (0, 0, 0), point


def test_unknown_pattern_falls_back_to_the_grid(qapp):
    fallback = render_test_pattern(200, 150, "no-such-pattern")
    grid = render_test_pattern(200, 150, GRID)
    assert fallback == grid


def test_degenerate_size_still_produces_an_image(qapp):
    image = render_test_pattern(0, -5, GRID)
    assert image.width() >= 1 and image.height() >= 1


def test_label_changes_the_output(qapp):
    """The screen name is what proves the output landed on the right display."""
    without = render_test_pattern(400, 300, GRID)
    with_label = render_test_pattern(400, 300, GRID, "HDMI-2")
    assert without != with_label


def test_available_patterns_matches_the_combo_entries():
    assert available_patterns() == [value for value, _ in PATTERNS]


def test_pattern_choice_is_persisted_on_the_project(qapp):
    from pm.io.project_io import load_project, save_project
    from pm.model.project import Project
    import tempfile
    import os

    project = Project()
    project.ui_state["test_mode"] = True
    project.ui_state["test_pattern"] = CHECKER

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "p.pmap.json")
        save_project(project, path)
        reloaded = load_project(path)

    assert reloaded.ui_state["test_mode"] is True
    assert reloaded.ui_state["test_pattern"] == CHECKER


def test_toolbar_enables_the_pattern_picker_with_test_mode(qapp):
    from pm.ui.main_window import MainWindow

    window = MainWindow()
    assert not window.pattern_combo.isEnabled()

    window.action_test_mode.setChecked(True)
    assert window.pattern_combo.isEnabled()
    assert window.project.ui_state["test_mode"] is True

    window.pattern_combo.setCurrentIndex(window.pattern_combo.findData(BORDERS))
    assert window.project.ui_state["test_pattern"] == BORDERS

    window.action_test_mode.setChecked(False)
    assert not window.pattern_combo.isEnabled()

    # Toggling test mode dirtied the project, and closing a dirty window now
    # asks before discarding - which would block forever with no one to click.
    window.project.mark_saved()
    window.close()

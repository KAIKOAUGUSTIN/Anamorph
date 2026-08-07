# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest
from PySide6.QtGui import QUndoStack

from pm.model.output import Output, split_outputs
from pm.model.project import Project


@pytest.fixture
def dialog(qapp):
    from pm.ui.output_panel import OutputDialog

    project = Project()
    project.outputs = [Output(name="Projector 1")]
    stack = QUndoStack()
    return OutputDialog(project, stack), project, stack


@pytest.fixture
def window(qapp):
    from pm.ui.main_window import MainWindow

    win = MainWindow()
    yield win
    win.project.mark_saved()
    win.close()


# --- the dialog -------------------------------------------------------------

def test_the_selected_output_loads_into_the_form(dialog):
    widget, project, _ = dialog
    project.outputs[0].blend.left = 0.2
    project.outputs[0].color.gain_r = 0.5
    widget.refresh()

    assert widget.name_edit.text() == "Projector 1"
    assert widget.blend_spins[0].value() == pytest.approx(0.2)
    assert widget.gain_spins[0].value() == pytest.approx(0.5)


def test_editing_a_field_reaches_the_model(dialog):
    widget, project, _ = dialog

    widget.blend_spins[1].setValue(0.3)

    assert project.outputs[0].blend.right == pytest.approx(0.3)


def test_an_edit_is_undoable(dialog):
    widget, project, stack = dialog

    widget.brightness.setValue(-0.4)
    assert project.outputs[0].color.brightness == pytest.approx(-0.4)

    stack.undo()
    assert project.outputs[0].color.brightness == pytest.approx(0.0)


def test_adding_and_removing_outputs_is_undoable(dialog):
    widget, project, stack = dialog

    widget._on_add()
    assert len(project.outputs) == 2

    widget._on_remove()
    assert len(project.outputs) == 1

    stack.undo()
    assert len(project.outputs) == 2
    stack.undo()
    assert len(project.outputs) == 1


def test_tiling_replaces_the_outputs_in_one_undo_step(dialog):
    widget, project, stack = dialog
    depth = stack.count()

    widget.tile_count.setValue(3)
    widget._on_tile()

    assert len(project.outputs) == 3
    assert stack.count() == depth + 1, "tiling is one act, not one per projector"

    stack.undo()
    assert len(project.outputs) == 1


def test_tiled_outputs_arrive_already_overlapping(dialog):
    widget, project, _ = dialog
    widget.tile_count.setValue(2)
    widget._on_tile()

    left, right = project.outputs
    assert left.region.u1 > right.region.u0
    assert left.blend.right > 0.0 and right.blend.left > 0.0


def test_a_reversed_region_is_straightened_out(dialog):
    """Typing U1 below U0 must not invert the projector's view."""
    widget, project, _ = dialog

    widget.region_spins[0].setValue(0.8)
    widget.region_spins[2].setValue(0.2)

    region = project.outputs[0].region
    assert region.u0 < region.u1


def test_resetting_the_keystone_returns_to_the_identity(dialog):
    widget, project, _ = dialog
    widget.corner_spins[0][0].setValue(0.25)
    assert project.outputs[0].has_keystone()

    widget._on_reset_keystone()

    assert not project.outputs[0].has_keystone()


def test_the_form_is_disabled_with_no_outputs(dialog):
    widget, project, stack = dialog
    widget._on_remove()

    assert project.outputs == []
    assert not widget.editor.isEnabled()


# --- the window -------------------------------------------------------------

def test_a_new_window_always_has_an_output(window):
    assert window.project.outputs


def test_the_toolbar_reports_how_many_outputs_are_live(window):
    window.project.outputs = split_outputs(3)
    window.project.outputs[2].enabled = False
    window._update_outputs_label()

    assert "2/3 outputs" in window.outputs_label.text()


def test_projecting_opens_one_window_per_enabled_output(window):
    from pm.model.project_store import available_screens

    screens = available_screens()
    if not screens:
        pytest.skip("no displays in this environment")

    window.project.outputs = split_outputs(2)
    for output in window.project.outputs:
        output.screen_id = screens[0][1]

    window._toggle_projection()
    try:
        assert len(window._projection_windows) == 2
    finally:
        window._toggle_projection()


def test_a_disabled_output_gets_no_window(window):
    from pm.model.project_store import available_screens

    screens = available_screens()
    if not screens:
        pytest.skip("no displays in this environment")

    window.project.outputs = split_outputs(2)
    for output in window.project.outputs:
        output.screen_id = screens[0][1]
    window.project.outputs[1].enabled = False

    window._toggle_projection()
    try:
        assert len(window._projection_windows) == 1
    finally:
        window._toggle_projection()


def test_an_output_with_no_screen_gets_no_window(window):
    window.project.outputs = [Output(name="unassigned", screen_id=None)]

    window._toggle_projection()
    try:
        assert window._projection_windows == {}
    finally:
        window._toggle_projection()


def test_disabling_an_output_closes_its_window(window):
    from pm.model.project_store import available_screens

    screens = available_screens()
    if not screens:
        pytest.skip("no displays in this environment")

    window.project.outputs = split_outputs(2)
    for output in window.project.outputs:
        output.screen_id = screens[0][1]
    window._toggle_projection()

    try:
        window.project.outputs[0].enabled = False
        window._sync_projection_windows()
        assert len(window._projection_windows) == 1
    finally:
        window._toggle_projection()

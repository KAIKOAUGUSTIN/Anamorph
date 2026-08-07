# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Things you need at five minutes to doors.

Blackout, knowing what the project cannot find, and being able to point it
somewhere else - none of which are about making a mapping look good, and all
of which decide whether the show happens.
"""

import pytest
from PySide6.QtGui import QUndoStack

from media.availability import forget, is_missing, media_exists, missing_paths, missing_shapes
from model.commands import CanvasSizeCommand, RelinkMediaCommand
from model.media import MediaRef
from model.project import Project
from model.shapes import circle_from_center, mesh_from_rect, polygon_from_points
from ui.relink_dialog import apply_relink, find_in_folder, relink_map

QUAD = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]


@pytest.fixture(autouse=True)
def _clean_availability_cache():
    forget()
    yield
    forget()


def _shape_with(path, kind="image", name="wall"):
    shape = polygon_from_points(list(QUAD), name=name)
    shape.media.kind = kind
    shape.media.path = str(path)
    return shape


# --- blackout ---------------------------------------------------------------

def test_a_project_starts_lit():
    assert Project().blackout is False


def test_blackout_is_not_saved():
    """A project that opens black sends the operator hunting for why nothing
    is on the wall. It is a live-operation state, like the playhead."""
    project = Project()
    project.set_blackout(True)

    assert "blackout" not in project.to_dict()
    assert Project.from_dict(project.to_dict()).blackout is False


def test_blackout_does_not_dirty_the_project():
    """Blacking out is not an edit to the show, and must not make the close
    prompt ask to save a state that is deliberately not saved."""
    project = Project()
    project.mark_saved()

    project.set_blackout(True)

    assert project.blackout is True
    assert project.dirty is False


def test_blackout_still_repaints():
    project = Project()
    seen = []
    project.changed.connect(lambda: seen.append(True))

    project.set_blackout(True)

    assert seen, "the projectors have to be told"


def test_setting_the_same_state_twice_is_a_no_op():
    project = Project()
    project.set_blackout(True)
    seen = []
    project.changed.connect(lambda: seen.append(True))

    project.set_blackout(True)

    assert seen == []


def test_the_toolbar_drives_the_blackout(qapp):
    from ui.main_window import MainWindow

    win = MainWindow()
    try:
        assert not win.project.blackout

        win.action_blackout.setChecked(True)
        assert win.project.blackout is True

        win.action_blackout.setChecked(False)
        assert win.project.blackout is False
    finally:
        win.project.mark_saved()
        win.close()


def test_blackout_is_not_pause(qapp):
    """Pausing leaves the last frame on the wall. Those are different needs."""
    from ui.main_window import MainWindow

    win = MainWindow()
    try:
        win.action_blackout.setChecked(True)

        assert win.project.blackout is True
        assert win.project.transport.playing is True, "the show clock keeps running"
    finally:
        win.project.mark_saved()
        win.close()


# --- knowing what is missing ------------------------------------------------

def test_a_file_that_is_there_is_not_missing(tmp_path):
    clip = tmp_path / "clip.png"
    clip.write_bytes(b"x")
    assert media_exists(_shape_with(clip).media)


def test_a_file_that_is_gone_is_missing(tmp_path):
    assert is_missing(_shape_with(tmp_path / "gone.png").media)


def test_a_surface_with_no_media_is_not_missing_anything():
    assert media_exists(None)
    assert media_exists(MediaRef())
    assert media_exists(polygon_from_points(list(QUAD)).media)


def test_a_camera_is_never_reported_missing():
    """Whether the device answers is the decoder's problem; probing it here
    would open and close the capture on every repaint."""
    assert media_exists(MediaRef(kind="camera", path="0"))


def test_missing_surfaces_are_listed(tmp_path):
    here = tmp_path / "here.png"
    here.write_bytes(b"x")
    shapes = [
        _shape_with(here, name="ok"),
        _shape_with(tmp_path / "gone.png", name="broken"),
        polygon_from_points(list(QUAD), name="no media"),
    ]

    assert [s.name for s in missing_shapes(shapes)] == ["broken"]


def test_the_same_missing_path_is_listed_once(tmp_path):
    gone = tmp_path / "gone.png"
    shapes = [_shape_with(gone), _shape_with(gone), _shape_with(tmp_path / "other.png")]

    assert missing_paths(shapes) == [str(gone), str(tmp_path / "other.png")]


def test_the_answer_is_cached_but_not_forever(tmp_path):
    clip = tmp_path / "clip.png"
    media = _shape_with(clip).media
    assert is_missing(media)

    clip.write_bytes(b"x")
    assert is_missing(media), "the cached answer stands for a moment"

    forget()
    assert not is_missing(media), "and a fresh look sees the file"


def test_the_layer_list_marks_a_broken_surface(qapp, tmp_path):
    from ui.object_list import ObjectList

    widget = ObjectList()
    widget.set_shapes([_shape_with(tmp_path / "gone.png", name="broken")])

    assert "⚠" in widget.list.item(0).text()


def test_the_layer_list_leaves_a_good_surface_alone(qapp, tmp_path):
    from ui.object_list import ObjectList

    clip = tmp_path / "clip.png"
    clip.write_bytes(b"x")
    widget = ObjectList()
    widget.set_shapes([_shape_with(clip, name="fine")])

    assert "⚠" not in widget.list.item(0).text()


def test_the_toolbar_counts_what_is_missing(qapp, tmp_path):
    from ui.main_window import MainWindow

    win = MainWindow()
    try:
        win._update_missing_media()
        assert not win.missing_button.isVisible() or win.missing_button.text() == ""

        win.project.add_shape(_shape_with(tmp_path / "gone.png"))
        win.project.add_shape(_shape_with(tmp_path / "also_gone.png"))
        win._update_missing_media()

        assert "2" in win.missing_button.text()
    finally:
        win.project.mark_saved()
        win.close()


# --- relinking --------------------------------------------------------------

def test_a_file_is_found_by_name_in_the_new_folder(tmp_path):
    new = tmp_path / "new"
    new.mkdir()
    (new / "clip.png").write_bytes(b"x")

    assert find_in_folder("/old/place/clip.png", str(new)) == str(new / "clip.png")


def test_a_folder_without_the_file_finds_nothing(tmp_path):
    assert find_in_folder("/old/clip.png", str(tmp_path)) is None
    assert find_in_folder("", str(tmp_path)) is None


def test_the_whole_folder_is_relinked_at_once(tmp_path):
    """Media moves by the folder, so one answer should fix all of it."""
    new = tmp_path / "new"
    new.mkdir()
    for name in ("a.png", "b.png"):
        (new / name).write_bytes(b"x")

    mapping = relink_map(["/old/a.png", "/old/b.png", "/old/c.png"], str(new))

    assert mapping == {"/old/a.png": str(new / "a.png"), "/old/b.png": str(new / "b.png")}


def test_relinking_repoints_every_surface_on_that_file(tmp_path):
    new = tmp_path / "new"
    new.mkdir()
    (new / "clip.png").write_bytes(b"x")

    project = Project()
    project.add_shape(_shape_with("/old/clip.png", name="one"))
    project.add_shape(_shape_with("/old/clip.png", name="two"))
    project.add_shape(_shape_with("/old/other.png", name="untouched"))
    project.media_library = ["/old/clip.png"]

    moved = apply_relink(project, relink_map(missing_paths(project.shapes), str(new)))

    assert moved == 2
    assert project.shapes[0].media.path == str(new / "clip.png")
    assert project.shapes[1].media.path == str(new / "clip.png")
    assert project.shapes[2].media.path == "/old/other.png"
    assert project.media_library == [str(new / "clip.png")]


def test_relinking_is_undoable(tmp_path):
    new = tmp_path / "new"
    new.mkdir()
    (new / "clip.png").write_bytes(b"x")

    project = Project()
    project.add_shape(_shape_with("/old/clip.png"))
    stack = QUndoStack()

    apply_relink(project, {"/old/clip.png": str(new / "clip.png")}, stack)
    assert project.shapes[0].media.path == str(new / "clip.png")

    stack.undo()
    assert project.shapes[0].media.path == "/old/clip.png"


def test_relinking_nothing_pushes_nothing(tmp_path):
    project = Project()
    stack = QUndoStack()

    assert apply_relink(project, {}, stack) == 0
    assert stack.count() == 0


def test_a_relink_undo_leaves_later_edits_alone(tmp_path):
    """Stored as a path mapping, not a shape snapshot: undoing the relink must
    not also roll back whatever was edited after it."""
    new = tmp_path / "new"
    new.mkdir()
    (new / "clip.png").write_bytes(b"x")

    project = Project()
    project.add_shape(_shape_with("/old/clip.png"))
    stack = QUndoStack()
    apply_relink(project, {"/old/clip.png": str(new / "clip.png")}, stack)

    project.shapes[0].name = "renamed after the relink"
    stack.undo()

    assert project.shapes[0].name == "renamed after the relink"
    assert project.shapes[0].media.path == "/old/clip.png"


def test_the_relink_dialog_lists_what_is_broken(qapp, tmp_path):
    from ui.relink_dialog import RelinkDialog

    project = Project()
    project.add_shape(_shape_with(tmp_path / "gone.png"))
    dialog = RelinkDialog(project)
    try:
        assert dialog.list.count() == 1
        assert dialog.list.item(0).text() == str(tmp_path / "gone.png")
    finally:
        dialog.close()


def test_the_relink_dialog_says_so_when_nothing_is_broken(qapp):
    from ui.relink_dialog import RelinkDialog

    dialog = RelinkDialog(Project())
    try:
        assert dialog.list.count() == 0
        assert not dialog.folder_button.isEnabled()
    finally:
        dialog.close()


def test_relinking_through_the_dialog_fixes_the_project(qapp, tmp_path):
    from ui.relink_dialog import RelinkDialog

    new = tmp_path / "new"
    new.mkdir()
    (new / "clip.png").write_bytes(b"x")

    project = Project()
    project.add_shape(_shape_with("/old/clip.png"))
    dialog = RelinkDialog(project, QUndoStack())
    try:
        dialog._relink_from(str(new))

        assert dialog.relinked == 1
        assert project.shapes[0].media.path == str(new / "clip.png")
        assert dialog.list.count() == 0
    finally:
        dialog.close()


# --- the undo gaps ----------------------------------------------------------

def test_the_canvas_size_is_undoable():
    """It changes how the whole show is composited and was the one edit that
    could not be taken back."""
    project = Project()
    stack = QUndoStack()

    stack.push(CanvasSizeCommand(project, 1920, 1080))
    assert (project.canvas.width, project.canvas.height) == (1920, 1080)

    stack.undo()
    assert (project.canvas.width, project.canvas.height) == (1280, 720)


def test_a_canvas_size_is_never_zero():
    project = Project()
    CanvasSizeCommand(project, 0, -5).redo()
    assert project.canvas.width >= 1 and project.canvas.height >= 1


def test_typing_a_canvas_size_in_the_dialog_is_undoable(qapp):
    from model.output import Output
    from ui.output_panel import OutputDialog

    project = Project()
    project.outputs = [Output(name="Projector 1")]
    stack = QUndoStack()
    dialog = OutputDialog(project, stack)
    try:
        dialog.canvas_width.setValue(1920)
        assert project.canvas.width == 1920

        stack.undo()
        assert project.canvas.width == 1280
    finally:
        dialog.close()


def test_the_relink_command_reports_what_it_moved():
    project = Project()
    project.add_shape(_shape_with("/old/a.png"))
    command = RelinkMediaCommand(project, {"/old/a.png": "/new/a.png"})

    command.redo()

    assert command.changed == 1


# --- every shape type shows the marker --------------------------------------

@pytest.mark.parametrize(
    "factory",
    [
        lambda: polygon_from_points(list(QUAD)),
        lambda: circle_from_center((50.0, 50.0), 40.0),
        lambda: mesh_from_rect((50.0, 50.0), 80.0),
    ],
)
def test_any_surface_can_report_missing_media(factory, tmp_path):
    shape = factory()
    shape.media.kind = "image"
    shape.media.path = str(tmp_path / "gone.png")

    assert is_missing(shape.media)

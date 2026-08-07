"""Projects that survive being moved, and work that survives a crash.

Two failures that only show up when it is too late: a show folder copied to
the machine driving the projectors and every surface comes up blank, and an
app closed hard with an afternoon of calibration in it.
"""

import json
import os

import pytest

from pm.io.media_paths import MAX_PARENT_HOPS, to_absolute, to_portable
from pm.io.project_io import BACKUP_SUFFIX, load_project, save_project
from pm.model.project import Project
from pm.model.shapes import polygon_from_points

QUAD = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]


def _project_with_media(path: str) -> Project:
    project = Project()
    shape = polygon_from_points(list(QUAD), name="wall")
    shape.media.kind = "image"
    shape.media.path = path
    project.add_shape(shape)
    project.media_library = [path]
    return project


# --- the path arithmetic ----------------------------------------------------

def test_media_beside_the_project_is_stored_relative():
    assert to_portable("/shows/gig/clip.mp4", "/shows/gig") == "clip.mp4"
    assert to_portable("/shows/gig/media/clip.mp4", "/shows/gig") == "media/clip.mp4"


def test_a_sibling_folder_is_still_worth_relating():
    assert to_portable("/shows/media/clip.mp4", "/shows/gig") == "../media/clip.mp4"


def test_media_far_from_the_project_stays_absolute():
    """Past a few hops it is a shared library, not part of the show."""
    deep = "/" + "/".join(["a"] * (MAX_PARENT_HOPS + 4)) + "/clip.mp4"
    base = "/" + "/".join(["b"] * (MAX_PARENT_HOPS + 4))
    assert to_portable(deep, base) == deep


def test_paths_survive_the_round_trip():
    absolute = os.path.abspath("/shows/gig/media/clip.mp4")
    base = os.path.abspath("/shows/gig")
    assert to_absolute(to_portable(absolute, base), base) == absolute


def test_an_absolute_path_is_left_alone_on_load():
    assert to_absolute("/mnt/server/clip.mp4", "/shows/gig") == "/mnt/server/clip.mp4"


def test_no_base_means_no_rewriting():
    assert to_portable("/shows/clip.mp4", None) == "/shows/clip.mp4"
    assert to_absolute("clip.mp4", None) == "clip.mp4"


def test_separators_are_normalised_for_the_file():
    """A project written on Windows has to open on the box driving the show."""
    stored = to_portable(os.path.abspath("/shows/gig/media/clip.mp4"), os.path.abspath("/shows/gig"))
    assert "\\" not in stored


# --- what actually lands in the file ----------------------------------------

def test_the_saved_file_holds_relative_paths(tmp_path):
    media = tmp_path / "media" / "clip.png"
    media.parent.mkdir()
    media.write_bytes(b"x")
    path = tmp_path / "show.pmap.json"

    project = _project_with_media(str(media))
    save_project(project, str(path))

    data = json.loads(path.read_text())
    assert data["shapes"][0]["media"]["path"] == "media/clip.png"
    assert data["media_library"] == ["media/clip.png"]


def test_saving_does_not_rewrite_the_open_project(tmp_path):
    """The session keeps working after a save; it still needs real paths."""
    media = tmp_path / "clip.png"
    media.write_bytes(b"x")
    project = _project_with_media(str(media))

    save_project(project, str(tmp_path / "show.pmap.json"))

    assert project.shapes[0].media.path == str(media)


def test_a_moved_project_still_finds_its_media(tmp_path):
    """The whole point: copy the folder somewhere else and it still opens."""
    first = tmp_path / "here"
    (first / "media").mkdir(parents=True)
    (first / "media" / "clip.png").write_bytes(b"x")
    save_project(_project_with_media(str(first / "media" / "clip.png")), str(first / "show.pmap.json"))

    second = tmp_path / "there"
    second.mkdir()
    (second / "media").mkdir()
    (second / "media" / "clip.png").write_bytes(b"x")
    (second / "show.pmap.json").write_bytes((first / "show.pmap.json").read_bytes())

    reopened = load_project(str(second / "show.pmap.json"))

    assert reopened.shapes[0].media.path == str(second / "media" / "clip.png")
    assert os.path.exists(reopened.shapes[0].media.path)


def test_media_outside_the_project_keeps_its_absolute_path(tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    clip = outside / "clip.png"
    clip.write_bytes(b"x")
    deep = tmp_path / "a" / "b" / "c" / "d" / "e"
    deep.mkdir(parents=True)
    path = deep / "show.pmap.json"

    save_project(_project_with_media(str(clip)), str(path))

    data = json.loads(path.read_text())
    assert data["shapes"][0]["media"]["path"] == str(clip)


def test_an_old_file_with_absolute_paths_still_opens(tmp_path):
    path = tmp_path / "show.pmap.json"
    project = _project_with_media("/mnt/server/clip.png")
    save_project(project, str(path))

    assert load_project(str(path)).shapes[0].media.path == "/mnt/server/clip.png"


def test_a_shape_with_no_media_is_untouched(tmp_path):
    project = Project()
    project.add_shape(polygon_from_points(list(QUAD)))
    path = tmp_path / "show.pmap.json"

    save_project(project, str(path))

    assert json.loads(path.read_text())["shapes"][0]["media"]["path"] == ""


# --- backups and atomic writes ----------------------------------------------

def test_saving_over_a_project_keeps_the_previous_one(tmp_path):
    path = tmp_path / "show.pmap.json"
    project = Project()
    project.add_shape(polygon_from_points(list(QUAD), name="first"))
    save_project(project, str(path))

    project.shapes[0].name = "second"
    save_project(project, str(path))

    backup = json.loads((tmp_path / ("show.pmap.json" + BACKUP_SUFFIX)).read_text())
    assert backup["shapes"][0]["name"] == "first"
    assert json.loads(path.read_text())["shapes"][0]["name"] == "second"


def test_the_first_save_writes_no_backup(tmp_path):
    path = tmp_path / "show.pmap.json"
    save_project(Project(), str(path))
    assert not (tmp_path / ("show.pmap.json" + BACKUP_SUFFIX)).exists()


def test_no_temporary_file_is_left_behind(tmp_path):
    path = tmp_path / "show.pmap.json"
    save_project(Project(), str(path))
    assert [p.name for p in tmp_path.iterdir()] == ["show.pmap.json"]


# --- the session, and recovery ----------------------------------------------

@pytest.fixture
def store(tmp_path):
    from pm.model.project_store import ProjectStore

    store = ProjectStore()
    store.set_base_path(str(tmp_path / "appdata"))
    return store


def test_a_restored_session_remembers_which_file_it_came_from(store, tmp_path, qapp):
    from pm.model.project_store import ProjectStore

    project = Project()
    project.path = str(tmp_path / "show.pmap.json")
    project.add_shape(polygon_from_points(list(QUAD), name="wall"))
    store.set_project(project)
    store.save()

    other = ProjectStore()
    other.set_base_path(str(tmp_path / "appdata"))
    restored = other.load()

    # It used to claim the session copy in app data *was* the project, so the
    # next Ctrl+S wrote there and left the operator's file stale.
    assert restored.path == str(tmp_path / "show.pmap.json")
    assert restored.shapes[0].name == "wall"


def test_a_clean_session_comes_back_clean(store, tmp_path, qapp):
    from pm.model.project_store import ProjectStore

    project = Project()
    project.add_shape(polygon_from_points(list(QUAD)))
    store.set_project(project)
    store.save()

    other = ProjectStore()
    other.set_base_path(str(tmp_path / "appdata"))
    restored = other.load()

    assert restored.dirty is False
    assert other.recovered_unsaved is False


def test_an_autosave_comes_back_as_unsaved_work(store, tmp_path, qapp):
    from pm.model.project_store import ProjectStore

    project = Project()
    project.add_shape(polygon_from_points(list(QUAD), name="wall"))
    project.path = str(tmp_path / "show.pmap.json")
    store.set_project(project)
    project.touch()

    store.save(mark_saved=False)

    assert project.dirty is True, "autosave must not claim the work is saved"

    other = ProjectStore()
    other.set_base_path(str(tmp_path / "appdata"))
    restored = other.load()

    assert restored.dirty is True
    assert other.recovered_unsaved is True
    assert restored.shapes[0].name == "wall"


def test_the_session_write_is_atomic(store, tmp_path, qapp):
    project = Project()
    store.set_project(project)
    store.save()

    names = sorted(p.name for p in (tmp_path / "appdata").iterdir())
    assert names == ["session.pmap.json"]


def test_a_corrupt_session_falls_back_to_a_fresh_project(store, tmp_path, qapp):
    store.save()
    store.session_path().write_text("{ not json")

    project = store.load()

    assert isinstance(project, Project)
    assert project.outputs, "a project with no output cannot show anything"


# --- the window's autosave --------------------------------------------------

def test_the_window_autosaves_without_claiming_the_work_is_saved(qapp):
    from pm.ui.main_window import MainWindow

    win = MainWindow()
    try:
        win.project.add_shape(polygon_from_points(list(QUAD)))
        assert win.project.dirty

        win._autosave()

        assert win.store.session_path().exists()
        assert win.project.dirty, "the close prompt still has to warn"
    finally:
        win.project.mark_saved()
        win.close()


def test_a_clean_project_is_not_written_on_every_tick(qapp):
    from pm.ui.main_window import MainWindow

    win = MainWindow()
    try:
        win.project.mark_saved()
        path = win.store.session_path()
        if path.exists():
            path.unlink()

        win._autosave()

        assert not path.exists()
    finally:
        win.project.mark_saved()
        win.close()


# --- the output preview -----------------------------------------------------

def _preview(qapp):
    from pm.model.output import Output
    from pm.ui.output_preview import OutputPreview

    project = Project()
    project.outputs = [Output(name="Stage Left"), Output(name="Stage Right")]
    return OutputPreview(project), project


def test_the_preview_lists_every_output(qapp):
    preview, project = _preview(qapp)
    try:
        labels = [preview.output_combo.itemText(i) for i in range(preview.output_combo.count())]
        assert labels == ["Stage Left", "Stage Right"]
        assert preview.current_output() is project.outputs[0]
    finally:
        preview.close()


def test_the_preview_follows_the_output_being_edited(qapp):
    preview, project = _preview(qapp)
    try:
        preview.show_output(project.outputs[1].id)
        assert preview.current_output() is project.outputs[1]
    finally:
        preview.close()


def test_the_preview_stays_put_when_following_is_off(qapp):
    preview, project = _preview(qapp)
    try:
        preview.follow_check.setChecked(False)
        preview.show_output(project.outputs[1].id)
        assert preview.current_output() is project.outputs[0]
    finally:
        preview.close()


def test_adding_an_output_reaches_the_preview(qapp):
    from pm.model.output import Output

    preview, project = _preview(qapp)
    try:
        project.add_output(Output(name="Ceiling"))
        labels = [preview.output_combo.itemText(i) for i in range(preview.output_combo.count())]
        assert labels == ["Stage Left", "Stage Right", "Ceiling"]
    finally:
        preview.close()


def test_the_preview_says_how_much_canvas_the_output_covers(qapp):
    preview, project = _preview(qapp)
    try:
        project.canvas.width, project.canvas.height = 1920, 1080
        project.outputs[0].region.u1 = 0.5
        project.outputs[0].blend.right = 0.2
        preview._update_aspect_label()

        assert "960x1080" in preview.aspect_label.text()
        assert "blend" in preview.aspect_label.text()
    finally:
        preview.close()


def test_a_preview_with_no_outputs_says_so_instead_of_crashing(qapp):
    from pm.ui.output_preview import OutputPreview

    project = Project()
    project.outputs = []
    preview = OutputPreview(project)
    try:
        assert preview.current_output() is None
        assert preview._error is not None
    finally:
        preview.close()

import pytest

from pm.model.project import Project
from pm.model.shapes import polygon_from_points

QUAD = [(70.0, 20.0), (190.0, 20.0), (250.0, 240.0), (10.0, 240.0)]
PENTAGON = QUAD + [(130.0, 260.0)]


@pytest.fixture
def panel(qapp):
    from pm.ui.property_panel import PropertyPanel

    return PropertyPanel()


def _load_image(monkeypatch, panel, path="/tmp/does-not-need-to-exist.png"):
    """Drive _pick_media without opening a file dialog."""
    from PySide6.QtWidgets import QFileDialog

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (path, "")))
    panel._pick_media("image")


def test_fit_mode_labels_keep_serialised_values(panel):
    values = [panel.fit_mode.itemData(i) for i in range(panel.fit_mode.count())]
    assert values == ["stretch", "contain", "cover", "warp"]
    assert panel.fit_mode.itemText(values.index("warp")) == "Corner pin"


def test_loading_media_on_a_quad_defaults_to_corner_pin(panel, monkeypatch):
    shape = polygon_from_points(list(QUAD))
    panel.set_shape(shape)

    _load_image(monkeypatch, panel)

    assert shape.media.fit_mode == "warp"
    assert panel.fit_mode.currentData() == "warp"


def test_loading_media_on_a_non_quad_stays_stretched(panel, monkeypatch):
    shape = polygon_from_points(list(PENTAGON))
    panel.set_shape(shape)

    _load_image(monkeypatch, panel)

    assert shape.media.fit_mode == "stretch"


def test_replacing_media_keeps_a_deliberate_fit_mode(panel, monkeypatch):
    shape = polygon_from_points(list(QUAD))
    panel.set_shape(shape)
    _load_image(monkeypatch, panel, "/tmp/first.png")

    panel._select_fit_mode("cover")
    assert shape.media.fit_mode == "cover"

    _load_image(monkeypatch, panel, "/tmp/second.png")
    assert shape.media.path == "/tmp/second.png"
    assert shape.media.fit_mode == "cover"


def test_corner_pin_entry_is_disabled_for_non_quads(panel):
    quad = polygon_from_points(list(QUAD))
    pentagon = polygon_from_points(list(PENTAGON))
    index = panel.fit_mode.findData("warp")

    panel.set_shape(quad)
    assert panel.fit_mode.model().item(index).isEnabled()

    panel.set_shape(pentagon)
    assert not panel.fit_mode.model().item(index).isEnabled()


def test_reset_corners_rebuilds_an_upright_rectangle(panel, monkeypatch):
    shape = polygon_from_points(list(QUAD))
    panel.set_shape(shape)
    _load_image(monkeypatch, panel)
    assert panel.reset_corners_btn.isVisibleTo(panel)

    panel._on_reset_corners()

    assert shape.points == [(10.0, 20.0), (250.0, 20.0), (250.0, 240.0), (10.0, 240.0)]
    assert len(shape.edges) == 4


def test_reset_corners_ignores_non_quads(panel):
    shape = polygon_from_points(list(PENTAGON))
    panel.set_shape(shape)

    panel._on_reset_corners()

    assert shape.points == PENTAGON


def test_origin_handle_is_highlighted_on_a_pinned_quad(qapp):
    from pm.ui.canvas_editor import CanvasEditor

    project = Project()
    shape = polygon_from_points(list(QUAD))
    shape.media.kind = "image"
    shape.media.path = "/tmp/whatever.png"
    shape.media.fit_mode = "warp"
    project.add_shape(shape)

    canvas = CanvasEditor(project)
    canvas.select_shape(shape.id)
    item = canvas.items_by_id[shape.id]

    accents = [h.brush().color().getRgb()[:3] == (255, 176, 46) for h in item.handles]
    # Exactly one corner carries the media's origin.
    assert accents.count(True) == 1
    # ...and it is the vertex nearest the bounding box's top-left.
    assert accents.index(True) == 0


def test_handles_stay_neutral_without_corner_pin(qapp):
    from pm.ui.canvas_editor import CanvasEditor

    project = Project()
    shape = polygon_from_points(list(QUAD))  # no media assigned
    project.add_shape(shape)

    canvas = CanvasEditor(project)
    canvas.select_shape(shape.id)
    item = canvas.items_by_id[shape.id]

    assert all(h.brush().color().getRgb()[:3] == (0, 212, 170) for h in item.handles)

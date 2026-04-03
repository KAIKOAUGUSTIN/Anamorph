from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QAction, QActionGroup, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QToolBar,
    QLabel,
    QHBoxLayout,
    QWidgetAction,
    QWidget,
    QVBoxLayout,
)

from pm.io.project_io import load_project, save_project
from pm.model.project import Project
from pm.model.shapes import Shape
from pm.ui.canvas_editor import CanvasEditor
from pm.ui.object_list import ObjectList
from pm.ui.property_panel import PropertyPanel
from pm.ui.projection_window import ProjectionWindow
from pm.ui.widgets import ArrowSlider


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.project = Project()
        self.projection_window: Optional[ProjectionWindow] = None
        self.selected_screen_index: Optional[int] = None

        self._build_ui()
        self._connect_signals()
        self._auto_select_screen()
        self._refresh_object_list()

    def _build_ui(self) -> None:
        self.setWindowTitle("PROJECTION MAPPER")
        screen = QGuiApplication.primaryScreen()
        if screen:
            available = screen.availableGeometry()
            self.resize(min(1600, available.width()), min(900, available.height()))
        else:
            self.resize(1600, 900)

        # Canvas and panels
        self.canvas = CanvasEditor(self.project)
        self.object_list = ObjectList()
        self.object_list.setObjectName("objectListPanel")
        self.property_panel = PropertyPanel()
        self.property_panel.setObjectName("propertyPanel")

        self.object_list.setMinimumWidth(200)
        self.property_panel.setMinimumWidth(260)
        self.object_list.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.property_panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

        object_scroll = QScrollArea()
        object_scroll.setWidgetResizable(True)
        object_scroll.setFrameShape(QFrame.NoFrame)
        object_scroll.setWidget(self.object_list)
        object_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        property_scroll = QScrollArea()
        property_scroll.setWidgetResizable(True)
        property_scroll.setFrameShape(QFrame.NoFrame)
        property_scroll.setWidget(self.property_panel)
        property_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(object_scroll)
        splitter.addWidget(self.canvas)
        splitter.addWidget(property_scroll)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([220, 1000, 280])

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(splitter)
        self.setCentralWidget(container)

        # Toolbar
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(20, 20))
        self.addToolBar(toolbar)

        # Tool actions - make them checkable for exclusive selection
        self.action_select = QAction("Select", self)
        self.action_polygon = QAction("Polygon", self)
        self.action_circle = QAction("Circle", self)

        for action in (self.action_select, self.action_polygon, self.action_circle):
            action.setCheckable(True)
        self.action_select.setChecked(True)

        tool_group = QActionGroup(self)
        tool_group.setExclusive(True)
        tool_group.addAction(self.action_select)
        tool_group.addAction(self.action_polygon)
        tool_group.addAction(self.action_circle)

        toolbar.addAction(self.action_select)
        toolbar.addAction(self.action_polygon)
        toolbar.addAction(self.action_circle)

        toolbar.addSeparator()

        # Edit mode actions
        self.action_mode_points = QAction("Points", self)
        self.action_mode_scale = QAction("Scale", self)
        self.action_mode_rotate = QAction("Rotate", self)
        for action in (self.action_mode_points, self.action_mode_scale, self.action_mode_rotate):
            action.setCheckable(True)
        self.action_mode_points.setChecked(True)

        mode_group = QActionGroup(self)
        mode_group.setExclusive(True)
        mode_group.addAction(self.action_mode_points)
        mode_group.addAction(self.action_mode_scale)
        mode_group.addAction(self.action_mode_rotate)

        toolbar.addAction(self.action_mode_points)
        toolbar.addAction(self.action_mode_scale)
        toolbar.addAction(self.action_mode_rotate)

        toolbar.addSeparator()

        # Projection controls
        self.action_projection = QAction("Project", self)
        self.action_test_mode = QAction("Test Mode", self)
        self.action_test_mode.setCheckable(True)
        toolbar.addAction(self.action_projection)
        toolbar.addAction(self.action_test_mode)

        # Spacer for zoom control
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        toolbar.addWidget(spacer)

        # Zoom control
        zoom_widget = QWidget()
        zoom_layout = QHBoxLayout(zoom_widget)
        zoom_layout.setContentsMargins(12, 0, 12, 0)
        zoom_layout.setSpacing(8)
        zoom_label = QLabel("ZOOM")
        zoom_label.setStyleSheet("color: #707070; font-weight: 600; font-size: 10px; letter-spacing: 1px;")
        self.zoom_slider = ArrowSlider(Qt.Horizontal)
        self.zoom_slider.setRange(25, 400)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setFixedWidth(120)
        self.zoom_slider.setSingleStep(5)
        zoom_layout.addWidget(zoom_label)
        zoom_layout.addWidget(self.zoom_slider)

        zoom_action = QWidgetAction(self)
        zoom_action.setDefaultWidget(zoom_widget)
        toolbar.addAction(zoom_action)

        # Delete action (keyboard shortcut only)
        self.action_delete = QAction("Delete", self)
        self.action_delete.setShortcuts([QKeySequence.Delete, QKeySequence.Backspace])
        self.action_delete.setShortcutContext(Qt.ApplicationShortcut)
        self.addAction(self.action_delete)

        # Menu bar
        file_menu = self.menuBar().addMenu("File")
        self.action_new = QAction("New Project", self)
        self.action_open = QAction("Open...", self)
        self.action_save = QAction("Save", self)
        self.action_save_as = QAction("Save As...", self)
        file_menu.addAction(self.action_new)
        file_menu.addAction(self.action_open)
        file_menu.addAction(self.action_save)
        file_menu.addAction(self.action_save_as)

        settings_menu = self.menuBar().addMenu("Settings")
        self.action_select_screen = QAction("Projection Display...", self)
        settings_menu.addAction(self.action_select_screen)

        edit_menu = self.menuBar().addMenu("Edit")
        edit_menu.addAction(self.action_delete)

        # Status bar with styled mode indicator
        self.mode_label = QLabel("POINTS")
        self.mode_label.setStyleSheet("""
            QLabel {
                color: #00d4aa;
                font-size: 10px;
                font-weight: 700;
                letter-spacing: 2px;
                padding: 4px 12px;
                background: rgba(0, 212, 170, 0.1);
                border-radius: 3px;
            }
        """)
        self.statusBar().addPermanentWidget(self.mode_label)

    def _connect_signals(self) -> None:
        self.action_select.triggered.connect(lambda _checked=False: self._set_tool("select"))
        self.action_polygon.triggered.connect(lambda _checked=False: self._set_tool("polygon"))
        self.action_circle.triggered.connect(lambda _checked=False: self._set_tool("circle"))
        self.action_projection.triggered.connect(lambda _checked=False: self._open_projection())
        self.zoom_slider.valueChanged.connect(self._on_zoom_changed)
        self.action_test_mode.toggled.connect(self._on_test_mode_toggled)
        self.action_delete.triggered.connect(lambda _checked=False: self._delete_selected_shapes())

        self.action_new.triggered.connect(lambda _checked=False: self._new_project())
        self.action_open.triggered.connect(lambda _checked=False: self._open_project())
        self.action_save.triggered.connect(lambda _checked=False: self._save_project())
        self.action_save_as.triggered.connect(lambda _checked=False: self._save_project(save_as=True))

        self.action_select_screen.triggered.connect(lambda _checked=False: self._select_projection_screen())
        self.action_mode_points.triggered.connect(lambda _checked=False: self.canvas.set_edit_mode("points"))
        self.action_mode_scale.triggered.connect(lambda _checked=False: self.canvas.set_edit_mode("scale"))
        self.action_mode_rotate.triggered.connect(lambda _checked=False: self.canvas.set_edit_mode("rotate"))

        self.canvas.selection_changed.connect(self._on_canvas_selection)
        self.canvas.zoom_changed.connect(self._on_canvas_zoom_changed)
        self.canvas.edit_mode_changed.connect(self._on_edit_mode_changed)
        self.object_list.shape_selected.connect(self._on_list_selection)
        self.object_list.visibility_changed.connect(self._on_visibility_change)
        self.property_panel.shape_changed.connect(self._on_property_changed)

        self.project.changed.connect(self._refresh_object_list)

    def _on_canvas_selection(self, shape: Optional[Shape]) -> None:
        self.property_panel.set_shape(shape)
        self.object_list.select_shape(shape.id if shape else None)

    def _on_edit_mode_changed(self, mode: str) -> None:
        mode_labels = {"points": "POINTS", "scale": "SCALE", "rotate": "ROTATE"}
        if mode == "points":
            self.action_mode_points.setChecked(True)
        elif mode == "scale":
            self.action_mode_scale.setChecked(True)
        elif mode == "rotate":
            self.action_mode_rotate.setChecked(True)
        self.mode_label.setText(mode_labels.get(mode, mode.upper()))

    def _on_list_selection(self, shape_id: str) -> None:
        self.canvas.select_shape(shape_id)
        shape = self.project.get_shape(shape_id)
        self.property_panel.set_shape(shape)

    def _on_visibility_change(self, shape_id: str, visible: bool) -> None:
        shape = self.project.get_shape(shape_id)
        if shape:
            shape.visible = visible
            self.canvas.set_shape_visibility(shape_id, visible)
            self.project.touch()

    def _on_property_changed(self) -> None:
        self.canvas._sync_items()
        self.project.touch()

    def _set_tool(self, tool: str) -> None:
        self.canvas.set_tool(tool)
        messages = {
            "polygon": "Click on canvas to create polygon, adjust via vertices",
            "circle": "Click on canvas to create circle, adjust via handles",
            "select": "Selection active. Drag to pan, Shift+drag to move shapes"
        }
        self.statusBar().showMessage(messages.get(tool, ""), 3000)

    def _refresh_object_list(self) -> None:
        selected_id = None
        items = self.canvas.scene.selectedItems()
        if items:
            item = items[0]
            if hasattr(item, "model"):
                selected_id = item.model.id
        self.object_list.set_shapes(self.project.shapes)
        if selected_id:
            self.object_list.select_shape(selected_id)

    def _new_project(self) -> None:
        self._set_project(Project())

    def _open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open Project", "", "Projection Map (*.pmap.json)")
        if not path:
            return
        try:
            project = load_project(path)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to open project: {exc}")
            return
        self._set_project(project)

    def _save_project(self, save_as: bool = False) -> None:
        path = self.project.path
        if save_as or not path:
            path, _ = QFileDialog.getSaveFileName(self, "Save Project", "", "Projection Map (*.pmap.json)")
        if not path:
            return
        try:
            save_project(self.project, path)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to save project: {exc}")

    def _set_project(self, project: Project) -> None:
        try:
            self.project.changed.disconnect(self._refresh_object_list)
        except Exception:
            pass
        self.project = project
        self.project.changed.connect(self._refresh_object_list)
        self.canvas.project = self.project
        self.canvas.scene.project = self.project
        self.canvas.project.changed.connect(self.canvas._sync_items)
        self.canvas.project.changed.connect(self._refresh_object_list)
        self.canvas._sync_items()
        self._refresh_object_list()
        self.property_panel.set_shape(None)
        if self.projection_window:
            self.projection_window.close()
            self.projection_window = None
        self.action_test_mode.setChecked(bool(self.project.ui_state.get("test_mode", False)))

    def _auto_select_screen(self) -> None:
        screens = QGuiApplication.screens()
        primary = QGuiApplication.primaryScreen()
        if len(screens) > 1:
            for idx, screen in enumerate(screens):
                if screen != primary:
                    self.selected_screen_index = idx
                    self._apply_screen_resolution(screen)
                    break
        else:
            self.selected_screen_index = 0
            if screens:
                self._apply_screen_resolution(screens[0])
        self.project.ui_state["last_projection_screen_id"] = self.selected_screen_index

    def _select_projection_screen(self) -> None:
        screens = QGuiApplication.screens()
        items = [f"{i}: {screen.name()}" for i, screen in enumerate(screens)]
        current = self.selected_screen_index or 0
        value, ok = QInputDialog.getItem(self, "Projection Display", "Select display:", items, current, False)
        if ok and value:
            index = int(value.split(":")[0])
            self.selected_screen_index = index
            self.project.ui_state["last_projection_screen_id"] = index
            if index < len(screens):
                self._apply_screen_resolution(screens[index])

    def _open_projection(self) -> None:
        screens = QGuiApplication.screens()
        index = self.selected_screen_index or 0
        if index >= len(screens):
            index = 0
        screen = screens[index] if screens else None
        if not self.projection_window:
            self.projection_window = ProjectionWindow(self.project, self)
            self.projection_window.open_on_screen(screen)
            self.projection_window.renderer.update()
        if screen:
            self._apply_screen_resolution(screen)

    def _apply_screen_resolution(self, screen) -> None:
        if not screen:
            return
        geometry = screen.geometry()
        self.project.canvas.width = geometry.width()
        self.project.canvas.height = geometry.height()
        self.project.touch()
        self.canvas.fit_to_canvas()
        if hasattr(self, "zoom_slider"):
            self.zoom_slider.blockSignals(True)
            self.zoom_slider.setValue(int(self.canvas.get_zoom() * 100))
            self.zoom_slider.blockSignals(False)

    def _on_zoom_changed(self, value: int) -> None:
        self.canvas.set_zoom(value / 100.0)

    def _on_canvas_zoom_changed(self, zoom: float) -> None:
        if not hasattr(self, "zoom_slider"):
            return
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(int(zoom * 100))
        self.zoom_slider.blockSignals(False)

    def _on_test_mode_toggled(self, checked: bool) -> None:
        self.project.ui_state["test_mode"] = bool(checked)
        self.project.touch()

    def _delete_selected_shapes(self) -> None:
        selected_ids = []
        items = self.canvas.scene.selectedItems()
        for item in items:
            if hasattr(item, "model"):
                selected_ids.append(item.model.id)
            elif hasattr(item, "owner") and hasattr(item.owner, "model"):
                selected_ids.append(item.owner.model.id)
        if not selected_ids:
            list_items = self.object_list.list.selectedItems()
            for item in list_items:
                shape_id = item.data(Qt.UserRole)
                if shape_id:
                    selected_ids.append(shape_id)
        if not selected_ids:
            return
        for shape_id in list(dict.fromkeys(selected_ids)):
            self.project.remove_shape(shape_id)
        self.property_panel.set_shape(None)

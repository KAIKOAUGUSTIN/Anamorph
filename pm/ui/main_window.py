from __future__ import annotations

from typing import Dict, Optional

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QAction, QActionGroup, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
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
from pm.model.workspace_manager import WorkspaceManager
from pm.ui.canvas_editor import CanvasEditor
from pm.ui.object_list import ObjectList
from pm.ui.property_panel import PropertyPanel
from pm.ui.projection_window import ProjectionWindow
from pm.ui.widgets import ArrowSlider


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        # Workspace manager for handling multiple screens
        self.workspace_manager = WorkspaceManager(self)
        self.workspace_manager.set_base_path(self._get_workspace_base_path())

        # Track projection windows per screen
        self._projection_windows: Dict[str, ProjectionWindow] = {}

        # Track known screens to detect new ones
        self._known_screens: set = set()

        self.workspace_manager.workspace_changed.connect(self._on_workspace_changed)

        self.selected_screen_index: Optional[int] = None

        self._build_ui()
        self._connect_signals()
        self._initialize_screens()
        self._refresh_object_list()

    def _get_workspace_base_path(self) -> str:
        """Get base path for workspace storage."""
        import os
        from pathlib import Path
        # Store workspaces in user's app data
        app_data = os.getenv('APPDATA', str(Path.home()))
        base = Path(app_data) / "ProjectionMapper"
        base.mkdir(parents=True, exist_ok=True)
        return str(base)

    def _build_ui(self) -> None:
        self.setWindowTitle("PROJECTION MAPPER")
        screen = QGuiApplication.primaryScreen()
        if screen:
            available = screen.availableGeometry()
            self.resize(min(1600, available.width()), min(900, available.height()))
        else:
            self.resize(1600, 900)

        # Get initial project from workspace manager
        self.project = Project()

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

        # Screen selector dropdown (NEW)
        self.screen_combo = QComboBox()
        self.screen_combo.setFixedWidth(180)
        self.screen_combo.setStyleSheet("""
            QComboBox {
                background: #2a2a2a;
                color: #00d4aa;
                border: 1px solid #3a3a3a;
                padding: 4px 8px;
                border-radius: 3px;
            }
            QComboBox:hover {
                border-color: #00d4aa;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox QAbstractItemView {
                background: #2a2a2a;
                color: #ffffff;
                selection-background-color: #00d4aa;
            }
        """)
        toolbar.addWidget(self.screen_combo)

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
        self.action_rescan = QAction("Rescan Screens", self)
        settings_menu.addAction(self.action_rescan)

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

        # Project name indicator
        self.project_label = QLabel("PROJECT: Untitled")
        self.project_label.setStyleSheet("""
            QLabel {
                color: #707070;
                font-size: 10px;
                font-weight: 600;
                letter-spacing: 1px;
            }
        """)
        self.statusBar().addWidget(self.project_label)

    def _connect_signals(self) -> None:
        self.action_select.triggered.connect(lambda _checked=False: self._set_tool("select"))
        self.action_polygon.triggered.connect(lambda _checked=False: self._set_tool("polygon"))
        self.action_circle.triggered.connect(lambda _checked=False: self._set_tool("circle"))
        self.action_projection.triggered.connect(lambda _checked=False: self._toggle_projection())
        self.zoom_slider.valueChanged.connect(self._on_zoom_changed)
        self.action_test_mode.toggled.connect(self._on_test_mode_toggled)
        self.action_delete.triggered.connect(lambda _checked=False: self._delete_selected_shapes())
        self.action_rescan.triggered.connect(lambda _checked=False: self._rescan_screens())

        self.action_new.triggered.connect(lambda _checked=False: self._new_project())
        self.action_open.triggered.connect(lambda _checked=False: self._open_project())
        self.action_save.triggered.connect(lambda _checked=False: self._save_project())
        self.action_save_as.triggered.connect(lambda _checked=False: self._save_project(save_as=True))

        self.action_mode_points.triggered.connect(lambda _checked=False: self.canvas.set_edit_mode("points"))
        self.action_mode_scale.triggered.connect(lambda _checked=False: self.canvas.set_edit_mode("scale"))
        self.action_mode_rotate.triggered.connect(lambda _checked=False: self.canvas.set_edit_mode("rotate"))

        self.canvas.selection_changed.connect(self._on_canvas_selection)
        self.canvas.zoom_changed.connect(self._on_canvas_zoom_changed)
        self.canvas.edit_mode_changed.connect(self._on_edit_mode_changed)
        self.object_list.shape_selected.connect(self._on_list_selection)
        self.object_list.visibility_changed.connect(self._on_visibility_change)

        # Connect screen addition/removal signals (use instance)
        app = QGuiApplication.instance()
        if app:
            app.primaryScreenChanged.connect(self._on_primary_screen_changed)
            app.screenAdded.connect(self._on_screen_added)
            app.screenRemoved.connect(self._on_screen_removed)
        self.property_panel.shape_changed.connect(self._on_property_changed)

        self.project.changed.connect(self._refresh_object_list)
        self.project.changed.connect(self._update_project_label)

        # Screen combo
        self.screen_combo.currentIndexChanged.connect(self._on_screen_selected)

    def _initialize_screens(self) -> None:
        """Initialize screen detection and workspace setup."""
        # Store known screens for change detection
        all_screens = QGuiApplication.screens()
        for screen in all_screens:
            self._known_screens.add(screen.name())

        self._update_screen_combo()

        # Auto-select first available projection screen
        screens = self.workspace_manager.get_available_screens()
        if screens:
            idx, screen_id, screen_name, geometry = screens[0]
            self.workspace_manager.switch_to_screen(screen_id, screen_name)
            self.project = self.workspace_manager.get_current_workspace()
            self._set_project(self.project)
            self.screen_combo.setCurrentIndex(0)
        else:
            # No projection screens available
            self.project = Project()
            self.project.name = "No Screens"
            self._set_project(self.project)

    def _update_screen_combo(self) -> None:
        """Update the screen dropdown with available screens."""
        self.screen_combo.blockSignals(True)
        self.screen_combo.clear()

        screens = self.workspace_manager.get_available_screens()
        for idx, screen_id, screen_name, geometry in screens:
            item_text = f"{screen_name} ({geometry.width()}x{geometry.height()})"
            self.screen_combo.addItem(item_text, (idx, screen_id, screen_name))

        if self.screen_combo.count() == 0:
            self.screen_combo.addItem("No screens available", None)

        self.screen_combo.blockSignals(False)

    def _on_screen_selected(self, index: int) -> None:
        """Handle screen selection from dropdown."""
        if index < 0:
            return

        data = self.screen_combo.itemData(index)
        if not data:
            return

        idx, screen_id, screen_name = data
        self._switch_to_screen(idx, screen_id, screen_name)

    def _switch_to_screen(self, screen_index: int, screen_id: str, screen_name: str) -> None:
        """Switch to a different screen workspace."""
        # Get the geometry from available screens
        screens = self.workspace_manager.get_available_screens()
        geometry = None
        for s_idx, s_id, s_name, s_geo in screens:
            if s_id == screen_id:
                geometry = s_geo
                break

        # Switch workspace
        self.project = self.workspace_manager.switch_to_screen(screen_id, screen_name)
        self._set_project(self.project)

        # Apply screen resolution
        if geometry:
            self.project.canvas.width = geometry.width()
            self.project.canvas.height = geometry.height()
            self.project.touch()
            self.canvas.fit_to_canvas()

        self.selected_screen_index = screen_index

    def _on_workspace_changed(self, screen_id: str) -> None:
        """Handle workspace change signal."""
        project = self.workspace_manager.get_workspace(screen_id)
        if project:
            self.project = project
            self._update_project_label()

    def _rescan_screens(self) -> None:
        """Rescan for connected screens."""
        self._update_screen_combo()
        self.statusBar().showMessage("Screens rescanned", 2000)

    def _update_project_label(self) -> None:
        """Update the project name label."""
        name = self.project.name if hasattr(self.project, 'name') else "Untitled"
        self.project_label.setText(f"PROJECT: {name}")

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
        """Create a new project for the current screen."""
        screen_id = self.workspace_manager.get_current_screen_id()
        if screen_id:
            new_project = Project()
            new_project.name = "Untitled"
            self.workspace_manager._workspaces[screen_id] = new_project
            self.project = new_project
            self._set_project(self.project)
        else:
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
            self.project.changed.disconnect(self._update_project_label)
        except Exception:
            pass

        self.project = project
        self.project.changed.connect(self._refresh_object_list)
        self.project.changed.connect(self._update_project_label)
        self.canvas.project = self.project
        self.canvas.scene.project = self.project
        self.project.changed.connect(self.canvas._sync_items)
        self._refresh_object_list()
        self.property_panel.set_shape(None)
        self._update_project_label()

        # Close any open projection windows
        for pw in list(self._projection_windows.values()):
            pw.close()
        self._projection_windows.clear()

        self.action_test_mode.setChecked(bool(self.project.ui_state.get("test_mode", False)))

    def _toggle_projection(self) -> None:
        """Toggle projection for the current screen."""
        screen_id = self.workspace_manager.get_current_screen_id()
        if not screen_id:
            self.statusBar().showMessage("No screen selected for projection", 3000)
            return

        # Check if projection is already open for this screen
        if screen_id in self._projection_windows:
            self._projection_windows[screen_id].close()
            del self._projection_windows[screen_id]
            return

        # Find the screen
        all_screens = QGuiApplication.screens()
        screens = self.workspace_manager.get_available_screens()

        target_screen = None
        for idx, s_id, s_name, geometry in screens:
            if s_id == screen_id:
                target_screen = all_screens[idx] if idx < len(all_screens) else None
                break

        if not target_screen:
            self.statusBar().showMessage("Screen not found", 3000)
            return

        # Create projection window
        pw = ProjectionWindow(self.project, self)
        pw.open_on_screen(target_screen)
        self._projection_windows[screen_id] = pw

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

    def _on_screen_added(self, screen) -> None:
        """Handle new screen connected."""
        screen_name = screen.name()

        # Check if this is a new screen
        if screen_name in self._known_screens:
            return

        self._known_screens.add(screen_name)

        # Check if it's not the primary screen
        primary = QGuiApplication.primaryScreen()
        if screen == primary:
            return

        # Show dialog asking to switch to the new screen
        geometry = screen.geometry()
        msg = QMessageBox(self)
        msg.setWindowTitle("New Screen Detected")
        msg.setText(f"A new screen was connected:\n\n{screen_name}\n{geometry.width()}x{geometry.height()}\n\nSwitch to this screen?")
        msg.setIcon(QMessageBox.Question)
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg.setDefaultButton(QMessageBox.Yes)

        # Style the message box
        msg.setStyleSheet("""
            QMessageBox {
                background-color: #1a1a1a;
            }
            QMessageBox QLabel {
                color: #ffffff;
                font-size: 13px;
            }
            QPushButton {
                background-color: #2a2a2a;
                color: #00d4aa;
                border: 1px solid #3a3a3a;
                padding: 8px 20px;
                border-radius: 4px;
                font-weight: bold;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #3a3a3a;
                border-color: #00d4aa;
            }
            QPushButton:pressed {
                background-color: #1a1a1a;
            }
        """)

        result = msg.exec()

        if result == QMessageBox.Yes:
            # Update screen combo and switch
            self._update_screen_combo()

            # Find the screen in available screens
            screens = self.workspace_manager.get_available_screens()
            for idx, screen_id, s_name, _ in screens:
                if s_name == screen_name:
                    # Find combo index for this screen
                    for i in range(self.screen_combo.count()):
                        data = self.screen_combo.itemData(i)
                        if data and data[1] == screen_id:
                            self.screen_combo.setCurrentIndex(i)
                            break
                    break
        else:
            # Just update the combo without switching
            self._update_screen_combo()

    def _on_screen_removed(self, screen) -> None:
        """Handle screen disconnected."""
        screen_name = screen.name()

        if screen_name in self._known_screens:
            self._known_screens.discard(screen_name)

        # Close projection window for this screen if open
        screens = self.workspace_manager.get_available_screens()
        all_screens = QGuiApplication.screens()

        # Find screen_id for the removed screen
        for idx, screen_id, s_name, _ in screens:
            if s_name == screen_name and screen_id in self._projection_windows:
                self._projection_windows[screen_id].close()
                del self._projection_windows[screen_id]
                break

        # Update screen combo
        self._update_screen_combo()

        # Show notification
        self.statusBar().showMessage(f"Screen disconnected: {screen_name}", 5000)

    def _on_primary_screen_changed(self, screen) -> None:
        """Handle primary screen change."""
        self._update_screen_combo()

    def closeEvent(self, event) -> None:
        """Handle app close - save all workspaces."""
        self.workspace_manager.save_all_workspaces()
        # Clean up projection windows
        for pw in list(self._projection_windows.values()):
            pw.close()
        self._projection_windows.clear()
        super().closeEvent(event)

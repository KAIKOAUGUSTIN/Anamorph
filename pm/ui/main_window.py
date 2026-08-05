from __future__ import annotations

from typing import Dict, Optional

from PySide6.QtCore import Qt, QSize, QStandardPaths
from PySide6.QtGui import QAction, QActionGroup, QGuiApplication, QKeySequence, QUndoStack
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
from pm.model.commands import AddShapeCommand, RemoveShapesCommand, ShapeEditCommand, duplicate_shape
from pm.model.project import Project
from pm.model.shapes import Shape, shape_to_dict
from pm.model.workspace_manager import WorkspaceManager
from pm.render.test_pattern import PATTERNS
from pm.ui.canvas_editor import CanvasEditor
from pm.ui.object_list import ObjectList
from pm.ui.property_panel import PropertyPanel
from pm.ui.projection_window import ProjectionWindow
from pm.ui.widgets import ArrowSlider


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        # One stack per window; cleared when the active project is swapped,
        # since commands hold references into a specific project's shape list.
        self.undo_stack = QUndoStack(self)

        # Workspace manager for handling multiple screens
        self.workspace_manager = WorkspaceManager(self)
        self.workspace_manager.set_base_path(self._get_workspace_base_path())

        # Track projection windows per screen
        self._projection_windows: Dict[str, ProjectionWindow] = {}

        # Track known screens to detect new ones
        self._known_screens: set = set()

        self.workspace_manager.workspace_changed.connect(self._on_workspace_changed)

        self.selected_screen_index: Optional[int] = None
        self._connected_project: Optional[Project] = None

        self._build_ui()
        self._connect_signals()
        self._initialize_screens()
        self._refresh_object_list()

    def _get_workspace_base_path(self) -> str:
        """Get base path for workspace storage using QStandardPaths."""
        from pathlib import Path
        # Use QStandardPaths for cross-platform compatibility
        app_data = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
        if not app_data:
            app_data = QStandardPaths.writableLocation(QStandardPaths.HomeLocation)
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
        self.canvas.set_undo_stack(self.undo_stack)
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

        # Points/Scale/Rotate used to live here as exclusive modes. Scaling
        # and rotating are modifiers on the drag now, so there is nothing to
        # switch between - and no trip to the toolbar mid-show.
        self.action_duplicate = QAction("Duplicate", self)
        self.action_duplicate.setShortcut(QKeySequence("Ctrl+D"))
        self.action_duplicate.setShortcutContext(Qt.ApplicationShortcut)
        self.action_duplicate.setToolTip("Copy the selected surface, offset from the original (Ctrl+D)")
        self.addAction(self.action_duplicate)
        toolbar.addAction(self.action_duplicate)

        toolbar.addSeparator()

        self.action_snap = QAction("Snap", self)
        self.action_snap.setCheckable(True)
        self.action_snap.setChecked(True)
        self.action_snap.setToolTip(
            "Snap dragged vertices to other surfaces' corners and edges.\n"
            "Hold Alt to bypass for a single drag."
        )
        toolbar.addAction(self.action_snap)

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
        self.action_test_mode.setToolTip(
            "Replace the output with a calibration pattern for focusing and\n"
            "squaring the projector before mapping anything."
        )
        toolbar.addAction(self.action_projection)
        toolbar.addAction(self.action_test_mode)

        self.pattern_combo = QComboBox()
        self.pattern_combo.setFixedWidth(140)
        for value, label in PATTERNS:
            self.pattern_combo.addItem(label, value)
        self.pattern_combo.setEnabled(False)
        toolbar.addWidget(self.pattern_combo)

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
        self.action_undo = self.undo_stack.createUndoAction(self, "Undo")
        self.action_redo = self.undo_stack.createRedoAction(self, "Redo")
        self.action_undo.setShortcut(QKeySequence.Undo)
        self.action_redo.setShortcuts([QKeySequence.Redo, QKeySequence("Ctrl+Y")])
        self.action_undo.setShortcutContext(Qt.ApplicationShortcut)
        self.action_redo.setShortcutContext(Qt.ApplicationShortcut)
        self.addAction(self.action_undo)
        self.addAction(self.action_redo)
        edit_menu.addAction(self.action_undo)
        edit_menu.addAction(self.action_redo)
        edit_menu.addSeparator()
        edit_menu.addAction(self.action_delete)

        # Status bar with styled mode indicator
        self.mode_label = QLabel("DRAG MOVE · ALT ROTATE · CTRL SCALE")
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
        self.action_snap.toggled.connect(self.canvas.set_snap_enabled)
        self.pattern_combo.currentIndexChanged.connect(self._on_test_pattern_changed)

        self.action_new.triggered.connect(lambda _checked=False: self._new_project())
        self.action_open.triggered.connect(lambda _checked=False: self._open_project())
        self.action_save.triggered.connect(lambda _checked=False: self._save_project())
        self.action_save_as.triggered.connect(lambda _checked=False: self._save_project(save_as=True))

        self.action_duplicate.triggered.connect(lambda _checked=False: self._duplicate_selected())

        self.canvas.selection_changed.connect(self._on_canvas_selection)
        self.canvas.zoom_changed.connect(self._on_canvas_zoom_changed)
        self.object_list.shape_selected.connect(self._on_list_selection)
        self.object_list.visibility_changed.connect(self._on_visibility_change)
        self.object_list.solo_requested.connect(self._on_solo_requested)

        # Connect screen addition/removal signals (use instance)
        app = QGuiApplication.instance()
        if app:
            app.primaryScreenChanged.connect(self._on_primary_screen_changed)
            app.screenAdded.connect(self._on_screen_added)
            app.screenRemoved.connect(self._on_screen_removed)
        self.property_panel.shape_changed.connect(self._on_property_changed)

        # Same set _set_project manages, so a later switch cleans these up
        # instead of stacking a second copy on top.
        for slot in self._project_slots():
            self.project.changed.connect(slot)
        self._connected_project = self.project
        self.property_panel.set_undo_context(self.project, self.undo_stack)

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
            _, screen_id, screen_name, _ = screens[0]
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

    _MSG_BOX_STYLE = """
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
        """

    def _styled_message_box(self, title: str, text: str, icon, buttons, default) -> QMessageBox:
        msg = QMessageBox(self)
        msg.setWindowTitle(title)
        msg.setText(text)
        msg.setIcon(icon)
        msg.setStandardButtons(buttons)
        msg.setDefaultButton(default)
        msg.setStyleSheet(self._MSG_BOX_STYLE)
        return msg

    def _update_screen_combo_selection(self, screen_id: str) -> None:
        for i in range(self.screen_combo.count()):
            data = self.screen_combo.itemData(i)
            if data and data[1] == screen_id:
                self.screen_combo.setCurrentIndex(i)
                break

    def _find_screen_geometry(self, screen_id: str):
        screens = self.workspace_manager.get_available_screens()
        for _, s_id, _, s_geo in screens:
            if s_id == screen_id:
                return s_geo
        return None

    def _switch_to_screen(self, screen_index: int, screen_id: str, screen_name: str) -> None:
        """Switch to a different screen workspace."""
        if not self._confirm_discard("Switch screens anyway?"):
            current_id = self.workspace_manager.get_current_screen_id()
            if current_id:
                self.screen_combo.blockSignals(True)
                self._update_screen_combo_selection(current_id)
                self.screen_combo.blockSignals(False)
            return

        geometry = self._find_screen_geometry(screen_id)
        self.project = self.workspace_manager.switch_to_screen(screen_id, screen_name)
        self._set_project(self.project)

        if geometry:
            was_clean = not self._has_unsaved_changes()
            self.project.canvas.width = geometry.width()
            self.project.canvas.height = geometry.height()
            self.project.touch()
            if was_clean:
                # Matching the canvas to the target display is bookkeeping,
                # not an edit worth warning the user about losing.
                self.project.mark_saved()
            self.canvas.fit_to_canvas()

        self.selected_screen_index = screen_index

    def _has_unsaved_changes(self) -> bool:
        """True only if the project changed since it was last saved or loaded."""
        return bool(getattr(self.project, "dirty", False))

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

    def _on_solo_requested(self, shape_id: str) -> None:
        """Show only this surface, or restore everything if it already is.

        One undo step for the whole toggle - soloing is a single act, not one
        edit per layer.
        """
        others = [s for s in self.project.shapes if s.id != shape_id]
        if not others:
            return

        # Already soloed if every other surface is hidden.
        restoring = all(not s.visible for s in others)
        target = self.project.get_shape(shape_id)

        self.undo_stack.beginMacro("Unsolo" if restoring else "Solo")
        for shape in self.project.shapes:
            wanted = True if restoring else (shape is target)
            if shape.visible == wanted:
                continue
            before = shape_to_dict(shape)
            shape.visible = wanted
            self.undo_stack.push(
                ShapeEditCommand(self.project, shape.id, before, shape_to_dict(shape), "Solo")
            )
            self.canvas.set_shape_visibility(shape.id, wanted)
        self.undo_stack.endMacro()

    def _duplicate_selected(self) -> None:
        item = self.canvas._current_selected_item()
        if item is None:
            self.statusBar().showMessage("Select a surface to duplicate", 3000)
            return
        copy = duplicate_shape(item.model)
        self.undo_stack.push(AddShapeCommand(self.project, copy, "Duplicate Shape"))
        self.canvas.select_shape(copy.id)
        self.property_panel.set_shape(copy)

    def _on_list_selection(self, shape_id: str) -> None:
        self.canvas.select_shape(shape_id)
        shape = self.project.get_shape(shape_id)
        self.property_panel.set_shape(shape)

    def _on_visibility_change(self, shape_id: str, visible: bool) -> None:
        shape = self.project.get_shape(shape_id)
        if not shape or shape.visible == visible:
            return

        # Through the stack like every other edit; toggling the eye used to be
        # the one mutation Ctrl+Z could not reach.
        before = shape_to_dict(shape)
        shape.visible = visible
        self.undo_stack.push(
            ShapeEditCommand(
                self.project, shape_id, before, shape_to_dict(shape),
                "Show Shape" if visible else "Hide Shape",
            )
        )
        self.canvas.set_shape_visibility(shape_id, visible)

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

    def _confirm_discard(self, action: str) -> bool:
        """Ask before throwing away unsaved work. True means carry on.

        Offers Save as well as Discard - a mapping that took an hour to
        calibrate should never be one click from gone.
        """
        if not self._has_unsaved_changes():
            return True

        msg = self._styled_message_box(
            "Unsaved Changes",
            f"'{self.project.name}' has unsaved changes.\n\n{action}",
            QMessageBox.Warning,
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        answer = msg.exec()
        if answer == QMessageBox.Cancel:
            return False
        if answer == QMessageBox.Save:
            self._save_project()
            # The save dialog can itself be cancelled; only proceed if the
            # project actually reached disk.
            return not self._has_unsaved_changes()
        return True

    def _adopt_project(self, project: Project) -> None:
        """Make `project` the active one, and tell the workspace manager."""
        screen_id = self.workspace_manager.get_current_screen_id()
        if screen_id:
            self.workspace_manager.set_workspace(screen_id, project)
        self._set_project(project)

    def _new_project(self) -> None:
        """Create a new project for the current screen."""
        if not self._confirm_discard("Start a new project anyway?"):
            return
        new_project = Project()
        new_project.name = "Untitled"
        self._adopt_project(new_project)

    def _open_project(self) -> None:
        if not self._confirm_discard("Open another project anyway?"):
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open Project", "", "Projection Map (*.pmap.json)")
        if not path:
            return
        try:
            project = load_project(path)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to open project: {exc}")
            return
        self._adopt_project(project)

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

    def _project_slots(self):
        """Everything that has to follow the active project. Connected and
        disconnected as one set so the two can never drift apart."""
        return (
            self._refresh_object_list,
            self._update_project_label,
            # Keeps the coordinate boxes honest while a vertex is dragged.
            self.property_panel.refresh_geometry,
        )

    def _set_project(self, project: Project) -> None:
        # Disconnect from whichever project we actually attached to, not from
        # self.project: _on_workspace_changed fires during a screen switch and
        # has already repointed that attribute by the time we get here. Old
        # workspaces stay alive in the manager, so leaving connections behind
        # would pile up a new set on every switch.
        if self._connected_project is not None and self._connected_project is not project:
            for slot in self._project_slots():
                self._connected_project.changed.disconnect(slot)
            self._connected_project = None

        self.project = project
        self.canvas.set_project(project)
        if self._connected_project is not project:
            for slot in self._project_slots():
                self.project.changed.connect(slot)
            self._connected_project = project

        # Commands capture a project instance; carrying them across a switch
        # would undo edits into a shape list that no longer exists.
        self.undo_stack.clear()
        self.property_panel.set_undo_context(self.project, self.undo_stack)

        self._refresh_object_list()
        self.property_panel.set_shape(None)
        self._update_project_label()

        # Close any open projection windows
        for pw in self._projection_windows.values():
            pw.close()
        self._projection_windows.clear()

        test_mode = bool(self.project.ui_state.get("test_mode", False))
        self.action_test_mode.setChecked(test_mode)
        self.pattern_combo.setEnabled(test_mode)
        pattern_index = self.pattern_combo.findData(self.project.ui_state.get("test_pattern", "grid"))
        self.pattern_combo.blockSignals(True)
        self.pattern_combo.setCurrentIndex(pattern_index if pattern_index >= 0 else 0)
        self.pattern_combo.blockSignals(False)

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
        self.pattern_combo.setEnabled(bool(checked))
        self.project.touch()
        if checked and not self._projection_windows:
            self.statusBar().showMessage(
                "Test pattern is live on the projection output - press Project to open it", 5000
            )

    def _on_test_pattern_changed(self, index: int) -> None:
        value = self.pattern_combo.itemData(index)
        if not value:
            return
        self.project.ui_state["test_pattern"] = value
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
        unique_ids = list(dict.fromkeys(selected_ids))
        self.undo_stack.push(
            RemoveShapesCommand(
                self.project,
                unique_ids,
                "Delete Shape" if len(unique_ids) == 1 else f"Delete {len(unique_ids)} Shapes",
            )
        )
        self.property_panel.set_shape(None)

    def _on_screen_added(self, screen) -> None:
        """Handle new screen connected."""
        screen_name = screen.name()

        if screen_name in self._known_screens:
            return

        self._known_screens.add(screen_name)

        primary = QGuiApplication.primaryScreen()
        if screen == primary:
            return

        # Deliberately not a modal dialog. A display can appear mid-show when
        # a cable is jostled, and a modal here would block the output until
        # someone found the mouse. The screen is added to the dropdown and
        # announced; switching to it stays the operator's call.
        geometry = screen.geometry()
        self._update_screen_combo()
        self.statusBar().showMessage(
            f"Screen connected: {screen_name} ({geometry.width()}x{geometry.height()}) "
            f"- available in the screen selector",
            8000,
        )

    def _on_screen_removed(self, screen) -> None:
        """Handle screen disconnected."""
        screen_name = screen.name()

        if screen_name in self._known_screens:
            self._known_screens.discard(screen_name)

        # Close projection window for this screen if open
        screens = self.workspace_manager.get_available_screens()

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
        if not self._confirm_discard("Quit anyway?"):
            event.ignore()
            return

        self.workspace_manager.save_all_workspaces()
        # Clean up projection windows
        for pw in self._projection_windows.values():
            pw.close()
        self._projection_windows.clear()
        super().closeEvent(event)

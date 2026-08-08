# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import logging

from typing import Dict, Optional

from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QAction, QActionGroup, QGuiApplication, QKeySequence, QUndoStack
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QPushButton,
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

from about import APP_NAME
from app_paths import workspace_base_path
from fileio.project_io import load_project, save_project
from model.commands import (
    AddShapeCommand, RemoveShapesCommand, SetGroupCommand, ShapeEditCommand,
    duplicate_shape,
)
from model.project import Project
from model.shapes import Shape, group_members, new_group_id, shape_to_dict
from model.output import Output
from media.clip_pool import reset_clip_pool
from model.project_store import ProjectStore, available_screens, find_screen
from render.test_pattern import PATTERNS
from ui.canvas_editor import CanvasEditor
from ui.output_panel import OutputDialog
from ui.object_list import ObjectList
from ui.problem_log import ProblemLog
from ui.transport_bar import TransportBar
from ui.property_panel import PropertyPanel
from ui.projection_window import ProjectionWindow
from ui.widgets import ArrowSlider, NoScrollComboBox


logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    # Often enough that a crash costs a moment's work, rarely enough that the
    # write never lands in the middle of a drag.
    AUTOSAVE_INTERVAL_MS = 20_000

    def __init__(self) -> None:
        super().__init__()
        # One stack per window; cleared when the active project is swapped,
        # since commands hold references into a specific project's shape list.
        self.undo_stack = QUndoStack(self)

        # One project for the whole rig. Projectors are outputs onto its
        # canvas, not separate workspaces.
        self._output_preview = None

        # Warnings and errors used to end at a console nobody is watching.
        # Installed before anything else here, so a failure during startup -
        # a session file that will not parse, a driver that refuses - is
        # caught rather than missed.
        self.problem_log = ProblemLog(self)
        self.problem_log.install()
        self.problem_log.problem_added.connect(self._on_problem)

        self.store = ProjectStore(self)
        self.store.set_base_path(self._get_workspace_base_path())

        # Autosave writes the session copy, never the operator's own file, and
        # deliberately leaves `dirty` set: the work is safe from a crash but it
        # has not been saved, and the close prompt still has to say so.
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(self.AUTOSAVE_INTERVAL_MS)
        self._autosave_timer.timeout.connect(self._autosave)
        self._autosave_timer.start()

        # One projection window per output.
        self._projection_windows: Dict[str, ProjectionWindow] = {}
        self._output_dialog: Optional[OutputDialog] = None
        self._projecting = False

        # Track known screens to detect new ones
        self._known_screens: set = set()
        self._connected_project: Optional[Project] = None

        self._build_ui()
        self._connect_signals()
        self._initialize_screens()
        self._refresh_object_list()

    def _get_workspace_base_path(self) -> str:
        """Where the session copy lives.

        `app_paths` owns this because the directory moved when the app started
        naming itself, and the move has to carry the previous session with it.
        """
        return workspace_base_path()

    def _build_ui(self) -> None:
        self.setWindowTitle(APP_NAME)
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
        self.action_mesh = QAction("Mesh", self)
        self.action_mesh.setToolTip(
            "A surface that bends: a grid of control points for columns,\n"
            "cylinders, domes and anything else four corners cannot describe."
        )

        for action in (self.action_select, self.action_polygon, self.action_circle, self.action_mesh):
            action.setCheckable(True)
            self.action_select.setChecked(True)

        tool_group = QActionGroup(self)
        tool_group.setExclusive(True)
        tool_group.addAction(self.action_select)
        tool_group.addAction(self.action_polygon)
        tool_group.addAction(self.action_circle)
        tool_group.addAction(self.action_mesh)

        toolbar.addAction(self.action_select)
        toolbar.addAction(self.action_polygon)
        toolbar.addAction(self.action_circle)
        toolbar.addAction(self.action_mesh)

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

        self.action_mask = QAction("Mask", self)
        self.action_mask.setShortcut(QKeySequence("Ctrl+M"))
        self.action_mask.setShortcutContext(Qt.ApplicationShortcut)
        self.action_mask.setToolTip(
            "Cut a hole in the selected surface - a window, a doorway, a pillar\n"
            "in front of the wall. Drag the red corners to shape it (Ctrl+M)"
        )
        self.addAction(self.action_mask)
        toolbar.addAction(self.action_mask)

        self.action_group = QAction("Group", self)
        self.action_group.setShortcut(QKeySequence("Ctrl+G"))
        self.action_group.setShortcutContext(Qt.ApplicationShortcut)
        self.action_group.setToolTip(
            "Tie the selected surfaces together so a drag moves them as one\n"
            "- a window frame, a row of columns (Ctrl+G)"
        )
        self.action_ungroup = QAction("Ungroup", self)
        self.action_ungroup.setShortcut(QKeySequence("Ctrl+Shift+G"))
        self.action_ungroup.setShortcutContext(Qt.ApplicationShortcut)
        self.action_ungroup.setToolTip("Break the group apart again (Ctrl+Shift+G)")
        self.addAction(self.action_group)
        self.addAction(self.action_ungroup)
        toolbar.addAction(self.action_group)
        toolbar.addAction(self.action_ungroup)

        # The panic button. Deliberately its own control rather than a mode of
        # the transport: pausing leaves the last frame on the wall, and what
        # you need when something goes wrong is darkness.
        self.action_blackout = QAction("Blackout", self)
        self.action_blackout.setCheckable(True)
        self.action_blackout.setShortcut(QKeySequence("B"))
        self.action_blackout.setShortcutContext(Qt.ApplicationShortcut)
        self.action_blackout.setToolTip(
            "Kill every projector at once, without stopping the show (B).\n"
            "Pausing would leave the last frame up; this goes dark."
        )
        self.addAction(self.action_blackout)

        self.action_preview = QAction("Preview", self)
        self.action_preview.setToolTip(
            "Watch what a projector shows - region, keystone, blend and colour\n"
            "- without turning the projector on"
        )
        self.addAction(self.action_preview)

        self.action_help = QAction("Help", self)
        self.action_help.setShortcut(QKeySequence("F1"))
        self.action_help.setShortcutContext(Qt.ApplicationShortcut)
        self.action_help.setToolTip("Every gesture and shortcut, on one sheet (F1)")
        self.addAction(self.action_help)

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

        self.action_outputs = QAction("Outputs...", self)
        self.action_outputs.setToolTip(
            "Calibrate the projectors: canvas region, keystone, edge blend and colour"
        )
        toolbar.addAction(self.action_outputs)
        toolbar.addAction(self.action_preview)
        toolbar.addAction(self.action_blackout)

        self.outputs_label = QLabel("")
        self.outputs_label.setStyleSheet("color: #00d4aa; padding: 0 8px;")
        toolbar.addWidget(self.outputs_label)

        # Missing media is the thing you most want to find out about before
        # doors, not during. It sits in the toolbar and opens the fix.
        self.missing_button = QPushButton()
        self.missing_button.setObjectName("warningButton")
        self.missing_button.setFlat(True)
        self.missing_button.setVisible(False)
        self.missing_button.setToolTip("Some media is not where the project expects it")
        self.missing_button.clicked.connect(lambda: self._open_relink_dialog())
        toolbar.addWidget(self.missing_button)

        # Sits next to the missing-media count, and stays out of the way until
        # there is something to say.
        self.problems_button = QPushButton()
        self.problems_button.setObjectName("warningButton")
        self.problems_button.setFlat(True)
        self.problems_button.setVisible(False)
        self.problems_button.clicked.connect(lambda: self._open_problem_dialog())
        toolbar.addWidget(self.problems_button)

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

        self.pattern_combo = NoScrollComboBox()
        self.pattern_combo.setFixedWidth(140)
        for value, label in PATTERNS:
            self.pattern_combo.addItem(label, value)
        self.pattern_combo.setEnabled(False)
        toolbar.addWidget(self.pattern_combo)

        toolbar.addSeparator()

        # The show clock, next to the projection controls it governs.
        self.transport_bar = TransportBar(self.project, self)
        toolbar.addWidget(self.transport_bar)

        toolbar.addSeparator()
        toolbar.addAction(self.action_help)

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

        # These were menu items with no keys behind them, while the help sheet
        # has been promising them all along - the app was telling the operator
        # something that was not true.
        for action, sequence in (
            (self.action_new, QKeySequence.New),
            (self.action_open, QKeySequence.Open),
            (self.action_save, QKeySequence.Save),
            (self.action_save_as, QKeySequence.SaveAs),
        ):
            action.setShortcut(sequence)
            action.setShortcutContext(Qt.ApplicationShortcut)
            self.addAction(action)
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

        # The About box is where this program states its licence. Without it a
        # packaged build would carry no notice at all - the LICENSE file does
        # not travel into a frozen binary on its own.
        help_menu = self.menuBar().addMenu("Help")
        self.action_about = QAction(f"About {APP_NAME}", self)
        help_menu.addAction(self.action_help)
        help_menu.addSeparator()
        help_menu.addAction(self.action_about)

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
        self.action_mesh.triggered.connect(lambda _checked=False: self._set_tool("mesh"))
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
        self.action_mask.triggered.connect(lambda _checked=False: self._mask_selected())
        self.action_group.triggered.connect(lambda _checked=False: self._group_selected())
        self.action_ungroup.triggered.connect(lambda _checked=False: self._ungroup_selected())
        self.action_help.triggered.connect(lambda _checked=False: self._show_help())
        self.action_about.triggered.connect(lambda _checked=False: self._show_about())
        self.transport_bar.changed.connect(self.canvas.viewport().update)

        self.action_play_pause = QAction("Play/Pause", self)
        self.action_play_pause.setShortcut(QKeySequence(Qt.Key_Space))
        self.action_play_pause.setShortcutContext(Qt.ApplicationShortcut)
        self.action_play_pause.triggered.connect(lambda _c=False: self.transport_bar.toggle())
        self.addAction(self.action_play_pause)

        self.canvas.selection_changed.connect(self._on_canvas_selection)
        self.canvas.tool_changed.connect(self._on_canvas_tool_changed)
        self.canvas.handle_mode_changed.connect(self._on_handle_mode_changed)
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
        self.action_outputs.triggered.connect(lambda _c=False: self._open_output_dialog())
        self.action_preview.triggered.connect(lambda _c=False: self._show_output_preview())
        self.action_blackout.toggled.connect(self._on_blackout_toggled)

        self.action_relink = QAction("Relink media...", self)
        self.action_relink.setToolTip("Point the project at media that has moved")
        self.action_relink.triggered.connect(lambda _c=False: self._open_relink_dialog())
        self.addAction(self.action_relink)

    def _initialize_screens(self) -> None:
        """Load the session project and make sure it has somewhere to project."""
        for screen in QGuiApplication.screens():
            self._known_screens.add(screen.name())

        project = self.store.load()
        self._set_project(project)
        if self.store.recovered_unsaved:
            where = project.path or "an unsaved project"
            self.statusBar().showMessage(
                f"Recovered unsaved changes to {where} - save to keep them", 12000
            )

        # A project with no output cannot show anything; give it one aimed at
        # whatever display is attached.
        if not project.outputs:
            project.outputs = [Output(name="Projector 1")]
        for output in project.outputs:
            if output.screen_id is None or find_screen(output.screen_id) is None:
                screens = available_screens()
                if screens:
                    output.screen_id = screens[0][1]

        self._update_outputs_label()
        self.canvas.fit_to_canvas()

    def _report_failure(self, what: str, path: str, exc: Exception) -> None:
        """Say it in a box, and keep it in the list.

        The box is what stops the operator carrying on as if it worked; the
        list is what they can still read ten minutes later when they wonder
        what that message said.
        """
        detail = f"{what}:\n{path}\n\n{exc}"
        logger.error("%s: %s (%s)", what, path, exc)
        box = self._styled_message_box(
            "Error", detail, QMessageBox.Critical, QMessageBox.Ok, QMessageBox.Ok
        )
        box.exec()

    def _on_problem(self, problem) -> None:
        """Say it once in the status bar, and keep it in the list."""
        self._refresh_problems_button()
        self.statusBar().showMessage(problem.message, 8000 if problem.is_error else 5000)

    def _refresh_problems_button(self) -> None:
        count = self.problem_log.count()
        self.problems_button.setVisible(bool(count))
        if count:
            errors = self.problem_log.error_count()
            self.problems_button.setText(f"{'✕' if errors else '⚠'} {count} problem(s)")
            latest = self.problem_log.latest()
            self.problems_button.setToolTip(
                (latest.message if latest else "") + "\n\nClick for the full list."
            )

    def _open_problem_dialog(self) -> None:
        from ui.problem_log import ProblemDialog

        dialog = ProblemDialog(self.problem_log, self)
        dialog.exec()
        self._refresh_problems_button()

    def _open_relink_dialog(self) -> None:
        from ui.relink_dialog import RelinkDialog

        dialog = RelinkDialog(self.project, self.undo_stack, self)
        dialog.exec()
        if dialog.relinked:
            self.statusBar().showMessage(f"Relinked {dialog.relinked} surface(s)", 5000)
        self._update_missing_media()
        self._refresh_object_list()
        self.canvas.viewport().update()

    def _update_missing_media(self) -> None:
        """Keep the toolbar honest about what the project cannot find."""
        from media.availability import forget, missing_paths

        forget()
        paths = missing_paths(self.project.shapes)
        self.missing_button.setVisible(bool(paths))
        if paths:
            self.missing_button.setText(f"⚠ {len(paths)} missing")
            self.missing_button.setToolTip(
                "Media not found:\n" + "\n".join(paths[:8]) + "\n\nClick to relink."
            )

    def _update_outputs_label(self) -> None:
        outputs = self.project.outputs
        live = sum(1 for o in outputs if o.enabled)
        canvas = self.project.canvas
        self.outputs_label.setText(
            f"{live}/{len(outputs)} outputs   canvas {canvas.width}x{canvas.height}"
        )

    def _open_output_dialog(self) -> None:
        dialog = OutputDialog(self.project, self.undo_stack, self)
        dialog.outputs_changed.connect(self._on_outputs_changed)
        dialog.preview_requested.connect(
            lambda output_id: self._show_output_preview(output_id, parent=dialog)
        )
        dialog.output_selected.connect(self._on_output_selected)
        self._output_dialog = dialog
        dialog.exec()
        self._output_dialog = None

    def _on_output_selected(self, output_id) -> None:
        preview = getattr(self, "_output_preview", None)
        if preview is not None and preview.isVisible():
            preview.show_output(output_id)

    def _show_output_preview(self, output_id=None, parent=None) -> None:
        """Open the live view of one projector.

        Parented to the outputs dialog when it asked, because that dialog is
        modal and a preview outside it would render but not respond.
        """
        from ui.output_preview import OutputPreview

        preview = getattr(self, "_output_preview", None)
        if preview is not None and parent is not None and preview.parent() is not parent:
            preview.close()
            preview = None
        if preview is None:
            preview = OutputPreview(self.project, parent or self)
            self._output_preview = preview
        preview.refresh()
        if output_id:
            preview.show_output(output_id)
        preview.show()
        preview.raise_()
        preview.activateWindow()

    def _on_outputs_changed(self) -> None:
        self._update_outputs_label()
        # Live projection windows follow the calibration as it is tuned.
        self._sync_projection_windows()

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

    def _has_unsaved_changes(self) -> bool:
        """True only if the project changed since it was last saved or loaded."""
        return bool(getattr(self.project, "dirty", False))

    def _rescan_screens(self) -> None:
        """Re-read the attached displays."""
        self._update_outputs_label()
        self._sync_projection_windows()
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

    def _mask_selected(self) -> None:
        item = self.canvas._current_selected_item()
        if item is None:
            self.statusBar().showMessage("Select a surface to mask", 3000)
            return
        if not self.canvas.add_mask(item):
            self.statusBar().showMessage("This surface cannot be masked", 3000)
            return
        self.property_panel.set_shape(self.project.get_shape(item.model.id))

    def _on_blackout_toggled(self, on: bool) -> None:
        self.project.set_blackout(on)
        self.canvas.viewport().update()
        self.statusBar().showMessage(
            "BLACKOUT - every projector is dark (B to restore)" if on else "Blackout cleared",
            0 if on else 3000,
        )

    def _show_help(self) -> None:
        """Non-modal: a reference you can leave open while you work."""
        if getattr(self, "_help_dialog", None) is None:
            from ui.help_dialog import HelpDialog

            self._help_dialog = HelpDialog(self)
        self._help_dialog.show()
        self._help_dialog.raise_()
        self._help_dialog.activateWindow()

    def _show_about(self) -> None:
        from ui.about_dialog import AboutDialog

        AboutDialog(self).exec()

    def _group_selected(self) -> None:
        """Tie the selected surfaces together. Two is the minimum that means
        anything - a group of one is just a shape."""
        ids = self.canvas.selected_shape_ids()
        if len(ids) < 2:
            self.statusBar().showMessage("Select two or more surfaces to group", 3000)
            return
        group_id = new_group_id()
        self.undo_stack.push(
            SetGroupCommand(self.project, {shape_id: group_id for shape_id in ids}, "Group")
        )
        self.canvas.select_shape(ids[0])

    def _ungroup_selected(self) -> None:
        ids = [
            shape.id
            for shape_id in self.canvas.selected_shape_ids()
            for shape in group_members(self.project.shapes, self._group_of(shape_id))
        ]
        if not ids:
            self.statusBar().showMessage("Select a grouped surface to ungroup", 3000)
            return
        self.undo_stack.push(
            # `fromkeys` already maps every id to None, and already drops the
            # duplicates a group's members arrive with.
            SetGroupCommand(self.project, dict.fromkeys(ids), "Ungroup")
        )

    def _group_of(self, shape_id: str):
        shape = self.project.get_shape(shape_id)
        return getattr(shape, "group_id", None) if shape else None

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

    def _on_canvas_tool_changed(self, tool: str) -> None:
        """Follow the canvas back to Select after it places a shape."""
        action = {
            "select": self.action_select,
            "polygon": self.action_polygon,
            "circle": self.action_circle,
            "mesh": self.action_mesh,
        }.get(tool)
        if action is not None and not action.isChecked():
            action.setChecked(True)

    def _on_handle_mode_changed(self, point_mode: bool) -> None:
        self.statusBar().showMessage(
            "Points: drag the corners, curve and mask controls"
            if point_mode
            else "Transform: drag the box grips to scale, the top grip to rotate",
            4000,
        )

    def _set_tool(self, tool: str) -> None:
        self.canvas.set_tool(tool)
        messages = {
            "polygon": "Click on canvas to create polygon, adjust via vertices",
            "circle": "Click on canvas to create circle, adjust via handles",
            "select": "Selection active. Drag to pan, Shift+drag to move shapes"
        }
        self.statusBar().showMessage(messages.get(tool, ""), 3000)

    def _refresh_object_list(self) -> None:
        self._update_missing_media()
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
        """Make `project` the active one, and tell the store."""
        if not project.outputs:
            project.outputs = [Output(name="Projector 1")]
        self.store.set_project(project)
        self._set_project(project)
        self._update_outputs_label()

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
            self._report_failure("Could not open project", path, exc)
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
            # Modal on purpose. Everything else can be a status message the
            # operator catches up with; a save that did not happen is the one
            # they have to know about before doing anything else.
            self._report_failure("Could not save project", path, exc)

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
        # The show clock belongs to the project, so the transport bar has to
        # follow it here - the single place `self.project` changes. Hooking it
        # to one of the callers instead left the bar driving the project that
        # had just been replaced.
        if hasattr(self, "transport_bar"):
            self.transport_bar.set_project(project)
        if hasattr(self, "action_blackout"):
            self.action_blackout.setChecked(project.blackout)
        # Disconnect from whichever project we actually attached to, not from
        # self.project: a project swap repoints that attribute before we get
        # here, and the previous one can stay alive elsewhere, so leaving
        # connections behind would pile up a new set on every swap.
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
        """Open every enabled output, or close them all if any are open."""
        if self._projecting:
            self._projecting = False
            self._close_projection_windows()
            self.statusBar().showMessage("Projection stopped", 2000)
            return

        self._projecting = True
        opened = self._sync_projection_windows()
        if opened:
            self.statusBar().showMessage(f"Projecting to {opened} output(s)", 3000)
        else:
            self.statusBar().showMessage(
                "No enabled output has a screen assigned - see Outputs...", 4000
            )

    def _close_projection_windows(self) -> None:
        for window in list(self._projection_windows.values()):
            window.close()
        self._projection_windows.clear()

    def _sync_projection_windows(self) -> int:
        """Match the open windows to the enabled outputs. Returns how many.

        Called whenever the outputs change, so tuning keystone or blend with
        the projectors live shows up on the wall immediately - which is the
        only way calibration can actually be done.
        """
        if not self._projecting:
            # Editing outputs while stopped must not start a show. Visibility
            # used to stand in for this, which was incidental - and made the
            # behaviour untestable without a mapped window.
            self._close_projection_windows()
            return 0

        wanted = {}
        for output in self.project.outputs:
            if not output.enabled:
                continue
            screen_info = find_screen(output.screen_id)
            if screen_info is None:
                continue
            wanted[output.id] = (output, screen_info)

        for output_id in list(self._projection_windows):
            if output_id not in wanted:
                self._projection_windows.pop(output_id).close()

        all_screens = QGuiApplication.screens()
        for output_id, (output, screen_info) in wanted.items():
            index = screen_info[0]
            screen = all_screens[index] if index < len(all_screens) else None
            window = self._projection_windows.get(output_id)
            if window is None:
                window = ProjectionWindow(self.project, output=output)
                self._projection_windows[output_id] = window
                window.open_on_screen(screen)
            else:
                # The window holds the same Output object the dialog edits,
                # so calibration changes need no plumbing beyond a repaint.
                window.renderer.output = output
                window.renderer.update()

        return len(self._projection_windows)

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
        self._update_outputs_label()
        self.statusBar().showMessage(
            f"Screen connected: {screen_name} ({geometry.width()}x{geometry.height()}) "
            f"- assign it to an output under Outputs...",
            8000,
        )

    def _on_screen_removed(self, screen) -> None:
        """Handle screen disconnected."""
        self._known_screens.discard(screen.name())
        # Any window aimed at the vanished display closes with it; the output
        # keeps its screen id so plugging the projector back in restores it.
        self._sync_projection_windows()
        self._update_outputs_label()
        self.statusBar().showMessage(f"Screen disconnected: {screen.name()}", 5000)

    def _on_primary_screen_changed(self, screen) -> None:
        """Handle primary screen change."""
        self._update_outputs_label()

    def _autosave(self) -> None:
        """Keep a crash from costing more than the last twenty seconds."""
        if not self.project.dirty:
            return
        self.store.save(mark_saved=False)

    def closeEvent(self, event) -> None:
        """Handle app close - save all workspaces."""
        if not self._confirm_discard("Quit anyway?"):
            event.ignore()
            return

        self.store.save()
        # Decoder threads are daemons, but a clean stop releases the capture
        # devices - a camera left open is one the next app cannot have.
        reset_clip_pool()
        # Clean up projection windows
        for pw in self._projection_windows.values():
            pw.close()
        self._projection_windows.clear()
        super().closeEvent(event)

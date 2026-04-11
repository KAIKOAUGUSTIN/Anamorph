"""Workspace manager for handling multiple projects per screen."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional
import json

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QGuiApplication

from pm.model.project import Project


class WorkspaceManager(QObject):
    """Manages multiple workspaces (projects) for different projection screens.

    Each screen (except the primary/editor screen) has its own workspace.
    When switching screens, the corresponding project is loaded.
    """

    # Signals
    workspace_changed = Signal(str)  # Emitted when active workspace changes
    workspace_added = Signal(str)    # Emitted when a new workspace is created
    workspace_removed = Signal(str)  # Emitted when a workspace is removed

    # Workspace storage directory
    WORKSPACE_DIR = "workspaces"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._workspaces: Dict[str, Project] = {}
        self._current_screen_id: Optional[str] = None
        self._base_path: Optional[str] = None

    def set_base_path(self, path: str) -> None:
        """Set the base path for saving workspaces."""
        self._base_path = path
        self._load_workspaces()

    def _load_workspaces(self) -> None:
        """Load existing workspaces from disk."""
        if not self._base_path:
            return

        workspace_dir = Path(self._base_path) / self.WORKSPACE_DIR
        if not workspace_dir.exists():
            workspace_dir.mkdir(parents=True, exist_ok=True)
            return

        for workspace_file in workspace_dir.glob("*.workspace.json"):
            try:
                screen_id = workspace_file.stem.replace(".workspace", "")
                with open(workspace_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                project = Project.from_dict(data)
                project.path = str(workspace_file)
                self._workspaces[screen_id] = project
            except Exception as e:
                print(f"Failed to load workspace {workspace_file}: {e}")

    def _save_workspace(self, screen_id: str) -> None:
        """Save a workspace to disk."""
        if not self._base_path:
            return

        workspace_dir = Path(self._base_path) / self.WORKSPACE_DIR
        workspace_dir.mkdir(parents=True, exist_ok=True)

        project = self._workspaces.get(screen_id)
        if not project:
            return

        workspace_file = workspace_dir / f"{screen_id}.workspace.json"
        try:
            with open(workspace_file, "w", encoding="utf-8") as f:
                json.dump(project.to_dict(), f, indent=2)
            project.path = str(workspace_file)
        except Exception as e:
            print(f"Failed to save workspace {screen_id}: {e}")

    def get_or_create_workspace(self, screen_id: str, screen_name: str = "") -> Project:
        """Get or create a workspace for the given screen."""
        if screen_id not in self._workspaces:
            project = Project()
            project.name = f"Project - {screen_name or screen_id}"
            self._workspaces[screen_id] = project
            self.workspace_added.emit(screen_id)
        return self._workspaces[screen_id]

    def get_workspace(self, screen_id: str) -> Optional[Project]:
        """Get a workspace by screen ID."""
        return self._workspaces.get(screen_id)

    def switch_to_screen(self, screen_id: str, screen_name: str = "") -> Project:
        """Switch to a screen and return its workspace."""
        # Save current workspace before switching
        if self._current_screen_id and self._current_screen_id in self._workspaces:
            self._save_workspace(self._current_screen_id)

        self._current_screen_id = screen_id
        project = self.get_or_create_workspace(screen_id, screen_name)
        self.workspace_changed.emit(screen_id)
        return project

    def get_current_workspace(self) -> Optional[Project]:
        """Get the currently active workspace."""
        if self._current_screen_id:
            return self._workspaces.get(self._current_screen_id)
        return None

    def get_current_screen_id(self) -> Optional[str]:
        """Get the currently selected screen ID."""
        return self._current_screen_id

    def get_available_screens(self) -> List[tuple]:
        """Get list of available screens for projection (excluding primary).

        Returns list of (index, screen_id, screen_name, geometry) tuples.
        """
        screens = []
        all_screens = QGuiApplication.screens()
        primary = QGuiApplication.primaryScreen()

        for idx, screen in enumerate(all_screens):
            # Skip primary screen (index 0) - it's for the editor
            if screen == primary:
                continue

            screen_id = f"screen_{idx}"
            screen_name = screen.name()
            geometry = screen.geometry()
            screens.append((idx, screen_id, screen_name, geometry))

        return screens

    def save_all_workspaces(self) -> None:
        """Save all workspaces to disk."""
        for screen_id in self._workspaces:
            self._save_workspace(screen_id)

    def duplicate_workspace(self, source_screen_id: str, target_screen_id: str) -> Optional[Project]:
        """Duplicate a workspace to another screen."""
        source = self._workspaces.get(source_screen_id)
        if not source:
            return None

        # Deep copy the project
        new_project = Project.from_dict(source.to_dict())
        new_project.path = None  # Will be set when saved
        self._workspaces[target_screen_id] = new_project
        self._save_workspace(target_screen_id)
        return new_project

    def remove_workspace(self, screen_id: str) -> None:
        """Remove a workspace (does not delete from disk)."""
        if screen_id in self._workspaces:
            del self._workspaces[screen_id]
            self.workspace_removed.emit(screen_id)

    def has_workspace(self, screen_id: str) -> bool:
        """Check if a workspace exists for the given screen."""
        return screen_id in self._workspaces

    def get_workspace_count(self) -> int:
        """Get the number of workspaces."""
        return len(self._workspaces)

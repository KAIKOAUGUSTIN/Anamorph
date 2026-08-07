"""Where the single project lives on disk, and what screens are available.

This replaces the per-screen workspace manager. That design gave every display
its own separate Project, which made a second projector a second *artwork*
rather than a second view of the same one - and left edge blending with
nothing to blend. A rig has one canvas; the projectors are outputs onto it.
"""

from __future__ import annotations

import json
import os
import logging
from pathlib import Path
from typing import List, Optional, Tuple

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QGuiApplication

from pm.model.output import Output
from pm.io.media_paths import base_dir_for, rewrite_media_paths, to_absolute
from pm.model.project import Project

logger = logging.getLogger(__name__)

PROJECT_FILENAME = "session.pmap.json"
# Bookkeeping the session file carries and a `.pmap.json` must never contain:
# a project that records its own path breaks the moment it is moved.
SESSION_KEY = "_session"
LEGACY_WORKSPACE_DIR = "workspaces"

# (index, screen_id, screen_name, geometry)
ScreenInfo = Tuple[int, str, str, object]


def screen_id_for(index: int) -> str:
    return f"screen_{index}"


def available_screens(include_primary: bool = True) -> List[ScreenInfo]:
    """Every attached display.

    The primary screen is included now. It used to be filtered out because it
    held the editor, but an output is free to target any display - a single
    projector plugged into a laptop is the commonest rig there is, and hiding
    it made that setup impossible to select.
    """
    screens: List[ScreenInfo] = []
    primary = QGuiApplication.primaryScreen()
    for index, screen in enumerate(QGuiApplication.screens()):
        if not include_primary and screen == primary:
            continue
        screens.append((index, screen_id_for(index), screen.name(), screen.geometry()))
    return screens


def find_screen(screen_id: Optional[str]) -> Optional[ScreenInfo]:
    if not screen_id:
        return None
    for info in available_screens():
        if info[1] == screen_id:
            return info
    return None


def screen_geometry(screen_id: Optional[str]):
    """The pixel geometry of a screen, or None when it is gone."""
    info = find_screen(screen_id)
    return info[3] if info else None


class ProjectStore(QObject):
    """Holds the one project and knows where to persist it."""

    project_replaced = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._base_path: Optional[Path] = None
        self._project = Project()
        # Set by `load` when the restored session held work that never made it
        # to the operator's own file. The window says so once, in the status
        # bar - a modal on startup would be answered without being read.
        self.recovered_unsaved = False

    @property
    def project(self) -> Project:
        return self._project

    def set_base_path(self, path: str) -> None:
        self._base_path = Path(path)
        self._base_path.mkdir(parents=True, exist_ok=True)

    def set_project(self, project: Project) -> None:
        self._project = project
        self.project_replaced.emit()

    def session_path(self) -> Optional[Path]:
        return self._base_path / PROJECT_FILENAME if self._base_path else None

    def load(self) -> Project:
        """The last session, a migrated legacy workspace, or a fresh project."""
        path = self.session_path()
        if path and path.exists():
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                session = data.get(SESSION_KEY) or {}
                base = session.get("source_path")
                rewrite_media_paths(data, lambda p: to_absolute(p, base_dir_for(base)))
                project = Project.from_dict(data)
                # The session used to claim it *was* the project file, so the
                # next Ctrl+S wrote over the copy in app data and left the
                # operator's own file untouched and stale.
                project.path = base
                project.mark_saved()
                if session.get("dirty"):
                    # Work that never reached disk: the app was closed hard,
                    # or crashed. It is back, and it is still unsaved.
                    project.dirty = True
                    self.recovered_unsaved = True
                self._project = project
                return project
            except Exception as exc:
                logger.warning("Could not read %s: %s", path, exc)

        migrated = self._migrate_legacy_workspaces()
        if migrated is not None:
            self._project = migrated
            return migrated

        self._project = Project()
        self._project.outputs = [Output(name="Projector 1")]
        return self._project

    def save(self, mark_saved: bool = True) -> None:
        """Write the session copy.

        `mark_saved=False` is the autosave path: the work is safe from a crash
        but it has *not* reached the operator's own file, and clearing the
        dirty flag here would stop the close prompt from ever asking again.
        """
        path = self.session_path()
        if not path:
            return
        try:
            data = self._project.to_dict()
            # The session lives in app data and the media does not, so its
            # paths stay absolute - but it has to remember which file the
            # project came from, or a restored session forgets where to save.
            data[SESSION_KEY] = {
                "source_path": self._project.path,
                "dirty": bool(self._project.dirty) and not mark_saved,
            }
            temp = path.with_suffix(path.suffix + ".tmp")
            with open(temp, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
            if mark_saved:
                self._project.mark_saved()
        except Exception as exc:
            logger.warning("Could not write %s: %s", path, exc)

    def _migrate_legacy_workspaces(self) -> Optional[Project]:
        """Fold the old one-project-per-screen files into a single project.

        The workspace with the most shapes is taken as the artwork - it is the
        one that was actually worked on - and every screen that had a workspace
        becomes an output onto it. The old files are left alone rather than
        deleted, so a mistaken merge is recoverable by hand.
        """
        if not self._base_path:
            return None
        legacy_dir = self._base_path / LEGACY_WORKSPACE_DIR
        if not legacy_dir.exists():
            return None

        loaded: List[Tuple[str, Project]] = []
        for workspace_file in sorted(legacy_dir.glob("*.workspace.json")):
            try:
                with open(workspace_file, "r", encoding="utf-8") as handle:
                    project = Project.from_dict(json.load(handle))
                loaded.append((workspace_file.stem.replace(".workspace", ""), project))
            except Exception as exc:
                logger.warning("Skipping legacy workspace %s: %s", workspace_file, exc)

        if not loaded:
            return None

        screen_id, project = max(loaded, key=lambda pair: len(pair[1].shapes))
        project.outputs = [
            Output(name=f"Projector {i + 1}", screen_id=sid)
            for i, (sid, _) in enumerate(loaded)
        ]
        # Keep the richest workspace's own screen first; it is the one the
        # operator was looking at.
        project.outputs.sort(key=lambda o: o.screen_id != screen_id)
        project.path = None
        project.touch()
        logger.info("Migrated %d legacy workspaces into one project", len(loaded))
        return project

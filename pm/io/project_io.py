from __future__ import annotations

import json
import os
import logging
import shutil
from typing import Any, Dict

from pm.io.media_paths import base_dir_for, rewrite_media_paths, to_absolute, to_portable
from pm.model.project import Project

logger = logging.getLogger(__name__)

# Kept next to the project as `show.pmap.json.bak`. Overwriting a good file
# with a bad one is the failure that hurts, and it is silent: the operator
# finds out when the show does not open.
BACKUP_SUFFIX = ".bak"


def save_project(project: Project, path: str, backup: bool = True) -> None:
    """Write the project, with media paths made relative to `path`.

    The previous contents are kept as a `.bak` alongside. Writing goes to a
    temporary file first and is then moved into place, so a crash mid-write
    cannot leave a half-written project where the good one used to be.
    """
    data: Dict[str, Any] = project.to_dict()
    base = base_dir_for(path)
    rewrite_media_paths(data, lambda p: to_portable(p, base))

    if backup and os.path.exists(path):
        try:
            shutil.copy2(path, path + BACKUP_SUFFIX)
        except OSError as exc:
            # A backup that cannot be written must not stop the save: losing
            # the safety net is bad, losing the work is worse. It is worth
            # saying so, though - a read-only show folder is something the
            # operator wants to hear about before the next save matters.
            logger.warning("Could not back up %s: %s", path, exc)

    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)

    project.path = path
    project.mark_saved()


def load_project(path: str) -> Project:
    """Read a project, resolving its media paths against its own folder."""
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    base = base_dir_for(path)
    rewrite_media_paths(data, lambda p: to_absolute(p, base))

    project = Project.from_dict(data)
    project.path = path
    project.mark_saved()
    return project

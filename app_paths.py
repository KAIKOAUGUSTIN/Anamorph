# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Where the session copy lives, and how it survives being renamed.

`QStandardPaths` derives `AppDataLocation` from the application and
organization names. Setting those - which the app now does, so the folder is
called Anamorph instead of whatever the interpreter happened to be called -
moves the directory. The session copy is the crash net: an operator who has
worked for an hour without saving has their work *only* there, and a release
that silently relocated it would come up empty exactly once, which is the one
time it matters.

So the move is performed rather than merely allowed. `app_main` records where
the data used to live before it renames anything, and the first run under the
new name carries the old session across.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QStandardPaths

logger = logging.getLogger(__name__)

# The folder the session used to sit in, under an AppDataLocation that was
# named after the running executable because the app set no name of its own.
LEGACY_DIR_NAME = "ProjectionMapper"

_legacy_app_data: Optional[str] = None


def remember_legacy_app_data() -> None:
    """Capture the pre-rename data location.

    Must be called *before* `setApplicationName`/`setOrganizationName`, since
    afterwards the old location is no longer computable - it depended on the
    executable's name, which differs between running from source and running
    a packaged build.
    """
    global _legacy_app_data
    _legacy_app_data = QStandardPaths.writableLocation(
        QStandardPaths.AppDataLocation
    ) or None


def _app_data_dir() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    if not base:
        base = QStandardPaths.writableLocation(QStandardPaths.HomeLocation)
    return Path(base)


def legacy_workspace_base() -> Optional[Path]:
    if _legacy_app_data is None:
        return None
    candidate = Path(_legacy_app_data) / LEGACY_DIR_NAME
    return candidate if candidate.is_dir() else None


def workspace_base_path() -> str:
    """The directory holding the session copy, created if missing.

    On the first run after the rename this also brings the previous session
    across, so the crash net is not reset by a version bump.
    """
    base = _app_data_dir()
    base.mkdir(parents=True, exist_ok=True)

    legacy = legacy_workspace_base()
    if legacy is not None and legacy.resolve() != base.resolve():
        _adopt(legacy, base)

    return str(base)


def _adopt(legacy: Path, base: Path) -> None:
    """Copy a previous session across, once, without overwriting anything.

    Copy rather than move: if the operator goes back to an older build, its
    session is still where it left it. The cost is one duplicated file, which
    is measured in kilobytes.
    """
    for source in legacy.iterdir():
        target = base / source.name
        if target.exists():
            # Already migrated, or the new location is in use. Either way the
            # newer state wins - re-copying would undo work.
            continue
        try:
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)
        except OSError as exc:
            logger.warning("Could not carry %s over from the previous version: %s",
                           source.name, exc)
        else:
            logger.info("Carried %s over from %s", source.name, legacy)

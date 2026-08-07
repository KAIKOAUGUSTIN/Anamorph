"""Where a project's media lives, written so the project can be moved.

A `.pmap.json` used to store absolute paths. Copy the show folder to the
machine that drives the projectors - which is what everyone does - and every
surface comes up blank, because `/home/kaio/shows/wall.mp4` does not exist
there. The paths are stored relative to the project file instead, so the
folder travels as one piece.

Only the file format is relative. The in-memory model always holds absolute
paths, because the image cache and the video decoder open them directly and
have no idea where the project came from.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Optional

# How far a relative path may climb before it stops being worth it. `show.pmap
# .json` next to a `media/` folder needs none; `shows/a.pmap.json` reaching a
# sibling `media/` needs one. Past a few hops the media is not really part of
# the project any more - a network mount, a shared library - and an absolute
# path survives a move better than `../../../..` does.
MAX_PARENT_HOPS = 3


def base_dir_for(project_path: Optional[str]) -> Optional[str]:
    """The folder a project's relative paths are measured from."""
    if not project_path:
        return None
    return os.path.dirname(os.path.abspath(project_path)) or None


def to_portable(path: str, base_dir: Optional[str]) -> str:
    """Absolute path -> relative to `base_dir`, when that is a good idea.

    Returns the path unchanged when there is no base, when it is already
    relative, or when relating the two would take more hops than it is worth -
    including the case of a different drive on Windows, where `relpath` simply
    refuses.
    """
    if not path or not base_dir or not os.path.isabs(path):
        return path
    try:
        relative = os.path.relpath(path, base_dir)
    except ValueError:
        return path
    hops = _parent_hops(relative)
    if hops > MAX_PARENT_HOPS:
        return path
    # Always forward slashes on the wire: a project written on Windows has to
    # open on the Linux box driving the projectors.
    return relative.replace(os.sep, "/")


def to_absolute(path: str, base_dir: Optional[str]) -> str:
    """Relative path -> absolute, against `base_dir`.

    An already-absolute path is left alone, so a project that points at a
    media server keeps pointing at it.
    """
    if not path or os.path.isabs(path):
        return path
    native = path.replace("/", os.sep)
    if not base_dir:
        return path
    return os.path.normpath(os.path.join(base_dir, native))


def _parent_hops(relative: str) -> int:
    hops = 0
    for part in relative.split(os.sep):
        if part == os.pardir:
            hops += 1
        else:
            break
    return hops


def rewrite_media_paths(data: Dict[str, Any], convert: Callable[[str], str]) -> Dict[str, Any]:
    """Run `convert` over every media path in a serialised project.

    Works on the dict rather than the model on purpose: saving must not
    rewrite the paths of the project the operator is still working in.
    """
    for shape in data.get("shapes", []) or []:
        media = shape.get("media")
        if isinstance(media, dict) and media.get("path"):
            media["path"] = convert(media["path"])
    library: List[str] = data.get("media_library") or []
    if library:
        data["media_library"] = [convert(entry) for entry in library]
    return data

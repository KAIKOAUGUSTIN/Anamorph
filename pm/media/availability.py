"""Which media a project can actually find.

A missing file used to be silent: `get_qimage` returned None, the decoder
failed to open, and the surface simply came up empty. On a wall, in the dark,
that reads as "I mapped it wrong" rather than "the file is not there" - and
the difference matters at five minutes to doors.

Answers are cached with a short life. This is asked once per repaint of the
layer list and once per status refresh; hitting the filesystem every time
would put a `stat` per surface into the frame budget, and a file that comes
back still shows up within a second or two.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional, Tuple

# Long enough to keep it off the hot path, short enough that plugging a drive
# back in is noticed while the operator is still looking at the screen.
CACHE_SECONDS = 1.0

_cache: Dict[str, Tuple[float, bool]] = {}


def media_exists(media: Any) -> bool:
    """True when this media reference points at something openable.

    A camera is "available" whenever it has a device index: whether the device
    answers is the decoder's problem, and probing it here would open and close
    the capture on every repaint.
    """
    if media is None or not getattr(media, "kind", None):
        return True
    path = getattr(media, "path", "")
    if not path:
        return True
    if media.kind == "camera":
        return True
    return _exists_cached(path)


def is_missing(media: Any) -> bool:
    return not media_exists(media)


def missing_shapes(shapes) -> List[Any]:
    """Every surface pointing at media that is not there."""
    return [shape for shape in shapes if is_missing(getattr(shape, "media", None))]


def missing_paths(shapes) -> List[str]:
    """The distinct paths that cannot be found, in the order first seen."""
    seen: List[str] = []
    for shape in missing_shapes(shapes):
        path = shape.media.path
        if path not in seen:
            seen.append(path)
    return seen


def _exists_cached(path: str) -> bool:
    now = time.monotonic()
    cached = _cache.get(path)
    if cached is not None and now - cached[0] < CACHE_SECONDS:
        return cached[1]
    try:
        found = os.path.isfile(path)
    except OSError:
        # A dead network mount raises rather than returning False.
        found = False
    _cache[path] = (now, found)
    return found


def forget(path: Optional[str] = None) -> None:
    """Drop cached answers. Called after a relink, and by tests."""
    if path is None:
        _cache.clear()
    else:
        _cache.pop(path, None)

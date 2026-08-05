"""Shared QImage cache for the editing viewport.

QGraphicsItem.paint runs on every viewport update, so decoding media from disk
inside it would re-read the file dozens of times a second while the user drags
a corner. Entries are keyed by path and invalidated by mtime, so replacing a
file on disk still shows up without restarting.
"""

from __future__ import annotations

import os
from typing import Dict, Optional, Tuple

from PySide6.QtGui import QImage

# path -> (mtime, image or None). Failures are cached too, otherwise a broken
# path costs a filesystem round trip on every repaint.
_cache: Dict[str, Tuple[float, Optional[QImage]]] = {}


def get_qimage(path: str) -> Optional[QImage]:
    """Decoded image for a path, or None if it is missing or unreadable."""
    if not path:
        return None

    try:
        mtime = os.path.getmtime(path)
    except OSError:
        _cache.pop(path, None)
        return None

    cached = _cache.get(path)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    image = QImage(path)
    if image.isNull():
        image = None
    _cache[path] = (mtime, image)
    return image


def clear() -> None:
    _cache.clear()

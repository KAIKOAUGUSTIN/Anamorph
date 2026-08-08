# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-only

"""Draw the application icon, and write the three formats a build needs.

The mark is the thing the app does: a square, corner-pinned. The faint outline
is where the image starts, the solid quad is where it lands on an off-axis
wall, and the four dots are the corners an operator drags. It reads at 16px as
a lopsided quadrilateral, which is enough to be recognisable in a taskbar.

Drawn with QPainter rather than a vector file from an editor, for the same
reason `render/test_pattern.py` is: the drawing is the source, it is diffable,
and nothing in the repository depends on a binary nobody can regenerate.

    python packaging/make_icon.py

Writes `assets/icon.png` (1024), `assets/icon.ico` (Windows) and
`assets/icon.icns` (macOS). Committed, because a build machine should not need
Qt to produce an icon that never changes.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QBrush, QColor, QGuiApplication, QImage, QLinearGradient, QPainter,
    QPainterPath, QPen,
)

SIZE = 1024

BACKDROP_TOP = QColor("#1b1f24")
BACKDROP_BOTTOM = QColor("#0e1114")
ACCENT = QColor("#00d4aa")
ACCENT_DIM = QColor("#00a080")
GHOST = QColor(0, 212, 170, 70)

# The unpinned square, and where its corners end up. Deliberately not a
# symmetric trapezoid: a projector is never perfectly square to the wall, and
# a symmetric shape reads as "cone" rather than "corner pin".
SOURCE = [(0.22, 0.22), (0.78, 0.22), (0.78, 0.78), (0.22, 0.78)]
PINNED = [(0.30, 0.15), (0.85, 0.31), (0.72, 0.87), (0.17, 0.66)]


def _path(points, size: int) -> QPainterPath:
    path = QPainterPath()
    path.moveTo(QPointF(points[0][0] * size, points[0][1] * size))
    for x, y in points[1:]:
        path.lineTo(QPointF(x * size, y * size))
    path.closeSubpath()
    return path


def draw(size: int = SIZE) -> QImage:
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)

    # Rounded backdrop, so the mark has a body of its own on any wallpaper.
    backdrop = QLinearGradient(0, 0, 0, size)
    backdrop.setColorAt(0.0, BACKDROP_TOP)
    backdrop.setColorAt(1.0, BACKDROP_BOTTOM)
    painter.setBrush(QBrush(backdrop))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(QRectF(0, 0, size, size), size * 0.22, size * 0.22)

    # Where the image starts: the square, before anything is dragged.
    ghost = QPen(GHOST, size * 0.012)
    ghost.setStyle(Qt.DashLine)
    painter.setPen(ghost)
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(_path(SOURCE, size))

    # Where it lands.
    fill = QLinearGradient(0, size * 0.15, size, size * 0.87)
    fill.setColorAt(0.0, QColor(0, 212, 170, 235))
    fill.setColorAt(1.0, QColor(0, 140, 120, 205))
    painter.setBrush(QBrush(fill))
    painter.setPen(QPen(ACCENT, size * 0.022, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.drawPath(_path(PINNED, size))

    # The corners you drag.
    painter.setPen(Qt.NoPen)
    for x, y in PINNED:
        painter.setBrush(QColor("#f2fbf8"))
        painter.drawEllipse(QPointF(x * size, y * size), size * 0.045, size * 0.045)
        painter.setBrush(ACCENT_DIM)
        painter.drawEllipse(QPointF(x * size, y * size), size * 0.022, size * 0.022)

    painter.end()
    return image


def main() -> int:
    QGuiApplication.instance() or QGuiApplication(sys.argv)

    assets = ROOT / "assets"
    assets.mkdir(exist_ok=True)

    master = assets / "icon.png"
    draw(SIZE).save(str(master), "PNG")

    # Pillow writes both container formats; Qt writes neither.
    from PIL import Image

    source = Image.open(master)
    # Windows reads the largest it needs from the set; 16 and 32 are drawn
    # separately by Qt rather than downscaled, because a 1024 mark reduced to
    # 16px turns to mud.
    small = {}
    for edge in (16, 32, 48):
        path = assets / f"_icon_{edge}.png"
        draw(edge).save(str(path), "PNG")
        small[edge] = Image.open(path)

    source.save(
        assets / "icon.ico",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    source.save(assets / "icon.icns")

    for edge in small:
        (assets / f"_icon_{edge}.png").unlink()

    for name in ("icon.png", "icon.ico", "icon.icns"):
        size_kb = (assets / name).stat().st_size / 1024
        print(f"{name:12} {size_kb:7.1f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

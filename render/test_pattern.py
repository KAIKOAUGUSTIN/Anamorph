# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-only

"""Calibration patterns for aligning a projector before any mapping starts.

The physical setup comes first: focus the lens, square the projector to the
surface, confirm the output really is filling the display it was assigned. All
of that needs known geometry on screen, not artwork - which is why every
mapping tool ships patterns like these.

Drawn with QPainter into a QImage rather than in GLSL, because the useful
parts are text and hairlines: the resolution readout, the edge rulers, the
numbered corners that tell you which edge you are looking at.
"""

from __future__ import annotations

from typing import List, Tuple

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen

GRID = "grid"
CHECKER = "checker"
BORDERS = "borders"

# (serialised value, display label)
PATTERNS: Tuple[Tuple[str, str], ...] = (
    (GRID, "Grid"),
    (CHECKER, "Checkerboard"),
    (BORDERS, "Borders + Centre"),
)

_ACCENT = QColor(0, 212, 170)
_DIM = QColor(70, 70, 78)
_BRIGHT = QColor(240, 240, 240)
_CELL = 64


def available_patterns() -> List[str]:
    return [value for value, _ in PATTERNS]


def render_test_pattern(width: int, height: int, kind: str = GRID, label: str = "") -> QImage:
    """A full-canvas calibration image at the exact output resolution."""
    width = max(int(width), 1)
    height = max(int(height), 1)

    image = QImage(width, height, QImage.Format_RGBA8888)
    image.fill(QColor(0, 0, 0))

    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, False)
    try:
        if kind == CHECKER:
            _draw_checker(painter, width, height)
        elif kind == BORDERS:
            _draw_borders(painter, width, height)
        else:
            _draw_grid(painter, width, height)
        _draw_frame(painter, width, height)
        _draw_readout(painter, width, height, label)
    finally:
        painter.end()

    return image


def _draw_grid(painter: QPainter, width: int, height: int) -> None:
    painter.setPen(QPen(_DIM, 1))
    for x in range(0, width, _CELL):
        painter.drawLine(x, 0, x, height)
    for y in range(0, height, _CELL):
        painter.drawLine(0, y, width, y)

    # Every fourth line brighter, so counting cells across a wall is possible
    # from the back of the room.
    painter.setPen(QPen(_ACCENT, 1))
    for x in range(0, width, _CELL * 4):
        painter.drawLine(x, 0, x, height)
    for y in range(0, height, _CELL * 4):
        painter.drawLine(0, y, width, y)

    _draw_diagonals(painter, width, height)


def _draw_checker(painter: QPainter, width: int, height: int) -> None:
    # Focus target: the eye resolves a soft checker edge far better than a
    # soft line.
    for row, y in enumerate(range(0, height, _CELL)):
        for col, x in enumerate(range(0, width, _CELL)):
            if (row + col) % 2 == 0:
                painter.fillRect(QRect(x, y, _CELL, _CELL), _BRIGHT)


def _draw_borders(painter: QPainter, width: int, height: int) -> None:
    _draw_diagonals(painter, width, height)

    # Centre cross with a sizing circle.
    cx, cy = width / 2.0, height / 2.0
    radius = min(width, height) * 0.12
    painter.setPen(QPen(_ACCENT, 2))
    painter.drawLine(int(cx - radius * 1.6), int(cy), int(cx + radius * 1.6), int(cy))
    painter.drawLine(int(cx), int(cy - radius * 1.6), int(cx), int(cy + radius * 1.6))
    painter.setBrush(Qt.NoBrush)
    painter.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))

    # Edge rulers: ticks every 100px, labelled every 500, so overscan and
    # cropping are measurable rather than guessed at.
    painter.setFont(QFont("Sans", 11))
    for x in range(0, width, 100):
        long_tick = x % 500 == 0
        length = 28 if long_tick else 14
        painter.setPen(QPen(_ACCENT if long_tick else _DIM, 2 if long_tick else 1))
        painter.drawLine(x, 0, x, length)
        painter.drawLine(x, height, x, height - length)
        if long_tick and x > 0:
            painter.setPen(QPen(_ACCENT, 1))
            painter.drawText(x + 4, 44, str(x))

    for y in range(0, height, 100):
        long_tick = y % 500 == 0
        length = 28 if long_tick else 14
        painter.setPen(QPen(_ACCENT if long_tick else _DIM, 2 if long_tick else 1))
        painter.drawLine(0, y, length, y)
        painter.drawLine(width, y, width - length, y)
        if long_tick and y > 0:
            painter.setPen(QPen(_ACCENT, 1))
            painter.drawText(36, y - 4, str(y))


def _draw_diagonals(painter: QPainter, width: int, height: int) -> None:
    painter.setPen(QPen(_DIM, 1))
    painter.drawLine(0, 0, width, height)
    painter.drawLine(width, 0, 0, height)


def _draw_frame(painter: QPainter, width: int, height: int) -> None:
    """A 1px border and corner brackets: proof no edge is being cropped."""
    painter.setPen(QPen(_BRIGHT, 1))
    painter.drawRect(0, 0, width - 1, height - 1)

    arm = max(24, min(width, height) // 12)
    painter.setPen(QPen(_ACCENT, 4))
    corners = (
        (0, 0, 1, 1),
        (width, 0, -1, 1),
        (0, height, 1, -1),
        (width, height, -1, -1),
    )
    for x, y, sx, sy in corners:
        painter.drawLine(x, y + (2 * sy), x + arm * sx, y + (2 * sy))
        painter.drawLine(x + (2 * sx), y, x + (2 * sx), y + arm * sy)


def _draw_readout(painter: QPainter, width: int, height: int, label: str) -> None:
    """Resolution and screen name, so the operator can confirm the output
    landed on the display they meant."""
    text = f"{width} x {height}"
    if label:
        text = f"{label}   {text}"

    painter.setFont(QFont("Sans", max(13, min(width, height) // 45), QFont.Bold))
    metrics = painter.fontMetrics()
    box = metrics.boundingRect(text).adjusted(-14, -10, 14, 10)
    box.moveCenter(QRect(0, 0, width, height).center())
    box.moveTop(int(height * 0.62))

    painter.setPen(Qt.NoPen)
    painter.fillRect(box, QColor(0, 0, 0, 200))
    painter.setPen(QPen(_ACCENT, 1))
    painter.drawRect(box)
    painter.drawText(box, Qt.AlignCenter, text)

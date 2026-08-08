# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-only

"""Problems the operator can actually see.

Every failure that is not fatal used to end at `logger.warning` - a codec the
build cannot open, a session file that would not parse, a framebuffer the
driver refused. All of it went to a console nobody is looking at during a
show, and on screen the surface simply came up empty.

This is a logging handler rather than a rewrite of every call site. Those
`logger.warning` calls are already in the right places and already say the
right thing; what was missing was somewhere for them to arrive. Anything
this app logs at WARNING or above shows up here, which also means a problem
added later is visible without anyone remembering to wire it.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import List, Optional

from about import PACKAGES
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

# Enough to see a pattern, few enough that a decoder failing every frame
# cannot eat the machine's memory.
MAX_PROBLEMS = 200


@dataclass
class Problem:
    when: float
    level: int
    source: str
    message: str

    @property
    def is_error(self) -> bool:
        return self.level >= logging.ERROR

    def clock(self) -> str:
        return time.strftime("%H:%M:%S", time.localtime(self.when))

    def line(self) -> str:
        mark = "✕" if self.is_error else "⚠"
        return f"{mark}  {self.clock()}  {self.message}"


class ProblemLog(QObject):
    """Collects warnings and errors, and says when something new arrives."""

    problem_added = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._problems: List[Problem] = []
        self._handler: Optional[logging.Handler] = None

    # --- collection ------------------------------------------------------

    def install(self, logger_name: str = "") -> None:
        """Start listening. Idempotent, so a second window does not double up.

        The default is the *root* logger. The app's modules are top-level -
        `ui`, `model`, `render` and the rest - so there is no one ancestor to
        hang this on any more, and the handler tells the app's own records
        from a dependency's by their top-level name instead. Passing an
        explicit logger (which the tests do) skips that filtering: you asked
        for that subtree, so everything in it is yours.
        """
        if self._handler is not None:
            return
        self._handler = _ProblemHandler(self, filtered=not logger_name)
        self._handler.setLevel(logging.WARNING)
        target = logging.getLogger(logger_name)
        target.addHandler(self._handler)
        # Without this the logger's own level decides what reaches us, and a
        # level set higher than WARNING would drop records before the handler
        # is ever consulted.
        if target.level == logging.NOTSET or target.level > logging.WARNING:
            target.setLevel(logging.WARNING)

    def uninstall(self, logger_name: str = "") -> None:
        if self._handler is None:
            return
        logging.getLogger(logger_name).removeHandler(self._handler)
        self._handler = None

    def add(self, level: int, source: str, message: str) -> Problem:
        problem = Problem(time.time(), level, source, message)
        self._problems.append(problem)
        # Drop the oldest rather than the newest: what just went wrong is
        # more useful than what went wrong an hour ago.
        if len(self._problems) > MAX_PROBLEMS:
            del self._problems[: len(self._problems) - MAX_PROBLEMS]
        self.problem_added.emit(problem)
        return problem

    # --- reading ---------------------------------------------------------

    def problems(self) -> List[Problem]:
        return list(self._problems)

    def count(self) -> int:
        return len(self._problems)

    def error_count(self) -> int:
        return sum(1 for p in self._problems if p.is_error)

    def latest(self) -> Optional[Problem]:
        return self._problems[-1] if self._problems else None

    def clear(self) -> None:
        self._problems.clear()


class _ProblemHandler(logging.Handler):
    def __init__(self, log: ProblemLog, filtered: bool = True) -> None:
        super().__init__()
        self._log = log
        self._filtered = filtered

    def emit(self, record: logging.LogRecord) -> None:
        # On the root logger everything passes through here, including a
        # dependency's chatter. The operator's list is for this app's
        # failures - a warning from a decoding library about a colour profile
        # is not something anyone can act on mid-show.
        if self._filtered and record.name.split(".")[0] not in PACKAGES:
            return
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - a broken format string
            message = str(record.msg)
        # Never let logging raise into whatever was being done at the time.
        try:
            self._log.add(record.levelno, record.name, message)
        except Exception:  # pragma: no cover
            pass


class ProblemDialog(QDialog):
    """The list, newest first, with the detail that a status message cannot hold."""

    def __init__(self, log: ProblemLog, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Problems")
        self.resize(720, 380)
        self._log = log

        layout = QVBoxLayout(self)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        self.list = QListWidget()
        self.list.setWordWrap(True)
        layout.addWidget(self.list, 1)

        buttons = QHBoxLayout()
        self.clear_button = QPushButton("Clear")
        self.clear_button.clicked.connect(self._on_clear)
        buttons.addWidget(self.clear_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        box = QDialogButtonBox(QDialogButtonBox.Close)
        box.rejected.connect(self.accept)
        layout.addWidget(box)

        self._log.problem_added.connect(lambda _p: self.refresh())
        self.refresh()

    def refresh(self) -> None:
        self.list.clear()
        for problem in reversed(self._log.problems()):
            item = QListWidgetItem(problem.line())
            item.setToolTip(f"{problem.source}\n{problem.message}")
            if problem.is_error:
                item.setForeground(Qt.red)
            self.list.addItem(item)

        total = self._log.count()
        if total:
            errors = self._log.error_count()
            self.summary.setText(
                f"{total} problem(s) this session, {errors} of them errors. "
                "Newest first."
            )
        else:
            self.summary.setText("Nothing has gone wrong this session.")
        self.clear_button.setEnabled(bool(total))

    def _on_clear(self) -> None:
        self._log.clear()
        self.refresh()

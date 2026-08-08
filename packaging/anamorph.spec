# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-only

"""PyInstaller recipe for a distributable Anamorph.

`--onedir`, and that is a licence decision before it is a technical one. Qt is
LGPL-3, which asks that whoever receives the binary can replace Qt with their
own build. In a one-directory bundle the Qt libraries sit as ordinary files
next to the executable and can be swapped; a `--onefile` build unpacks itself
into a temporary directory that disappears, which makes the same swap
impractical. `tests/test_packaging.py` checks the layout rather than trusting
this comment.

The licence texts are bundled for the same reason: `LICENSE` lives in the
repository, and a repository does not travel inside a frozen binary. Someone
who is handed the app and nothing else still has to be able to read the terms.
"""

import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT))

from about import APP_NAME  # noqa: E402

# Everything the operator must be able to read while holding only the binary.
LEGAL = [
    (str(ROOT / "LICENSE"), "licenses"),
    (str(ROOT / "licenses" / "LGPL-3.0.txt"), "licenses"),
    (str(ROOT / "THIRD-PARTY-NOTICES.md"), "licenses"),
]

# The window and taskbar mark, resolved at runtime through
# `app_paths.asset_path` so it is found from a checkout and from here alike.
ASSETS = [(str(ROOT / "assets" / "icon.png"), "assets")]

# The executable's own icon is a per-platform container: Windows wants .ico,
# macOS .icns, and Linux takes it from the window rather than the file.
if sys.platform == "win32":
    ICON = str(ROOT / "assets" / "icon.ico")
elif sys.platform == "darwin":
    ICON = str(ROOT / "assets" / "icon.icns")
else:
    ICON = None

# Qt modules PySide6-Essentials ships that this app never imports. Excluding
# them is size, not correctness - but a projection tool gets downloaded on
# venue wifi an hour before doors, and every megabyte is real there.
UNUSED_QT = [
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.QtQuickControls2",
    "PySide6.QtNetwork",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtDesigner",
    "PySide6.QtUiTools",
    "PySide6.QtHelp",
    "PySide6.QtPrintSupport",
    "PySide6.QtDBus",
    "PySide6.QtXml",
    "PySide6.QtSvg",
    "PySide6.QtSvgWidgets",
    "PySide6.QtConcurrent",
]

# The test stack and the interactive extras are developer tooling; none of it
# is reachable from the entry point, but PyInstaller finds tkinter through
# stdlib paths if it is not told otherwise.
DEV_ONLY = ["tkinter", "unittest", "pytest", "_pytest", "pydoc", "doctest", "PIL.ImageQt"]


a = Analysis(
    [str(ROOT / "projection_gui.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=LEGAL + ASSETS,
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=UNUSED_QT + DEV_ONLY,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=ICON,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)

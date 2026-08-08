# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-only

"""The obligations a frozen build carries, checked from the source tree.

Building a bundle takes minutes and a platform; these run in milliseconds and
guard the decisions that are invisible until someone is holding the binary:
that the licence texts travel with it, that the layout still permits replacing
Qt, and that the dependency trims have not quietly regressed.

The build itself is exercised by the release workflow. What cannot be caught
there is a change made months later by someone who does not know why the spec
says what it says - which is what these are for.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "packaging" / "anamorph.spec"
REQUIREMENTS = (ROOT / "requirements.txt").read_text(encoding="utf-8")


def spec_text() -> str:
    return SPEC.read_text(encoding="utf-8")


def test_the_bundle_is_one_directory_not_one_file():
    """`--onefile` unpacks into a temporary directory that disappears, which
    makes replacing Qt impractical - and replacing Qt is what LGPL-3 asks a
    recipient be able to do. COLLECT is what produces the replaceable layout."""
    text = spec_text()

    assert "COLLECT(" in text, "no COLLECT step: this would be a one-file build"
    assert "exclude_binaries=True" in text, (
        "the EXE must leave its binaries to COLLECT, or they are embedded"
    )


@pytest.mark.parametrize("document", ["LICENSE", "LGPL-3.0.txt", "THIRD-PARTY-NOTICES.md"])
def test_the_licence_texts_travel_inside_the_bundle(document):
    """A repository does not travel inside a frozen binary. Someone handed the
    app and nothing else still has to be able to read the terms - which is the
    same reason the About box exists."""
    assert document in spec_text(), f"{document} is not bundled by the spec"


def test_the_lgpl_text_is_present_and_is_actually_the_lgpl():
    """Qt is taken under LGPL-3, and PySide6's wheel does not ship the text -
    so it cannot be obtained from the dependency at build time."""
    text = (ROOT / "licenses" / "LGPL-3.0.txt").read_text(encoding="utf-8")

    assert "GNU LESSER GENERAL PUBLIC LICENSE" in text
    assert "Version 3, 29 June 2007" in text
    # Section 4 is the one that carries the relinking condition this whole
    # packaging approach is shaped around.
    assert "4. Combined Works" in text


def test_only_the_qt_modules_the_app_imports_are_shipped():
    """The meta-package pulls PySide6-Addons: 438 MB the app never imports,
    195 MB of it a whole Chromium. Nobody downloads that on venue wifi."""
    assert "PySide6-Essentials" in REQUIREMENTS
    assert not re.search(r"^PySide6>=", REQUIREMENTS, re.MULTILINE), (
        "the PySide6 meta-package drags the Addons wheel back in"
    )


def test_opencv_is_the_headless_build():
    """The app calls VideoCapture, VideoWriter and cvtColor and never opens an
    OpenCV window, so the GUI build's toolkit is weight and one more licence to
    track."""
    assert "opencv-python-headless" in REQUIREMENTS


def test_the_spec_takes_the_app_name_from_one_place():
    """`about.py` is the single source for identity; a name typed again here
    is a name that drifts."""
    assert "from about import APP_NAME" in spec_text()
    assert "name=APP_NAME" in spec_text()

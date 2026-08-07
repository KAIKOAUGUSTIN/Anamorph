# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The licence, kept true by something other than memory.

A licence is only as good as its weakest statement of itself. The repository
had the GPL text and nothing else: no notice in a single source file, no
version declared, nothing in the running program. Any one file copied out of
here carried no terms at all.

These tests are the part that does not decay. A 69th source file added without
a header, a dependency added without a notice, an About box that stops naming
the licence - each is caught here rather than noticed by a lawyer.
"""

import re
import subprocess
from pathlib import Path

import pytest

from about import COPYRIGHT, LICENSE_ID, VERSION, legal_notice

ROOT = Path(__file__).resolve().parent.parent

SPDX = f"SPDX-License-Identifier: {LICENSE_ID}"


def prose(*parts: str) -> str:
    """A markdown file with its wrapping flattened.

    Asserting on a phrase that happens to straddle a line break makes the
    test a hostage to the paragraph's width - it would fail on a reflow that
    changed nothing.
    """
    text = (ROOT.joinpath(*parts)).read_text(encoding="utf-8")
    return re.sub(r"\s+", " ", text)


def tracked_python_files():
    result = subprocess.run(
        ["git", "ls-files", "*.py"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    return sorted(result.stdout.split())


# --- every file says what it is ---------------------------------------------

def test_there_are_python_files_to_check():
    """Guards the guard: a broken listing would make every check below pass."""
    assert len(tracked_python_files()) > 50


@pytest.mark.parametrize("name", tracked_python_files())
def test_every_source_file_carries_the_notice(name):
    """A file copied out of this repository has to arrive with its terms."""
    head = "\n".join((ROOT / name).read_text(encoding="utf-8").split("\n")[:8])

    assert SPDX in head, f"{name} has no SPDX identifier"
    assert "Copyright (C)" in head, f"{name} has no copyright line"


def test_the_headers_agree_with_the_declared_licence():
    """`about` and the file headers must not drift apart."""
    header = (ROOT / "about.py").read_text(encoding="utf-8")
    assert SPDX in header
    assert LICENSE_ID == "GPL-3.0-or-later", (
        "the version is a decision, not an accident - changing it is a "
        "relicensing that every contributor has to agree to"
    )


# --- the repository states it too -------------------------------------------

def test_the_licence_file_is_the_gpl_3():
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "GNU GENERAL PUBLIC LICENSE" in text
    assert "Version 3, 29 June 2007" in text


def test_the_readme_states_the_licence_and_points_at_the_terms():
    text = prose("README.md")
    assert "GNU General Public License, version 3 or later" in text
    assert "LICENSE" in text
    assert "CONTRIBUTING.md" in text
    assert "WITHOUT ANY" in text, "no-warranty statement missing"


def test_the_dco_is_quoted_in_full():
    """The sign-off means nothing if what is being certified is not on file."""
    text = prose("CONTRIBUTING.md")

    assert "Developer's Certificate of Origin 1.1" in text
    for clause in ("(a)", "(b)", "(c)", "(d)"):
        assert clause in text, f"DCO clause {clause} is missing"
    assert "git commit -s" in text, "how to sign off is the whole instruction"
    assert "Signed-off-by:" in text


def test_contributing_is_honest_about_what_the_dco_does_not_do():
    """A DCO is not a CLA. Someone signing has to be able to see that from
    the document they are signing."""
    text = prose("CONTRIBUTING.md")
    assert "You keep the copyright" in text
    assert "cannot be relicensed" in text


def test_the_pull_request_template_asks_for_the_sign_off():
    text = prose(".github", "PULL_REQUEST_TEMPLATE.md")
    assert "git commit -s" in text
    assert "SPDX-License-Identifier" in text


# --- dependencies ------------------------------------------------------------

def test_every_dependency_has_a_third_party_notice():
    """A dependency added without a notice is the omission nobody notices
    until a build is being shipped."""
    notices = prose("THIRD-PARTY-NOTICES.md").lower()
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")

    for line in requirements.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name = re.split(r"[<>=!~\[]", line)[0].strip()
        assert name.lower() in notices, (
            f"{name} is a dependency with no entry in THIRD-PARTY-NOTICES.md"
        )


def test_the_qt_obligation_is_written_down():
    """LGPL relinking is the condition a frozen binary breaks first, and it
    is invisible from the source tree."""
    text = prose("THIRD-PARTY-NOTICES.md")
    assert "LGPL-3.0" in text
    assert "dynamically" in text


# --- the running program -----------------------------------------------------

def test_the_notice_carries_the_four_facts_the_gpl_asks_for():
    """GPL-3 section 0: copyright, no warranty, that it may be conveyed under
    this License, and how to read the License."""
    notice = legal_notice()

    assert COPYRIGHT in notice
    assert "NO WARRANTY" in notice
    assert "redistribute" in notice
    assert "LICENSE" in notice and "gnu.org/licenses" in notice


def test_the_about_box_shows_the_notice(qapp):
    from ui.about_dialog import AboutDialog

    from PySide6.QtWidgets import QLabel

    dialog = AboutDialog()
    try:
        assert legal_notice() in dialog.notice.text()

        shown = " ".join(label.text() for label in dialog.findChildren(QLabel))
        assert VERSION in shown, "a build that cannot name itself is unreportable"
        assert "GNU General Public License" in shown
    finally:
        dialog.close()


def test_the_help_menu_reaches_it(qapp):
    """An About box nothing opens is an About box that does not exist."""
    from ui.main_window import MainWindow

    win = MainWindow()
    try:
        menus = [action.text() for action in win.menuBar().actions()]
        assert "Help" in menus
        assert win.action_about.text().startswith("About")
    finally:
        win.project.mark_saved()
        win.close()

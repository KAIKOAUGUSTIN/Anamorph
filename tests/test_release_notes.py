# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-only

"""The thing that picks version numbers, which nobody checks by hand.

A version is a compatibility contract, and this script writes it unattended on
every merge. The parts worth pinning are the ones where being wrong is silent:
a declared marker losing to a model's guess, a breaking change below 1.0
minting a 1.0.0 nobody decided on, and the fallback failing to exist when the
endpoint is down.
"""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / ".github" / "scripts" / "next_release.py"


@pytest.fixture(scope="module")
def release():
    """Imported by path: `.github` is not a package and never will be."""
    spec = importlib.util.spec_from_file_location("next_release", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def commit(release, subject, body=""):
    return release.Commit("abc1234", subject, body)


# --- what the authors declared ----------------------------------------------

def test_a_feature_prefix_is_a_minor_bump(release):
    assert release.bump_from_markers([commit(release, "feat: mesh warping")]) == "minor"


def test_a_fix_prefix_is_a_patch_bump(release):
    assert release.bump_from_markers([commit(release, "fix: circle wedge")]) == "patch"


def test_a_bang_means_breaking(release):
    assert release.bump_from_markers([commit(release, "feat!: drop workspaces")]) == "major"


def test_a_breaking_change_trailer_is_found_in_the_body(release):
    """The subject often has no room for it, so the trailer has to work."""
    changed = commit(release, "Rework outputs", "BREAKING CHANGE: old files will not open")
    assert release.bump_from_markers([changed]) == "major"


def test_an_explicit_trailer_wins_where_the_subject_has_no_shape(release):
    """This repository's commit subjects are sentences, not `feat:` prefixes.
    The trailer is how an author here declares intent without adopting a style
    the rest of the history does not use."""
    changed = commit(release, "Package it: a bundle someone can download", "Release-Type: minor")
    assert release.bump_from_markers([changed]) == "minor"


def test_the_largest_declaration_in_the_range_wins(release):
    """Ten fixes and one breaking change is a breaking release."""
    commits = [
        commit(release, "fix: one"),
        commit(release, "feat: two"),
        commit(release, "fix!: three"),
    ]
    assert release.bump_from_markers(commits) == "major"


def test_saying_nothing_is_not_a_declaration(release):
    """It has to return None, or the model is never asked."""
    assert release.bump_from_markers([commit(release, "Tidy the outputs dialog")]) is None


# --- the arithmetic ---------------------------------------------------------

@pytest.mark.parametrize("current,bump,expected", [
    ("0.1.0", "patch", "0.1.1"),
    ("0.1.0", "minor", "0.2.0"),
    ("0.1.9", "patch", "0.1.10"),
    ("1.4.2", "minor", "1.5.0"),
    ("1.4.2", "major", "2.0.0"),
])
def test_version_arithmetic(release, current, bump, expected):
    assert release.next_version(current, bump) == expected


def test_a_breaking_change_below_one_does_not_mint_a_one_point_oh(release):
    """1.0.0 is a promise about stability. Reaching it because one commit said
    "breaking" would claim something nobody decided."""
    assert release.next_version("0.3.4", "major") == "0.4.0"


# --- the model's answer, and its absence -------------------------------------

def test_a_fenced_json_reply_is_still_read(release):
    reply = (
        "Here you go:\n```json\n"
        '{"bump": "minor", "reason": "adds masks", '
        '"sections": {"Added": ["Masks"], "Nonsense": ["ignored"]}}\n```'
    )
    parsed = release._parse(reply)

    assert parsed["bump"] == "minor"
    assert parsed["sections"] == {"Added": ["Masks"]}, "unknown sections must be dropped"


def test_a_reply_with_an_invalid_bump_is_refused(release):
    assert release._parse('{"bump": "enormous", "sections": {}}') is None


def test_a_reply_that_is_not_json_is_refused(release):
    assert release._parse("I think this is a minor release.") is None


def test_the_model_is_skipped_when_it_is_not_configured(release, monkeypatch):
    """No key must mean the fallback, not a crash and not a hang."""
    for name in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)

    assert release.ask_model([commit(release, "fix: something")]) is None


def test_the_fallback_still_produces_a_changelog(release):
    """A release must not be blocked by a third party being unreachable."""
    sections = release.fallback_sections([
        commit(release, "feat: edge blend"),
        commit(release, "fix: stroke width (#42)"),
        commit(release, "Tidy the toolbar"),
    ])

    assert sections["Added"] == ["edge blend"]
    assert sections["Fixed"] == ["stroke width"], "the PR number is noise in release notes"
    assert sections["Changed"] == ["Tidy the toolbar"]


# --- the entry it writes -----------------------------------------------------

def test_the_entry_has_the_same_shape_every_time(release):
    entry = release.render("0.2.0", {"Fixed": ["b"], "Added": ["a"]}, when="2026-08-08")

    assert entry.startswith("## [0.2.0] - 2026-08-08")
    # Declared order, not the order the model happened to answer in.
    assert entry.index("### Added") < entry.index("### Fixed")


def test_empty_sections_are_left_out(release):
    entry = release.render("0.2.0", {"Added": ["a"], "Removed": []}, when="2026-08-08")
    assert "### Removed" not in entry


def test_the_changelog_has_the_marker_the_script_writes_against(release):
    """Without it `prepend` would silently put the entry nowhere."""
    assert "<!-- releases -->" in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


def test_dry_run_writes_nothing(release, monkeypatch, capsys, tmp_path):
    """The flag exists so an endpoint can be tried before it is trusted with a
    release. If it wrote anyway, the first experiment would move the version."""
    changelog = release.CHANGELOG
    before = changelog.read_text(encoding="utf-8")
    about_before = (release.ROOT / "about.py").read_text(encoding="utf-8")

    monkeypatch.setattr(release.sys, "argv", ["next_release.py", "--dry-run"])
    for name in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)

    assert release.main() == 0
    assert "would prepend" in capsys.readouterr().out
    assert changelog.read_text(encoding="utf-8") == before
    assert (release.ROOT / "about.py").read_text(encoding="utf-8") == about_before

# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-only

"""The thing that reports failures, which fails silently if it breaks.

CI runs one job per platform rather than one per test file, and what makes
that readable is the annotation: file, test, line and message, attached to the
diff. If this reporter stops finding the location, a red run goes back to
being "open the log and scroll", and nothing would say so - the report step
would still be green.
"""

import importlib.util
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / ".github" / "scripts" / "test_report.py"


@pytest.fixture(scope="module")
def reporter():
    """Imported by path: `.github` is not a package and never will be."""
    spec = importlib.util.spec_from_file_location("test_report", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def real_report(tmp_path_factory):
    """A JUnit report from a suite that actually failed.

    Handwritten XML would test the parser against my idea of pytest's output
    rather than pytest's output, and the attributes it emits have already
    changed once between families.
    """
    work = tmp_path_factory.mktemp("failing")
    (work / "test_broken.py").write_text(
        "def test_that_passes():\n"
        "    assert True\n"
        "\n"
        "def test_that_fails():\n"
        "    assert 1 == 8, 'stroke width came out 1px'\n"
        "\n"
        "def test_that_raises():\n"
        "    raise RuntimeError('no GL context')\n"
    )
    report = work / "report.xml"
    subprocess.run(
        [sys.executable, "-m", "pytest", "test_broken.py", "-q",
         f"--junitxml={report}", "-p", "no:cacheprovider"],
        cwd=work, capture_output=True, text=True,
    )
    return report


def test_it_finds_every_failure(reporter, real_report):
    failures, totals = reporter.collect(real_report)

    assert {f.test for f in failures} == {"test_that_fails", "test_that_raises"}
    assert totals["tests"] == 3


def test_it_points_at_the_line_that_failed(reporter, real_report):
    """Not the line the test is defined on - the assertion can be far from it,
    and an annotation on the `def` makes the reader hunt anyway."""
    failures, _ = reporter.collect(real_report)
    by_name = {f.test: f for f in failures}

    assert by_name["test_that_fails"].line == 5
    assert by_name["test_that_raises"].line == 8
    assert by_name["test_that_fails"].file.endswith("test_broken.py")


def test_a_windows_traceback_gives_a_path_github_can_match(reporter):
    """The Windows runner reports `tests\\test_playback.py:379:`.

    A backslash path is not rejected by GitHub - it is silently unmatched, so
    the annotation detaches from the file and floats at the top of the run.
    That is the failure mode this script exists to prevent, appearing only on
    the platform the suite runs on least.
    """
    case = ET.Element("testcase")

    path, line = reporter.locate(case, "tests\\test_playback.py:379: AssertionError")

    assert path == "tests/test_playback.py"
    assert line == 379


def test_a_windows_path_in_the_fallback_is_normalised_too(reporter):
    """The fallback reads the testcase attributes, and on Windows those carry
    backslashes as well - fixing only the traceback would leave the collection
    error case broken."""
    case = ET.Element("testcase", {"file": "tests\\test_masks.py", "line": "40"})

    path, line = reporter.locate(case, "")

    assert path == "tests/test_masks.py"
    assert line == 41


def test_the_message_survives(reporter, real_report):
    failures, _ = reporter.collect(real_report)
    by_name = {f.test: f for f in failures}

    assert "stroke width came out 1px" in by_name["test_that_fails"].message
    assert "no GL context" in by_name["test_that_raises"].message


def test_the_annotation_is_the_shape_github_reads(reporter, real_report, capsys):
    failures, _ = reporter.collect(real_report)
    reporter.annotate(failures)

    printed = capsys.readouterr().out.splitlines()
    assert len(printed) == 2
    for line in printed:
        assert line.startswith("::error file=")
        assert ",line=" in line and ",title=" in line and "::" in line[8:]


def test_a_green_run_says_so(reporter, tmp_path):
    (tmp_path / "test_fine.py").write_text("def test_fine():\n    assert True\n")
    report = tmp_path / "green.xml"
    subprocess.run(
        [sys.executable, "-m", "pytest", "test_fine.py", "-q",
         f"--junitxml={report}", "-p", "no:cacheprovider"],
        cwd=tmp_path, capture_output=True,
    )
    failures, totals = reporter.collect(report)

    summary = reporter.summarise(failures, totals, "tests (ubuntu-latest)")
    assert "Nothing failed" in summary
    assert "|" not in summary, "no table when there is nothing to put in it"


def test_a_missing_report_is_not_silence(reporter, tmp_path, capsys, monkeypatch):
    """pytest can die before writing one - a collection error, an import that
    blew up. Saying nothing there is the worst outcome: a red job with an
    empty summary reads like the reporter is broken."""
    monkeypatch.setattr(sys, "argv", ["test_report.py", str(tmp_path / "gone.xml")])

    assert reporter.main() == 0
    assert "::error" in capsys.readouterr().out


def test_the_summary_table_cannot_be_broken_by_a_message(reporter):
    """A pipe in an assertion message would end the markdown cell early and
    the row would render as nonsense."""
    failure = reporter.Failure(
        file="tests/test_x.py", line=3, test="test_pipes", kind="failure",
        message="assert a|b == c",
    )
    summary = reporter.summarise([failure], {"tests": 1, "failures": 1, "errors": 0,
                                              "skipped": 0}, "tests")

    row = [line for line in summary.splitlines() if "test_pipes" in line][0]
    assert "a\\|b" in row, "the pipe has to be escaped, not dropped"
    assert row.replace("\\|", "").count("|") == 4, "an unescaped pipe adds a column"

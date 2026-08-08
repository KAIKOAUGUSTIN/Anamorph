# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Turn a pytest JUnit report into something readable without opening a log.

CI used to run one job per test file so that a red tick would name the area.
That does not survive a second operating system - 25 suites times three
platforms is 75 jobs - and it was always the weaker signal: a job called
"masks" tells you the area, while an annotation tells you the file, the test,
the line and the message, on the diff itself.

Two outputs, neither needing write permission on the repository, so both work
on a pull request from a fork:

- `::error` annotations, which GitHub attaches to the source line.
- A table in the job summary, which is the first thing shown for a red run.
"""

from __future__ import annotations

import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, NamedTuple, Optional, Tuple

# Long enough to recognise the failure, short enough that the annotation stays
# readable where GitHub renders it.
MESSAGE_LIMIT = 400

# The last `path.py:123:` in a pytest traceback is where it actually broke.
TRACEBACK_LOCATION = re.compile(r"^(\S+\.py):(\d+):", re.MULTILINE)


class Failure(NamedTuple):
    file: str
    line: int
    test: str
    kind: str
    message: str


def locate(case: ET.Element, traceback: str) -> Tuple[str, int]:
    """Where to point the annotation.

    The traceback's last frame is the line that actually failed. The
    `file`/`line` attributes on the testcase are the *definition* of the test
    - a whole function earlier when the assertion is deep in it - and they
    only exist under `junit_family=xunit1`, so they are the fallback rather
    than the source.
    """
    frames = TRACEBACK_LOCATION.findall(traceback or "")
    if frames:
        path, line = frames[-1]
        return path, int(line)

    path = case.get("file") or _path_from_classname(case.get("classname"))
    # xunit1 counts test definitions from zero; GitHub counts lines from one,
    # and an annotation one line off lands on a decorator or a blank line.
    line = case.get("line")
    return path, int(line) + 1 if line is not None else 1


def _path_from_classname(classname: Optional[str]) -> str:
    """`tests.test_masks` -> `tests/test_masks.py`, when nothing better exists."""
    if not classname:
        return ""
    return classname.replace(".", "/") + ".py"


def collect(report: Path) -> tuple[List[Failure], dict]:
    root = ET.parse(report).getroot()
    # `pytest --junitxml` writes <testsuites><testsuite>, but a bare
    # <testsuite> root has been seen from other versions.
    suites = root.iter("testsuite")

    failures: List[Failure] = []
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}

    for suite in suites:
        for key in totals:
            totals[key] += int(suite.get(key, 0) or 0)

        for case in suite.iter("testcase"):
            for kind in ("failure", "error"):
                node = case.find(kind)
                if node is None:
                    continue
                message = (node.get("message") or node.text or "").strip()
                path, line = locate(case, node.text or "")
                failures.append(Failure(
                    file=path,
                    line=line,
                    test=case.get("name", "") or "",
                    kind=kind,
                    message=" ".join(message.split())[:MESSAGE_LIMIT],
                ))

    return failures, totals


def annotate(failures: List[Failure]) -> None:
    """One `::error` per failure, placed on the line that failed."""
    for failure in failures:
        location = f"file={failure.file},line={failure.line}" if failure.file else ""
        title = f"{failure.kind} in {failure.test}"
        print(f"::error {location},title={title}::{failure.message}")


def summarise(failures: List[Failure], totals: dict, label: str) -> str:
    passed = totals["tests"] - totals["failures"] - totals["errors"] - totals["skipped"]
    lines = [f"## {label}", ""]

    if not failures:
        lines += [
            f"**{passed} passed**, {totals['skipped']} skipped. Nothing failed.",
            "",
        ]
        return "\n".join(lines)

    lines += [
        f"**{len(failures)} failed**, {passed} passed, {totals['skipped']} skipped.",
        "",
        "| Test | Where | What went wrong |",
        "|---|---|---|",
    ]
    for failure in failures:
        where = f"`{failure.file}:{failure.line}`" if failure.file else "—"
        message = failure.message.replace("|", "\\|") or "(no message)"
        lines.append(f"| `{failure.test}` | {where} | {message} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    report = Path(sys.argv[1] if len(sys.argv) > 1 else "report.xml")
    label = sys.argv[2] if len(sys.argv) > 2 else "Tests"

    if not report.exists():
        # pytest died before writing a report - a collection error, or an
        # import that failed. The log is the only evidence, so say where.
        print(f"::error::No test report at {report}: pytest did not get far "
              f"enough to write one. See the step log above.")
        return 0

    failures, totals = collect(report)
    annotate(failures)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(summarise(failures, totals, label))
    else:
        print(summarise(failures, totals, label))

    # The job's success is decided by pytest's own exit code; this step only
    # reports. Exiting non-zero here would mask a pytest crash as a reporting
    # failure.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

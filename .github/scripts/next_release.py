# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-only

"""Decide the next version and write its changelog entry.

A version number is a compatibility contract, so the decision is not left to a
guess when an answer exists. A marker in the commits wins outright; only when
nobody said anything is the model asked, and its answer is printed with its
reasoning so a wrong call is visible rather than silent.

The model writes the prose either way. That is the half it is good at, and
this repository's commit messages explain *why* a change was made, which is
exactly what release notes need and what a list of subjects cannot give.

Nothing here blocks on the endpoint. If it is down, misconfigured or answers
with something that will not parse, the run falls back to markers alone and a
mechanical grouping - a release must not fail because a third party is having
an afternoon.

Configured entirely through the environment:

    LLM_BASE_URL   OpenAI-compatible endpoint (NVIDIA NIM speaks this)
    LLM_MODEL      model id at that endpoint
    LLM_API_KEY    absent disables the call and takes the fallback
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import List, NamedTuple, Optional

ROOT = Path(__file__).resolve().parent.parent.parent
CHANGELOG = ROOT / "CHANGELOG.md"

# The order sections appear in every entry, so two releases can be compared by
# eye. Taken from Keep a Changelog rather than invented.
SECTIONS = ["Added", "Changed", "Fixed", "Removed", "Security"]

BUMPS = ("major", "minor", "patch")

# Conventional Commits, plus an explicit trailer for the case where the subject
# does not fit the shape but the author still knows the answer.
FEAT = re.compile(r"^(feat|feature)(\([^)]*\))?!?:", re.IGNORECASE)
FIX = re.compile(r"^(fix|bugfix|perf)(\([^)]*\))?!?:", re.IGNORECASE)
BREAKING = re.compile(r"^\w+(\([^)]*\))?!:|^BREAKING[ -]CHANGE:", re.MULTILINE)
TRAILER = re.compile(r"^Release-Type:\s*(major|minor|patch)\s*$", re.MULTILINE | re.IGNORECASE)

# A commit the release machinery wrote itself. Reading these back would let a
# release describe its own paperwork, and worse, trigger another one.
OWN_WORK = re.compile(r"^Release v\d+\.\d+\.\d+", re.IGNORECASE)

MODEL_TIMEOUT_SECONDS = 60


class Commit(NamedTuple):
    sha: str
    subject: str
    body: str

    @property
    def text(self) -> str:
        return f"{self.subject}\n{self.body}".strip()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()


def last_tag() -> Optional[str]:
    """The newest `vX.Y.Z`, by version order rather than by date.

    Date order is wrong here: a tag pushed late for an older branch would
    otherwise be taken as the baseline and swallow everything since.
    """
    tags = [t for t in git("tag", "--list", "v*").splitlines() if VERSION_TAG.match(t)]
    if not tags:
        return None
    return max(tags, key=lambda t: tuple(int(p) for p in t[1:].split(".")))


VERSION_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def commits_since(tag: Optional[str]) -> List[Commit]:
    span = f"{tag}..HEAD" if tag else "HEAD"
    raw = git("log", span, "--no-merges", "--format=%H%x1f%s%x1f%b%x1e")
    commits = []
    for chunk in raw.split("\x1e"):
        chunk = chunk.strip()
        if not chunk:
            continue
        sha, subject, body = (chunk.split("\x1f") + ["", ""])[:3]
        if OWN_WORK.match(subject):
            continue
        commits.append(Commit(sha[:8], subject, body))
    return commits


def bump_from_markers(commits: List[Commit]) -> Optional[str]:
    """What the authors declared, if any of them declared anything.

    Checked before the model and never overridden by it: whoever wrote the
    change knew whether it breaks callers, and a model reading the diff
    afterwards is reconstructing that from evidence.
    """
    found = set()
    for commit in commits:
        trailer = TRAILER.search(commit.text)
        if trailer:
            found.add(trailer.group(1).lower())
        if BREAKING.search(commit.text):
            found.add("major")
        elif FEAT.match(commit.subject):
            found.add("minor")
        elif FIX.match(commit.subject):
            found.add("patch")
    for level in BUMPS:  # the largest declared wins
        if level in found:
            return level
    return None


def ask_model(commits: List[Commit]) -> Optional[dict]:
    """Classification and prose from an OpenAI-compatible endpoint.

    Returns None on anything at all going wrong. The caller has a fallback and
    a release that cannot be cut because a model is unreachable would be a
    worse failure than the one this avoids.
    """
    key = os.environ.get("LLM_API_KEY")
    base = os.environ.get("LLM_BASE_URL")
    model = os.environ.get("LLM_MODEL")
    if not (key and base and model):
        return None

    log = "\n\n".join(f"- {c.subject}\n{c.body}".strip() for c in commits)[:24000]
    prompt = (
        "You are writing release notes for Anamorph, a projection mapping "
        "application. Below are the commits since the last release.\n\n"
        "Return STRICT JSON, no prose outside it, with these keys:\n"
        '  "bump": one of "major", "minor", "patch"\n'
        '  "reason": one sentence explaining the bump\n'
        '  "sections": an object whose keys are any of '
        f'{SECTIONS}, each a list of short strings\n\n'
        "Rules:\n"
        "- patch = bug fixes and internal work only.\n"
        "- minor = any new capability a user can reach.\n"
        "- major = an existing project file, workflow or shortcut stops "
        "working the way it did.\n"
        "- Each bullet is one user-visible outcome, written for someone "
        "operating a projector, not for a developer. No commit hashes.\n"
        "- Omit sections with nothing in them.\n\n"
        f"COMMITS:\n{log}"
    )

    request = urllib.request.Request(
        f"{base.rstrip('/')}/chat/completions",
        data=json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": 1600,
        }).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=MODEL_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read())
        content = payload["choices"][0]["message"]["content"]
        return _parse(content)
    except (urllib.error.URLError, OSError, KeyError, IndexError, ValueError) as exc:
        print(f"::warning::Release notes model unavailable ({exc}); "
              f"falling back to markers and commit subjects.")
        return None


def _parse(content: str) -> Optional[dict]:
    """Pull the JSON object out of a reply that may be wrapped in a fence."""
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        return None
    data = json.loads(match.group(0))
    if data.get("bump") not in BUMPS:
        return None
    sections = data.get("sections")
    if not isinstance(sections, dict):
        return None
    data["sections"] = {
        name: [str(item) for item in items]
        for name, items in sections.items()
        if name in SECTIONS and items
    }
    return data or None


def fallback_sections(commits: List[Commit]) -> dict:
    """Grouped commit subjects: readable, never wrong, never insightful."""
    out: dict = {}
    for commit in commits:
        if FIX.match(commit.subject):
            out.setdefault("Fixed", []).append(_strip_prefix(commit.subject))
        elif FEAT.match(commit.subject):
            out.setdefault("Added", []).append(_strip_prefix(commit.subject))
        else:
            out.setdefault("Changed", []).append(_strip_prefix(commit.subject))
    return out


def _strip_prefix(subject: str) -> str:
    subject = re.sub(r"^\w+(\([^)]*\))?!?:\s*", "", subject)
    return re.sub(r"\s*\(#\d+\)$", "", subject).strip()


def next_version(current: str, bump: str) -> str:
    major, minor, patch = (int(p) for p in current.split("."))
    if bump == "major":
        # Below 1.0 the public promise has not been made yet, and semver says
        # anything may change. Shipping 1.0.0 by accident, because one commit
        # said "breaking", would claim a stability nobody decided on.
        return f"0.{minor + 1}.0" if major == 0 else f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def render(version: str, sections: dict, when: Optional[str] = None) -> str:
    lines = [f"## [{version}] - {when or date.today().isoformat()}", ""]
    for name in SECTIONS:
        items = sections.get(name)
        if not items:
            continue
        lines.append(f"### {name}")
        lines += [f"- {item}" for item in items]
        lines.append("")
    return "\n".join(lines)


def prepend(entry: str) -> None:
    """Newest first, under the header, leaving older entries untouched."""
    text = CHANGELOG.read_text(encoding="utf-8")
    marker = "<!-- releases -->"
    head, _, tail = text.partition(marker)
    CHANGELOG.write_text(f"{head}{marker}\n\n{entry}{tail.lstrip()}", encoding="utf-8")


def emit(name: str, value: str) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")
    print(f"{name}={value}")


def main() -> int:
    sys.path.insert(0, str(ROOT))
    from about import VERSION

    tag = last_tag()
    commits = commits_since(tag)
    if not commits:
        print("Nothing to release since " + (tag or "the beginning") + ".")
        emit("release", "no")
        return 0

    declared = bump_from_markers(commits)
    # Asked either way: even when the bump is already settled, the prose is
    # the half worth having.
    answer = ask_model(commits)

    if declared:
        bump, why = declared, f"declared in the commits ({len(commits)} since {tag or 'start'})"
        if answer and answer["bump"] != declared:
            print(f"::notice::The model proposed '{answer['bump']}' and the "
                  f"commits declared '{declared}'. The declaration wins.")
    elif answer:
        bump, why = answer["bump"], f"proposed by the model: {answer.get('reason', '')}"
    else:
        bump, why = "patch", "nothing declared and no model answer; defaulting to patch"

    sections = (answer or {}).get("sections") or fallback_sections(commits)
    version = next_version(VERSION, bump)

    print(f"{VERSION} -> {version} ({bump}): {why}")
    prepend(render(version, sections))

    about = ROOT / "about.py"
    about.write_text(
        re.sub(rf'^VERSION = "{re.escape(VERSION)}"',
               f'VERSION = "{version}"',
               about.read_text(encoding="utf-8"), count=1, flags=re.MULTILINE),
        encoding="utf-8",
    )

    emit("release", "yes")
    emit("version", version)
    emit("tag", f"v{version}")
    emit("bump", bump)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

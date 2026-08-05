from __future__ import annotations

import json
from typing import Any, Dict

from pm.model.project import Project


def save_project(project: Project, path: str) -> None:
    data: Dict[str, Any] = project.to_dict()
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
    project.path = path
    project.mark_saved()


def load_project(path: str) -> Project:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    project = Project.from_dict(data)
    project.path = path
    project.mark_saved()
    return project

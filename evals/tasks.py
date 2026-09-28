"""Load `tasks.yaml`, refusing anything the harness could not run."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from evals.assertions import validate

__all__ = ["TASKS_FILE", "Task", "load_tasks"]

TASKS_FILE = Path(__file__).with_name("tasks.yaml")


@dataclass(frozen=True)
class Task:
    id: str
    prompt: str
    assertions: list[dict[str, Any]]


def load_tasks(path: Path = TASKS_FILE) -> list[Task]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    tasks: list[Task] = []
    for entry in raw["tasks"]:
        for assertion in entry["assertions"]:
            validate(assertion)
        tasks.append(Task(entry["id"], entry["prompt"], list(entry["assertions"])))
    ids = [task.id for task in tasks]
    if len(set(ids)) != len(ids):
        raise ValueError(f"duplicate task ids in {path}")
    return tasks

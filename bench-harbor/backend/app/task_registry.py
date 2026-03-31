"""Discover tasks under <repo>/tasks by locating task.toml files."""

from __future__ import annotations

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]
from dataclasses import dataclass
from pathlib import Path

from .config import settings


@dataclass(frozen=True)
class TaskInfo:
    id: str
    root: Path
    instruction_path: Path
    solution_dir: Path
    tests_dir: Path
    environment_dir: Path

    def task_toml_path(self) -> Path:
        return self.root / "task.toml"

    @property
    def dockerfile(self) -> Path:
        return self.environment_dir / "Dockerfile"


def discover_tasks() -> list[TaskInfo]:
    root = settings.tasks_root
    if not root.is_dir():
        return []
    out: list[TaskInfo] = []
    for task_toml in sorted(root.rglob("task.toml")):
        task_root = task_toml.parent
        try:
            rel = task_root.relative_to(root)
        except ValueError:
            continue
        task_id = rel.as_posix()
        instruction = task_root / "instruction.md"
        solution = task_root / "solution"
        tests = task_root / "tests"
        env_dir = task_root / "environment"
        if not env_dir.is_dir() or not (env_dir / "Dockerfile").is_file():
            continue
        out.append(
            TaskInfo(
                id=task_id,
                root=task_root,
                instruction_path=instruction,
                solution_dir=solution,
                tests_dir=tests,
                environment_dir=env_dir,
            )
        )
    return out


def get_task(task_id: str) -> TaskInfo | None:
    for t in discover_tasks():
        if t.id == task_id:
            return t
    return None


def task_metadata(task: TaskInfo) -> dict:
    meta: dict = {"id": task.id, "has_instruction": task.instruction_path.is_file()}
    if task.instruction_path.is_file():
        meta["instruction_preview"] = task.instruction_path.read_text(encoding="utf-8")[:500]
    if task.task_toml_path().is_file():
        try:
            data = tomllib.loads(task.task_toml_path().read_text(encoding="utf-8"))
            m = data.get("metadata") or {}
            meta["title"] = m.get("category") or task.id
            meta["difficulty"] = m.get("difficulty")
        except Exception:
            meta.setdefault("title", task.id)
    else:
        meta.setdefault("title", task.id)
    return meta

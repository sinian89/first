"""Build images and run exec against benchmark containers."""

from __future__ import annotations

import re
import shlex

import docker
from docker.errors import DockerException, NotFound

from .task_registry import TaskInfo


def _slug_task_id(task_id: str) -> str:
    s = re.sub(r"[^a-z0-9._-]", "-", task_id.lower())
    s = re.sub(r"-+", "-", s).strip("-") or "task"
    return s[:200]


def _safe_image_tag(task_id: str) -> str:
    return f"bench-harbor/{_slug_task_id(task_id)}:local"


def _safe_container_name(task_id: str) -> str:
    """One stable name per task so a new session replaces the previous container."""
    return f"bh-{_slug_task_id(task_id)}"


class ContainerSession:
    def __init__(self, task: TaskInfo, image_tag: str, container_id: str, name: str):
        self.task = task
        self.image_tag = image_tag
        self.container_id = container_id
        self.name = name


def docker_client():
    try:
        return docker.from_env()
    except DockerException as e:
        raise RuntimeError(f"Docker not available: {e}") from e


def remove_container_by_name(name: str) -> None:
    client = docker_client()
    try:
        c = client.containers.get(name)
        c.remove(force=True)
    except NotFound:
        pass
    except DockerException:
        pass


def build_image(task: TaskInfo) -> str:
    client = docker_client()
    tag = _safe_image_tag(task.id)
    stream = client.api.build(
        path=str(task.environment_dir),
        dockerfile="Dockerfile",
        tag=tag,
        rm=True,
        decode=True,
    )
    for chunk in stream:
        if isinstance(chunk, dict) and chunk.get("error"):
            raise RuntimeError(chunk["error"])
    return tag


def start_container(task: TaskInfo, image_tag: str) -> ContainerSession:
    client = docker_client()
    name = _safe_container_name(task.id)
    remove_container_by_name(name)
    solution = str(task.solution_dir.resolve())
    tests = str(task.tests_dir.resolve())
    container = client.containers.run(
        image_tag,
        command=["sleep", "infinity"],
        detach=True,
        name=name,
        working_dir="/app",
        volumes={
            solution: {"bind": "/solution", "mode": "ro"},
            tests: {"bind": "/tests", "mode": "ro"},
        },
    )
    return ContainerSession(task, image_tag, container.id, name)


def remove_container(container_id: str) -> None:
    client = docker_client()
    try:
        c = client.containers.get(container_id)
        c.remove(force=True)
    except (NotFound, DockerException):
        pass


def exec_in_container(
    container_id: str,
    cmd: list[str],
    workdir: str = "/app",
) -> tuple[int, str]:
    client = docker_client()
    c = client.containers.get(container_id)
    exit_code, output = c.exec_run(cmd, workdir=workdir)
    text = output.decode("utf-8", errors="replace") if isinstance(output, bytes) else str(output)
    return int(exit_code or 0), text


def read_container_file_text(container_id: str, path_in_container: str) -> str | None:
    """Read a UTF-8 file from the container if it exists; otherwise None."""
    q = shlex.quote(path_in_container)
    _code, out = exec_in_container(
        container_id,
        ["bash", "-lc", f"if test -r {q}; then cat {q}; fi"],
        workdir="/",
    )
    if not out:
        return None
    return out

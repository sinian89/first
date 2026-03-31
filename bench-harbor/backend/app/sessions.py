"""In-memory session registry (one container per session)."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field

from .docker_ops import ContainerSession


@dataclass
class BenchSession:
    id: str
    container: ContainerSession
    terminal_proc: asyncio.subprocess.Process | None = None
    terminal_master_fd: int | None = None
    terminal_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    human_active: bool = False
    llm_messages: list[dict[str, str]] = field(default_factory=list)


_REGISTRY: dict[str, BenchSession] = {}


def create_session(container: ContainerSession) -> BenchSession:
    sid = uuid.uuid4().hex
    s = BenchSession(id=sid, container=container)
    _REGISTRY[sid] = s
    return s


def get_session(session_id: str) -> BenchSession | None:
    return _REGISTRY.get(session_id)


def delete_session(session_id: str) -> BenchSession | None:
    return _REGISTRY.pop(session_id, None)

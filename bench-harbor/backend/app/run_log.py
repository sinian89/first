"""Append-only JSONL logs per session and per attempt."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import settings


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def session_dir(session_id: str) -> Path:
    d = settings.data_dir / "runs" / session_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_meta(session_id: str, meta: dict[str, Any]) -> None:
    d = session_dir(session_id)
    p = d / "meta.json"
    payload = {**meta, "updated_at": _utc_iso()}
    if p.is_file():
        try:
            old = json.loads(p.read_text(encoding="utf-8"))
            old.update(payload)
            payload = old
        except Exception:
            pass
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def append_event(
    session_id: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
    attempt_id: str | None = None,
) -> dict[str, Any]:
    d = session_dir(session_id)
    ev = {
        "ts": _utc_iso(),
        "type": event_type,
        "attempt_id": attempt_id,
        "payload": payload or {},
    }
    line = json.dumps(ev, ensure_ascii=False) + "\n"
    with (d / "events.jsonl").open("a", encoding="utf-8") as f:
        f.write(line)
    return ev


def new_attempt_id() -> str:
    return uuid.uuid4().hex[:12]


def append_artifact_record(session_id: str, record: dict[str, Any]) -> None:
    """Append one JSON line to artifacts.jsonl (index of saved logs for this session)."""
    d = session_dir(session_id)
    row = {**record, "logged_at": _utc_iso()}
    with (d / "artifacts.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_artifacts_jsonl(session_id: str) -> list[dict[str, Any]]:
    p = session_dir(session_id) / "artifacts.jsonl"
    if not p.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def read_events_jsonl(session_id: str) -> list[dict[str, Any]]:
    p = session_dir(session_id) / "events.jsonl"
    if not p.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows

"""OpenAI-compatible chat + bash block extraction for agent loop."""

from __future__ import annotations

import asyncio
import datetime
import re
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

SYSTEM = """You are helping complete a terminal-benchmark task inside a Linux Docker container.
Working directory is /app. Reference solution scripts (read-only) live under /solution if needed.
Tests are mounted at /tests (usually run only when the user asks).

Rules:
- Reply with a short plan when useful, then exactly ONE shell command to run inside the container.
- Put the command in a fenced bash block, e.g.
```bash
echo hello
```
- If the task is fully satisfied and nothing else should be run, output ```bash
# DONE
```
with that exact comment only, or a single line `exit 0` after you are sure work is complete.
- Do not use interactive editors that need a TTY unless unavoidable; prefer heredocs or echo.
"""


def format_conversation_text(
    messages: list[dict[str, str]],
    *,
    max_chars: int | None = 1_000_000,
) -> str:
    """Human-readable log of the exact chat sent to the LLM (system + user + assistant turns)."""
    lines: list[str] = []
    for i, m in enumerate(messages):
        role = (m.get("role") or "?").strip().upper()
        content = m.get("content") or ""
        bar = "─" * 72
        lines.append(f"{bar}\n### {role}  (message {i})\n{bar}\n{content}\n")
    out = "\n".join(lines)
    if max_chars is not None and len(out) > max_chars:
        out = (
            out[: max_chars - 120]
            + "\n\n… [truncated: see llm_*_conversation.txt on server for full log] …\n"
        )
    return out


def extract_bash_block(text: str) -> str | None:
    for m in re.finditer(r"```(?:bash|sh)?\s*\n([\s\S]*?)```", text, re.IGNORECASE):
        inner = m.group(1).strip()
        if inner:
            return inner
    return None


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Parse Retry-After header (seconds or HTTP-date)."""
    h = response.headers.get("retry-after")
    if not h:
        return None
    h = h.strip()
    try:
        sec = float(h)
        if sec >= 0:
            return min(sec, 300.0)
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(h)
        if dt is not None:
            now = datetime.datetime.now(datetime.timezone.utc)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            delta = (dt - now).total_seconds()
            if delta > 0:
                return min(delta, 300.0)
    except Exception:
        pass
    return None


async def chat_complete(
    base_url: str,
    model: str,
    messages: list[dict[str, str]],
    api_key: str | None = None,
    timeout_sec: float = 120.0,
    max_retries: int = 8,
    retry_base_sec: float = 2.0,
) -> str:
    url = base_url.rstrip("/") + "/v1/chat/completions"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
    }
    data: dict[str, Any] | None = None
    async with httpx.AsyncClient(timeout=timeout_sec) as client:
        for attempt in range(max_retries + 1):
            r = await client.post(url, json=body, headers=headers)
            if r.status_code in (429, 503):
                if attempt >= max_retries:
                    r.raise_for_status()
                wait = _retry_after_seconds(r)
                if wait is None:
                    wait = min(retry_base_sec * (2**attempt), 120.0)
                await asyncio.sleep(wait)
                continue
            r.raise_for_status()
            data = r.json()
            break

    if not data:
        raise RuntimeError("LLM request failed after retries")

    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("LLM returned no choices")
    msg = choices[0].get("message") or {}
    return (msg.get("content") or "").strip()

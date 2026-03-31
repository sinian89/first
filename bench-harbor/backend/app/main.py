"""Bench Harbor API: tasks, Docker sessions, oracle/LLM/human/test flows, WebSocket terminal."""

from __future__ import annotations

import asyncio
import json
import os
import pty
import uuid
from typing import Any

import docker
from docker.errors import NotFound
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import run_log
from .config import settings
from .docker_ops import (
    build_image,
    exec_in_container,
    read_container_file_text,
    remove_container,
    start_container,
)
from .llm_runner import iter_llm_run
from .sessions import BenchSession, create_session, delete_session, get_session
from .task_registry import discover_tasks, get_task, task_metadata

app = FastAPI(title="Bench Harbor", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = settings.data_dir.parent / "web" / "static"
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def root_page():
    index = STATIC_DIR / "index.html"
    if index.is_file():
        return FileResponse(index)
    return {"service": "bench-harbor", "hint": "Add web/static/index.html or open /docs"}


class CreateSessionBody(BaseModel):
    task_id: str


class LLMRunBody(BaseModel):
    base_url: str = Field(..., description="OpenAI-compatible API base, e.g. https://api.openai.com")
    model: str
    api_key: str | None = None
    max_steps: int = 30
    # Seconds to wait after each container command before the next LLM call (reduces rate-limit bursts).
    step_delay_sec: float = Field(default=1.5, ge=0.0, le=120.0)
    # Extra retries for 429/503 (each waits with backoff or Retry-After).
    llm_max_retries: int = Field(default=8, ge=0, le=30)


@app.get("/api/tasks")
def api_tasks():
    tasks = discover_tasks()
    return {"tasks": [{**task_metadata(t), "path": t.id} for t in tasks]}


@app.post("/api/sessions")
def api_create_session(body: CreateSessionBody):
    task = get_task(body.task_id)
    if not task:
        raise HTTPException(404, f"Unknown task: {body.task_id}")
    run_id = uuid.uuid4().hex
    try:
        tag = build_image(task)
    except RuntimeError as e:
        raise HTTPException(500, f"Docker build failed: {e}") from e
    except Exception as e:
        raise HTTPException(500, f"Build error: {e}") from e
    try:
        cs = start_container(task, tag)
    except Exception as e:
        raise HTTPException(500, f"Could not start container: {e}") from e
    bench = create_session(cs)
    run_log.session_dir(bench.id)
    run_log.write_meta(
        bench.id,
        {
            "session_id": bench.id,
            "task_id": task.id,
            "image": tag,
            "container_id": cs.container_id,
            "container_name": cs.name,
            "external_run_id": run_id,
        },
    )
    run_log.append_event(
        bench.id,
        "session_created",
        {"task_id": task.id, "image": tag, "container_id": cs.container_id},
    )
    return {
        "session_id": bench.id,
        "task_id": task.id,
        "container_id": cs.container_id,
        "image": tag,
    }


@app.delete("/api/sessions/{session_id}")
def api_delete_session(session_id: str):
    s = get_session(session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    if s.terminal_proc and s.terminal_proc.returncode is None:
        s.terminal_proc.terminate()
    if s.terminal_master_fd is not None:
        try:
            os.close(s.terminal_master_fd)
        except OSError:
            pass
        s.terminal_master_fd = None
    s.terminal_proc = None
    delete_session(session_id)
    remove_container(s.container.container_id)
    run_log.append_event(session_id, "session_deleted", {})
    return {"ok": True}


def _require_session(session_id: str) -> BenchSession:
    s = get_session(session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    return s


@app.post("/api/sessions/{session_id}/oracle")
async def api_oracle(session_id: str):
    s = _require_session(session_id)
    attempt = run_log.new_attempt_id()
    run_log.append_event(
        session_id,
        "oracle_start",
        {"script": "/solution/solve.sh"},
        attempt_id=attempt,
    )
    code, out = exec_in_container(
        s.container.container_id,
        ["bash", "-lc", "bash /solution/solve.sh"],
        workdir="/app",
    )
    run_log.append_event(
        session_id,
        "oracle_end",
        {"exit_code": code, "output_chars": len(out)},
        attempt_id=attempt,
    )
    log_dir = run_log.session_dir(session_id)
    log_path = log_dir / f"oracle_{attempt}.txt"
    log_path.write_text(out, encoding="utf-8", errors="replace")
    meta = {
        "kind": "oracle",
        "attempt_id": attempt,
        "task_id": s.container.task.id,
        "exit_code": code,
        "script": "/solution/solve.sh",
        "stdout_stderr_file": log_path.name,
    }
    (log_dir / f"oracle_{attempt}_meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    run_log.append_artifact_record(
        session_id,
        {
            "kind": "oracle",
            "task_id": s.container.task.id,
            "attempt_id": attempt,
            "exit_code": code,
            "files": [log_path.name, f"oracle_{attempt}_meta.json"],
        },
    )
    return {
        "attempt_id": attempt,
        "exit_code": code,
        "output": out,
        "saved_files": [log_path.name, f"oracle_{attempt}_meta.json"],
        "session_log_dir": str(log_dir),
    }


@app.post("/api/sessions/{session_id}/test")
async def api_test(session_id: str):
    s = _require_session(session_id)
    attempt = run_log.new_attempt_id()
    run_log.append_event(session_id, "test_start", {"script": "/tests/test.sh"}, attempt_id=attempt)
    code, out = exec_in_container(
        s.container.container_id,
        ["bash", "-lc", "bash /tests/test.sh"],
        workdir="/app",
    )
    run_log.append_event(
        session_id,
        "test_end",
        {"exit_code": code, "output_chars": len(out)},
        attempt_id=attempt,
    )
    log_dir = run_log.session_dir(session_id)
    log_path = log_dir / f"test_{attempt}.txt"
    log_path.write_text(out, encoding="utf-8", errors="replace")

    files_saved = [log_path.name]
    ctrf = read_container_file_text(s.container.container_id, "/logs/verifier/ctrf.json")
    if ctrf is not None and ctrf.strip():
        ctrf_path = log_dir / f"test_{attempt}_ctrf.json"
        ctrf_path.write_text(ctrf, encoding="utf-8", errors="replace")
        files_saved.append(ctrf_path.name)
    reward = read_container_file_text(s.container.container_id, "/logs/verifier/reward.txt")
    if reward is not None and reward.strip():
        reward_path = log_dir / f"test_{attempt}_reward.txt"
        reward_path.write_text(reward.strip() + "\n", encoding="utf-8")
        files_saved.append(reward_path.name)

    meta = {
        "kind": "test",
        "attempt_id": attempt,
        "task_id": s.container.task.id,
        "exit_code": code,
        "script": "/tests/test.sh",
        "stdout_stderr_file": log_path.name,
        "verifier_ctrf": f"test_{attempt}_ctrf.json" if f"test_{attempt}_ctrf.json" in files_saved else None,
        "verifier_reward": f"test_{attempt}_reward.txt"
        if f"test_{attempt}_reward.txt" in files_saved
        else None,
    }
    meta_path = log_dir / f"test_{attempt}_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    files_saved.append(meta_path.name)

    run_log.append_artifact_record(
        session_id,
        {
            "kind": "test",
            "task_id": s.container.task.id,
            "attempt_id": attempt,
            "exit_code": code,
            "files": files_saved,
        },
    )
    return {
        "attempt_id": attempt,
        "exit_code": code,
        "output": out,
        "saved_files": files_saved,
        "session_log_dir": str(log_dir),
    }


@app.post("/api/sessions/{session_id}/llm/run")
async def api_llm_run(session_id: str, body: LLMRunBody):
    s = _require_session(session_id)
    task = s.container.task
    if not task.instruction_path.is_file():
        raise HTTPException(400, "Task has no instruction.md")
    instruction = task.instruction_path.read_text(encoding="utf-8")
    done: dict[str, Any] | None = None
    async for ev in iter_llm_run(
        session_id,
        s.container.container_id,
        instruction,
        body,
        task_id=s.container.task.id,
    ):
        if ev.get("type") == "done":
            done = ev
            break
    if not done:
        raise HTTPException(500, "LLM run finished without a completion event")
    aid = done["attempt_id"]
    log_dir = run_log.session_dir(session_id)
    return {
        "attempt_id": aid,
        "transcript": done["transcript"],
        "conversation": done["conversation"],
        "conversation_text": done["conversation_text"],
        "conversation_truncated": done["conversation_truncated"],
        "saved_files": [
            f"llm_{aid}.json",
            f"llm_{aid}_conversation.txt",
            f"llm_{aid}_conversation.json",
        ],
        "session_log_dir": str(log_dir),
    }


@app.post("/api/sessions/{session_id}/llm/run-stream")
async def api_llm_run_stream(session_id: str, body: LLMRunBody):
    """Same as /llm/run but streams NDJSON events for live UI (one JSON object per line)."""
    s = _require_session(session_id)
    task = s.container.task
    if not task.instruction_path.is_file():
        raise HTTPException(400, "Task has no instruction.md")
    instruction = task.instruction_path.read_text(encoding="utf-8")

    async def ndjson():
        async for ev in iter_llm_run(
            session_id,
            s.container.container_id,
            instruction,
            body,
            task_id=s.container.task.id,
        ):
            yield (json.dumps(ev, ensure_ascii=False) + "\n").encode("utf-8")

    return StreamingResponse(ndjson(), media_type="application/x-ndjson; charset=utf-8")


@app.get("/api/sessions/{session_id}/logs")
def api_logs(session_id: str):
    _require_session(session_id)
    return {"events": run_log.read_events_jsonl(session_id)}


@app.get("/api/sessions/{session_id}/events.jsonl")
def api_events_file(session_id: str):
    _require_session(session_id)
    p = run_log.session_dir(session_id) / "events.jsonl"
    if not p.is_file():
        raise HTTPException(404, "No events file yet")
    return FileResponse(
        path=str(p),
        filename=f"{session_id}_events.jsonl",
        media_type="text/plain; charset=utf-8",
    )


@app.get("/api/sessions/{session_id}/artifacts")
def api_session_artifacts(session_id: str):
    """JSON list of saved log files (oracle / test / llm) for this session."""
    _require_session(session_id)
    return {"artifacts": run_log.read_artifacts_jsonl(session_id)}


@app.get("/api/sessions/{session_id}/artifacts.jsonl")
def api_artifacts_file(session_id: str):
    _require_session(session_id)
    p = run_log.session_dir(session_id) / "artifacts.jsonl"
    if not p.is_file():
        raise HTTPException(404, "No artifact index yet")
    return FileResponse(
        path=str(p),
        filename=f"{session_id}_artifacts.jsonl",
        media_type="text/plain; charset=utf-8",
    )


@app.post("/api/sessions/{session_id}/human/start")
def api_human_start(session_id: str):
    s = _require_session(session_id)
    attempt = run_log.new_attempt_id()
    s.human_active = True
    run_log.append_event(session_id, "human_start", {}, attempt_id=attempt)
    return {"attempt_id": attempt, "human_active": True}


@app.post("/api/sessions/{session_id}/human/end")
def api_human_end(session_id: str):
    s = _require_session(session_id)
    s.human_active = False
    run_log.append_event(session_id, "human_end", {})
    return {"human_active": False}


@app.websocket("/ws/sessions/{session_id}/terminal")
async def ws_terminal(websocket: WebSocket, session_id: str):
    """Bridge browser xterm to `docker exec -it bash` via a host PTY (line discipline + echo)."""
    await websocket.accept()
    s = get_session(session_id)
    if not s:
        await websocket.close(code=4004)
        return
    client = docker.from_env()
    try:
        c = client.containers.get(s.container.container_id)
    except NotFound:
        await websocket.close(code=4004)
        return
    short_id = c.short_id

    master_fd: int | None = None
    proc: asyncio.subprocess.Process | None = None

    async with s.terminal_lock:
        if s.terminal_proc and s.terminal_proc.returncode is None:
            s.terminal_proc.terminate()
            try:
                await asyncio.wait_for(s.terminal_proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                s.terminal_proc.kill()
        # Do not close the previous connection's PTY here; that WebSocket still owns it.
        s.terminal_proc = None
        s.terminal_master_fd = None

        mfd, sfd = pty.openpty()
        master_fd = mfd
        slave_fd = sfd
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "exec",
                "-it",
                "-w",
                "/app",
                short_id,
                "bash",
                "--noprofile",
                "--norc",
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
            )
        finally:
            try:
                os.close(slave_fd)
            except OSError:
                pass
        s.terminal_proc = proc
        s.terminal_master_fd = master_fd

    assert master_fd is not None and proc is not None

    run_log.append_event(
        session_id,
        "terminal_attached",
        {"container": short_id, "pty": True},
    )

    bytes_out = 0
    bytes_in = 0
    loop = asyncio.get_running_loop()

    async def pump_out():
        nonlocal bytes_out
        try:
            while True:
                chunk = await loop.run_in_executor(None, lambda: os.read(master_fd, 65536))
                if not chunk:
                    break
                bytes_out += len(chunk)
                await websocket.send_bytes(chunk)
        except (WebSocketDisconnect, asyncio.CancelledError):
            raise
        except Exception:
            pass

    reader = asyncio.create_task(pump_out())
    try:
        while True:
            msg = await websocket.receive()
            mtype = msg.get("type")
            if mtype == "websocket.disconnect":
                break
            if mtype is not None and mtype != "websocket.receive":
                continue
            raw = msg.get("bytes")
            if raw is not None and len(raw) > 0:
                bytes_in += len(raw)

                def _write(b: bytes = raw) -> None:
                    os.write(master_fd, b)

                try:
                    await loop.run_in_executor(None, _write)
                except OSError:
                    break
                continue
            text = msg.get("text")
            if text:
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if data.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        pass
    finally:
        reader.cancel()
        try:
            await reader
        except asyncio.CancelledError:
            pass
        try:
            os.close(master_fd)
        except OSError:
            pass
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                proc.kill()
        if s.terminal_proc is proc:
            s.terminal_proc = None
            s.terminal_master_fd = None
        run_log.append_event(
            session_id,
            "terminal_detached",
            {"bytes_to_container": bytes_in, "bytes_from_container": bytes_out},
        )


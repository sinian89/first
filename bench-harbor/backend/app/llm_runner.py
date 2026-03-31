"""Shared LLM agent loop: yields UI/log events; used by JSON and streaming endpoints."""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

from . import run_log
from .docker_ops import exec_in_container
from .llm_client import SYSTEM, chat_complete, extract_bash_block, format_conversation_text


async def iter_llm_run(
    session_id: str,
    container_id: str,
    instruction: str,
    body: Any,
    task_id: str,
) -> AsyncIterator[dict[str, Any]]:
    """
    Yields event dicts for UI (stream) and logging.
    Final event is always {"type": "done", ...} with transcript, conversation, etc.
    """
    attempt = run_log.new_attempt_id()
    run_log.append_event(
        session_id,
        "llm_run_start",
        {
            "model": body.model,
            "base_url": body.base_url,
            "max_steps": body.max_steps,
            "step_delay_sec": body.step_delay_sec,
            "llm_max_retries": body.llm_max_retries,
        },
        attempt_id=attempt,
    )

    yield {
        "type": "started",
        "attempt_id": attempt,
        "max_steps": body.max_steps,
        "model": body.model,
    }

    messages: list[dict[str, str]] = [
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            "content": f"Task instructions:\n\n{instruction}\n\nBegin by proposing the first shell command.",
        },
    ]

    yield {"type": "message", "role": "system", "content": SYSTEM}
    yield {
        "type": "message",
        "role": "user",
        "content": messages[1]["content"],
    }

    transcript: list[dict[str, Any]] = []

    for step in range(body.max_steps):
        yield {"type": "round_start", "step": step}

        try:
            reply = await chat_complete(
                body.base_url,
                body.model,
                messages,
                api_key=body.api_key,
                max_retries=body.llm_max_retries,
            )
        except Exception as e:
            transcript.append({"step": step, "error": str(e)})
            run_log.append_event(
                session_id,
                "llm_error",
                {"step": step, "error": str(e)},
                attempt_id=attempt,
            )
            yield {"type": "error", "step": step, "message": str(e)}
            break

        messages.append({"role": "assistant", "content": reply})
        transcript.append({"step": step, "assistant": reply})
        yield {"type": "assistant", "step": step, "content": reply}

        block = extract_bash_block(reply)
        if block is None:
            transcript.append({"step": step, "note": "no bash block; stopping"})
            yield {"type": "note", "step": step, "text": "No bash fence in reply; stopping."}
            break
        if block.strip() in ("# DONE", "# done") or block.strip() == "exit 0":
            transcript.append({"step": step, "done": True})
            yield {"type": "done_signal", "step": step, "command": block.strip()}
            break

        yield {"type": "shell_start", "step": step, "command": block}

        code, out = exec_in_container(
            container_id,
            ["bash", "-lc", block],
            workdir="/app",
        )
        user_msg = f"Exit code: {code}\n\n--- stdout/stderr ---\n{out}"
        messages.append({"role": "user", "content": user_msg})
        transcript.append({"step": step, "command": block, "exit_code": code, "output": out})

        yield {
            "type": "shell_result",
            "step": step,
            "command": block,
            "exit_code": code,
            "output": out,
        }

        yield {"type": "message", "role": "user", "content": user_msg}

        run_log.append_event(
            session_id,
            "llm_step",
            {"step": step, "exit_code": code, "cmd_preview": block[:200]},
            attempt_id=attempt,
        )
        if body.step_delay_sec > 0 and step < body.max_steps - 1:
            await asyncio.sleep(body.step_delay_sec)

    run_log.append_event(session_id, "llm_run_end", {"steps": len(transcript)}, attempt_id=attempt)
    log_dir = run_log.session_dir(session_id)
    log_path = log_dir / f"llm_{attempt}.json"
    log_path.write_text(
        json.dumps(transcript, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    conv_path = log_dir / f"llm_{attempt}_conversation.txt"
    conversation_text = format_conversation_text(messages, max_chars=None)
    conv_path.write_text(conversation_text, encoding="utf-8", errors="replace")
    conv_json_path = log_dir / f"llm_{attempt}_conversation.json"
    conv_json_path.write_text(
        json.dumps(messages, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    conversation_text_response = format_conversation_text(messages, max_chars=400_000)

    run_log.append_artifact_record(
        session_id,
        {
            "kind": "llm",
            "task_id": task_id,
            "attempt_id": attempt,
            "model": body.model,
            "base_url": body.base_url,
            "files": [
                log_path.name,
                conv_path.name,
                conv_json_path.name,
            ],
            "transcript_steps": len(transcript),
        },
    )

    yield {
        "type": "done",
        "attempt_id": attempt,
        "transcript": transcript,
        "conversation": messages,
        "conversation_text": conversation_text_response,
        "conversation_truncated": len(conversation_text_response) < len(conversation_text),
        "saved_files": [
            log_path.name,
            conv_path.name,
            conv_json_path.name,
        ],
        "session_log_dir": str(log_dir),
    }

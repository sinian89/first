/* global Terminal, FitAddon */

const $ = (id) => document.getElementById(id);

let sessionId = null;
let taskId = null;
let term = null;
let fit = null;
let ws = null;
const transport = { ws: null };

function api(path, opts = {}) {
  return fetch(path, {
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  }).then(async (r) => {
    const text = await r.text();
    let data;
    try {
      data = text ? JSON.parse(text) : {};
    } catch {
      data = { raw: text };
    }
    if (!r.ok) {
      const msg = data.detail || data.message || data.raw || r.statusText;
      throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
    }
    return data;
  });
}

function wsUrl(path) {
  const p = location.protocol === "https:" ? "wss:" : "ws:";
  return `${p}//${location.host}${path}`;
}

function showModal(id, show) {
  $(id).classList.toggle("hidden", !show);
}

function showOutputModal(title, body) {
  $("modalOutTitle").textContent = title;
  $("modalOutBody").textContent = body;
  showModal("modalOut", true);
}

function llmMkRoleLabel(text) {
  const l = document.createElement("div");
  l.className = "llm-role-label";
  l.textContent = text;
  return l;
}

function llmMkPre(text, extraClass) {
  const p = document.createElement("pre");
  p.textContent = text == null ? "" : String(text);
  if (extraClass) p.classList.add(extraClass);
  return p;
}

function llmFeedScrollToBottom() {
  const feed = $("llmProcessFeed");
  if (feed) feed.scrollTop = feed.scrollHeight;
}

function llmFeedPrepare() {
  const feed = $("llmProcessFeed");
  const empty = $("llmFeedEmpty");
  if (empty) empty.remove();
  feed.innerHTML = "";
}

function appendLlmStreamEvent(ev) {
  const feed = $("llmProcessFeed");
  switch (ev.type) {
    case "started": {
      const el = document.createElement("div");
      el.className = "llm-block llm-started";
      el.appendChild(llmMkRoleLabel("RUN STARTED"));
      const p = document.createElement("p");
      p.style.margin = "0.35rem 0 0";
      p.style.fontSize = "0.8rem";
      p.textContent = `Attempt ${ev.attempt_id} · model ${ev.model} · max steps ${ev.max_steps}`;
      el.appendChild(p);
      feed.appendChild(el);
      break;
    }
    case "round_start": {
      const el = document.createElement("div");
      el.className = "llm-round";
      el.textContent = `— Round ${ev.step + 1} (LLM call) —`;
      feed.appendChild(el);
      break;
    }
    case "message": {
      const el = document.createElement("div");
      el.className = `llm-block llm-msg llm-role-${ev.role}`;
      el.appendChild(llmMkRoleLabel(String(ev.role).toUpperCase()));
      el.appendChild(llmMkPre(ev.content));
      feed.appendChild(el);
      break;
    }
    case "assistant": {
      const el = document.createElement("div");
      el.className = "llm-block llm-assistant";
      el.appendChild(llmMkRoleLabel("ASSISTANT"));
      el.appendChild(llmMkPre(ev.content));
      feed.appendChild(el);
      break;
    }
    case "shell_start": {
      const el = document.createElement("div");
      el.className = "llm-block llm-shell";
      el.appendChild(llmMkRoleLabel(`SHELL · step ${ev.step}`));
      el.appendChild(llmMkPre(ev.command));
      feed.appendChild(el);
      break;
    }
    case "shell_result": {
      const el = document.createElement("div");
      el.className = "llm-block llm-shell";
      el.appendChild(llmMkRoleLabel(`CONTAINER OUTPUT · exit ${ev.exit_code}`));
      el.appendChild(llmMkPre(ev.output, "shell-out"));
      feed.appendChild(el);
      break;
    }
    case "done_signal": {
      const el = document.createElement("div");
      el.className = "llm-block";
      el.appendChild(llmMkRoleLabel("MODEL DONE"));
      el.appendChild(llmMkPre(ev.command));
      feed.appendChild(el);
      break;
    }
    case "note": {
      const el = document.createElement("div");
      el.className = "llm-block";
      el.appendChild(llmMkRoleLabel("NOTE"));
      el.appendChild(llmMkPre(ev.text));
      feed.appendChild(el);
      break;
    }
    case "error": {
      const el = document.createElement("div");
      el.className = "llm-block llm-error";
      el.appendChild(llmMkRoleLabel("ERROR"));
      el.appendChild(llmMkPre(ev.message));
      feed.appendChild(el);
      break;
    }
    default:
      break;
  }
  llmFeedScrollToBottom();
}

async function runLlmWithLiveUi(body) {
  llmFeedPrepare();
  $("panelLlmProcess").scrollIntoView({ behavior: "smooth", block: "nearest" });

  const res = await fetch(`/api/sessions/${sessionId}/llm/run-stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = j.detail || JSON.stringify(j);
    } catch {
      msg = await res.text();
    }
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  let donePayload = null;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const lines = buf.split("\n");
    buf = lines.pop() || "";
    for (const line of lines) {
      if (!line.trim()) continue;
      const ev = JSON.parse(line);
      if (ev.type === "done") donePayload = ev;
      else appendLlmStreamEvent(ev);
    }
  }
  if (buf.trim()) {
    try {
      const ev = JSON.parse(buf);
      if (ev.type === "done") donePayload = ev;
      else appendLlmStreamEvent(ev);
    } catch (_) {
      /* ignore incomplete last line */
    }
  }
  if (!donePayload) throw new Error("Stream ended without completion");
  const fin = document.createElement("div");
  fin.className = "llm-block llm-done";
  fin.appendChild(llmMkRoleLabel("RUN COMPLETE"));
  const p = document.createElement("p");
  p.style.margin = "0.35rem 0 0";
  p.style.fontSize = "0.8rem";
  p.textContent = `Attempt ${donePayload.attempt_id}. See summary modal for full export.`;
  fin.appendChild(p);
  $("llmProcessFeed").appendChild(fin);
  llmFeedScrollToBottom();
  return donePayload;
}

function initTerm() {
  if (term) return;
  const FitCtor =
    typeof FitAddon !== "undefined" && (FitAddon.FitAddon || FitAddon);
  term = new Terminal({
    cursorBlink: true,
    fontSize: 13,
    theme: { background: "#0c0c0c", foreground: "#e0e0e0" },
  });
  if (typeof FitCtor === "function") {
    fit = new FitCtor();
    term.loadAddon(fit);
  } else {
    fit = null;
    console.warn(
      "Bench Harbor: FitAddon failed to load (check CDN / network). Terminal works without auto-resize.",
    );
  }
  term.open($("terminal"));
  if (fit) fit.fit();
  term.onData((d) => {
    const w = transport.ws;
    if (w && w.readyState === WebSocket.OPEN) w.send(new TextEncoder().encode(d));
  });
  window.addEventListener("resize", () => {
    if (fit) fit.fit();
  });
}

function setSessionUI() {
  const has = !!sessionId;
  $("btnOracle").disabled = !has;
  $("btnLLM").disabled = !has;
  $("btnHumanStart").disabled = !has;
  $("btnHumanEnd").disabled = !has;
  $("btnTest").disabled = !has;
  $("btnConnect").disabled = !has;
  $("btnRefreshLogs").disabled = !has;
  $("btnDownloadLogs").disabled = !has;
  $("btnDownloadArtifacts").disabled = !has;
  $("btnTeardown").disabled = !has;
  if (has) {
    $("sessionInfo").textContent = `Session: ${sessionId} · task: ${taskId}`;
  } else {
    $("sessionInfo").textContent = "";
  }
}

async function loadTasks() {
  const { tasks } = await api("/api/tasks");
  const sel = $("taskSelect");
  sel.innerHTML = "";
  for (const t of tasks) {
    const o = document.createElement("option");
    o.value = t.path;
    o.textContent = `${t.path}${t.title ? ` — ${t.title}` : ""}`;
    sel.appendChild(o);
  }
}

function connectWs() {
  if (!sessionId) return;
  initTerm();
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    ws.close();
  }
  const url = wsUrl(`/ws/sessions/${sessionId}/terminal`);
  $("wsStatus").textContent = "Connecting…";
  ws = new WebSocket(url);
  ws.binaryType = "arraybuffer";
  ws.onopen = () => {
    $("wsStatus").textContent = "Connected";
    if (fit) fit.fit();
    term.focus();
  };
  ws.onclose = () => {
    $("wsStatus").textContent = "Disconnected";
    if (transport.ws === ws) transport.ws = null;
  };
  ws.onerror = () => {
    $("wsStatus").textContent = "WebSocket error";
  };
  ws.onmessage = (ev) => {
    if (ev.data instanceof ArrayBuffer) {
      term.write(new Uint8Array(ev.data));
    } else {
      term.write(ev.data);
    }
  };
  transport.ws = ws;
}

async function refreshLogs() {
  if (!sessionId) return;
  const { events } = await api(`/api/sessions/${sessionId}/logs`);
  $("logPreview").textContent = events
    .slice(-40)
    .map((e) => `${e.ts} [${e.type}] ${JSON.stringify(e.payload || {})}`)
    .join("\n");
}

function downloadEvents() {
  if (!sessionId) return;
  window.open(`/api/sessions/${sessionId}/events.jsonl`, "_blank");
}

$("btnPrepare").onclick = async () => {
  taskId = $("taskSelect").value;
  if (!taskId) return;
  $("btnPrepare").disabled = true;
  $("sessionInfo").textContent = "Building image (may take several minutes)…";
  try {
    const res = await api("/api/sessions", {
      method: "POST",
      body: JSON.stringify({ task_id: taskId }),
    });
    sessionId = res.session_id;
    taskId = res.task_id;
    setSessionUI();
    $("sessionInfo").textContent = `Session: ${sessionId} · ${res.image}`;
    await refreshLogs();
  } catch (e) {
    $("sessionInfo").textContent = `Error: ${e.message}`;
  } finally {
    $("btnPrepare").disabled = false;
  }
};

$("btnTeardown").onclick = async () => {
  if (!sessionId) return;
  if (ws) ws.close();
  ws = null;
  transport.ws = null;
  await api(`/api/sessions/${sessionId}`, { method: "DELETE" });
  sessionId = null;
  taskId = null;
  setSessionUI();
  $("logPreview").textContent = "";
};

$("btnConnect").onclick = () => connectWs();

$("btnOracle").onclick = async () => {
  if (!sessionId) return;
  initTerm();
  if (fit) fit.fit();
  term.writeln("\r\n\x1b[36m— Running oracle: bash /solution/solve.sh —\x1b[0m\r\n");
  try {
    const res = await api(`/api/sessions/${sessionId}/oracle`, { method: "POST" });
    term.write(res.output || "");
    term.writeln(`\r\n\x1b[33mexit code: ${res.exit_code}\x1b[0m\r\n`);
    showOutputModal(`Oracle (exit ${res.exit_code})`, res.output || "");
    await refreshLogs();
  } catch (e) {
    term.writeln(`\r\n\x1b[31m${e.message}\x1b[0m\r\n`);
  }
};

$("btnLLM").onclick = () => showModal("modalLLM", true);
$("llmCancel").onclick = () => showModal("modalLLM", false);

$("llmRun").onclick = async () => {
  if (!sessionId) return;
  const base_url = $("llmBase").value.trim();
  const model = $("llmModel").value.trim();
  const api_key = $("llmKey").value.trim() || null;
  const max_steps = parseInt($("llmSteps").value, 10) || 30;
  const step_delay_sec = parseFloat($("llmDelay").value);
  const delay =
    Number.isFinite(step_delay_sec) && step_delay_sec >= 0 ? step_delay_sec : 2;
  if (!base_url || !model) {
    alert("Base URL and model are required.");
    return;
  }
  const payload = {
    base_url,
    model,
    api_key,
    max_steps,
    step_delay_sec: delay,
  };
  showModal("modalLLM", false);
  initTerm();
  if (fit) fit.fit();
  term.writeln("\r\n\x1b[36m— LLM simulation (live feed in panel above) —\x1b[0m\r\n");
  $("btnLLM").disabled = true;
  $("llmRun").disabled = true;
  try {
    const res = await runLlmWithLiveUi(payload);
    let modalBody = "";
    if (res.conversation_text) {
      modalBody +=
        "=== LLM conversation (messages sent to the API: system, user, assistant, …) ===\n\n";
      modalBody += res.conversation_text;
      if (res.conversation_truncated) {
        modalBody +=
          "\n\n[Truncated in browser; full log: bench-harbor/data/runs/<session>/llm_*_conversation.txt]\n";
      }
      modalBody += "\n\n";
    }
    modalBody += "=== Step transcript (JSON) ===\n\n";
    modalBody += JSON.stringify(res.transcript, null, 2);
    showOutputModal("LLM run — full export", modalBody);
    for (const row of res.transcript || []) {
      if (row.assistant)
        term.writeln(`\x1b[35m[assistant step ${row.step}]\x1b[0m`);
      if (row.command)
        term.writeln(
          `\x1b[33m$ ${String(row.command).slice(0, 200)}${String(row.command).length > 200 ? "…" : ""}\x1b[0m`,
        );
      if (row.output) term.write(row.output);
      if (row.error) term.writeln(`\x1b[31m${row.error}\x1b[0m`);
    }
    await refreshLogs();
  } catch (e) {
    showOutputModal("LLM error", e.message);
  } finally {
    $("btnLLM").disabled = !sessionId;
    $("llmRun").disabled = false;
  }
};

$("btnLlmClearFeed").onclick = () => {
  const feed = $("llmProcessFeed");
  feed.innerHTML = "";
  const p = document.createElement("p");
  p.className = "muted small llm-feed-empty";
  p.id = "llmFeedEmpty";
  p.appendChild(document.createTextNode("Run "));
  const strong = document.createElement("strong");
  strong.textContent = "LLM";
  p.appendChild(strong);
  p.appendChild(document.createTextNode(" to stream the conversation here."));
  feed.appendChild(p);
};

$("btnHumanStart").onclick = async () => {
  if (!sessionId) return;
  try {
    await api(`/api/sessions/${sessionId}/human/start`, { method: "POST" });
    connectWs();
    await refreshLogs();
  } catch (e) {
    alert(e.message);
  }
};

$("btnHumanEnd").onclick = async () => {
  if (!sessionId) return;
  try {
    await api(`/api/sessions/${sessionId}/human/end`, { method: "POST" });
    await refreshLogs();
  } catch (e) {
    alert(e.message);
  }
};

$("btnTest").onclick = async () => {
  if (!sessionId) return;
  initTerm();
  if (fit) fit.fit();
  term.writeln("\r\n\x1b[36m— Running tests: bash /tests/test.sh —\x1b[0m\r\n");
  try {
    const res = await api(`/api/sessions/${sessionId}/test`, { method: "POST" });
    term.write(res.output || "");
    term.writeln(`\r\n\x1b[33mexit code: ${res.exit_code}\x1b[0m\r\n`);
    showOutputModal(`Tests (exit ${res.exit_code})`, res.output || "");
    await refreshLogs();
  } catch (e) {
    term.writeln(`\r\n\x1b[31m${e.message}\x1b[0m\r\n`);
  }
};

$("btnRefreshLogs").onclick = () => refreshLogs();
$("btnDownloadLogs").onclick = () => downloadEvents();

$("btnDownloadArtifacts").onclick = () => {
  if (!sessionId) return;
  window.open(`/api/sessions/${sessionId}/artifacts.jsonl`, "_blank");
};

$("modalOutClose").onclick = () => showModal("modalOut", false);

loadTasks().catch((e) => {
  $("taskSelect").innerHTML = "";
  const o = document.createElement("option");
  o.textContent = `Failed to load tasks: ${e.message}`;
  $("taskSelect").appendChild(o);
});

setSessionUI();

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import unquote

from .db import connect
from .ids import new_id
from .memory import delete_memory, ensure_db, list_memories
from .osint import (
    browser_profile_dir,
    collect_browser_documents,
    collect_osint_documents,
    research_target_with_browser_receipt,
    research_target_with_receipt,
    save_research_collection,
)
from .persona_knowledge import delete_persona_knowledge, list_persona_knowledge, research_persona_from_wikipedia
from .personas import add_persona_for_model, delete_persona, list_personas
from .sessions import current_db_path
from .tool_manager import all_models


def run_web_ui(
    conn: sqlite3.Connection,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
    research_browser: bool = False,
) -> int:
    db_path = current_db_path(conn)
    if not db_path:
        raise RuntimeError("Cogito web UI needs a file-backed database")
    server = ThreadingHTTPServer((host, port), make_handler(db_path))
    url = f"http://{host}:{server.server_address[1]}"
    print(f"Cogito web UI: {url}")
    stop_browser = threading.Event()
    if open_browser:
        open_web_ui(url, research_browser=research_browser, stop_event=stop_browser)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        stop_browser.set()
        server.server_close()
    return 0


def open_web_ui(url: str, *, research_browser: bool, stop_event: threading.Event) -> None:
    if not research_browser:
        threading.Timer(0.25, lambda: webbrowser.open(url)).start()
        return
    thread = threading.Thread(target=open_research_browser_ui, args=(url, stop_event), daemon=True)
    thread.start()


def open_research_browser_ui(url: str, stop_event: threading.Event) -> None:
    try:
        asyncio.run(open_research_browser_ui_async(url, stop_event))
    except Exception:
        webbrowser.open(url)


async def open_research_browser_ui_async(url: str, stop_event: threading.Event) -> None:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError("browser UI needs playwright; run: .venv/bin/pip install -e .") from exc

    profile_dir = browser_profile_dir()
    profile_dir.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        try:
            context = await p.chromium.launch_persistent_context(
                str(profile_dir),
                headless=False,
                channel="chrome",
                viewport={"width": 1440, "height": 1000},
            )
        except Exception:
            context = await p.chromium.launch_persistent_context(
                str(profile_dir),
                headless=False,
                viewport={"width": 1440, "height": 1000},
            )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        while not stop_event.is_set():
            await asyncio.sleep(0.5)
        await context.close()


def make_handler(db_path: str):
    pending_research: dict[str, dict[str, Any]] = {}

    class CogitoWebHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            try:
                if self.path == "/" or self.path.startswith("/?"):
                    self.send_html(INDEX_HTML)
                    return
                if self.path == "/api/state":
                    self.send_json(with_connection(db_path, build_state))
                    return
                self.send_error(404)
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=500)

        def do_POST(self) -> None:
            try:
                payload = self.read_json()
                if self.path == "/api/personas":
                    self.send_json(with_connection(db_path, lambda conn: create_persona(conn, payload)))
                    return
                if self.path == "/api/research":
                    self.send_json(with_connection(db_path, lambda conn: run_research(conn, payload)))
                    return
                if self.path == "/api/research/preview":
                    self.send_json(preview_research(payload, pending_research))
                    return
                if self.path == "/api/research/approve":
                    self.send_json(with_connection(db_path, lambda conn: approve_research(conn, payload, pending_research)))
                    return
                self.send_error(404)
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=500)

        def do_DELETE(self) -> None:
            try:
                if self.path.startswith("/api/personas/"):
                    name = unquote(self.path.removeprefix("/api/personas/"))
                    with_connection(db_path, lambda conn: delete_persona(conn, name))
                    self.send_json({"ok": True})
                    return
                if self.path.startswith("/api/memories/"):
                    memory_id = unquote(self.path.removeprefix("/api/memories/"))
                    self.send_json(with_connection(db_path, lambda conn: delete_memory(conn, memory_id)))
                    return
                if self.path.startswith("/api/persona-knowledge/"):
                    item_id = unquote(self.path.removeprefix("/api/persona-knowledge/"))
                    self.send_json(with_connection(db_path, lambda conn: delete_persona_knowledge(conn, item_id)))
                    return
                self.send_error(404)
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=500)

        def read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("content-length") or "0")
            if not length:
                return {}
            return json.loads(self.rfile.read(length).decode("utf-8"))

        def send_json(self, payload: Any, status: int = 200) -> None:
            data = json.dumps(payload, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def send_html(self, html: str) -> None:
            data = html.encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args) -> None:
            return None

    return CogitoWebHandler


def with_connection(db_path: str, callback):
    conn = connect(db_path)
    try:
        ensure_db(conn)
        return callback(conn)
    finally:
        conn.close()


def build_state(conn: sqlite3.Connection) -> dict[str, Any]:
    personas = []
    for persona in list_personas(conn):
        knowledge = list_persona_knowledge(conn, persona_name=persona["name"])
        personas.append(
            {
                "name": persona["name"],
                "agent": persona["agent"],
                "model": persona.get("model"),
                "description": persona["description"],
                "knowledge_count": len(knowledge),
                "facts": [ui_fact(item) for item in knowledge[:80]],
            }
        )
    memories = [
        memory
        for memory in list_memories(conn)
        if memory.get("type") in {"public_research", "fact", "goal", "preference"}
    ]
    return {"personas": personas, "memories": [ui_fact(memory) for memory in memories[:160]], "models": model_options()}


def ui_fact(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if key not in {"embedding", "embedding_model"}}


def create_persona(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    name = required(payload, "name").strip().lstrip("@")
    model = required(payload, "model").strip()
    mode = payload.get("mode") or "description"
    description = (payload.get("description") or "").strip()
    source = (payload.get("source") or "").strip()
    browser = bool(payload.get("browser"))
    if mode == "historical":
        subject = source or description or name
        persona = add_persona_for_model(
            conn,
            name=name,
            model=model,
            description=f"Historical/public persona researched as {subject}.",
        )
        created = research_persona_from_wikipedia(conn, persona_name=name, subject=subject)
        return {
            "persona": persona,
            "research": {
                "target": f"@{name}",
                "query": subject,
                "saved_chunks": [
                    {
                        "store": "persona_rag",
                        "id": item["id"],
                        "source_url": item.get("source_url"),
                        "preview": item["text"][:160],
                    }
                    for item in created
                ],
            },
        }
    if not description:
        raise ValueError("description is required for description personas")
    persona = add_persona_for_model(conn, name=name, model=model, description=description)
    research = None
    if source:
        research = run_research(conn, {"target": f"@{name}", "source": source, "browser": browser})
    return {"persona": persona, "research": research}


def preview_research(payload: dict[str, Any], pending_research: dict[str, dict[str, Any]]) -> dict[str, Any]:
    target = required(payload, "target")
    source = required(payload, "source")
    browser = bool(payload.get("browser"))
    limit = int(payload.get("limit") or 8)
    collection = (
        collect_browser_documents(source, limit=limit, wait_seconds=10.0)
        if browser
        else collect_osint_documents(source, limit=limit)
    )
    token = new_id("rsrch")
    pending_research[token] = {"target": target, "collection": collection}
    return simplify_collection(token, target, collection)


def approve_research(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
    pending_research: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    token = required(payload, "token")
    selected_urls = set(payload.get("selected_urls") or [])
    item = pending_research.pop(token, None)
    if item is None:
        raise KeyError("research preview expired or was already approved")
    collection = filter_collection(item["collection"], selected_urls)
    receipt = save_research_collection(conn, target=item["target"], collection=collection)
    return simplify_receipt(receipt)


def run_research(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    target = required(payload, "target")
    source = required(payload, "source")
    browser = bool(payload.get("browser"))
    research_fn = research_target_with_browser_receipt if browser else research_target_with_receipt
    return simplify_receipt(research_fn(conn, target=target, source=source))


def filter_collection(collection: dict[str, Any], selected_urls: set[str]) -> dict[str, Any]:
    if not selected_urls:
        return collection | {"documents": [], "scanned_sources": []}
    return collection | {
        "documents": [doc for doc in collection.get("documents", []) if doc.get("url") in selected_urls],
        "scanned_sources": [src for src in collection.get("scanned_sources", []) if src.get("url") in selected_urls],
    }


def simplify_collection(token: str, target: str, collection: dict[str, Any]) -> dict[str, Any]:
    return {
        "token": token,
        "target": target,
        "query": collection["query"],
        "seed_urls": collection.get("seed_urls", []),
        "discovered_urls": collection.get("discovered_urls", []),
        "scanned_sources": collection.get("scanned_sources", []),
        "failed_sources": collection.get("failed_sources", []),
        "browser_profile": collection.get("browser_profile"),
    }


def simplify_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    return {
        "target": receipt["target"],
        "query": receipt["query"],
        "seed_urls": receipt.get("seed_urls", []),
        "discovered_urls": receipt.get("discovered_urls", []),
        "scanned_sources": receipt.get("scanned_sources", []),
        "failed_sources": receipt.get("failed_sources", []),
        "saved_chunks": receipt.get("saved_chunks", []),
        "browser_profile": receipt.get("browser_profile"),
    }


def required(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required")
    return value


def model_options() -> list[str]:
    return sorted(set(["gpt-5.5", "gpt-5.4", "sonnet", "opus", "qwen3:0.6b", "qwen3:1.7b", *all_models()]))


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Cogito Memory Desk</title>
  <style>
    :root {
      --paper: #f3efe3;
      --ink: #1f211d;
      --muted: #68685e;
      --line: #d6cdb8;
      --panel: #fffaf0;
      --iron: #272c29;
      --green: #2f6d4f;
      --amber: #a96926;
      --red: #9b3f36;
      --blue: #365f78;
      --shadow: rgba(44, 37, 25, 0.13);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--ink);
      background:
        linear-gradient(90deg, rgba(31,33,29,.035) 1px, transparent 1px) 0 0 / 26px 26px,
        linear-gradient(rgba(31,33,29,.026) 1px, transparent 1px) 0 0 / 26px 26px,
        var(--paper);
      font-family: ui-serif, Georgia, "Times New Roman", serif;
    }
    header {
      height: 74px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 28px;
      border-bottom: 1px solid var(--line);
      background: rgba(243, 239, 227, .94);
      position: sticky;
      top: 0;
      z-index: 2;
    }
    h1 { margin: 0; font-size: 24px; letter-spacing: 0; font-weight: 700; }
    header span { color: var(--muted); font: 13px ui-sans-serif, system-ui, sans-serif; }
    main {
      display: grid;
      grid-template-columns: minmax(360px, 420px) minmax(0, 1fr);
      gap: 18px;
      padding: 18px;
      min-height: calc(100vh - 74px);
    }
    aside, .board {
      border: 1px solid var(--line);
      background: rgba(255, 250, 240, .88);
      box-shadow: 0 18px 55px var(--shadow);
    }
    aside { padding: 16px; align-self: start; position: sticky; top: 92px; }
    .board { padding: 16px; }
    .tabs { display: flex; gap: 6px; margin-bottom: 14px; }
    .tab, button {
      border: 1px solid var(--iron);
      background: var(--iron);
      color: #fffaf0;
      padding: 9px 11px;
      font: 700 13px ui-sans-serif, system-ui, sans-serif;
      cursor: pointer;
    }
    .tab[aria-selected="true"] { background: var(--green); border-color: var(--green); }
    label { display: block; font: 700 12px ui-sans-serif, system-ui, sans-serif; color: var(--muted); margin: 12px 0 5px; }
    input, textarea, select {
      width: 100%;
      border: 1px solid var(--line);
      background: #fffdf7;
      color: var(--ink);
      padding: 10px;
      font: 14px ui-sans-serif, system-ui, sans-serif;
      outline: none;
    }
    textarea { min-height: 88px; resize: vertical; }
    .row { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .check { display: flex; gap: 8px; align-items: center; margin-top: 10px; color: var(--muted); font: 13px ui-sans-serif, system-ui, sans-serif; }
    .check input { width: auto; }
    .actions { display: flex; gap: 8px; margin-top: 14px; flex-wrap: wrap; }
    .secondary { background: transparent; color: var(--iron); }
    .danger { background: var(--red); border-color: var(--red); }
    .approve { background: var(--green); border-color: var(--green); }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(330px, 1fr)); gap: 12px; }
    .card {
      border: 1px solid var(--line);
      background: rgba(255, 253, 247, .92);
      padding: 14px;
      min-height: 150px;
    }
    .card h3 { margin: 0 0 6px; font-size: 19px; }
    .meta { color: var(--muted); font: 12px ui-sans-serif, system-ui, sans-serif; margin-bottom: 10px; }
    .fact {
      border-left: 3px solid var(--blue);
      padding: 8px 10px;
      margin: 8px 0;
      background: rgba(54, 95, 120, .07);
      font-size: 14px;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }
    .fact button { margin-top: 8px; padding: 6px 8px; font-size: 11px; }
    .source {
      border: 1px solid var(--line);
      background: #fffdf7;
      padding: 10px;
      margin: 8px 0;
      font: 13px ui-sans-serif, system-ui, sans-serif;
    }
    .source label { margin: 0 0 6px; color: var(--ink); display: flex; gap: 8px; align-items: start; }
    .source input { width: auto; margin-top: 2px; }
    .toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; gap: 12px; }
    .toolbar h2 { margin: 0; font-size: 22px; }
    #status, #review { white-space: pre-wrap; font: 12px ui-monospace, SFMono-Regular, Menlo, monospace; color: var(--muted); }
    #review { margin-top: 14px; }
    .hidden { display: none; }
    @media (max-width: 920px) {
      main { grid-template-columns: 1fr; }
      aside { position: static; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Cogito Memory Desk</h1>
      <span>Local persona registry, OSINT review queue, and fact vault</span>
    </div>
    <button class="secondary" onclick="loadState()">Refresh</button>
  </header>
  <main>
    <aside>
      <div class="tabs">
        <button class="tab" id="tab-person" aria-selected="true" onclick="showForm('person')">Person</button>
        <button class="tab" id="tab-research" aria-selected="false" onclick="showForm('research')">Research</button>
      </div>

      <form id="person-form">
        <label>Name</label>
        <input name="name" placeholder="architect or aristotle" required />
        <div class="row">
          <div>
            <label>Model</label>
            <input name="model" list="models" value="gpt-5.5" required />
          </div>
          <div>
            <label>Mode</label>
            <select name="mode">
              <option value="description">Description</option>
              <option value="historical">Historical / public</option>
            </select>
          </div>
        </div>
        <label>Description or historical subject</label>
        <textarea name="description" placeholder="Persona behavior, or a public/historical name"></textarea>
        <label>Optional URL or query</label>
        <input name="source" placeholder="LinkedIn, website, publication, query" />
        <label class="check"><input type="checkbox" name="browser" /> Use logged-in browser</label>
        <div class="actions">
          <button type="submit">Add person</button>
        </div>
      </form>

      <form id="research-form" class="hidden">
        <label>Target</label>
        <input name="target" list="targets" value="@me" required />
        <label>URL or query</label>
        <textarea name="source" placeholder="https://www.linkedin.com/in/... or a search query" required></textarea>
        <label class="check"><input type="checkbox" name="browser" /> Use logged-in browser</label>
        <div class="actions">
          <button type="submit">Scan sources</button>
        </div>
      </form>
      <datalist id="models"></datalist>
      <datalist id="targets"></datalist>
      <div id="review"></div>
      <p id="status"></p>
    </aside>

    <section class="board">
      <div class="toolbar">
        <h2>Facts</h2>
        <span class="meta" id="counts"></span>
      </div>
      <div id="memory-grid" class="grid"></div>
    </section>
  </main>

  <script>
    let state = { personas: [], memories: [], models: [] };
    let preview = null;
    const $ = (id) => document.getElementById(id);
    function esc(value) {
      return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    }
    function showForm(name) {
      $('person-form').classList.toggle('hidden', name !== 'person');
      $('research-form').classList.toggle('hidden', name !== 'research');
      $('tab-person').setAttribute('aria-selected', name === 'person');
      $('tab-research').setAttribute('aria-selected', name === 'research');
    }
    async function api(path, options = {}) {
      const res = await fetch(path, { headers: { 'content-type': 'application/json' }, ...options });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || JSON.stringify(data));
      return data;
    }
    async function loadState() {
      state = await api('/api/state');
      $('models').innerHTML = state.models.map(m => `<option value="${esc(m)}"></option>`).join('');
      $('targets').innerHTML = ['@me', ...state.personas.map(p => '@' + p.name)].map(t => `<option value="${esc(t)}"></option>`).join('');
      $('counts').textContent = `${state.memories.length} user facts | ${state.personas.length} personas`;
      renderFacts();
    }
    function renderFacts() {
      const cards = [];
      cards.push(`<article class="card"><h3>@me</h3><div class="meta">user memory</div>${state.memories.slice(0, 20).map(m => `<div class="fact">${esc(m.text)}<button class="secondary" onclick="deleteMemory('${esc(m.id)}')">Reject fact</button></div>`).join('') || '<div class="meta">No facts yet</div>'}</article>`);
      for (const p of state.personas) {
        cards.push(`<article class="card"><h3>@${esc(p.name)}</h3><div class="meta">${esc(p.model || 'default')} · ${esc(p.agent)} · ${p.knowledge_count} facts</div><p>${esc(p.description)}</p>${p.facts.slice(0, 14).map(f => `<div class="fact">${esc(f.text)}${f.source_url ? `<div class="meta">${esc(f.source_url)}</div>` : ''}<button class="secondary" onclick="deleteKnowledge('${esc(f.id)}')">Reject fact</button></div>`).join('')}<button class="danger" onclick="deletePersona('${esc(p.name)}')">Delete persona</button></article>`);
      }
      $('memory-grid').innerHTML = cards.join('');
    }
    function formPayload(form) {
      const data = new FormData(form);
      const payload = Object.fromEntries(data.entries());
      payload.browser = data.get('browser') === 'on';
      return payload;
    }
    $('person-form').addEventListener('submit', async (event) => {
      event.preventDefault();
      $('status').textContent = 'Adding person...';
      $('review').innerHTML = '';
      try {
        const result = await api('/api/personas', { method: 'POST', body: JSON.stringify(formPayload(event.target)) });
        $('status').textContent = summarizeReceipt(result.research || result.persona);
        event.target.reset();
        event.target.model.value = 'gpt-5.5';
        await loadState();
      } catch (err) { $('status').textContent = String(err); }
    });
    $('research-form').addEventListener('submit', async (event) => {
      event.preventDefault();
      $('status').textContent = 'Scanning sources...';
      $('review').innerHTML = '';
      try {
        preview = await api('/api/research/preview', { method: 'POST', body: JSON.stringify(formPayload(event.target)) });
        $('status').textContent = '';
        renderReview(preview);
      } catch (err) { $('status').textContent = String(err); }
    });
    function renderReview(data) {
      const sources = data.scanned_sources || [];
      $('review').innerHTML = `<div class="meta">Review sources for ${esc(data.target)} · ${esc(data.query)}</div>` +
        (sources.map((s, i) => `<div class="source"><label><input type="checkbox" data-url="${esc(s.url)}" checked /> <span>${esc(s.url)}</span></label><div>${esc(s.preview)}</div><div class="meta">${s.chars || 0} chars</div></div>`).join('') || '<div class="source">No readable sources found.</div>') +
        `<div class="actions"><button class="approve" onclick="approveSelected()">Approve selected</button><button class="secondary" onclick="discardPreview()">Discard</button></div>` +
        (data.failed_sources?.length ? `<div class="meta">Failed: ${esc(data.failed_sources.map(s => s.url).join(', '))}</div>` : '');
    }
    async function approveSelected() {
      if (!preview) return;
      const selected_urls = [...document.querySelectorAll('#review input[type=checkbox]:checked')].map(input => input.dataset.url);
      $('status').textContent = 'Saving approved facts...';
      try {
        const result = await api('/api/research/approve', { method: 'POST', body: JSON.stringify({ token: preview.token, selected_urls }) });
        $('review').innerHTML = '';
        preview = null;
        $('status').textContent = summarizeReceipt(result);
        await loadState();
      } catch (err) { $('status').textContent = String(err); }
    }
    function discardPreview() {
      preview = null;
      $('review').innerHTML = '';
      $('status').textContent = 'Research discarded.';
    }
    function summarizeReceipt(result) {
      if (!result || !result.saved_chunks) return JSON.stringify(result, null, 2);
      const lines = [`Saved ${result.saved_chunks.length} chunks for ${result.target}`, `Query: ${result.query}`];
      for (const source of result.scanned_sources || []) lines.push(`Scanned: ${source.url}`);
      for (const chunk of result.saved_chunks || []) lines.push(`Saved: ${chunk.preview}`);
      for (const failed of result.failed_sources || []) lines.push(`Failed: ${failed.url} (${failed.error})`);
      return lines.join('\n');
    }
    async function deletePersona(name) {
      if (!confirm(`Delete @${name}?`)) return;
      await api('/api/personas/' + encodeURIComponent(name), { method: 'DELETE' });
      await loadState();
    }
    async function deleteMemory(id) {
      await api('/api/memories/' + encodeURIComponent(id), { method: 'DELETE' });
      await loadState();
    }
    async function deleteKnowledge(id) {
      await api('/api/persona-knowledge/' + encodeURIComponent(id), { method: 'DELETE' });
      await loadState();
    }
    loadState().catch(err => $('status').textContent = String(err));
  </script>
</body>
</html>
"""

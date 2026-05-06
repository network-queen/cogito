from __future__ import annotations

import html
import queue
import re
import sqlite3
import sys
import threading
import time
from typing import TextIO

from .agent_bridge import run_agent_capture, stop_agent_pty
from .db import connect, default_db_path
from .memory import list_memories
from .persona_knowledge import add_persona_knowledge, list_persona_knowledge, research_persona_from_wikipedia
from .personas import (
    add_persona_for_model,
    delete_persona,
    get_persona,
    get_self_persona,
    list_personas,
    maybe_extract_persona_call,
)
from .settings import (
    get_chat_model,
    get_embedding_model,
    get_memory_model,
    set_chat_model,
    set_embedding_model,
    set_memory_model,
)
from .sessions import (
    add_turn,
    ask_session,
    create_session,
    current_db_path,
    get_session,
    process_pending_memory_jobs,
    set_session_model,
)
from .tool_manager import all_models, model_catalog


COMMAND_HELP = [
    ("/model [MODEL]", "show or change active model"),
    ("/models", "list detected models"),
    ("/persona add NAME MODEL [DESCRIPTION]", "create persona; auto-researches when description is omitted"),
    ("/persona list", "list personas"),
    ("/persona use NAME", "set active persona"),
    ("/persona show NAME", "show persona"),
    ("/persona delete NAME", "delete persona"),
    ("/persona restart NAME", "restart persona PTY"),
    ("/persona knowledge NAME TEXT", "add persona RAG fact"),
    ("/persona research NAME SUBJECT", "import public persona RAG"),
    ("/persona clear", "clear active persona"),
    ("/chat-model [MODEL]", "show or change default local chat model"),
    ("/memory-model [MODEL]", "show or change memory extractor"),
    ("/embedding-model [MODEL]", "show or change relevance embeddings"),
    ("/memories", "show memories"),
    ("/session", "show session info"),
    ("/verbose on|off", "toggle metadata"),
    ("/help", "show full command reference"),
    ("/exit", "leave Cogito"),
]

COMMAND_EXAMPLES = [
    "/chat-model qwen3:0.6b",
    "/model gpt-5.5",
    "/persona add aristotle gpt-5.5",
    "/persona add architect gpt-5.5 Senior pragmatic software architect.",
    "/persona research architect Martin Fowler",
    "/persona knowledge architect Prefers evolutionary architecture over large speculative rewrites.",
    "/persona use architect",
    "@me decide based on what you know about me",
    "@architect review this design",
    "/memory-model qwen3:1.7b",
    "/embedding-model nomic-embed-text",
]

PERSONA_ACTIONS = ["add", "list", "use", "show", "delete", "restart", "knowledge", "research", "clear"]
VERBOSE_OPTIONS = ["on", "off"]
CHAT_MODEL_OPTIONS = ["qwen3:0.6b", "qwen3:1.7b", "llama3.2"]
MEMORY_MODEL_OPTIONS = ["qwen3:0.6b", "qwen3:1.7b", "heuristic", "off"]
EMBEDDING_MODEL_OPTIONS = ["nomic-embed-text", "mxbai-embed-large", "off"]
FALLBACK_MODEL_OPTIONS = ["-", "gpt-5.5", "gpt-5.4", "sonnet", "opus", *CHAT_MODEL_OPTIONS]


def run_chat(
    conn: sqlite3.Connection,
    *,
    agent: str = "local",
    model: str | None = None,
    session_id: str | None = None,
    title: str = "Cogito chat",
    lens: str = "coding",
    max_sensitivity: str = "professional",
    execute: bool = True,
    memory_mode: str = "background",
    yolo: bool = False,
    verbose: bool = False,
    input_stream: TextIO = sys.stdin,
    output_stream: TextIO = sys.stdout,
) -> int:
    interactive = input_stream is sys.stdin and sys.stdin.isatty()
    session = (
        get_session(conn, session_id)
        if session_id
        else create_session(conn, title=title, agent=agent, model=model, lens=lens, max_sensitivity=max_sensitivity)
    )
    process_pending_memory_jobs(conn, limit=3)
    active_persona: dict | None = None
    if interactive and execute:
        return run_split_tui(
            conn,
            session=session,
            memory_mode=memory_mode,
            yolo=yolo,
            verbose=verbose,
            output_stream=output_stream,
        )
    if input_stream is sys.stdin:
        setup_autocomplete(conn)
    if verbose:
        write(output_stream, f"Cogito chat. Session: {session['id']}. Model: {session.get('active_model') or 'local default'}.")
        write(output_stream, "Commands: /model, /models, /persona, /chat-model, /memory-model, /memories, /session, /help, /exit")

    while True:
        try:
            if input_stream is sys.stdin:
                line = read_interactive_line(conn, session=session, verbose=verbose, interactive=interactive)
            else:
                line = input_stream.readline()
                if line == "":
                    break
                line = line.rstrip("\n")
        except (EOFError, KeyboardInterrupt):
            write(output_stream, "")
            break

        text = line.strip()
        if not text:
            continue
        if text.startswith("/"):
            if not is_known_command(text):
                show_command_matches(output_stream, text)
                continue
            should_continue, session, active_persona = handle_command(
                conn,
                text,
                session=session,
                active_persona=active_persona,
                output_stream=output_stream,
                verbose=verbose,
            )
            if not should_continue:
                break
            if text == "/verbose on":
                verbose = True
            elif text == "/verbose off":
                verbose = False
            continue
        called_persona, routed_text = maybe_extract_persona_call(conn, text)
        turn_persona = called_persona or active_persona
        turn_agent = turn_persona["agent"] if turn_persona else session["active_agent"]
        turn_model = turn_persona.get("model") if turn_persona else None
        turn_yolo = yolo or bool(turn_persona.get("yolo")) if turn_persona else yolo

        result = ask_session(
            conn,
            session_id=session["id"],
            user_prompt=routed_text,
            agent=turn_agent,
            execute=execute,
            memory_mode=memory_mode,
            stream=execute and verbose,
            yolo=turn_yolo,
            model=turn_model,
            persona=turn_persona,
            echo_output=False,
        )
        session = result["session"]
        if not execute:
            write(output_stream, result["prompt"])
        elif not verbose and result["output"]:
            write_agent_output(output_stream, result["output"])

    if verbose:
        write(output_stream, "Cogito session closed.")
    return 0


def handle_command(
    conn: sqlite3.Connection,
    command: str,
    *,
    session: dict,
    active_persona: dict | None,
    output_stream: TextIO,
    verbose: bool,
) -> tuple[bool, dict, dict | None]:
    parts = command.split()
    name = parts[0]
    if name in {"/exit", "/quit", "/q"}:
        return False, session, active_persona
    if name == "/help":
        show_help(output_stream)
        return True, session, active_persona
    if name == "/verbose":
        if len(parts) != 2 or parts[1] not in {"on", "off"}:
            write(output_stream, "Usage: /verbose on|off")
            return True, session, active_persona
        write(output_stream, f"Verbose: {parts[1]}")
        return True, session, active_persona
    if name == "/session":
        if verbose:
            write(output_stream, format_session(session))
        return True, session, active_persona
    if name == "/memories":
        memories = list_memories(conn)[:10]
        if not memories:
            write(output_stream, muted("No memories stored."))
        else:
            for memory in memories:
                meta = f"[{memory['type']}, {memory['sensitivity']}]"
                write(output_stream, f"{color('-', 'cyan')} {memory['text']} {muted(meta)}")
        return True, session, active_persona
    if name == "/model":
        if len(parts) == 1:
            write(output_stream, f"Model: {session.get('active_model') or get_chat_model(conn)}")
            return True, session, active_persona
        model = " ".join(parts[1:])
        updated = set_session_model(conn, session_id=session["id"], model=None if model == "-" else model)
        if verbose:
            write(output_stream, f"Model: {updated.get('active_model') or get_chat_model(conn)}")
        return True, updated, active_persona
    if name == "/models":
        for agent, models in model_catalog().items():
            if models:
                write(output_stream, f"{color(agent, 'cyan')}: {', '.join(models[:12])}")
        return True, session, active_persona
    if name == "/chat-model":
        if len(parts) == 1:
            write(output_stream, f"Chat model: {get_chat_model(conn)}")
            return True, session, active_persona
        model = set_chat_model(conn, " ".join(parts[1:]))
        write(output_stream, f"Chat model: {model}")
        return True, session, active_persona
    if name == "/persona":
        return handle_persona_command(
            conn,
            parts,
            session=session,
            active_persona=active_persona,
            output_stream=output_stream,
            verbose=verbose,
        )
    if name == "/memory-model":
        if len(parts) == 1:
            write(output_stream, f"Memory model: {get_memory_model(conn)}")
            return True, session, active_persona
        model = set_memory_model(conn, " ".join(parts[1:]))
        write(output_stream, f"Memory model: {model}")
        return True, session, active_persona
    if name == "/embedding-model":
        if len(parts) == 1:
            write(output_stream, f"Embedding model: {get_embedding_model(conn)}")
            return True, session, active_persona
        model = set_embedding_model(conn, " ".join(parts[1:]))
        write(output_stream, f"Embedding model: {model}")
        return True, session, active_persona
    write(output_stream, f"Unknown command: {name}. Use /help.")
    return True, session, active_persona


class TextSink:
    def __init__(self, callback):
        self.callback = callback

    def write(self, text: str) -> None:
        if text:
            self.callback(text.rstrip("\n"))

    def flush(self) -> None:
        return None


def run_split_tui(
    conn: sqlite3.Connection,
    *,
    session: dict,
    memory_mode: str,
    yolo: bool,
    verbose: bool,
    output_stream: TextIO,
) -> int:
    try:
        from prompt_toolkit import Application
        from prompt_toolkit.formatted_text import HTML
        from prompt_toolkit.history import FileHistory
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import Float, FloatContainer, HSplit, Layout, VSplit, Window
        from prompt_toolkit.layout.controls import FormattedTextControl
        from prompt_toolkit.layout.menus import CompletionsMenu
        from prompt_toolkit.widgets import TextArea
    except ImportError:
        write(output_stream, "prompt_toolkit not installed")
        return 1

    db_path = current_db_path(conn)
    state = {
        "session": session,
        "active_persona": None,
        "lines": [color("Cogito", "cyan") + " model-first chat"],
        "jobs": [],
        "workers": {},
        "closed": False,
    }
    lock = threading.Lock()
    app_ref = {"app": None}

    def left_text():
        with lock:
            return "\n".join(strip_ansi(line) for line in state["lines"][-200:])

    def right_text():
        with lock:
            if not state["jobs"]:
                return HTML("<ansigray>No persona calls yet.</ansigray>")
            chunks = []
            for job in state["jobs"][-8:]:
                status = job["status"]
                color_name = "ansigreen" if status == "done" else "ansiyellow" if status == "running" else "ansired"
                header = f"<{color_name}>@{html.escape(job['persona'])} {html.escape(status)}</{color_name}> <ansigray>{html.escape(job['model'])}</ansigray>"
                body = escape_terminal_html("\n".join(job["lines"][-80:]) or "waiting...")
                chunks.append(header + "\n" + body)
            separator = "\n\n<ansigray>" + ("-" * 36) + "</ansigray>\n\n"
            return HTML(separator.join(chunks))

    transcript = FormattedTextControl(lambda: left_text(), focusable=False)
    jobs = FormattedTextControl(right_text, focusable=False)
    hint = FormattedTextControl(
        lambda: HTML(f"<ansigray>{html.escape(get_instruction_hint(input_area.text))}</ansigray>"),
        focusable=False,
    )
    input_area = TextArea(
        height=1,
        prompt=HTML("<ansicyan>&gt;</ansicyan> "),
        multiline=False,
        completer=CogitoCompleter(conn),
        complete_while_typing=True,
        history=FileHistory(history_path()),
    )
    root = FloatContainer(
        content=VSplit(
            [
                HSplit([Window(transcript, wrap_lines=True), Window(hint, height=1), input_area], width=80),
                Window(width=1, char="|", style="class:separator"),
                Window(jobs, wrap_lines=True, width=52),
            ]
        ),
        floats=[
            Float(xcursor=True, ycursor=True, content=CompletionsMenu(max_height=12, scroll_offset=1)),
        ],
    )
    kb = KeyBindings()

    def append_left(text: str) -> None:
        with lock:
            state["lines"].append(text)
        if app_ref["app"]:
            app_ref["app"].invalidate()

    def append_job(job: dict, text: str) -> None:
        with lock:
            job["lines"].append(clean_terminal_text(text.rstrip("\n")))
        if app_ref["app"]:
            app_ref["app"].invalidate()

    def run_background_persona(persona: dict, prompt: str, routed_text: str) -> None:
        job = {
            "persona": persona["name"],
            "model": persona.get("model") or "default",
            "status": "running",
            "lines": [f"started {time.strftime('%H:%M:%S')}", f"prompt: {routed_text}"],
        }
        with lock:
            state["jobs"].append(job)
        if app_ref["app"]:
            app_ref["app"].invalidate()

        bg_conn = None
        try:
            if not db_path:
                raise RuntimeError("background persona calls need a file-backed Cogito DB")
            bg_conn = connect(db_path)
            result = ask_session(
                bg_conn,
                session_id=state["session"]["id"],
                user_prompt=routed_text,
                agent=persona["agent"],
                execute=False,
                memory_mode=memory_mode,
                persona=persona,
            )
            enriched_prompt = str(result["prompt"])
            if persona["agent"] == "local":
                result = ask_session(
                    bg_conn,
                    session_id=state["session"]["id"],
                    user_prompt=routed_text,
                    agent=persona["agent"],
                    execute=True,
                    memory_mode="off",
                    stream=True,
                    yolo=yolo or bool(persona.get("yolo")),
                    model=persona.get("model"),
                    persona=persona,
                    echo_output=False,
                    on_output=lambda line: append_job(job, line),
                )
            else:
                append_job(job, f"running {persona['agent']} in non-interactive mode")
                result = run_agent_capture(
                    agent=persona["agent"],
                    prompt=enriched_prompt,
                    stream=False,
                    yolo=yolo or bool(persona.get("yolo")),
                    model=persona.get("model"),
                )
                captured = clean_terminal_text(str(result.get("output") or "")).strip()
                add_turn(
                    bg_conn,
                    session_id=state["session"]["id"],
                    agent=persona["agent"],
                    role="agent",
                    content=captured or "No persona output captured.",
                    prompt=enriched_prompt,
                    exit_code=int(result["exit_code"]),
                )
                if not captured:
                    append_job(job, "no output captured")
                else:
                    append_job(job, captured)
                    append_left(color(f"@{persona['name']}\n{captured}", "green"))
            with lock:
                job["status"] = "done" if result["exit_code"] == 0 else f"exit {result['exit_code']}"
                if "session" in result:
                    state["session"] = result["session"]
        except Exception as exc:
            append_job(job, f"error: {exc}")
            with lock:
                job["status"] = "error"
        finally:
            if bg_conn is not None:
                bg_conn.close()
            if app_ref["app"]:
                app_ref["app"].invalidate()

    def persona_worker(persona: dict, work_queue: queue.Queue) -> None:
        while True:
            prompt, routed_text = work_queue.get()
            if prompt is None:
                return
            try:
                run_background_persona(persona, prompt, routed_text)
            finally:
                work_queue.task_done()

    def enqueue_persona(persona: dict, prompt: str, routed_text: str) -> None:
        name = persona["name"]
        with lock:
            worker = state["workers"].get(name)
            if worker is None:
                work_queue: queue.Queue = queue.Queue()
                thread = threading.Thread(target=persona_worker, args=(persona, work_queue), daemon=True)
                worker = {"queue": work_queue, "thread": thread}
                state["workers"][name] = worker
                thread.start()
            worker["queue"].put((prompt, routed_text))

    def submit() -> None:
        text = input_area.text.strip()
        if text:
            input_area.buffer.append_to_history()
        input_area.text = ""
        if not text:
            return
        append_left(color("> " + text, "cyan"))
        if text.startswith("/"):
            if not is_known_command(text):
                sink = TextSink(append_left)
                show_command_matches(sink, text)
                return
            sink = TextSink(append_left)
            keep_going, new_session, active_persona = handle_command(
                conn,
                text,
                session=state["session"],
                active_persona=state["active_persona"],
                output_stream=sink,
                verbose=True,
            )
            state["session"] = new_session
            state["active_persona"] = active_persona
            if not keep_going:
                state["closed"] = True
                if app_ref["app"]:
                    app_ref["app"].exit()
            return
        called_persona, routed_text = maybe_extract_persona_call(conn, text)
        turn_persona = called_persona or state["active_persona"]
        if turn_persona:
            append_left(muted(f"queued @{turn_persona['name']}"))
            enqueue_persona(turn_persona, text, routed_text)
            return
        try:
            result = ask_session(
                conn,
                session_id=state["session"]["id"],
                user_prompt=text,
                execute=True,
                memory_mode=memory_mode,
                stream=False,
                yolo=yolo,
                echo_output=False,
            )
            state["session"] = result["session"]
            if result["output"]:
                append_left(color(result["output"].rstrip(), "green"))
        except Exception as exc:
            append_left(color(f"error: {exc}", "red"))

    def accept_completion_if_open() -> bool:
        buffer = input_area.buffer
        state = buffer.complete_state
        if not state or not state.current_completion:
            return False
        buffer.apply_completion(state.current_completion)
        return True

    @kb.add("tab")
    def _complete_next(event):
        buffer = input_area.buffer
        if buffer.complete_state:
            buffer.complete_next()
        else:
            buffer.start_completion(select_first=True)

    @kb.add("s-tab")
    def _complete_previous(event):
        buffer = input_area.buffer
        if buffer.complete_state:
            buffer.complete_previous()
        else:
            buffer.start_completion(select_first=True)

    @kb.add("up")
    def _history_previous(event):
        buffer = input_area.buffer
        buffer.load_history_if_not_yet_loaded()
        buffer.history_backward()

    @kb.add("down")
    def _history_next(event):
        buffer = input_area.buffer
        buffer.load_history_if_not_yet_loaded()
        buffer.history_forward()

    @kb.add("enter")
    def _submit(event):
        if accept_completion_if_open():
            return
        submit()

    @kb.add("c-c")
    def _interrupt(event):
        input_area.text = ""

    @kb.add("c-d")
    def _exit(event):
        event.app.exit()

    app = Application(layout=Layout(root, focused_element=input_area), key_bindings=kb, full_screen=True)
    app_ref["app"] = app
    app.run()
    return 0


def handle_persona_command(
    conn: sqlite3.Connection,
    parts: list[str],
    *,
    session: dict,
    active_persona: dict | None,
    output_stream: TextIO,
    verbose: bool,
) -> tuple[bool, dict, dict | None]:
    if len(parts) == 1 or parts[1] == "list":
        personas = list_personas(conn)
        if not personas:
            write(output_stream, muted("No personas."))
        for persona in personas:
            model = persona.get("model") or "default"
            write(output_stream, f"{color('@' + persona['name'], 'magenta')}: {model} {muted(persona['agent'])}")
        return True, session, active_persona
    action = parts[1]
    if action == "add":
        if len(parts) < 4:
            write(output_stream, "Usage: /persona add NAME MODEL [DESCRIPTION]")
            return True, session, active_persona
        name, model = parts[2], parts[3]
        should_research = len(parts) == 4
        description = " ".join(parts[4:]) if len(parts) > 4 else f"Public persona researched as {name}."
        persona = add_persona_for_model(conn, name=name, model=model, description=description)
        imported = 0
        if should_research:
            try:
                imported = len(research_persona_from_wikipedia(conn, persona_name=name, subject=name))
            except Exception as exc:
                write(output_stream, f"Persona saved, but research failed: {exc}")
                return True, session, active_persona
        if verbose:
            write(output_stream, f"Persona saved: {persona['name']}")
        elif should_research:
            write(output_stream, f"Persona saved with {imported} researched chunks.")
        return True, session, active_persona
    if action == "use":
        if len(parts) != 3:
            write(output_stream, "Usage: /persona use NAME")
            return True, session, active_persona
        persona = get_persona(conn, parts[2])
        updated = set_session_model(conn, session_id=session["id"], model=persona.get("model"))
        if verbose:
            write(output_stream, f"Persona: {persona['name']} ({persona.get('model') or 'default'})")
        return True, updated, persona
    if action == "show":
        if len(parts) != 3:
            write(output_stream, "Usage: /persona show NAME")
            return True, session, active_persona
        persona = get_self_persona() if parts[2] == "me" else get_persona(conn, parts[2])
        write(output_stream, format_persona(persona))
        if not persona.get("virtual"):
            knowledge = list_persona_knowledge(conn, persona_name=persona["name"])[:8]
            if knowledge:
                write(output_stream, color("Knowledge", "cyan"))
                for item in knowledge:
                    source = muted(item.get("source_url") or "")
                    write(output_stream, f"- {item['text']} {source}".rstrip())
        return True, session, active_persona
    if action == "knowledge":
        if len(parts) < 4:
            write(output_stream, "Usage: /persona knowledge NAME TEXT")
            return True, session, active_persona
        if parts[2] == "me":
            write(output_stream, "Use normal chat to store user facts; @me reads permitted user memory.")
            return True, session, active_persona
        item = add_persona_knowledge(conn, persona_name=parts[2], text=" ".join(parts[3:]))
        if verbose:
            write(output_stream, f"Persona knowledge saved: {item['id']}")
        return True, session, active_persona
    if action == "research":
        if len(parts) < 4:
            write(output_stream, "Usage: /persona research NAME SUBJECT")
            return True, session, active_persona
        if parts[2] == "me":
            write(output_stream, "Research imports are for external personas. @me uses user memory.")
            return True, session, active_persona
        created = research_persona_from_wikipedia(conn, persona_name=parts[2], subject=" ".join(parts[3:]))
        write(output_stream, f"Persona knowledge imported: {len(created)} chunks")
        return True, session, active_persona
    if action in {"delete", "del", "rm"}:
        if len(parts) != 3:
            write(output_stream, "Usage: /persona delete NAME")
            return True, session, active_persona
        stop_agent_pty(parts[2])
        delete_persona(conn, parts[2])
        if verbose:
            write(output_stream, f"Persona deleted: {parts[2]}")
        return True, session, None if active_persona and active_persona["name"] == parts[2] else active_persona
    if action == "restart":
        if len(parts) != 3:
            write(output_stream, "Usage: /persona restart NAME")
            return True, session, active_persona
        restarted = stop_agent_pty(parts[2])
        write(output_stream, f"Persona restarted: {parts[2]}" if restarted else f"Persona was not running: {parts[2]}")
        return True, session, active_persona
    if action == "clear":
        if verbose:
            write(output_stream, "Persona cleared.")
        return True, session, None
    write(output_stream, "Usage: /persona add|use|list|show|delete|restart|knowledge|research|clear")
    return True, session, active_persona


def format_session(session: dict) -> str:
    return (
        f"Session: {session['id']}\n"
        f"Title: {session['title']}\n"
        f"Model: {session.get('active_model') or 'local default'}\n"
        f"Lens: {session['lens']}\n"
        f"Max sensitivity: {session['max_sensitivity']}"
    )


def format_persona(persona: dict) -> str:
    return (
        f"Persona: {persona['name']}\n"
        f"Model: {persona.get('model') or 'default'}\n"
        f"Adapter: {persona['agent']}\n"
        f"Yolo: {persona['yolo']}\n"
        f"{persona['description']}"
    )


def write(stream: TextIO, text: str) -> None:
    stream.write(text + "\n")
    stream.flush()


def write_agent_output(stream: TextIO, text: str) -> None:
    write(stream, color(text.rstrip(), "green"))


def is_known_command(text: str) -> bool:
    command_names = {command.split()[0] for command, _ in COMMAND_HELP}
    return text.split()[0] in command_names


def show_command_matches(output_stream: TextIO, prefix: str) -> None:
    matches = command_matches(prefix)
    if not matches:
        write(output_stream, muted(f"No commands match {prefix}"))
        return
    for command, description in matches:
        write(output_stream, f"{color(command, 'cyan')} {muted(description)}")


def show_help(output_stream: TextIO) -> None:
    write(output_stream, color("Commands", "cyan"))
    for command, description in COMMAND_HELP:
        write(output_stream, f"{color(command, 'cyan')} {muted(description)}")
    write(output_stream, "")
    write(output_stream, color("Examples", "cyan"))
    for example in COMMAND_EXAMPLES:
        write(output_stream, f"  {example}")


def command_matches(prefix: str) -> list[tuple[str, str]]:
    normalized = prefix.lower()
    return [
        (command, description)
        for command, description in COMMAND_HELP
        if command.lower().startswith(normalized) or normalized in command.lower()
    ]


def color(text: str, name: str) -> str:
    codes = {
        "blue": "34",
        "cyan": "36",
        "green": "32",
        "magenta": "35",
        "red": "31",
        "gray": "90",
        "yellow": "33",
    }
    code = codes.get(name)
    if not code:
        return text
    return f"\033[{code}m{text}\033[0m"


def muted(text: str) -> str:
    return color(text, "gray")


def strip_ansi(text: str) -> str:
    return re.sub(r"\033\[[0-9;]*m", "", text)


def clean_terminal_text(text: str) -> str:
    text = strip_ansi(text)
    return "".join(
        char
        for char in text
        if char in "\n\r\t" or ord(char) >= 32
    )


def escape_terminal_html(text: str) -> str:
    return html.escape(clean_terminal_text(text))


def setup_autocomplete(conn: sqlite3.Connection) -> None:
    try:
        import atexit
        import readline
    except ImportError:
        return

    commands = [item[0].split(" ")[0] for item in COMMAND_HELP] + [
        "/model",
        "/models",
        "/persona add",
        "/persona clear",
        "/persona delete",
        "/persona knowledge",
        "/persona list",
        "/persona research",
        "/persona restart",
        "/persona show",
        "/persona use",
        "/verbose off",
        "/verbose on",
    ]

    def complete(text: str, state: int) -> str | None:
        line = readline.get_line_buffer()
        options = completion_options(conn, line, text, commands)
        if state < len(options):
            return options[state]
        return None

    readline.set_completer(complete)
    readline.parse_and_bind("tab: complete")
    history = history_path()
    try:
        readline.read_history_file(history)
    except FileNotFoundError:
        pass
    except OSError:
        return
    atexit.register(readline.write_history_file, history)


def read_interactive_line(conn: sqlite3.Connection, *, session: dict, verbose: bool, interactive: bool) -> str:
    if interactive:
        prompt_toolkit_line = read_with_prompt_toolkit(conn, session=session, verbose=verbose)
        if prompt_toolkit_line is not None:
            return prompt_toolkit_line
    prompt = ""
    if interactive:
        label = f"cogito[{session['active_agent']}]" if verbose else ">"
        prompt = color(label, "cyan") + " "
    return input(prompt)


def read_with_prompt_toolkit(conn: sqlite3.Connection, *, session: dict, verbose: bool) -> str | None:
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.application.current import get_app
        from prompt_toolkit.formatted_text import HTML
        from prompt_toolkit.history import FileHistory
    except ImportError:
        return None

    label = f"cogito[{session['active_agent']}]" if verbose else ">"
    prompt = HTML(f"<ansicyan>{label}</ansicyan> ")

    def bottom_toolbar():
        hint = get_instruction_hint(get_app().current_buffer.document.text_before_cursor)
        if not hint:
            return ""
        return HTML(f"<ansigray>{html.escape(hint)}</ansigray>")

    prompt_session = PromptSession(
        completer=CogitoCompleter(conn),
        complete_while_typing=True,
        bottom_toolbar=bottom_toolbar,
        history=FileHistory(history_path()),
        reserve_space_for_menu=8,
    )
    return prompt_session.prompt(prompt)


def history_path() -> str:
    path = default_db_path().parent / "history"
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


try:
    from prompt_toolkit.completion import Completer as PromptToolkitCompleter
except ImportError:
    PromptToolkitCompleter = object


class CogitoCompleter(PromptToolkitCompleter):
    def __init__(self, conn: sqlite3.Connection):
        super().__init__()
        self.conn = conn

    def get_completions(self, document, complete_event):
        try:
            from prompt_toolkit.completion import Completion
        except ImportError:
            return
        text = document.text_before_cursor
        for value, display, meta, start_position in prompt_completions(self.conn, text):
            yield Completion(value, start_position=start_position, display=display, display_meta=meta)

    async def get_completions_async(self, document, complete_event):
        for completion in self.get_completions(document, complete_event):
            yield completion


def prompt_completions(conn: sqlite3.Connection, text: str) -> list[tuple[str, str, str, int]]:
    if text.startswith("@"):
        personas = [get_self_persona(), *list_personas(conn)]
        return [
            (f"@{persona['name']} ", f"@{persona['name']}", persona["agent"], -len(text))
            for persona in personas
            if f"@{persona['name']}".startswith(text)
        ]
    argument_completions = command_argument_completions(conn, text)
    if argument_completions:
        return argument_completions
    persona_name_prefixes = (
        "/persona use ",
        "/persona show ",
        "/persona delete ",
        "/persona restart ",
        "/persona knowledge ",
        "/persona research ",
    )
    for prefix in persona_name_prefixes:
        if text.startswith(prefix):
            fragment = text.removeprefix(prefix)
            personas = [get_self_persona(), *list_personas(conn)] if prefix == "/persona show " else list_personas(conn)
            return [
                (persona["name"], persona["name"], persona["agent"], -len(fragment))
                for persona in personas
                if persona["name"].startswith(fragment)
            ]
    if text.startswith("/"):
        return [command_completion(command, description, text) for command, description in command_matches(text)]
    return []


def command_completion(command: str, description: str, text: str) -> tuple[str, str, str, int]:
    name, _, args = command.partition(" ")
    value = name + (" " if args else "")
    meta = f"{args} - {description}" if args else description
    return value, name, meta, -len(text)


def command_argument_completions(conn: sqlite3.Connection, text: str) -> list[tuple[str, str, str, int]]:
    if text.startswith("/model "):
        return option_completions(model_options(), last_fragment(text), "model")
    if text.startswith("/verbose "):
        return option_completions(VERBOSE_OPTIONS, last_fragment(text), "mode")
    if text.startswith("/chat-model "):
        return option_completions(CHAT_MODEL_OPTIONS, last_fragment(text), "local chat model")
    if text.startswith("/memory-model "):
        return option_completions(MEMORY_MODEL_OPTIONS, last_fragment(text), "memory extractor")
    if text.startswith("/embedding-model "):
        return option_completions(EMBEDDING_MODEL_OPTIONS, last_fragment(text), "embedding model")
    if text == "/persona " or text.startswith("/persona "):
        return persona_argument_completions(conn, text)
    return []


def persona_argument_completions(conn: sqlite3.Connection, text: str) -> list[tuple[str, str, str, int]]:
    parts = text.split()
    fragment = last_fragment(text)
    if len(parts) == 1 or (len(parts) == 2 and not text.endswith(" ")):
        return option_completions(PERSONA_ACTIONS, fragment, "persona command")
    if len(parts) < 2:
        return []
    action = parts[1]
    if action in {"use", "show", "delete", "restart", "knowledge", "research"}:
        names = [persona["name"] for persona in list_personas(conn)]
        if action == "show":
            names = ["me", *names]
        return option_completions(names, fragment, "persona")
    if action != "add":
        return []
    arg_index = persona_add_arg_index(text)
    if arg_index == 1:
        return option_completions(model_options(), fragment, "model; adapter inferred")
    return []


def persona_add_arg_index(text: str) -> int:
    parts = text.split()
    arg_count = max(0, len(parts) - 2)
    if text.endswith(" "):
        return arg_count
    return max(0, arg_count - 1)


def option_completions(options: list[str], fragment: str, meta: str) -> list[tuple[str, str, str, int]]:
    return [
        (option + " ", option, meta, -len(fragment))
        for option in options
        if option.startswith(fragment)
    ]


def last_fragment(text: str) -> str:
    if text.endswith(" "):
        return ""
    return text.rsplit(" ", 1)[-1]


def get_instruction_hint(text: str) -> str:
    if not text.startswith("/"):
        return ""
    if text.startswith("/model"):
        return "next: MODEL"
    if text.startswith("/verbose"):
        return "next: on | off"
    if text.startswith("/chat-model"):
        return "next: MODEL, for example qwen3:0.6b or llama3.2"
    if text.startswith("/memory-model"):
        return "next: MODEL, for example qwen3:0.6b, heuristic, or off"
    if text.startswith("/embedding-model"):
        return "next: MODEL, for example nomic-embed-text or off"
    if text.startswith("/persona"):
        return get_persona_hint(text)
    return ""


def get_persona_hint(text: str) -> str:
    parts = text.split()
    if text == "/persona" or text == "/persona " or len(parts) == 1:
        return "next: add | list | use | show | delete | restart | knowledge | research | clear"
    action = parts[1]
    if action == "add":
        return persona_add_hint(text)
    if action in {"use", "show", "delete", "restart", "knowledge", "research"}:
        return "next: NAME"
    if action in {"list", "clear"}:
        return ""
    return "next: add | list | use | show | delete | restart | knowledge | research | clear"


def persona_add_hint(text: str) -> str:
    fields = ["NAME", "MODEL", "[DESCRIPTION]"]
    parts = text.split()
    completed = max(0, len(parts) - 2)
    if completed and not text.endswith(" "):
        completed = min(completed, len(fields))
    remaining = fields[completed:]
    if not remaining:
        return ""
    return "next: " + " ".join(remaining)


def completion_options(conn: sqlite3.Connection, line: str, text: str, commands: list[str]) -> list[str]:
    if line.startswith("@"):
        return [
            f"@{persona['name']} "
            for persona in [get_self_persona(), *list_personas(conn)]
            if f"@{persona['name']}".startswith(text)
        ]
    if line.startswith("/persona "):
        return readline_persona_options(conn, line, text)
    if line.startswith("/model "):
        return [model for model in model_options() if model.startswith(text)]
    if line.startswith("/verbose "):
        return [option for option in VERBOSE_OPTIONS if option.startswith(text)]
    if line.startswith("/chat-model "):
        return [model for model in CHAT_MODEL_OPTIONS if model.startswith(text)]
    if line.startswith("/memory-model "):
        return [model for model in MEMORY_MODEL_OPTIONS if model.startswith(text)]
    if line.startswith("/embedding-model "):
        return [model for model in EMBEDDING_MODEL_OPTIONS if model.startswith(text)]
    if line.startswith("/"):
        return [command for command in commands if command.startswith(line)]
    return []


def readline_persona_options(conn: sqlite3.Connection, line: str, text: str) -> list[str]:
    parts = line.split()
    if len(parts) == 1 or (len(parts) == 2 and not line.endswith(" ")):
        return [action for action in PERSONA_ACTIONS if action.startswith(text)]
    action = parts[1] if len(parts) > 1 else ""
    if action in {"use", "show", "delete", "restart", "knowledge", "research"}:
        personas = [get_self_persona(), *list_personas(conn)] if action == "show" else list_personas(conn)
        return [persona["name"] for persona in personas if persona["name"].startswith(text)]
    if action == "add":
        arg_index = persona_add_arg_index(line)
        if arg_index == 1:
            return [model for model in model_options() if model.startswith(text)]
    return []


def model_options() -> list[str]:
    return sorted(set(FALLBACK_MODEL_OPTIONS + all_models()))

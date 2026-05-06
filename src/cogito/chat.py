from __future__ import annotations

import html
import sqlite3
import sys
from typing import TextIO

from .memory import list_memories
from .personas import add_persona, delete_persona, get_persona, list_personas, maybe_extract_persona_call
from .settings import (
    get_chat_model,
    get_embedding_model,
    get_memory_model,
    set_chat_model,
    set_embedding_model,
    set_memory_model,
)
from .sessions import ask_session, create_session, get_session, process_pending_memory_jobs, set_session_agent


COMMAND_HELP = [
    ("/tool local|codex|claude|opencode", "switch underlying tool"),
    ("/persona add NAME AGENT MODEL DESCRIPTION", "create persona"),
    ("/persona list", "list personas"),
    ("/persona use NAME", "set active persona"),
    ("/persona show NAME", "show persona"),
    ("/persona delete NAME", "delete persona"),
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
    "/tool local",
    "/tool claude",
    "/persona add architect codex gpt-5.5 Senior pragmatic software architect.",
    "/persona use architect",
    "@architect review this design",
    "/memory-model qwen3:1.7b",
    "/embedding-model nomic-embed-text",
]

AGENT_OPTIONS = ["local", "codex", "codex-exec", "claude", "opencode"]
PERSONA_ACTIONS = ["add", "list", "use", "show", "delete", "clear"]
VERBOSE_OPTIONS = ["on", "off"]
CHAT_MODEL_OPTIONS = ["qwen3:0.6b", "qwen3:1.7b", "llama3.2"]
MEMORY_MODEL_OPTIONS = ["qwen3:0.6b", "qwen3:1.7b", "heuristic", "off"]
EMBEDDING_MODEL_OPTIONS = ["nomic-embed-text", "mxbai-embed-large", "off"]
PERSONA_MODEL_OPTIONS = ["-", "gpt-5.5", "gpt-5.4", "sonnet", "opus", *CHAT_MODEL_OPTIONS]


def run_chat(
    conn: sqlite3.Connection,
    *,
    agent: str = "local",
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
        else create_session(conn, title=title, agent=agent, lens=lens, max_sensitivity=max_sensitivity)
    )
    process_pending_memory_jobs(conn, limit=3)
    active_persona: dict | None = None
    if input_stream is sys.stdin:
        setup_autocomplete(conn)
    if verbose:
        write(output_stream, f"Cogito chat. Session: {session['id']}. Tool: {session['active_agent']}.")
        write(output_stream, "Commands: /tool, /persona, /chat-model, /memory-model, /memories, /session, /help, /exit")

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
        )
        session = result["session"]
        if not execute:
            write(output_stream, result["prompt"])

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
    if name == "/tool":
        if len(parts) != 2:
            write(output_stream, "Usage: /tool local|codex|claude|opencode")
            return True, session, active_persona
        updated = set_session_agent(conn, session_id=session["id"], agent=parts[1])
        if verbose:
            write(output_stream, f"Tool: {updated['active_agent']}")
        return True, updated, active_persona
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
            write(output_stream, f"{color('@' + persona['name'], 'magenta')}: {persona['agent']} {muted(model)}")
        return True, session, active_persona
    action = parts[1]
    if action == "add":
        if len(parts) < 6:
            write(output_stream, "Usage: /persona add NAME AGENT MODEL DESCRIPTION")
            return True, session, active_persona
        name, agent, model = parts[2], parts[3], parts[4]
        description = " ".join(parts[5:])
        persona = add_persona(conn, name=name, agent=agent, model=None if model == "-" else model, description=description)
        if verbose:
            write(output_stream, f"Persona saved: {persona['name']}")
        return True, session, active_persona
    if action == "use":
        if len(parts) != 3:
            write(output_stream, "Usage: /persona use NAME")
            return True, session, active_persona
        persona = get_persona(conn, parts[2])
        updated = set_session_agent(conn, session_id=session["id"], agent=persona["agent"])
        if verbose:
            write(output_stream, f"Persona: {persona['name']} ({persona['agent']})")
        return True, updated, persona
    if action == "show":
        if len(parts) != 3:
            write(output_stream, "Usage: /persona show NAME")
            return True, session, active_persona
        write(output_stream, format_persona(get_persona(conn, parts[2])))
        return True, session, active_persona
    if action in {"delete", "del", "rm"}:
        if len(parts) != 3:
            write(output_stream, "Usage: /persona delete NAME")
            return True, session, active_persona
        delete_persona(conn, parts[2])
        if verbose:
            write(output_stream, f"Persona deleted: {parts[2]}")
        return True, session, None if active_persona and active_persona["name"] == parts[2] else active_persona
    if action == "clear":
        if verbose:
            write(output_stream, "Persona cleared.")
        return True, session, None
    write(output_stream, "Usage: /persona add|use|list|show|delete|clear")
    return True, session, active_persona


def format_session(session: dict) -> str:
    return (
        f"Session: {session['id']}\n"
        f"Title: {session['title']}\n"
        f"Tool: {session['active_agent']}\n"
        f"Lens: {session['lens']}\n"
        f"Max sensitivity: {session['max_sensitivity']}"
    )


def format_persona(persona: dict) -> str:
    return (
        f"Persona: {persona['name']}\n"
        f"Tool: {persona['agent']}\n"
        f"Model: {persona.get('model') or 'default'}\n"
        f"Yolo: {persona['yolo']}\n"
        f"{persona['description']}"
    )


def write(stream: TextIO, text: str) -> None:
    stream.write(text + "\n")
    stream.flush()


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
        "cyan": "36",
        "magenta": "35",
        "gray": "90",
    }
    code = codes.get(name)
    if not code:
        return text
    return f"\033[{code}m{text}\033[0m"


def muted(text: str) -> str:
    return color(text, "gray")


def setup_autocomplete(conn: sqlite3.Connection) -> None:
    try:
        import readline
    except ImportError:
        return

    commands = [item[0].split(" ")[0] for item in COMMAND_HELP] + [
        "/persona add",
        "/persona clear",
        "/persona delete",
        "/persona list",
        "/persona show",
        "/persona use",
        "/tool claude",
        "/tool codex",
        "/tool local",
        "/tool opencode",
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
        from prompt_toolkit.formatted_text import HTML
        from prompt_toolkit.application.current import get_app
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
        reserve_space_for_menu=8,
    )
    return prompt_session.prompt(prompt)


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
        return [
            (f"@{persona['name']} ", f"@{persona['name']}", persona["agent"], -len(text))
            for persona in list_personas(conn)
            if f"@{persona['name']}".startswith(text)
        ]
    argument_completions = command_argument_completions(conn, text)
    if argument_completions:
        return argument_completions
    for prefix in ("/persona use ", "/persona show ", "/persona delete "):
        if text.startswith(prefix):
            fragment = text.removeprefix(prefix)
            return [
                (persona["name"], persona["name"], persona["agent"], -len(fragment))
                for persona in list_personas(conn)
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
    if text.startswith("/tool "):
        return option_completions(AGENT_OPTIONS, last_fragment(text), "agent")
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
    if action in {"use", "show", "delete"}:
        return option_completions([persona["name"] for persona in list_personas(conn)], fragment, "persona")
    if action != "add":
        return []
    arg_index = persona_add_arg_index(text)
    if arg_index == 1:
        return option_completions(AGENT_OPTIONS, fragment, "agent")
    if arg_index == 2:
        return option_completions(PERSONA_MODEL_OPTIONS, fragment, "model; use - for default")
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
    if text.startswith("/tool"):
        return "next: local | codex | codex-exec | claude | opencode"
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
        return "next: add | list | use | show | delete | clear"
    action = parts[1]
    if action == "add":
        return persona_add_hint(text)
    if action in {"use", "show", "delete"}:
        return "next: NAME"
    if action in {"list", "clear"}:
        return ""
    return "next: add | list | use | show | delete | clear"


def persona_add_hint(text: str) -> str:
    fields = ["NAME", "AGENT", "MODEL", "DESCRIPTION"]
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
        return [f"@{persona['name']} " for persona in list_personas(conn) if f"@{persona['name']}".startswith(text)]
    if line.startswith("/persona "):
        return readline_persona_options(conn, line, text)
    if line.startswith("/tool "):
        return [agent for agent in AGENT_OPTIONS if agent.startswith(text)]
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
    if action in {"use", "show", "delete"}:
        return [persona["name"] for persona in list_personas(conn) if persona["name"].startswith(text)]
    if action == "add":
        arg_index = persona_add_arg_index(line)
        if arg_index == 1:
            return [agent for agent in AGENT_OPTIONS if agent.startswith(text)]
        if arg_index == 2:
            return [model for model in PERSONA_MODEL_OPTIONS if model.startswith(text)]
    return []

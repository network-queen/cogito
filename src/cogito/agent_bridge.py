from __future__ import annotations

import shutil
import os
import pty
import select
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

from .local_extractor import ollama_chat_generate
from .memory import context_pack
from .policy import ContextRequest
from .settings import DEFAULT_CHAT_MODEL, normalize_chat_model


_PTY_SESSIONS: dict[str, "PersistentPtySession"] = {}


def build_agent_command(agent: str, prompt: str, *, yolo: bool = False, model: str | None = None) -> list[str]:
    if agent == "local":
        raise ValueError("local agent runs through Ollama, not an external command")
    if agent in {"codex", "codex-exec"}:
        command = ["codex", "exec"]
        if yolo:
            command.append("--dangerously-bypass-approvals-and-sandbox")
        if model:
            command.extend(["-m", model])
        return command + [prompt]
    if agent == "claude":
        command = ["claude", "-p"]
        if yolo:
            command.append("--dangerously-skip-permissions")
        if model:
            command.extend(["--model", model])
        return command + [prompt]
    if agent == "opencode":
        command = ["opencode", "run"]
        if yolo:
            command.append("--dangerously-skip-permissions")
        if model:
            command.extend(["-m", model])
        return command + [prompt]
    raise ValueError(f"unsupported agent: {agent}")


def build_interactive_agent_command(agent: str, *, yolo: bool = False, model: str | None = None) -> list[str]:
    if agent in {"codex", "codex-exec"}:
        command = ["codex", "--no-alt-screen"]
        if yolo:
            command.append("--dangerously-bypass-approvals-and-sandbox")
        if model:
            command.extend(["-m", model])
        return command
    if agent == "claude":
        command = ["claude"]
        if yolo:
            command.append("--dangerously-skip-permissions")
        if model:
            command.extend(["--model", model])
        return command
    if agent == "opencode":
        command = ["opencode"]
        if model:
            command.extend(["-m", model])
        return command
    raise ValueError(f"persistent PTY unsupported for agent: {agent}")


class PersistentPtySession:
    def __init__(
        self,
        *,
        key: str,
        agent: str,
        model: str | None,
        yolo: bool,
        on_output: Callable[[str], None] | None,
    ):
        self.key = key
        self.agent = agent
        self.model = model
        self.yolo = yolo
        self.on_output = on_output
        self.output_parts: list[str] = []
        self.lock = threading.Lock()
        self.output_lock = threading.Lock()
        self.closed = False
        self.command = build_interactive_agent_command(agent, yolo=yolo, model=model)
        if shutil.which(self.command[0]) is None:
            raise RuntimeError(f"{self.command[0]} not found in PATH")
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.execvp(self.command[0], self.command)
        self.reader = threading.Thread(target=self._read_loop, daemon=True)
        self.reader.start()

    def _read_loop(self) -> None:
        while not self.closed:
            try:
                ready, _, _ = select.select([self.fd], [], [], 0.2)
                if not ready:
                    continue
                data = os.read(self.fd, 4096)
                if not data:
                    break
                text = data.decode("utf-8", errors="replace")
                with self.output_lock:
                    self.output_parts.append(text)
                if self.on_output:
                    self.on_output(text)
            except OSError:
                break
        self.closed = True

    def send(self, prompt: str, *, timeout: float = 180.0, idle_timeout: float = 2.0) -> str:
        with self.lock:
            before = len(self.output_text())
            payload = b"\x1b[200~" + prompt.encode("utf-8", errors="replace") + b"\x1b[201~\r"
            os.write(self.fd, payload)
            deadline = time.monotonic() + timeout
            last_len = before
            last_change = time.monotonic()
            saw_output = False
            while time.monotonic() < deadline:
                time.sleep(0.2)
                current_len = len(self.output_text())
                if current_len > last_len:
                    saw_output = True
                    last_len = current_len
                    last_change = time.monotonic()
                if saw_output and time.monotonic() - last_change >= idle_timeout:
                    break
            return self.output_text()[before:]

    def output_text(self) -> str:
        with self.output_lock:
            return "".join(self.output_parts)

    def stop(self) -> None:
        self.closed = True
        try:
            os.close(self.fd)
        except OSError:
            pass
        try:
            os.kill(self.pid, 15)
        except OSError:
            pass


def get_pty_session(
    *,
    key: str,
    agent: str,
    model: str | None,
    yolo: bool,
    on_output: Callable[[str], None] | None,
) -> PersistentPtySession:
    existing = _PTY_SESSIONS.get(key)
    if existing and not existing.closed and existing.agent == agent and existing.model == model:
        if on_output:
            existing.on_output = on_output
        return existing
    if existing:
        existing.stop()
    session = PersistentPtySession(key=key, agent=agent, model=model, yolo=yolo, on_output=on_output)
    _PTY_SESSIONS[key] = session
    return session


def run_agent_pty(
    *,
    key: str,
    agent: str,
    prompt: str,
    yolo: bool = False,
    model: str | None = None,
    on_output: Callable[[str], None] | None = None,
) -> dict[str, str | int]:
    session = get_pty_session(key=key, agent=agent, model=model, yolo=yolo, on_output=on_output)
    output = session.send(prompt)
    return {"exit_code": 0, "output": output}


def stop_agent_pty(key: str) -> bool:
    session = _PTY_SESSIONS.pop(key, None)
    if not session:
        return False
    session.stop()
    return True


def build_enriched_prompt(context: str, user_prompt: str) -> str:
    return f"""Use this Cogito user context if relevant. Respect access policy.
Cogito stores and extracts user memories silently outside this agent call.
Do not claim that you saved, failed to save, attempted to save, or cancelled memory writes.
Do not call Cogito memory tools unless the user explicitly asks you to inspect, list, delete, or explain memory.
Answer only the user's request.

{context}

User request:
{user_prompt}
"""


def get_prompt(conn, *, user_prompt: str, request: ContextRequest, limit: int) -> str:
    pack = context_pack(conn, query=user_prompt, request=request, limit=limit)
    return build_enriched_prompt(pack["context"], user_prompt)


def run_agent(agent: str, prompt: str, *, yolo: bool = False, model: str | None = None) -> int:
    result = run_agent_capture(agent, prompt, stream=True, yolo=yolo, model=model)
    return int(result["exit_code"])


def run_agent_capture(
    agent: str,
    prompt: str,
    *,
    stream: bool = True,
    yolo: bool = False,
    model: str | None = None,
    on_output: Callable[[str], None] | None = None,
) -> dict[str, str | int]:
    if agent == "local":
        output = run_local_model(prompt, model=model)
        if on_output and output:
            on_output(output + "\n")
        if stream and output and on_output is None:
            sys.stdout.write(output + "\n")
            sys.stdout.flush()
        return {"exit_code": 0, "output": output}

    command = build_agent_command(agent, prompt, yolo=yolo, model=model)
    binary = command[0]
    if shutil.which(binary) is None:
        raise RuntimeError(f"{binary} not found in PATH")
    if not stream:
        return run_agent_quiet(agent, command)

    process = subprocess.Popen(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    output_parts: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        output_parts.append(line)
        if on_output:
            on_output(line)
        if on_output is None:
            sys.stdout.write(line)
            sys.stdout.flush()
    return {"exit_code": process.wait(), "output": "".join(output_parts)}


def run_agent_quiet(agent: str, command: list[str]) -> dict[str, str | int]:
    if agent in {"codex", "codex-exec"}:
        with tempfile.NamedTemporaryFile("r+", delete=False) as tmp:
            output_path = tmp.name
        try:
            quiet_command = command[:2] + ["--output-last-message", output_path] + command[2:]
            completed = subprocess.run(quiet_command, text=True, capture_output=True, check=False)
            output = Path(output_path).read_text().strip()
            if not output:
                output = extract_final_answer("".join(part for part in (completed.stdout, completed.stderr) if part))
            return {"exit_code": completed.returncode, "output": output}
        finally:
            Path(output_path).unlink(missing_ok=True)

    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    raw_output = "".join(part for part in (completed.stdout, completed.stderr) if part)
    return {"exit_code": completed.returncode, "output": extract_final_answer(raw_output)}


def run_local_model(prompt: str, *, model: str | None = None) -> str:
    model_spec = normalize_chat_model(model or DEFAULT_CHAT_MODEL)
    if model_spec.startswith("ollama:"):
        return ollama_chat_generate(model_spec.removeprefix("ollama:"), prompt)
    if model_spec.startswith("hf:"):
        raise RuntimeError("local hf chat models are not installed yet; use an ollama: model")
    raise RuntimeError(f"unsupported local chat model: {model_spec}")


def extract_final_answer(output: str) -> str:
    text = output.strip()
    if not text:
        return ""
    lines = [line.rstrip() for line in text.splitlines()]
    if "codex" in lines:
        index = len(lines) - 1 - lines[::-1].index("codex")
        answer = "\n".join(lines[index + 1 :]).strip()
        if answer:
            return trim_token_footer(answer)
    return trim_token_footer(text)


def trim_token_footer(output: str) -> str:
    lines = output.splitlines()
    for index, line in enumerate(lines):
        if line.strip().lower() == "tokens used":
            return "\n".join(lines[:index]).strip()
    return output.strip()


def setup_agent(agent: str, cogito_bin: str | None = None) -> tuple[int, str]:
    command = cogito_bin or find_cogito_command()
    if agent == "codex":
        args = ["codex", "mcp", "add", "cogito", "--", command, "mcp"]
    elif agent == "claude":
        args = ["claude", "mcp", "add", "cogito", "--", command, "mcp"]
    elif agent == "opencode":
        return 2, (
            "opencode MCP add command is interactive/version-dependent.\n"
            "Use this server command when it asks for stdio command:\n"
            f"{command} mcp"
        )
    else:
        raise ValueError(f"unsupported agent: {agent}")

    if shutil.which(args[0]) is None:
        return 127, f"{args[0]} not found in PATH"
    completed = subprocess.run(args, text=True, capture_output=True, check=False)
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    return completed.returncode, output.strip()


def find_cogito_command() -> str:
    current = Path(sys.argv[0]).resolve()
    if current.exists() and current.name == "cogito":
        return str(current)
    found = shutil.which("cogito")
    if found:
        return found
    return f"{sys.executable} -m cogito.cli"

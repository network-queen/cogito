from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .local_extractor import ollama_chat_generate
from .memory import context_pack
from .policy import ContextRequest
from .settings import DEFAULT_CHAT_MODEL, normalize_chat_model


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
) -> dict[str, str | int]:
    if agent == "local":
        output = run_local_model(prompt, model=model)
        if stream and output:
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

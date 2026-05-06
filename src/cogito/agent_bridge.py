from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from .memory import context_pack
from .policy import ContextRequest


AGENT_COMMANDS = {
    "codex": lambda prompt: ["codex", "exec", prompt],
    "codex-exec": lambda prompt: ["codex", "exec", prompt],
    "claude": lambda prompt: ["claude", "-p", prompt],
    "opencode": lambda prompt: ["opencode", "run", prompt],
}


def build_enriched_prompt(context: str, user_prompt: str) -> str:
    return f"""Use this Cogito user context if relevant. Respect access policy.

{context}

User request:
{user_prompt}
"""


def get_prompt(conn, *, user_prompt: str, request: ContextRequest, limit: int) -> str:
    pack = context_pack(conn, query=user_prompt, request=request, limit=limit)
    return build_enriched_prompt(pack["context"], user_prompt)


def run_agent(agent: str, prompt: str) -> int:
    result = run_agent_capture(agent, prompt, stream=True)
    return int(result["exit_code"])


def run_agent_capture(agent: str, prompt: str, *, stream: bool = True) -> dict[str, str | int]:
    if agent not in AGENT_COMMANDS:
        raise ValueError(f"unsupported agent: {agent}")
    command = AGENT_COMMANDS[agent](prompt)
    binary = command[0]
    if shutil.which(binary) is None:
        raise RuntimeError(f"{binary} not found in PATH")
    if not stream:
        completed = subprocess.run(command, text=True, capture_output=True, check=False)
        output = "".join(part for part in (completed.stdout, completed.stderr) if part)
        return {"exit_code": completed.returncode, "output": output}

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

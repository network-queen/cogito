from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


TOOL_AGENTS = ["local", "codex", "codex-exec", "claude", "opencode"]
EXTERNAL_TOOL_AGENTS = ["codex", "claude", "opencode"]
TOOL_ALIASES = {"codex-exec": "codex"}
_MODEL_CACHE: dict[str, tuple[float, list[str]]] = {}
_CACHE_TTL = 60.0


@dataclass(frozen=True)
class ToolCommandResult:
    code: int
    command: list[str]
    output: str


def tool_status(tool: str) -> dict[str, Any]:
    canonical = canonical_tool(tool)
    binary = shutil.which(canonical)
    version = None
    if binary:
        version = command_output([canonical, "--version"])
    return {
        "tool": tool,
        "binary": canonical,
        "installed": binary is not None,
        "path": binary,
        "version": version,
        "install_command": install_command(canonical),
        "update_command": update_command(canonical),
        "models": list_models(tool),
    }


def all_tool_statuses() -> list[dict[str, Any]]:
    return [tool_status(tool) for tool in TOOL_AGENTS]


def install_tool(tool: str) -> ToolCommandResult:
    command = install_command(canonical_tool(tool))
    return run_command(command)


def update_tool(tool: str) -> ToolCommandResult:
    command = update_command(canonical_tool(tool))
    return run_command(command)


def install_for_model(model: str) -> ToolCommandResult:
    return install_tool(infer_agent_for_model(model))


def update_for_model(model: str) -> ToolCommandResult:
    return update_tool(infer_agent_for_model(model))


def ensure_adapter_for_model(model: str | None) -> ToolCommandResult | None:
    if not model:
        return None
    agent = infer_agent_for_model(model)
    canonical = canonical_tool(agent)
    if canonical == "local" or shutil.which(canonical):
        return None
    return install_tool(canonical)


def install_command(tool: str) -> list[str]:
    if tool == "local":
        return ["docker", "compose", "up", "-d", "ollama"]
    if tool == "codex":
        return ["npm", "install", "-g", "@openai/codex"]
    if tool == "claude":
        return ["npm", "install", "-g", "@anthropic-ai/claude-code"]
    if tool == "opencode":
        return ["npm", "install", "-g", "opencode-ai"]
    raise ValueError(f"unsupported tool: {tool}")


def update_command(tool: str) -> list[str]:
    if tool == "local":
        return ["docker", "compose", "pull", "ollama"]
    if tool == "codex" and shutil.which("codex"):
        return ["codex", "update"]
    if tool == "claude" and shutil.which("claude"):
        return ["claude", "update"]
    if tool == "opencode" and shutil.which("opencode"):
        return ["opencode", "upgrade"]
    return install_command(tool)


def run_command(command: list[str]) -> ToolCommandResult:
    if shutil.which(command[0]) is None:
        return ToolCommandResult(127, command, f"{command[0]} not found in PATH")
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
    return ToolCommandResult(completed.returncode, command, output)


def list_models(tool: str, *, refresh: bool = False) -> list[str]:
    canonical = canonical_tool(tool)
    now = time.time()
    cached = _MODEL_CACHE.get(canonical)
    if cached and not refresh and now - cached[0] < _CACHE_TTL:
        return cached[1]
    models = scan_models(canonical)
    _MODEL_CACHE[canonical] = (now, models)
    return models


def model_catalog(*, refresh: bool = False) -> dict[str, list[str]]:
    return {tool: list_models(tool, refresh=refresh) for tool in TOOL_AGENTS if tool != "codex-exec"}


def all_models(*, refresh: bool = False) -> list[str]:
    values: list[str] = []
    for models in model_catalog(refresh=refresh).values():
        values.extend(models)
    return sorted(unique(values))


def infer_agent_for_model(model: str | None) -> str:
    if not model or model == "-":
        return "local"
    value = model.removeprefix("ollama:").strip()
    if "/" in value:
        return "opencode"
    lowered = value.lower()
    if lowered.startswith(("claude-", "sonnet", "opus", "haiku")):
        return "claude"
    if lowered.startswith(("gpt-", "o3", "o4")):
        return "codex"
    for agent in ("local", "codex", "claude", "opencode"):
        if value in list_models(agent):
            return agent
    return "local"


def scan_models(tool: str) -> list[str]:
    if tool == "local":
        return ollama_models()
    if tool == "codex":
        return codex_models()
    if tool == "claude":
        return claude_models()
    if tool == "opencode":
        return opencode_models()
    return []


def ollama_models() -> list[str]:
    output = command_output(["ollama", "list"])
    models = []
    for line in output.splitlines()[1:]:
        parts = line.split()
        if parts:
            models.append(parts[0])
    return sorted(unique(models))


def codex_models() -> list[str]:
    candidates = [
        Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser() / "models_cache.json",
        Path.home() / ".codex" / "models_cache.json",
    ]
    for path in candidates:
        try:
            data = json.loads(path.read_text())
        except Exception:
            continue
        models = data.get("models") if isinstance(data, dict) else data
        if isinstance(models, list):
            values = [str(item.get("slug") or item.get("id") or "").strip() for item in models if isinstance(item, dict)]
            return sorted(unique(value for value in values if value))
    return models_from_help("codex", ["codex", "--help"])


def claude_models() -> list[str]:
    output = command_output(["claude", "--help"])
    values = []
    model_help = re.search(r"--model <model>\s+(.*?)(?:\n\s+-|\n\s+--|\nCommands:)", output, re.DOTALL)
    if model_help:
        values.extend(re.findall(r"'([A-Za-z0-9._/-]+)'", model_help.group(1)))
    for key in ("ANTHROPIC_MODEL", "ANTHROPIC_SMALL_FAST_MODEL"):
        value = os.environ.get(key)
        if value:
            values.append(value)
    return sorted(unique(values))


def opencode_models() -> list[str]:
    output = command_output(["opencode", "models"])
    return sorted(unique(line.strip() for line in output.splitlines() if "/" in line))


def models_from_help(tool: str, command: list[str]) -> list[str]:
    output = command_output(command)
    values = re.findall(r"(?:^|\s)([A-Za-z0-9][A-Za-z0-9._/-]*[A-Za-z0-9])", output)
    return sorted(unique(value for value in values if tool not in value.lower()))


def command_output(command: list[str], timeout: float = 8.0) -> str:
    if shutil.which(command[0]) is None:
        return ""
    try:
        completed = subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=False)
    except Exception:
        return ""
    return "\n".join(part for part in (completed.stdout, completed.stderr) if part)


def canonical_tool(tool: str) -> str:
    return TOOL_ALIASES.get(tool, tool)


def unique(values) -> list[str]:
    seen: set[str] = set()
    result = []
    for value in values:
        item = str(value).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result

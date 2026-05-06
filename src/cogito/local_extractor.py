from __future__ import annotations

import json
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any

from .extraction import classify_candidate, extract_candidate_memories


DEFAULT_OLLAMA_URL = "http://localhost:11434"


def extract_with_model(text: str, model_spec: str) -> tuple[list[dict[str, Any]], str]:
    if model_spec == "heuristic":
        return extract_candidate_memories(text), "heuristic"
    if model_spec.startswith("ollama:"):
        model = model_spec.removeprefix("ollama:")
        try:
            model_memories = extract_with_ollama(text, model)
            return merge_memories(model_memories, extract_candidate_memories(text)), f"ollama:{model}"
        except Exception:
            return extract_candidate_memories(text), "heuristic-fallback"
    if model_spec.startswith("hf:"):
        return extract_candidate_memories(text), "heuristic-fallback-hf-not-installed"
    return extract_candidate_memories(text), "heuristic"


def extract_with_ollama(text: str, model: str) -> list[dict[str, Any]]:
    ensure_ollama(model)
    prompt = f"""Extract durable user memories from this message.

Return only JSON array. No markdown.
Each item:
{{"text": "...", "type": "fact|preference|goal|relationship|intent", "sensitivity": "public|professional|personal|intimate|financial|medical|legal|secret", "contexts": ["coding"|"professional"|"creative"|"personal"|"intimate"|"public_profile"], "confidence": 0.0-1.0}}

Rules:
- Store only facts/preferences/goals about the user, not task instructions.
- Do not store secrets, credentials, or private third-party data.
- Use [] if nothing durable should be remembered.
- Keep text concise and standalone.

Message:
{text}
"""
    response = ollama_generate(model, prompt)
    memories = parse_json_array(response)
    return [normalize_memory(item) for item in memories if isinstance(item, dict)]


def ensure_ollama(model: str) -> None:
    if shutil.which("ollama") is None:
        raise RuntimeError("ollama command not found")
    if not ollama_ready():
        subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wait_for_ollama()
    if not ollama_has_model(model):
        subprocess.run(["ollama", "pull", model], check=True)


def ollama_ready() -> bool:
    try:
        request_json("/api/tags")
        return True
    except Exception:
        return False


def wait_for_ollama(timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if ollama_ready():
            return
        time.sleep(0.25)
    raise RuntimeError("ollama server did not start")


def ollama_has_model(model: str) -> bool:
    payload = request_json("/api/tags")
    names = {item.get("name") for item in payload.get("models", [])}
    if model in names:
        return True
    if ":" not in model:
        return f"{model}:latest" in names
    return False


def ollama_generate(model: str, prompt: str) -> str:
    payload = request_json(
        "/api/generate",
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
        },
    )
    return str(payload.get("response", "[]"))


def ollama_chat_generate(model: str, prompt: str) -> str:
    ensure_ollama(model)
    payload = request_json(
        "/api/generate",
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.2},
        },
    )
    return str(payload.get("response", "")).strip()


def ollama_embed(model: str, text: str) -> list[float]:
    ensure_ollama(model)
    payload = request_json(
        "/api/embed",
        {
            "model": model,
            "input": text,
        },
    )
    embeddings = payload.get("embeddings")
    if isinstance(embeddings, list) and embeddings and isinstance(embeddings[0], list):
        return [float(value) for value in embeddings[0]]
    embedding = payload.get("embedding")
    if isinstance(embedding, list):
        return [float(value) for value in embedding]
    raise RuntimeError("ollama embed response missing embedding")


def request_json(path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        ollama_url() + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=120 if payload else 5) as response:
        return json.loads(response.read().decode("utf-8"))


def ollama_url() -> str:
    import os

    return os.environ.get("OLLAMA_URL", DEFAULT_OLLAMA_URL).rstrip("/")


def parse_json_array(value: str) -> list[Any]:
    value = value.strip()
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        start = value.find("[")
        end = value.rfind("]")
        if start == -1 or end == -1:
            return []
        parsed = json.loads(value[start : end + 1])
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict) and isinstance(parsed.get("memories"), list):
        return parsed["memories"]
    return []


def normalize_memory(item: dict[str, Any]) -> dict[str, Any]:
    text = str(item.get("text", "")).strip()
    if not text:
        raise ValueError("empty memory")
    base = classify_candidate(text)
    memory_type = str(item.get("type") or base["type"])
    sensitivity = str(item.get("sensitivity") or base["sensitivity"])
    contexts = item.get("contexts") or base["contexts"]
    if not isinstance(contexts, list):
        contexts = base["contexts"]
    confidence = float(item.get("confidence", 0.7))
    return {
        "text": text,
        "type": memory_type,
        "sensitivity": sensitivity,
        "contexts": sorted({str(context) for context in contexts}),
        "confidence": max(0.0, min(confidence, 1.0)),
    }


def merge_memories(primary: list[dict[str, Any]], fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in primary + fallback:
        key = item["text"].strip().lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged

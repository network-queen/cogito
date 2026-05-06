from __future__ import annotations

import re


FACT_PATTERNS = [
    re.compile(r"\bI am\b\s+(.+)", re.IGNORECASE),
    re.compile(r"\bI'm\b\s+(.+)", re.IGNORECASE),
    re.compile(r"\bI work\b\s+(.+)", re.IGNORECASE),
    re.compile(r"\bI prefer\b\s+(.+)", re.IGNORECASE),
    re.compile(r"\bI want\b\s+(.+)", re.IGNORECASE),
    re.compile(r"\bwe want\b\s+(.+)", re.IGNORECASE),
    re.compile(r"\bmy goal is\b\s+(.+)", re.IGNORECASE),
    re.compile(r"\bthe goal is\b\s+(.+)", re.IGNORECASE),
]


def extract_candidate_memories(text: str) -> list[dict]:
    candidates: list[dict] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        for pattern in FACT_PATTERNS:
            if pattern.search(line):
                candidates.append(classify_candidate(line))
                break
    return candidates


def classify_candidate(text: str) -> dict:
    lowered = text.lower()
    memory_type = "fact"
    if any(word in lowered for word in ("prefer", "like", "style")):
        memory_type = "preference"
    if any(word in lowered for word in ("goal", "want", "build", "start")):
        memory_type = "goal"

    sensitivity = "professional"
    contexts = ["professional"]
    if any(word in lowered for word in ("code", "repo", "software", "agent", "mcp", "ai", "app")):
        contexts.append("coding")
    if any(word in lowered for word in ("intimate", "partner", "therapy", "medical", "financial", "secret")):
        sensitivity = "personal"
        contexts.append("personal")

    return {
        "text": text,
        "type": memory_type,
        "sensitivity": sensitivity,
        "contexts": sorted(set(contexts)),
        "confidence": 0.55,
    }


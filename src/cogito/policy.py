from __future__ import annotations

from dataclasses import dataclass


SENSITIVITY_ORDER = {
    "public": 0,
    "professional": 1,
    "personal": 2,
    "intimate": 3,
    "financial": 4,
    "medical": 4,
    "legal": 4,
    "secret": 5,
}

DEFAULT_LENS_CONTEXTS = {
    "coding": {"coding", "professional", "public_profile"},
    "professional": {"professional", "coding", "public_profile"},
    "creative": {"creative", "professional", "public_profile"},
    "friend": {"personal", "creative", "public_profile"},
    "personal": {"personal", "creative", "public_profile"},
    "intimate": {"intimate", "personal", "creative", "public_profile"},
    "public_profile": {"public_profile"},
}


@dataclass(frozen=True)
class ContextRequest:
    lens: str = "coding"
    max_sensitivity: str = "professional"
    agent: str = "local"
    purpose: str = "context_retrieval"
    token_budget: int = 1200


def sensitivity_allowed(value: str, maximum: str) -> bool:
    return SENSITIVITY_ORDER.get(value, 99) <= SENSITIVITY_ORDER.get(maximum, -1)


def contexts_allowed(memory_contexts: list[str], lens: str) -> bool:
    allowed = DEFAULT_LENS_CONTEXTS.get(lens, {lens})
    return bool(set(memory_contexts) & allowed)


def memory_allowed(memory: dict, request: ContextRequest) -> bool:
    if memory.get("state") != "active":
        return False
    if not sensitivity_allowed(memory.get("sensitivity", "secret"), request.max_sensitivity):
        return False
    return contexts_allowed(memory.get("contexts", []), request.lens)


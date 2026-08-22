"""Small durable action transitions used by the application workflow."""
# ruff: noqa: E501

from __future__ import annotations

from pathlib import Path
from typing import Any

from ._state import identity, read_json, record_uri, write_json
from .contracts import TransitionReference


def issue_transition(
    workspace: str | Path, operation: str, payload: dict[str, Any]
) -> TransitionReference:
    transition_identity = identity({"operation": operation, **payload})
    reference = TransitionReference(operation=operation, identity=transition_identity)
    name = f"transition-{transition_identity.removeprefix('sha256:')}.json"
    existing = read_json(workspace, name)
    if existing is None:
        write_json(
            workspace,
            name,
            {"operation": operation, "identity": transition_identity, "consumed": False, **payload},
        )
    elif existing.get("operation") != operation or existing.get("identity") != transition_identity:
        raise ValueError("Transition identity collision")
    return reference


def read_transition(workspace: str | Path, reference: TransitionReference) -> dict[str, Any]:
    raw = read_json(workspace, f"transition-{reference.identity.removeprefix('sha256:')}.json")
    if (
        raw is None
        or raw.get("operation") != reference.operation
        or raw.get("identity") != reference.identity
    ):
        raise ValueError("Transition is unavailable or corrupt")
    return raw


def transition_uri(reference: TransitionReference) -> str:
    return record_uri(reference.operation, reference.identity)

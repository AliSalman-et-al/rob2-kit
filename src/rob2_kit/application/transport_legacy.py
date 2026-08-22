"""Agent-friendly transport helpers that never weaken canonical identities.

The application layer continues to persist content-addressed references. This
module only improves their wire representation: executable continuations keep
all discriminators, model-facing references receive durable short handles, and
transport validation failures become typed repairs rather than framework error
messages.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ._state import read_json, write_json

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_HANDLE = re.compile(r"^(?:e|r|tx|ack|img|src|h)[1-9][0-9]*$")
_COMPLETION = re.compile(
    r"\b(?:assessment(?:s)? (?:is|are|was|were)?\s*complete(?:d)?|"
    r"successfully completed|batch finalized|workflow complete|finalized successfully)\b",
    re.IGNORECASE,
)


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TransportRepair(_Closed):
    pointer: str = Field(default="", pattern=r"^(?:|/(?:[^~/]|~[01])+(?:/(?:[^~/]|~[01])+)*)$")
    code: str = Field(min_length=1)
    detail: str = Field(min_length=1)
    expected: object | None = None
    received: object | None = None
    suggested_patch: tuple[dict[str, object], ...] = ()


class TransportRepairReceipt(_Closed):
    outcome: str = "repair"
    repairs: tuple[TransportRepair, ...] = Field(min_length=1)


class SanitizedModelOutput(_Closed):
    text: str
    contradictions: tuple[str, ...] = ()


class StatusLike(Protocol):
    phase: object
    presentation: object

    def model_dump(self, **kwargs: object) -> dict[str, object]: ...


@dataclass(frozen=True)
class _Reference:
    prefix: str
    payload: dict[str, object]


def actionable_dump(value: object) -> object:
    """Dump typed values without dropping union discriminators.

    ``exclude_defaults=True`` is intentionally never used. The continuation
    ``operation`` and ``authority`` fields are executable protocol data even
    when their values equal model defaults.
    """

    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_none=True)
    if isinstance(value, Mapping):
        return {str(key): actionable_dump(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [actionable_dump(item) for item in value]
    return value


def actionable_json(value: BaseModel) -> str:
    return value.model_dump_json(exclude_none=True)


def _reference(value: Mapping[str, object]) -> _Reference | None:
    identity = value.get("identity")
    if not isinstance(identity, str) or _SHA256.fullmatch(identity) is None:
        return None
    kind = value.get("kind")
    operation = value.get("operation")
    uri = value.get("uri")
    if operation is not None and isinstance(operation, str):
        return _Reference("tx", {"operation": operation, "identity": identity})
    if kind == "evidence":
        return _Reference("e", {"kind": "evidence", "identity": identity})
    if kind == "review_ack":
        payload = {key: value[key] for key in ("kind", "identity", "uri") if key in value}
        return _Reference("ack", payload)
    if isinstance(uri, str) and uri.startswith("rob2://render/"):
        return _Reference("img", {"identity": identity, "uri": uri})
    if isinstance(kind, str):
        payload = {key: value[key] for key in ("kind", "identity", "uri") if key in value}
        return _Reference("r", payload)
    return None


def _load_handles(workspace: str | Path) -> dict[str, dict[str, object]]:
    raw = read_json(workspace, "wire-handles.json")
    if raw is None:
        return {}
    handles = raw.get("handles") if isinstance(raw, dict) else None
    if not isinstance(handles, dict):
        raise ValueError("wire handle index is corrupt")
    result: dict[str, dict[str, object]] = {}
    for handle, payload in handles.items():
        if (
            not isinstance(handle, str)
            or _HANDLE.fullmatch(handle) is None
            or not isinstance(payload, dict)
        ):
            raise ValueError("wire handle index is corrupt")
        result[handle] = payload
    return result


def _assign_handle(
    reference: _Reference,
    handles: MutableMapping[str, dict[str, object]],
) -> str:
    for handle, payload in handles.items():
        if payload == reference.payload:
            return handle
    used = {
        int(handle[len(reference.prefix) :])
        for handle in handles
        if handle.startswith(reference.prefix) and handle[len(reference.prefix) :].isdigit()
    }
    number = 1
    while number in used:
        number += 1
    handle = f"{reference.prefix}{number}"
    handles[handle] = reference.payload
    return handle


def annotate_handles(workspace: str | Path, value: object) -> object:
    """Attach stable short handles to reference-shaped wire objects.

    Canonical hashes remain present, so this is backwards compatible. The
    mapping is persisted and survives host/process restarts for the workspace.
    """

    handles = _load_handles(workspace)
    changed = False

    def visit(item: object) -> object:
        nonlocal changed
        if isinstance(item, BaseModel):
            return visit(item.model_dump(mode="json", exclude_none=True))
        if isinstance(item, Mapping):
            result = {str(key): visit(child) for key, child in item.items()}
            reference = _reference(result)
            if reference is not None:
                handle = _assign_handle(reference, handles)
                if result.get("handle") != handle:
                    result["handle"] = handle
                    changed = True
            return result
        if isinstance(item, Sequence) and not isinstance(item, str | bytes | bytearray):
            return [visit(child) for child in item]
        return item

    rendered = visit(value)
    if changed:
        write_json(workspace, "wire-handles.json", {"handles": handles})
    return rendered


def resolve_handles(workspace: str | Path, value: object) -> object:
    """Expand model-facing handles before typed application validation."""

    handles = _load_handles(workspace)

    def visit(item: object) -> object:
        if isinstance(item, Mapping):
            handle = item.get("handle")
            if isinstance(handle, str):
                stored = handles.get(handle)
                if stored is None:
                    raise ValueError(f"unknown or stale wire handle: {handle}")
                supplied = {
                    str(key): visit(child) for key, child in item.items() if key != "handle"
                }
                if supplied:
                    for key, expected in stored.items():
                        if key in supplied and supplied[key] != expected:
                            raise ValueError(f"wire handle {handle} conflicts with supplied {key}")
                    return {**stored, **supplied}
                return dict(stored)
            return {str(key): visit(child) for key, child in item.items()}
        if isinstance(item, str) and _HANDLE.fullmatch(item):
            stored = handles.get(item)
            if stored is None:
                raise ValueError(f"unknown or stale wire handle: {item}")
            return dict(stored)
        if isinstance(item, Sequence) and not isinstance(item, str | bytes | bytearray):
            return [visit(child) for child in item]
        return item

    return visit(value)


def _pointer(location: tuple[int | str, ...]) -> str:
    return "/" + "/".join(str(part).replace("~", "~0").replace("/", "~1") for part in location)


def validation_repairs(error: ValidationError, *, prefix: str = "") -> TransportRepairReceipt:
    repairs: list[TransportRepair] = []
    for item in error.errors(include_url=False, include_context=True, include_input=True):
        kind = str(item["type"])
        code = (
            "missing"
            if kind == "missing"
            else "extra"
            if kind == "extra_forbidden"
            else "wrong_type"
            if "type" in kind or kind in {"model_attributes_type", "model_type"}
            else "invalid"
        )
        location = tuple(
            part for part in item["loc"] if part not in {"function-after", "tagged-union"}
        )
        repairs.append(
            TransportRepair(
                pointer=prefix + _pointer(location),
                code=code,
                detail=str(item["msg"]),
                received=item.get("input"),
            )
        )
    unique = {(item.pointer, item.code, item.detail): item for item in repairs}
    return TransportRepairReceipt(repairs=tuple(unique[key] for key in sorted(unique)))


def sanitize_model_output(text: str, status: StatusLike) -> SanitizedModelOutput:
    """Remove operational completion claims that contradict durable status.

    Scientific rationale is retained. The launcher owns workflow-state prose;
    a model cannot turn a draft, review pause, or zero-assessed terminal into a
    completed assessment by wording alone.
    """

    phase = str(getattr(status.phase, "value", status.phase))
    presentation = getattr(status, "presentation", None)
    code = str(getattr(presentation, "code", ""))
    allow_completion = phase == "finalized" and code != "finalized_zero_assessed"
    kept: list[str] = []
    contradictions: list[str] = []
    for line in text.splitlines():
        if not allow_completion and _COMPLETION.search(line):
            contradictions.append(line.strip())
            continue
        kept.append(line)
    return SanitizedModelOutput(text="\n".join(kept).strip(), contradictions=tuple(contradictions))

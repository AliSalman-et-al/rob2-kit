"""Agent-friendly wire helpers layered over the canonical transport module."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from . import transport_legacy as _legacy
from ._state import write_json

TransportRepair = _legacy.TransportRepair
TransportRepairReceipt = _legacy.TransportRepairReceipt
SanitizedModelOutput = _legacy.SanitizedModelOutput
actionable_dump = _legacy.actionable_dump
actionable_json = _legacy.actionable_json
resolve_handles = _legacy.resolve_handles
validation_repairs = _legacy.validation_repairs
sanitize_model_output = _legacy.sanitize_model_output


def annotate_handles(workspace: str | Path, value: object) -> object:
    """Attach canonical handles plus stable Source handles."""

    rendered = _legacy.annotate_handles(workspace, value)
    handles = _legacy._load_handles(workspace)
    changed = False

    def visit(item: object) -> object:
        nonlocal changed
        if isinstance(item, Mapping):
            result = {str(key): visit(child) for key, child in item.items()}
            source_id, alias = result.get("source_id"), result.get("alias")
            if isinstance(source_id, str) and isinstance(alias, str) and "handle" not in result:
                handle = _legacy._assign_handle(
                    _legacy._Reference("src", {"source_id": source_id}), handles
                )
                result["handle"] = handle
                changed = True
            return result
        if isinstance(item, Sequence) and not isinstance(item, str | bytes | bytearray):
            return [visit(child) for child in item]
        return item

    result = visit(rendered)
    if changed:
        write_json(workspace, "wire-handles.json", {"handles": handles})
    return result


__all__ = [
    "SanitizedModelOutput",
    "TransportRepair",
    "TransportRepairReceipt",
    "actionable_dump",
    "actionable_json",
    "annotate_handles",
    "resolve_handles",
    "sanitize_model_output",
    "validation_repairs",
]

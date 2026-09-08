"""Resolve disposable public source handles against the current Batch."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ._state import _ensure, _root, _state

_SOURCE_ID = re.compile(r"^source_[0-9a-f]{64}$")
_SOURCE_HANDLE = re.compile(r"^sh_[0-9a-f]{16}$")


def source_handle(source_id: str) -> str:
    """Return the public handle derived from one canonical SourceId."""
    if not _SOURCE_ID.fullmatch(source_id):
        raise ValueError("source identity is malformed")
    return "sh_" + source_id.removeprefix("source_")[:16]


def _batch_sources(batch: object) -> list[tuple[str, str]]:
    if not isinstance(batch, dict) or not isinstance(batch.get("trials"), list):
        return []
    sources: list[tuple[str, str]] = []
    for trial in batch["trials"]:
        if not isinstance(trial, dict) or not isinstance(trial.get("id"), str):
            continue
        trial_id = trial["id"]
        for source in trial.get("sources", ()):
            if not isinstance(source, dict) or not isinstance(source.get("id"), str):
                continue
            source_id = source["id"]
            if _SOURCE_ID.fullmatch(source_id):
                sources.append((trial_id, source_id))
    return sources


def source_handle_map(batch: object) -> dict[str, tuple[tuple[str, str], ...]]:
    """Build the per-Batch public handle index without persisting it."""
    grouped: dict[str, list[tuple[str, str]]] = {}
    for trial_id, source_id in _batch_sources(batch):
        grouped.setdefault(source_handle(source_id), []).append((trial_id, source_id))
    return {handle: tuple(dict.fromkeys(matches)) for handle, matches in grouped.items()}


def resolve_source_handle(workspace: str | Path, trial_id: str, handle: str) -> str:
    """Resolve one public handle to exactly one SourceId in the current Batch."""
    if not _SOURCE_HANDLE.fullmatch(handle):
        raise ValueError("source handle is malformed")
    root = _root(workspace)
    _ensure(root)
    matches = source_handle_map((_state(root)).get("batch")).get(handle, ())
    if not matches:
        raise ValueError("source handle is unknown")
    trial_matches = tuple(
        dict.fromkeys(source_id for owner_trial, source_id in matches if owner_trial == trial_id)
    )
    if len(trial_matches) > 1:
        raise ValueError("source handle is ambiguous")
    if not trial_matches:
        if matches:
            raise ValueError("source handle is outside the active Trial")
        raise ValueError("source handle is unknown")
    return trial_matches[0]


def public_source_references(value: Any) -> Any:
    """Replace canonical SourceIds in one MCP response with public handles."""

    def reject_ambiguous_source_lists(item: Any) -> None:
        if isinstance(item, dict):
            sources = item.get("sources")
            if isinstance(sources, (list, tuple)):
                grouped: dict[tuple[object, str], set[str]] = {}
                for source in sources:
                    if not isinstance(source, dict):
                        continue
                    source_id = source.get("id")
                    if not isinstance(source_id, str) or not _SOURCE_ID.fullmatch(source_id):
                        continue
                    key = (source.get("trial_id"), source_handle(source_id))
                    grouped.setdefault(key, set()).add(source_id)
                if any(len(source_ids) > 1 for source_ids in grouped.values()):
                    raise ValueError("source handle is ambiguous")
            for item_value in item.values():
                reject_ambiguous_source_lists(item_value)
        elif isinstance(item, (list, tuple)):
            for item_value in item:
                reject_ambiguous_source_lists(item_value)

    reject_ambiguous_source_lists(value)

    def convert(item: Any) -> Any:
        if isinstance(item, dict):
            return {key: convert(item_value) for key, item_value in item.items()}
        if isinstance(item, list):
            return [convert(item_value) for item_value in item]
        if isinstance(item, tuple):
            return [convert(item_value) for item_value in item]
        if isinstance(item, str) and _SOURCE_ID.fullmatch(item):
            return source_handle(item)
        return item

    return convert(value)

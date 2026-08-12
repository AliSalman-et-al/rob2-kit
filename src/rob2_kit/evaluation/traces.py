"""Stable, host-neutral trace vocabulary for public replay tests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import Field

from rob2_kit.domain.revisions import FrozenModel


class NormalizedCall(FrozenModel):
    sequence: int = Field(ge=1)
    name: str = Field(min_length=1)
    arguments: dict[str, Any] = {}
    response_class: str = "success"
    run_state: str | None = None
    next_action: str | None = None
    workflow_events: tuple[str, ...] = ()
    checkpoint: str | None = None


class TraceFinal(FrozenModel):
    run_state: str | None = None
    next_action: str | None = None
    identities: dict[str, Any] = {}
    integrity: dict[str, Any] = {}


class TraceSignals(FrozenModel):
    call_count: int = Field(ge=0)
    repair_count: int = Field(ge=0)
    duration_ms: int | float | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    usage: dict[str, Any] = {}


class NormalizedTrace(FrozenModel):
    schema_version: int = 1
    scenario: str = Field(min_length=1)
    prompt_family: str = Field(min_length=1)
    host: str = Field(min_length=1)
    adapter: str | None = None
    model: str | None = None
    release: str | None = None
    execution_contract: str | None = None
    capabilities: tuple[str, ...] = ()
    skill_activation: tuple[str, ...] = ()
    calls: tuple[NormalizedCall, ...] = ()
    final: TraceFinal = TraceFinal()
    signals: TraceSignals = TraceSignals(call_count=0, repair_count=0)


def normalize_trace(raw: Mapping[str, Any]) -> NormalizedTrace:
    """Normalize one host trace while retaining semantic order and arguments."""

    if not isinstance(raw, Mapping):
        raise TypeError("trace must be a mapping")
    normalizer = _VolatileNormalizer()
    host_value = raw.get("host", "unknown")
    if isinstance(host_value, Mapping):
        host = str(host_value.get("name", "unknown"))
        adapter = raw.get("adapter", host_value.get("adapter"))
    else:
        host = str(host_value)
        adapter = raw.get("adapter")
    raw_calls = raw.get("calls", raw.get("tool_calls", ()))
    if not isinstance(raw_calls, Sequence) or isinstance(raw_calls, (str, bytes)):
        raise TypeError("trace calls must be a sequence")
    calls = tuple(
        _normalize_call(item, index, normalizer) for index, item in enumerate(raw_calls, 1)
    )
    final_raw = raw.get("final", {})
    if not isinstance(final_raw, Mapping):
        raise TypeError("trace final must be a mapping")
    signals_raw = raw.get("signals", {})
    if not isinstance(signals_raw, Mapping):
        raise TypeError("trace signals must be a mapping")
    final = TraceFinal(
        run_state=_optional_string(final_raw.get("run_state")),
        next_action=_optional_string(final_raw.get("next_action")),
        identities=normalizer.value(final_raw.get("identities", {}), key="identities"),
        integrity=normalizer.value(final_raw.get("integrity", {}), key="integrity"),
    )
    repair_count = sum(
        1 for call in calls if call.response_class in {"correctable_error", "repair"}
    )
    signals = TraceSignals(
        call_count=len(calls),
        repair_count=int(signals_raw.get("repair_count", repair_count)),
        duration_ms=signals_raw.get("duration_ms"),
        input_tokens=signals_raw.get("input_tokens"),
        output_tokens=signals_raw.get("output_tokens"),
        usage=normalizer.value(signals_raw.get("usage", {}), key="usage"),
    )
    return NormalizedTrace(
        scenario=str(raw.get("scenario", "unspecified")),
        prompt_family=str(raw.get("prompt_family", "unspecified")),
        host=host,
        adapter=str(adapter) if adapter is not None else None,
        model=str(raw["model"]) if raw.get("model") is not None else None,
        release=str(raw["release"]) if raw.get("release") is not None else None,
        execution_contract=(
            str(raw["execution_contract"]) if raw.get("execution_contract") is not None else None
        ),
        capabilities=tuple(str(item) for item in raw.get("capabilities", ())),
        skill_activation=tuple(str(item) for item in raw.get("skill_activation", ())),
        calls=calls,
        final=final,
        signals=signals,
    )


def _normalize_call(item: Any, sequence: int, normalizer: _VolatileNormalizer) -> NormalizedCall:
    if not isinstance(item, Mapping):
        raise TypeError("each trace call must be a mapping")
    arguments = item.get("arguments", item.get("args", {}))
    if not isinstance(arguments, Mapping):
        raise TypeError("trace call arguments must be a mapping")
    events = item.get("workflow_events", item.get("events", ()))
    if not isinstance(events, Sequence) or isinstance(events, (str, bytes)):
        raise TypeError("workflow_events must be a sequence")
    return NormalizedCall(
        sequence=sequence,
        name=str(item.get("name", item.get("tool", "unknown"))),
        arguments=normalizer.value(arguments, key="arguments"),
        response_class=str(item.get("response_class", item.get("response", "success"))),
        run_state=_optional_string(item.get("run_state", item.get("state"))),
        next_action=_optional_string(item.get("next_action")),
        workflow_events=tuple(str(event) for event in events),
        checkpoint=_optional_string(item.get("checkpoint")),
    )


def _optional_string(value: Any) -> str | None:
    return str(value) if value is not None else None


class _VolatileNormalizer:
    def __init__(self) -> None:
        self._handles: dict[tuple[str, str], str] = {}
        self._counts: dict[str, int] = {}

    def value(self, value: Any, *, key: str = "") -> Any:
        if isinstance(value, Mapping):
            return {str(name): self.value(item, key=str(name)) for name, item in value.items()}
        if isinstance(value, list):
            return [self.value(item, key=key) for item in value]
        if isinstance(value, tuple):
            return tuple(self.value(item, key=key) for item in value)
        if not isinstance(value, str):
            return value
        category = self._category(key, value)
        if category is None:
            return value
        handle_key = (category, value)
        if handle_key not in self._handles:
            index = self._counts.get(category, 0) + 1
            self._counts[category] = index
            self._handles[handle_key] = f"<{category}-{index}>"
        return self._handles[handle_key]

    @staticmethod
    def _category(key: str, value: str) -> str | None:
        normalized = key.casefold().replace("-", "_")
        if normalized in {"project_root", "path", "file_path", "absolute_path", "artifact_path"}:
            return "path"
        if normalized.endswith("cursor") or normalized == "cursor":
            return "cursor"
        if normalized in {
            "work_token",
            "proposal_token",
            "continuation_token",
            "idempotency_key",
            "token",
        } or normalized.endswith("_token"):
            return "work-token" if "work" in normalized or normalized == "token" else "token"
        if normalized.endswith("_at") or normalized in {"timestamp", "timestamp_utc"}:
            return "timestamp"
        prefix = value.split(":", 1)[0].casefold() if ":" in value else ""
        if prefix in {"artifact", "revision", "event", "operation"}:
            return prefix
        if prefix == "run":
            return "run"
        return None


__all__ = [
    "NormalizedCall",
    "NormalizedTrace",
    "TraceFinal",
    "TraceSignals",
    "normalize_trace",
]

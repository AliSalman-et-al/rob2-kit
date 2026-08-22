"""Privacy and failure-isolation tests for the in-process telemetry seam."""

from __future__ import annotations

from contextlib import nullcontext

import pytest
from pydantic import TypeAdapter, ValidationError

from rob2_kit.telemetry import (
    CardinalityEvent,
    CardinalityMetric,
    DurationEvent,
    DurationOperation,
    McpOperation,
    McpOutcome,
    McpOutcomeEvent,
    ProjectionEvent,
    ProjectionOperation,
    ProjectionOutcome,
    RepairEvent,
    RepairOutcome,
    RepairSurface,
    RetrievalEvent,
    RetrievalOperation,
    RetrievalOutcome,
    SerializedBytesBoundary,
    SerializedBytesEvent,
    SerializedBytesOperation,
    Telemetry,
    TelemetryEvent,
    emit_event,
    measured_duration,
)


def _events() -> tuple[TelemetryEvent, ...]:
    return (
        ProjectionEvent(
            operation=ProjectionOperation.MATERIALIZE,
            outcome=ProjectionOutcome.CREATED,
            page_count=2,
        ),
        RetrievalEvent(
            operation=RetrievalOperation.SEARCH,
            outcome=RetrievalOutcome.SUCCEEDED,
            operation_count=1,
            result_count=2,
        ),
        RepairEvent(
            surface=RepairSurface.DOMAIN,
            outcome=RepairOutcome.DEFECTS,
            defect_count=2,
        ),
        McpOutcomeEvent(operation=McpOperation.LIST_SOURCES, outcome=McpOutcome.SUCCESS),
        DurationEvent(operation=DurationOperation.RETRIEVAL, duration_ms=12),
        CardinalityEvent(metric=CardinalityMetric.SOURCES, value=2),
        SerializedBytesEvent(
            boundary=SerializedBytesBoundary.MCP_RESPONSE,
            operation=SerializedBytesOperation.LIST_SOURCES,
            byte_count=128,
        ),
    )


def test_event_union_is_closed_and_accepts_each_measurement_family() -> None:
    adapter = TypeAdapter(TelemetryEvent)

    for event in _events():
        assert adapter.validate_python(event) == event
        assert adapter.validate_json(event.model_dump_json()) == event


@pytest.mark.parametrize(
    "field",
    [
        {"prompt": "private"},
        {"response": "private"},
        {"query": "scientific terms"},
        {"source_text": "trial text"},
        {"label": "trial label"},
        {"rationale": "reasoning"},
        {"claim": "claim"},
        {"citation": "citation"},
        {"registry_content": "record"},
        {"credential": "secret"},
        {"private_path": "C:\\private"},
        {"hidden_reasoning": "thought"},
        {"path": "/private/repair/path"},
        {"subject_id": "trial-1"},
    ],
)
def test_forbidden_free_form_content_is_rejected(field: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        ProjectionEvent.model_validate(
            {
                "operation": ProjectionOperation.VERIFY,
                "outcome": ProjectionOutcome.REUSED,
                "page_count": 1,
                **field,
            }
        )


def test_categories_are_closed_and_measurements_are_non_negative_integers() -> None:
    with pytest.raises(ValidationError):
        ProjectionEvent(operation="unknown", outcome="created", page_count=1)
    with pytest.raises(ValidationError):
        DurationEvent(operation=DurationOperation.RETRIEVAL, duration_ms=-1)
    with pytest.raises(ValidationError):
        CardinalityEvent(metric=CardinalityMetric.SOURCES, value=True)
    with pytest.raises(ValidationError):
        SerializedBytesEvent(
            boundary="unknown",
            operation=SerializedBytesOperation.EXPORT,
            byte_count=1,
        )


def test_sink_failure_cannot_escape_event_emission() -> None:
    class BrokenSink:
        def emit(self, event: TelemetryEvent) -> None:
            raise RuntimeError("measurement failed")

    event = _events()[0]
    emit_event(BrokenSink(), event)
    Telemetry(BrokenSink()).emit(event)

    with measured_duration(BrokenSink(), DurationOperation.RETRIEVAL):
        pass


def test_callable_sink_and_duration_are_best_effort() -> None:
    received: list[TelemetryEvent] = []
    telemetry = Telemetry(received.append)

    telemetry.emit(_events()[0])
    with measured_duration(telemetry, DurationOperation.RETRIEVAL):
        pass

    assert len(received) == 2
    assert isinstance(received[1], DurationEvent)
    assert received[1].duration_ms >= 0


def test_default_telemetry_does_not_retain_events() -> None:
    with measured_duration(Telemetry(), DurationOperation.RETRIEVAL):
        pass
    # The only observable default behavior is successful completion.
    with nullcontext():
        Telemetry().emit(_events()[0])

"""Privacy-safe, in-process measurements for the v2 optimization seam.

Telemetry is deliberately a small boundary.  Events contain only closed
categories and non-negative measurements; they never carry workflow IDs,
scientific text, or implementation paths.  A sink is injected by the caller
when measurements are wanted.  The default sink is a no-op and does not write
or retain anything.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from time import perf_counter
from typing import Annotated, Literal, Protocol, TypeAlias, cast

from pydantic import BaseModel, ConfigDict, Field


class _StrictEvent(BaseModel):
    """Base for closed, immutable event payloads."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ProjectionOperation(StrEnum):
    MATERIALIZE = "materialize"
    VERIFY = "verify"
    REBUILD = "rebuild"
    INDEX = "index"


class ProjectionOutcome(StrEnum):
    CREATED = "created"
    REUSED = "reused"
    REBUILT = "rebuilt"
    FAILED = "failed"


class RetrievalOperation(StrEnum):
    SEARCH = "search"
    PAGE_READ = "page_read"
    WINDOW_READ = "window_read"
    TEXT_SELECTION = "text_selection"
    VISUAL_SELECTION = "visual_selection"


class RetrievalOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    CONDITION = "condition"
    FAILED = "failed"


class RepairSurface(StrEnum):
    PROPOSAL = "proposal"
    DOMAIN = "domain"


class RepairOutcome(StrEnum):
    DEFECTS = "defects"
    VALID = "valid"


class McpOperation(StrEnum):
    INGEST_BATCH = "ingest_batch"
    LIST_SOURCES = "list_sources"
    RETRIEVE_EVIDENCE = "retrieve_evidence"
    RENDER_PAGE = "render_page"
    SAVE_PROPOSAL = "save_proposal"
    APPROVE_BATCH = "approve_batch"
    VALIDATE_DOMAIN_JUDGMENT = "validate_domain_judgment"
    COMMIT_DOMAIN_JUDGMENT = "commit_domain_judgment"
    FINISH_TRIAL = "finish_trial"
    FINALIZE_BATCH = "finalize_batch"
    DISCARD_ACTIVE_BATCH = "discard_active_batch"
    CURRENT_BATCH = "current_batch"
    READ_RECORD = "read_record"
    REGISTRY_RECORD = "registry_record"


class McpOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    CONDITION = "condition"
    FAILED = "failed"


class DurationOperation(StrEnum):
    INGESTION = "ingestion"
    PROJECTION = "projection"
    RETRIEVAL = "retrieval"
    RENDERING = "rendering"
    PROPOSAL = "proposal"
    APPROVAL = "approval"
    DOMAIN_VALIDATION = "domain_validation"
    DOMAIN_COMMIT = "domain_commit"
    FINISH = "finish"
    RECOVERY = "recovery"
    FINALIZATION = "finalization"
    EXPORT = "export"


class CardinalityMetric(StrEnum):
    TRIALS = "trials"
    SOURCES = "sources"
    PAGES = "pages"
    DOMAINS = "domains"
    RETRIEVAL_OPERATIONS = "retrieval_operations"
    REPAIR_DEFECTS = "repair_defects"
    MCP_CALLS = "mcp_calls"
    REVISIONS = "revisions"
    EVIDENCE_READS = "evidence_reads"
    EXTRACTIONS = "extractions"
    INDEX_BUILDS = "index_builds"
    VALIDATION_ATTEMPTS = "validation_attempts"
    TURNS = "turns"


class SerializedBytesBoundary(StrEnum):
    MCP_REQUEST = "mcp_request"
    MCP_RESPONSE = "mcp_response"
    CANONICAL_RECORD = "canonical_record"
    ARTIFACT = "artifact"


class SerializedBytesOperation(StrEnum):
    INGEST_BATCH = "ingest_batch"
    LIST_SOURCES = "list_sources"
    RETRIEVE_EVIDENCE = "retrieve_evidence"
    RENDER_PAGE = "render_page"
    SAVE_PROPOSAL = "save_proposal"
    APPROVE_BATCH = "approve_batch"
    VALIDATE_DOMAIN_JUDGMENT = "validate_domain_judgment"
    COMMIT_DOMAIN_JUDGMENT = "commit_domain_judgment"
    FINISH_TRIAL = "finish_trial"
    FINALIZE_BATCH = "finalize_batch"
    DISCARD_ACTIVE_BATCH = "discard_active_batch"
    CURRENT_BATCH = "current_batch"
    READ_RECORD = "read_record"
    REGISTRY_RECORD = "registry_record"
    EXPORT = "export"


Measurement: TypeAlias = Annotated[int, Field(ge=0, strict=True)]


class ProjectionEvent(_StrictEvent):
    event_type: Literal["projection"] = "projection"
    operation: ProjectionOperation
    outcome: ProjectionOutcome
    page_count: Measurement


class RetrievalEvent(_StrictEvent):
    event_type: Literal["retrieval"] = "retrieval"
    operation: RetrievalOperation
    outcome: RetrievalOutcome
    operation_count: Measurement
    result_count: Measurement


class RepairEvent(_StrictEvent):
    event_type: Literal["repair"] = "repair"
    surface: RepairSurface
    outcome: RepairOutcome
    defect_count: Measurement


class McpOutcomeEvent(_StrictEvent):
    event_type: Literal["mcp_outcome"] = "mcp_outcome"
    operation: McpOperation
    outcome: McpOutcome


class DurationEvent(_StrictEvent):
    event_type: Literal["duration"] = "duration"
    operation: DurationOperation
    duration_ms: Measurement


class CardinalityEvent(_StrictEvent):
    event_type: Literal["cardinality"] = "cardinality"
    metric: CardinalityMetric
    value: Measurement


class SerializedBytesEvent(_StrictEvent):
    event_type: Literal["serialized_bytes"] = "serialized_bytes"
    boundary: SerializedBytesBoundary
    operation: SerializedBytesOperation
    byte_count: Measurement


TelemetryEvent: TypeAlias = Annotated[
    ProjectionEvent
    | RetrievalEvent
    | RepairEvent
    | McpOutcomeEvent
    | DurationEvent
    | CardinalityEvent
    | SerializedBytesEvent,
    Field(discriminator="event_type"),
]


class EventSink(Protocol):
    """Typed destination for one privacy-safe event."""

    def emit(self, event: TelemetryEvent) -> None:
        """Accept an event; implementations should not affect application flow."""


EventSinkCallable: TypeAlias = Callable[[TelemetryEvent], None]
EventSinkLike: TypeAlias = EventSink | EventSinkCallable


class NoOpEventSink:
    """Default sink: intentionally does not retain, serialize, or persist events."""

    def emit(self, event: TelemetryEvent) -> None:
        return None


NO_OP_EVENT_SINK = NoOpEventSink()

# Upper-case aliases make the public names read naturally beside the MCP
# acronym while retaining the project's usual ``Mcp`` spelling internally.
MCPOperation = McpOperation
MCPOutcome = McpOutcome
MCPOutcomeEvent = McpOutcomeEvent
TelemetrySink = EventSink
NullTelemetrySink = NoOpEventSink


def emit_event(sink: EventSinkLike | None, event: TelemetryEvent) -> None:
    """Best-effort event delivery.

    Measurement failures are isolated from the canonical operation.  A
    callable sink is accepted as a small convenience for tests and adapters;
    production code should use the typed ``EventSink.emit`` method.
    """

    if sink is None:
        return
    try:
        sink_emit = getattr(sink, "emit", None)
        if callable(sink_emit):
            sink_emit(event)
        else:
            cast(EventSinkCallable, sink)(event)
    except Exception:
        # Telemetry is observational only.  Sink bugs must never alter the
        # scientific record or the outcome of the operation being measured.
        return None


@dataclass(frozen=True, slots=True)
class Telemetry:
    """An injectable event sink with a no-op default."""

    sink: EventSinkLike = NO_OP_EVENT_SINK

    def emit(self, event: TelemetryEvent) -> None:
        emit_event(self.sink, event)


@contextmanager
def measured_duration(
    telemetry: Telemetry | EventSinkLike | None, operation: DurationOperation
) -> Iterator[None]:
    """Emit one elapsed-duration event after a measured operation.

    The event is emitted on both success and failure, and timing itself is not
    allowed to affect the operation.  Durations are rounded down to integer
    milliseconds and are never negative.
    """

    started = perf_counter()
    try:
        yield
    finally:
        elapsed = max(0, int((perf_counter() - started) * 1000))
        event = DurationEvent(operation=operation, duration_ms=elapsed)
        if isinstance(telemetry, Telemetry):
            telemetry.emit(event)
        else:
            emit_event(telemetry, event)


__all__ = [
    "CardinalityEvent",
    "CardinalityMetric",
    "DurationEvent",
    "DurationOperation",
    "EventSink",
    "EventSinkCallable",
    "EventSinkLike",
    "MCPOutcome",
    "MCPOutcomeEvent",
    "MCPOperation",
    "McpOperation",
    "McpOutcome",
    "McpOutcomeEvent",
    "NO_OP_EVENT_SINK",
    "NoOpEventSink",
    "NullTelemetrySink",
    "ProjectionEvent",
    "ProjectionOperation",
    "ProjectionOutcome",
    "RepairEvent",
    "RepairOutcome",
    "RepairSurface",
    "RetrievalEvent",
    "RetrievalOperation",
    "RetrievalOutcome",
    "SerializedBytesBoundary",
    "SerializedBytesEvent",
    "SerializedBytesOperation",
    "Telemetry",
    "TelemetryEvent",
    "TelemetrySink",
    "emit_event",
    "measured_duration",
]

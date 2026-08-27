"""Closed public workflow names and conflict type."""

from __future__ import annotations

TOOL_NAMES = (
    "prepare_batch",
    "get_status",
    "list_sources",
    "search_sources",
    "read_pages",
    "select_text_evidence",
    "render_page",
    "select_visual_evidence",
    "save_proposal",
    "get_domain_context",
    "save_domain_judgment",
    "request_trial_terminal",
    "finalize_batch",
)
COUNTERS = {
    "extraction_calls": 0,
    "derivative_rebuilds": 0,
    "source_projection_verifications": 0,
    "database_queries": 0,
    "serialized_bytes": 0,
    "render_bytes": 0,
    "elapsed_ms": 0.0,
}


class WorkflowConflict(RuntimeError):
    def __init__(self, expected: int, actual: int) -> None:
        super().__init__(f"workflow_conflict: expected revision {expected}, current {actual}")
        self.expected, self.actual = expected, actual

"""Closed public workflow names and conflict type."""

from __future__ import annotations

TOOL_NAMES = (
    "prepare_batch",
    "get_status",
    "save_working_checkpoint",
    "list_sources",
    "search_sources",
    "search_sources_batch",
    "read_pages",
    "select_text_evidence",
    "render_page",
    "select_visual_evidence",
    "validate_proposal",
    "save_proposal",
    "request_proposal_approval",
    "get_domain_context",
    "validate_domain_assessment",
    "save_domain_judgment",
    "review_trial",
    "close_trial",
    "finalize_batch",
)
COUNTERS = {
    "extraction_calls": 0,
    "derivative_rebuilds": 0,
    "source_projection_verifications": 0,
    "database_queries": 0,
    "serialized_bytes": 0,
    "render_bytes": 0,
    "search_ranking_validations": 0,
    "elapsed_ms": 0.0,
    "source_bytes_hashed": 0,
    "projection_rows_read": 0,
    "fts_rows_read": 0,
    "search_fts_rows_built": 0,
    "candidate_reconstructions": 0,
    "response_bytes": 0,
}


def reset_counters() -> None:
    """Reset process-local observability counters for one measured run."""

    for key in COUNTERS:
        COUNTERS[key] = 0.0 if key == "elapsed_ms" else 0


def counter_snapshot() -> dict[str, int | float]:
    """Return a detached counter receipt suitable for a performance artifact."""

    return dict(COUNTERS)


class WorkflowConflict(RuntimeError):
    def __init__(self, expected: int, actual: int) -> None:
        super().__init__(f"workflow_conflict: expected revision {expected}, current {actual}")
        self.expected, self.actual = expected, actual

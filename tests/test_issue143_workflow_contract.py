"""Contract tests for question-scoped v3 triage and receipt records."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from rob2_kit.evidence.workflow import (
    IrrelevantReason,
    TriageBasis,
    V3CandidateTriageRevision,
    V3TriageKind,
)


def _triage(**changes: object) -> V3CandidateTriageRevision:
    payload = {
        "revision_id": "triage:one",
        "attempt_id": "attempt:one",
        "sq_id": "sq:test:one",
        "page_handle": "page:one",
        "candidate_id": "candidate:one",
        "kind": V3TriageKind.IRRELEVANT,
        "irrelevant_reason": IrrelevantReason.LEXICAL_FALSE_POSITIVE,
        "basis": TriageBasis.PREVIEW,
    }
    return V3CandidateTriageRevision.model_validate(payload | changes)


def test_terminal_irrelevant_triage_requires_an_explicit_basis() -> None:
    with pytest.raises(ValidationError, match="explicit basis"):
        _triage(basis=None)


def test_retained_triage_requires_and_preserves_a_read_receipt() -> None:
    with pytest.raises(ValidationError, match="read-view receipt"):
        _triage(
            kind=V3TriageKind.RETAINED,
            irrelevant_reason=None,
            basis=None,
        )
    retained = _triage(
        kind=V3TriageKind.RETAINED,
        irrelevant_reason=None,
        basis=None,
        read_view_receipt="receipt:exact-read",
    )
    assert retained.read_view_receipt == "receipt:exact-read"


def test_duplicate_triage_requires_a_distinct_retained_target() -> None:
    with pytest.raises(ValidationError, match="distinct retained target"):
        _triage(
            kind=V3TriageKind.DUPLICATE,
            irrelevant_reason=None,
            basis=None,
            retained_target_id="candidate:one",
        )


def test_triage_identity_is_bound_to_question_attempt_page_and_candidate() -> None:
    first = _triage()
    second = _triage(
        revision_id="triage:two",
        sq_id="sq:test:two",
        page_handle="page:two",
    )
    assert first.disposition_fingerprint == second.disposition_fingerprint
    assert (first.sq_id, first.page_handle) != (second.sq_id, second.page_handle)


def test_unresolved_triage_requires_an_attributable_rationale() -> None:
    with pytest.raises(ValidationError, match="requires a rationale"):
        _triage(
            kind=V3TriageKind.UNRESOLVED,
            irrelevant_reason=None,
            basis=None,
        )

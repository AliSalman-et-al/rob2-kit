"""Contract tests for the isolated v2 Search workflow reducer."""

from __future__ import annotations

import pytest

from rob2_kit.application.run_engine import _preview_is_self_contained
from rob2_kit.domain.canonical import canonical_hash
from rob2_kit.evidence.search import (
    CanonicalEvidenceUnit,
    CanonicalUnitKind,
    EvidenceSearchIndex,
    EvidenceSearchPolicy,
    EvidenceSearchTriageFlags,
    SearchQuery,
)
from rob2_kit.evidence.workflow import (
    SearchPassKind,
    V2CandidateTriageRevision,
    V2EvidenceWorkflowState,
    V2IrrelevantReason,
    V2PageExposure,
    V2QueryAttemptKind,
    V2SearchAttempt,
    V2TriageBasis,
    V2TriageKind,
    record_v2_page_exposure,
    start_v2_search_attempt,
    submit_v2_page_triage,
    supersede_v2_search_attempt,
)


def _page(index: EvidenceSearchIndex, term: str, policy: EvidenceSearchPolicy):
    return index.search_v2(SearchQuery(terms=(term,)), policy=policy)


def _state(snapshot: str, policy: EvidenceSearchPolicy) -> V2EvidenceWorkflowState:
    return V2EvidenceWorkflowState(
        result_id="result:one",
        domain_id="domain:one",
        snapshot_hash=snapshot,
        search_policy_id=policy.policy_id,
        search_policy_hash=canonical_hash(policy),
    )


def _attempt(attempt_id: str, pass_kind: SearchPassKind, term: str) -> V2SearchAttempt:
    query = SearchQuery(terms=(term,))
    return V2SearchAttempt(
        attempt_id=attempt_id,
        sq_id="sq:one",
        pass_kind=pass_kind,
        query=query,
        query_hash=canonical_hash(query),
        kind=V2QueryAttemptKind.SELECTED,
    )


def test_v2_workflow_preserves_exposure_edges_and_round_trips(tmp_path) -> None:
    index = EvidenceSearchIndex(tmp_path / "workflow.sqlite3")
    snapshot = index.replace_units(
        (
            CanonicalEvidenceUnit(
                unit_id="unit:report-1",
                source_id="source:report",
                source_artifact_hash=canonical_hash({"source": 1}),
                parse_id="parse:report",
                page=1,
                kind=CanonicalUnitKind.PARAGRAPH,
                text="Alpha beta gamma source-authored evidence.",
                fragment_ids=("fragment:report-1",),
            ),
        )
    )
    policy = EvidenceSearchPolicy()
    state = _state(snapshot, policy)
    attempts = (
        _attempt("attempt:alpha", SearchPassKind.GUIDANCE_SEED, "alpha"),
        _attempt("attempt:beta", SearchPassKind.TRIAL_FOLLOW_UP, "beta"),
        _attempt("attempt:gamma", SearchPassKind.CONTRADICTION, "gamma"),
    )
    pages = tuple(_page(index, term, policy) for term in ("alpha", "beta", "gamma"))
    for attempt, page in zip(attempts, pages, strict=True):
        state = start_v2_search_attempt(state, attempt)
        state = record_v2_page_exposure(state, attempt_id=attempt.attempt_id, page=page)

    candidate_id = pages[0].candidate_ids[0]
    assert len(state.exposures) == 3
    assert {edge.candidate_id for edge in state.exposures} == {candidate_id}
    revisions = tuple(
        V2CandidateTriageRevision(
            revision_id=f"triage:{attempt.attempt_id}",
            candidate_id=candidate_id,
            attempt_id=attempt.attempt_id,
            sq_id=attempt.sq_id,
            page_handle=page.page_handle,
            kind=V2TriageKind.IRRELEVANT,
            irrelevant_reason=V2IrrelevantReason.LEXICAL_FALSE_POSITIVE,
            basis=V2TriageBasis.PREVIEW,
        )
        for attempt, page in zip(attempts, pages, strict=True)
    )
    state = submit_v2_page_triage(
        state,
        submission_id="submission:one",
        page_handles=tuple(page.page_handle for page in pages),
        revisions=revisions,
    )
    replay = submit_v2_page_triage(
        state,
        submission_id="submission:one",
        page_handles=tuple(page.page_handle for page in pages),
        revisions=revisions,
    )
    restored = V2EvidenceWorkflowState.model_validate_json(state.model_dump_json())
    assert replay == state == restored
    assert replay.content_hash == restored.content_hash
    assert state.coverage_complete() and state.freeze_valid()


def test_v2_workflow_requires_explicit_supersession_and_closed_triage(tmp_path) -> None:
    policy = EvidenceSearchPolicy()
    state = _state(canonical_hash({"snapshot": 1}), policy)
    old = _attempt("attempt:old", SearchPassKind.GUIDANCE_SEED, "alpha")
    state = start_v2_search_attempt(state, old)
    replacement = _attempt("attempt:new", SearchPassKind.GUIDANCE_SEED, "delta")
    state = supersede_v2_search_attempt(
        state,
        old_attempt_id=old.attempt_id,
        replacement=replacement,
        rationale="A narrower synonym preserves the intended lexical variant.",
    )
    assert state.attempts[0].kind is V2QueryAttemptKind.SUPERSEDED
    assert state.attempts[1].supersedes_attempt_id == old.attempt_id
    with pytest.raises(ValueError, match="other irrelevant"):
        V2CandidateTriageRevision(
            revision_id="triage:bad",
            candidate_id="candidate:one",
            attempt_id="attempt:one",
            sq_id="sq:one",
            page_handle="v2page:one",
            kind=V2TriageKind.IRRELEVANT,
            irrelevant_reason=V2IrrelevantReason.OTHER,
            basis=V2TriageBasis.PREVIEW,
        )


def test_v2_terminal_irrelevant_triage_requires_an_explicit_basis() -> None:
    with pytest.raises(ValueError, match="explicit preview or read receipt basis"):
        V2CandidateTriageRevision(
            revision_id="triage:missing-basis",
            candidate_id="candidate:one",
            attempt_id="attempt:one",
            sq_id="sq:one",
            page_handle="v2page:one",
            kind=V2TriageKind.IRRELEVANT,
            irrelevant_reason=V2IrrelevantReason.LEXICAL_FALSE_POSITIVE,
        )


def test_v2_triage_is_bound_to_each_sq_page_occurrence(tmp_path) -> None:
    index = EvidenceSearchIndex(tmp_path / "sq-occurrence.sqlite3")
    snapshot = index.replace_units(
        (
            CanonicalEvidenceUnit(
                unit_id="unit:shared",
                source_id="source:one",
                source_artifact_hash=canonical_hash({"source": 1}),
                parse_id="parse:one",
                page=1,
                kind=CanonicalUnitKind.PARAGRAPH,
                text="alpha beta source-authored evidence",
                fragment_ids=("fragment:one",),
            ),
        )
    )
    policy = EvidenceSearchPolicy()
    state = _state(snapshot, policy)
    attempts = (
        V2SearchAttempt(
            attempt_id="attempt:alpha",
            sq_id="sq:alpha",
            pass_kind=SearchPassKind.GUIDANCE_SEED,
            query=SearchQuery(terms=("alpha",)),
            query_hash=canonical_hash(SearchQuery(terms=("alpha",))),
            kind=V2QueryAttemptKind.SELECTED,
        ),
        V2SearchAttempt(
            attempt_id="attempt:beta",
            sq_id="sq:beta",
            pass_kind=SearchPassKind.GUIDANCE_SEED,
            query=SearchQuery(terms=("beta",)),
            query_hash=canonical_hash(SearchQuery(terms=("beta",))),
            kind=V2QueryAttemptKind.SELECTED,
        ),
    )
    pages = (_page(index, "alpha", policy), _page(index, "beta", policy))
    for attempt, page in zip(attempts, pages, strict=True):
        state = start_v2_search_attempt(state, attempt)
        state = record_v2_page_exposure(state, attempt_id=attempt.attempt_id, page=page)
    candidate_id = pages[0].candidate_ids[0]
    revisions = tuple(
        V2CandidateTriageRevision(
            revision_id=f"triage:{attempt.sq_id}",
            candidate_id=candidate_id,
            attempt_id=attempt.attempt_id,
            sq_id=attempt.sq_id,
            page_handle=page.page_handle,
            kind=(
                V2TriageKind.RETAINED
                if attempt.sq_id == "sq:alpha"
                else V2TriageKind.IRRELEVANT
            ),
            irrelevant_reason=(
                None if attempt.sq_id == "sq:alpha" else V2IrrelevantReason.LEXICAL_FALSE_POSITIVE
            ),
            basis=(None if attempt.sq_id == "sq:alpha" else V2TriageBasis.PREVIEW),
        )
        for attempt, page in zip(attempts, pages, strict=True)
    )
    state = submit_v2_page_triage(
        state,
        submission_id="submission:sq-pages",
        page_handles=tuple(page.page_handle for page in pages),
        revisions=revisions,
    )
    assert state.outstanding_triage_candidate_ids() == ()


def _preview_edge(**changes: object) -> V2PageExposure:
    payload: dict[str, object] = {
        "attempt_id": "attempt:one",
        "page_handle": "v2page:one",
        "candidate_id": "candidate:one",
        "canonical_unit_id": "unit:one",
        "location_handle": "loc:one",
        "source_id": "source:one",
        "source_artifact_hash": canonical_hash({"source": 1}),
        "parse_id": "parse:one",
        "canonical_start": 0,
        "canonical_end": 10,
        "left_omitted_character_count": 0,
        "right_omitted_character_count": 0,
        "undisplayed_match_count": 0,
        "triage_flags": EvidenceSearchTriageFlags(),
        "page_number": 1,
        "total_page_count": 1,
        "traversal_complete": True,
    }
    return V2PageExposure.model_validate(payload | changes)


@pytest.mark.parametrize(
    ("change", "value"),
    (
        ("left_omitted_character_count", 1),
        ("right_omitted_character_count", 1),
        ("undisplayed_match_count", 1),
        ("warnings", ("parser_warning",)),
        ("table_headers", ("Allocation",)),
        ("caption", "Table 2"),
        ("triage_flags", EvidenceSearchTriageFlags(has_reading_order_uncertainty=True)),
        ("triage_flags", EvidenceSearchTriageFlags(has_visual_uncertainty=True)),
        ("triage_flags", EvidenceSearchTriageFlags(has_duplicate_lineage=True)),
        ("triage_flags", EvidenceSearchTriageFlags(is_table_content=True)),
        ("triage_flags", EvidenceSearchTriageFlags(has_context_dependency=True)),
        ("triage_flags", EvidenceSearchTriageFlags(has_possible_contradiction=True)),
    ),
)
def test_preview_only_irrelevant_requires_receipt_for_every_objective_risk(
    change: str, value: object
) -> None:
    assert not _preview_is_self_contained(_preview_edge(**{change: value}))


def test_preview_only_irrelevant_permits_a_complete_unambiguous_preview() -> None:
    assert _preview_is_self_contained(_preview_edge())

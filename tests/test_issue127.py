"""Question-scoped coverage recorder regressions (#127/#128, migrated to v3)."""

from rob2_kit.application.evidence_runtime import V3EvidencePageTriageRequest
from tests.test_issue167_runtime import _outcome, _request, _runtime


def test_terminal_v3_search_receipts_are_recorded_per_question_before_answering(tmp_path) -> None:
    runtime, _, source_ids, _ = _runtime(tmp_path)
    initial = runtime.initialize()
    seed = runtime.search_page(_request(initial.content_hash, source_ids=source_ids))
    seed_triage = runtime.submit_page_triage(
        V3EvidencePageTriageRequest(
            expected_content_hash=seed.state.content_hash,
            submission_id="triage:issue127:seed",
            attempt_id="attempt:runtime:seed",
            page_handles=("page:1",),
            revisions=(),
        )
    )
    seed_closed = runtime.submit_stage_outcome(
        expected_content_hash=seed_triage.state.content_hash,
        submission=_outcome(seed_triage.state.workflow, "stage:runtime:seed"),
    )
    contradiction = runtime.search_page(
        _request(
            seed_closed.state.content_hash,
            stage="stage:runtime:contradiction",
            intent="intent:runtime:contradiction",
        )
    )
    contradiction_triage = runtime.submit_page_triage(
        V3EvidencePageTriageRequest(
            expected_content_hash=contradiction.state.content_hash,
            submission_id="triage:issue127:contradiction",
            attempt_id="attempt:runtime:contradiction",
            page_handles=("page:2",),
            revisions=(),
        )
    )
    closed = runtime.submit_stage_outcome(
        expected_content_hash=contradiction_triage.state.content_hash,
        submission=_outcome(contradiction_triage.state.workflow, "stage:runtime:contradiction"),
    )

    assert closed.progress["question_ready"] is True
    assert {receipt.stage_id for receipt in closed.state.workflow.stage_outcomes} == {
        "stage:runtime:seed",
        "stage:runtime:contradiction",
    }


def test_empty_materialized_scope_is_audited_without_an_unscoped_search(tmp_path) -> None:
    runtime, search, _, _ = _runtime(tmp_path, source_count=0)
    initial = runtime.initialize()
    result = runtime.search_page(_request(initial.content_hash, source_ids=()))

    assert result.blockers == ("materialized_source_scope_empty",)
    assert not search.calls

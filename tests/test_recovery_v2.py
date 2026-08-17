from datetime import UTC, datetime
from pathlib import Path

import pytest
from v2_helpers import approved_two_trial_workspace, approved_workspace, domain_operation

from rob2_kit.batch import ApprovedBatch, current_batch
from rob2_kit.batch_summary import FinalizationSuccess, finalize_batch_v2
from rob2_kit.detail import read_record
from rob2_kit.finish import ProblemFinishOperation, finish_problem_v2
from rob2_kit.ingestion import read_captured_batch
from rob2_kit.judgment_models import DomainDraftCommitOperation, DomainDraftValidated
from rob2_kit.judgments import (
    commit_domain_draft,
    judgment_key,
    revision_index_key,
    validate_domain_draft,
)
from rob2_kit.recovery import (
    DiscardActiveBatchRequest,
    current_batch_projection,
    discard_active_batch,
)

NOW = datetime(2026, 8, 14, tzinfo=UTC)


def test_recovery_never_returns_missing_approved_detail_reference(tmp_path: Path) -> None:
    workspace, _source = approved_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    from rob2_kit.storage import transaction

    with transaction(workspace) as connection:
        connection.execute(
            "DELETE FROM records WHERE name=?", (f"detail:batch:{approved.frozen_hash}",)
        )
    projection = current_batch_projection(workspace)
    assert projection.phase == "stale"
    assert projection.approved_batch_ref is None
    assert "Approved Batch Detail" in projection.conditions[0].detail


@pytest.mark.parametrize("phase", ["intake", "proposal", "approved", "partial", "terminal"])
@pytest.mark.parametrize("corruption", ["missing", "corrupt"])
def test_captured_detail_corruption_suppresses_all_dependent_recovery_refs(
    tmp_path: Path, phase: str, corruption: str
) -> None:
    workspace, source = approved_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    from rob2_kit.storage import transaction

    if phase == "intake":
        with transaction(workspace) as connection:
            connection.execute("DELETE FROM records WHERE name='active_batch'")
            connection.execute("DELETE FROM runtime_meta WHERE name='active_proposal_version'")
    elif phase == "proposal":
        with transaction(workspace) as connection:
            connection.execute("DELETE FROM records WHERE name='active_batch'")
    elif phase == "partial":
        operation = domain_operation(workspace, source, approved, "domain:randomization")
        validated = validate_domain_draft(workspace, operation)
        assert isinstance(validated, DomainDraftValidated)
        assert (
            commit_domain_draft(
                workspace,
                DomainDraftCommitOperation(
                    **operation.model_dump(),
                    validation_receipt=validated.receipt,
                    reviewed_candidate_hash=validated.candidate_hash,
                ),
            ).status
            == "committed"
        )
    elif phase == "terminal":
        assert (
            finish_problem_v2(
                workspace,
                ProblemFinishOperation(
                    approved_batch_hash=approved.frozen_hash,
                    trial_id="t",
                    result_id="r",
                    category="failed",
                    actor="finisher",
                    problems=({"code": "stop", "detail": "Terminal problem."},),
                ),
            ).status
            == "committed"
        )
    captured = read_captured_batch(workspace)
    assert captured is not None
    key = f"detail:batch:{captured.content_hash}"
    with transaction(workspace) as connection:
        if corruption == "missing":
            connection.execute("DELETE FROM records WHERE name=?", (key,))
        else:
            connection.execute("UPDATE records SET payload=? WHERE name=?", (b"{}", key))
    projection = current_batch_projection(workspace)
    assert projection.phase == "stale"
    assert projection.captured_batch_ref is None
    assert projection.proposal_ref is None
    assert projection.approved_batch_ref is None
    assert projection.summary_ref is None
    assert projection.trials == ()


def test_recovery_rejects_active_checkpoint_without_any_revision_history(
    tmp_path: Path,
) -> None:
    workspace, source = approved_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    operation = domain_operation(workspace, source, approved, "domain:randomization")
    validated = validate_domain_draft(workspace, operation)
    assert isinstance(validated, DomainDraftValidated)
    committed = commit_domain_draft(
        workspace,
        DomainDraftCommitOperation(
            **operation.model_dump(),
            validation_receipt=validated.receipt,
            reviewed_candidate_hash=validated.candidate_hash,
        ),
    )
    assert committed.status == "committed"
    active_key = judgment_key(approved.frozen_hash, "t", "r", "domain:randomization")
    from rob2_kit.storage import transaction

    with transaction(workspace) as connection:
        connection.execute("DELETE FROM records WHERE name=?", (revision_index_key(active_key),))
        connection.execute("DELETE FROM records WHERE name LIKE 'domain_judgment_revision:%'")
    projection = current_batch_projection(workspace)
    assert projection.phase == "stale"
    assert "revision history is missing its index" in projection.conditions[0].detail


def test_duplicate_result_ids_remain_trial_scoped_through_finalization(tmp_path: Path) -> None:
    workspace, _source_a, source_b = approved_two_trial_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    projection = current_batch_projection(workspace)
    progress_b = next(item for item in projection.trials if item.trial_id == "b")
    assert progress_b.recommended_packet_ref is not None

    operation = domain_operation(
        workspace,
        source_b,
        approved,
        "domain:randomization",
        trial_id="b",
        result_id="result",
    )
    validated = validate_domain_draft(workspace, operation)
    assert isinstance(validated, DomainDraftValidated)
    committed = commit_domain_draft(
        workspace,
        DomainDraftCommitOperation(
            **operation.model_dump(),
            validation_receipt=validated.receipt,
            reviewed_candidate_hash=validated.candidate_hash,
        ),
    )
    assert committed.status == "committed"
    assert committed.trial_id == "b"

    for trial_id in ("a", "b"):
        terminal = finish_problem_v2(
            workspace,
            ProblemFinishOperation(
                approved_batch_hash=approved.frozen_hash,
                trial_id=trial_id,
                result_id="result",
                category="needs_input",
                actor="terminal",
                problems=({"code": "missing", "detail": f"Input required for {trial_id}."},),
            ),
        )
        assert terminal.status == "committed"
        assert terminal.trial_id == trial_id
    finalized = finalize_batch_v2(workspace, "finalizer")
    assert isinstance(finalized, FinalizationSuccess)
    assert tuple(item.trial_id for item in finalized.outcomes) == ("a", "b")
    assert current_batch_projection(workspace).phase == "finalized"


def test_compact_finalization_reuses_summary_and_exposes_only_refs(tmp_path: Path) -> None:
    workspace, _source = approved_workspace(tmp_path)
    projection = current_batch_projection(workspace)
    assert projection.approved_batch_ref is not None
    for trial_id, result_id in (("t", "r"),):
        result = finish_problem_v2(
            workspace,
            ProblemFinishOperation(
                approved_batch_hash=projection.approved_batch_ref.identity,
                trial_id=trial_id,
                result_id=result_id,
                category="needs_input",
                actor="terminal",
                problems=({"code": f"code-{trial_id}", "detail": f"detail-{trial_id}"},),
            ),
        )
        assert result.status == "committed"
    first = finalize_batch_v2(workspace, "finalizer")
    assert isinstance(first, FinalizationSuccess)
    assert first.summary_ref.kind == "batch"
    assert len(first.outcomes) == 1
    assert "summary" not in first.model_fields_set
    summary = read_record(workspace, first.summary_ref)
    assert isinstance(summary, dict)
    assert summary["summary_hash"] == first.summary_ref.identity
    assert finalize_batch_v2(workspace, "different-retry") == first
    assert current_batch_projection(workspace).phase == "finalized"


def test_discard_removes_derivative_projection_store_but_preserves_bundle_residue(
    tmp_path: Path,
) -> None:
    workspace, _source = approved_workspace(tmp_path)
    internal = workspace / ".rob2-kit"
    projection = internal / "text-projections.sqlite3"
    assert projection.exists()
    journals = (
        internal / "active-batch.sqlite3-journal",
        internal / "text-projections.sqlite3-journal",
    )
    for journal in journals:
        journal.write_bytes(b"")
    bundle = workspace / "exports" / "preserved.txt"
    bundle.parent.mkdir()
    bundle.write_text("keep")
    state = current_batch_projection(workspace)
    assert state.approved_batch_ref is not None
    result = discard_active_batch(
        workspace,
        DiscardActiveBatchRequest(
            expected_frozen_hash=state.approved_batch_ref.identity,
            confirmation="I_UNDERSTAND_THIS_DISCARDS_THE_ACTIVE_BATCH",
            actor="researcher",
            observed_at=NOW,
            reason="Explicit discard for recovery.",
        ),
    )
    assert result.status == "discarded"
    assert not projection.exists()
    assert all(not journal.exists() for journal in journals)
    assert bundle.read_text() == "keep"

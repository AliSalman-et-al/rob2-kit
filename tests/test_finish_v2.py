from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pytest
from v2_helpers import approved_workspace, completed_workspace, domain_operation

from rob2_kit.batch import ApprovedBatch, current_batch
from rob2_kit.batch_summary import (
    BatchSaved,
    Counts,
    FailedEntry,
    FinalizationSuccess,
    finalize_batch,
    finalize_batch_v2,
    summary_content,
)
from rob2_kit.detail import detail_reference, read_record
from rob2_kit.finish import (
    AssessmentFinishOperation,
    AssessmentFinishSuccess,
    ProblemFinishOperation,
    ProblemFinishSuccess,
    finish_assessment_v2,
    finish_problem_v2,
)
from rob2_kit.judgment_models import DomainDraftCommitOperation, DomainDraftValidated
from rob2_kit.judgments import (
    commit_domain_draft,
    judgment_key,
    revision_index_key,
    validate_domain_draft,
)
from rob2_kit.models import canonical_json_bytes, sha256
from rob2_kit.packs import SCIENTIFIC_PACK
from rob2_kit.recovery import current_batch_projection


def _reviewed_hash(workspace: Path, approved: ApprovedBatch) -> str:
    projection = current_batch_projection(workspace)
    progress = next(item for item in projection.trials if item.trial_id == "t")
    assert progress.synthesis_ref is not None
    return progress.synthesis_ref.identity


def test_assessment_finish_requires_exact_synthesis_and_retries_compactly(
    tmp_path: Path,
) -> None:
    workspace, _source = completed_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    synthesis_hash = _reviewed_hash(workspace, approved)
    operation = AssessmentFinishOperation(
        approved_batch_hash=approved.frozen_hash,
        trial_id="t",
        result_id="r",
        reviewed_synthesis_hash=synthesis_hash,
        actor="finisher",
    )
    first = finish_assessment_v2(workspace, operation)
    assert isinstance(first, AssessmentFinishSuccess)
    retry = finish_assessment_v2(workspace, operation)
    assert retry == first
    assert "domain_judgments" not in first.model_dump_json()


def test_synthesis_detail_remains_available_until_batch_finalization(
    tmp_path: Path,
) -> None:
    workspace, _source = completed_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    synthesis_ref = detail_reference("synthesis", _reviewed_hash(workspace, approved))
    assert read_record(workspace, synthesis_ref)
    finished = finish_problem_v2(
        workspace,
        ProblemFinishOperation(
            approved_batch_hash=approved.frozen_hash,
            trial_id="t",
            result_id="r",
            category="needs_input",
            actor="finisher",
            problems=({"code": "missing", "detail": "More information is required."},),
        ),
    )
    assert isinstance(finished, ProblemFinishSuccess)
    assert read_record(workspace, synthesis_ref)
    assert isinstance(finalize_batch_v2(workspace, "finalizer"), FinalizationSuccess)
    assert current_batch_projection(workspace).trials[0].synthesis_ref is None
    with pytest.raises(ValueError, match="availability window"):
        read_record(workspace, synthesis_ref)


def test_assessed_recovery_regenerates_exact_missing_synthesis_and_rejects_corruption(
    tmp_path: Path,
) -> None:
    workspace, _source = completed_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    synthesis_ref = current_batch_projection(workspace).trials[0].synthesis_ref
    assert synthesis_ref is not None
    operation = AssessmentFinishOperation(
        approved_batch_hash=approved.frozen_hash,
        trial_id="t",
        result_id="r",
        reviewed_synthesis_hash=synthesis_ref.identity,
        actor="finisher",
    )
    assert isinstance(finish_assessment_v2(workspace, operation), AssessmentFinishSuccess)
    from rob2_kit.storage import transaction

    key = f"detail:synthesis:{synthesis_ref.identity}"
    with transaction(workspace) as connection:
        connection.execute("DELETE FROM records WHERE name=?", (key,))
    restarted = current_batch_projection(workspace)
    assert restarted.phase == "mixed_terminal"
    assert restarted.trials[0].synthesis_ref == synthesis_ref
    assert read_record(workspace, synthesis_ref)

    with transaction(workspace) as connection:
        connection.execute("UPDATE records SET payload=? WHERE name=?", (b"{}", key))
    corrupt = current_batch_projection(workspace)
    assert corrupt.phase == "stale"
    assert "invalid packet record" in corrupt.conditions[0].detail


def test_problem_finish_is_compact_and_idempotent(tmp_path: Path) -> None:
    workspace, _source = completed_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    operation = ProblemFinishOperation(
        approved_batch_hash=approved.frozen_hash,
        trial_id="t",
        result_id="r",
        category="needs_input",
        actor="finisher",
        problems=({"code": "missing", "detail": "More information is required."},),
    )
    first = finish_problem_v2(workspace, operation)
    assert isinstance(first, ProblemFinishSuccess)
    assert finish_problem_v2(workspace, operation) == first
    assert "problems" not in first.model_dump_json()


@pytest.mark.parametrize("category", ["needs_input", "failed"])
def test_partial_problem_terminal_clears_all_work_packet_refs(
    tmp_path: Path, category: Literal["needs_input", "failed"]
) -> None:
    workspace, _source = approved_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    old_work_ref = current_batch_projection(workspace).trials[0].recommended_packet_ref
    assert old_work_ref is not None
    result = finish_problem_v2(
        workspace,
        ProblemFinishOperation(
            approved_batch_hash=approved.frozen_hash,
            trial_id="t",
            result_id="r",
            category=category,
            actor="finisher",
            problems=({"code": "stop", "detail": "Terminal problem."},),
        ),
    )
    assert isinstance(result, ProblemFinishSuccess)
    progress = current_batch_projection(workspace).trials[0]
    assert progress.recommended_packet_ref is None
    assert progress.correction_packet_refs == ()
    assert progress.synthesis_ref is None
    with pytest.raises(ValueError, match="stale"):
        read_record(workspace, old_work_ref)


@pytest.mark.parametrize("completed_count", [1, 2, 3, 4])
def test_problem_finish_verifies_every_partial_revision_before_write(
    tmp_path: Path, completed_count: int
) -> None:
    workspace, source = approved_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    for domain in SCIENTIFIC_PACK.domains[:completed_count]:
        operation = domain_operation(workspace, source, approved, domain.id)
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
    from rob2_kit.storage import transaction

    active_key = judgment_key(
        approved.frozen_hash, "t", "r", SCIENTIFIC_PACK.domains[completed_count - 1].id
    )
    with transaction(workspace) as connection:
        connection.execute("DELETE FROM records WHERE name=?", (revision_index_key(active_key),))
    result = finish_problem_v2(
        workspace,
        ProblemFinishOperation(
            approved_batch_hash=approved.frozen_hash,
            trial_id="t",
            result_id="r",
            category="failed",
            actor="finisher",
            problems=({"code": "stop", "detail": "Terminal problem."},),
        ),
    )
    assert result.status == "condition"
    assert result.code == "checkpoint_invalid"
    with transaction(workspace) as connection:
        assert (
            connection.execute(
                "SELECT 1 FROM records WHERE name=?",
                (f"terminal_trial:{approved.frozen_hash}:t",),
            ).fetchone()
            is None
        )


@pytest.mark.parametrize("category", ["needs_input", "failed"])
def test_five_domain_problem_terminal_binds_regenerable_synthesis_until_finalization(
    tmp_path: Path, category: Literal["needs_input", "failed"]
) -> None:
    workspace, _source = completed_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    synthesis_ref = current_batch_projection(workspace).trials[0].synthesis_ref
    assert synthesis_ref is not None
    result = finish_problem_v2(
        workspace,
        ProblemFinishOperation(
            approved_batch_hash=approved.frozen_hash,
            trial_id="t",
            result_id="r",
            category=category,
            actor="finisher",
            problems=({"code": "stop", "detail": "Terminal problem."},),
        ),
    )
    assert isinstance(result, ProblemFinishSuccess)
    terminal = read_record(workspace, result.terminal_ref)
    assert isinstance(terminal, dict)
    assert terminal["synthesis_hash"] == synthesis_ref.identity
    from rob2_kit.storage import transaction

    key = f"detail:synthesis:{synthesis_ref.identity}"
    with transaction(workspace) as connection:
        row = connection.execute("SELECT payload FROM records WHERE name=?", (key,)).fetchone()
        assert row is not None
        payload = bytes(row[0])
        if category == "needs_input":
            connection.execute("DELETE FROM records WHERE name=?", (key,))
        else:
            connection.execute("UPDATE records SET payload=? WHERE name=?", (b"{}", key))
    recovered = current_batch_projection(workspace)
    if category == "failed":
        assert recovered.phase == "stale"
        with transaction(workspace) as connection:
            connection.execute("UPDATE records SET payload=? WHERE name=?", (payload, key))
        recovered = current_batch_projection(workspace)
    assert recovered.trials[0].synthesis_ref == synthesis_ref
    assert recovered.trials[0].recommended_packet_ref is None
    assert recovered.trials[0].correction_packet_refs == ()
    assert read_record(workspace, synthesis_ref)
    assert isinstance(finalize_batch_v2(workspace, "finalizer"), FinalizationSuccess)
    assert current_batch_projection(workspace).trials[0].synthesis_ref is None
    with pytest.raises(ValueError, match="availability window"):
        read_record(workspace, synthesis_ref)


def test_finalization_rejects_coherently_rehashed_swapped_problem_category(
    tmp_path: Path,
) -> None:
    workspace, _source = approved_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    assert isinstance(
        finish_problem_v2(
            workspace,
            ProblemFinishOperation(
                approved_batch_hash=approved.frozen_hash,
                trial_id="t",
                result_id="r",
                category="needs_input",
                actor="finisher",
                problems=({"code": "stop", "detail": "Terminal problem."},),
            ),
        ),
        ProblemFinishSuccess,
    )
    saved = finalize_batch(workspace, "finalizer", datetime(2026, 8, 16, tzinfo=UTC))
    assert isinstance(saved, BatchSaved)
    swapped_entry = FailedEntry.model_validate(
        {**saved.summary.entries[0].model_dump(), "status": "failed"}
    )
    incomplete = saved.summary.model_copy(
        update={
            "entries": (swapped_entry,),
            "counts": Counts(assessed=0, needs_input=0, failed=1),
            "summary_hash": "pending",
        }
    )
    swapped = incomplete.model_copy(update={"summary_hash": sha256(summary_content(incomplete))})
    from rob2_kit.storage import transaction

    with transaction(workspace) as connection:
        connection.execute(
            "UPDATE records SET payload=? WHERE name=?",
            (canonical_json_bytes(swapped), f"batch_summary:{approved.frozen_hash}"),
        )
    result = finalize_batch_v2(workspace, "retry")
    assert result.status == "condition"
    assert not (workspace / ".rob2-kit" / "batches").exists()
    assert current_batch_projection(workspace).phase == "stale"


def test_finish_and_recovery_each_verify_source_projection_once(
    tmp_path: Path, monkeypatch
) -> None:
    workspace, _source = completed_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    from rob2_kit import text_projection

    calls = 0
    original = text_projection.verified_pages

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(text_projection, "verified_pages", counted)
    finished = finish_problem_v2(
        workspace,
        ProblemFinishOperation(
            approved_batch_hash=approved.frozen_hash,
            trial_id="t",
            result_id="r",
            category="needs_input",
            actor="finisher",
            problems=({"code": "missing", "detail": "Input required."},),
        ),
    )
    assert isinstance(finished, ProblemFinishSuccess)
    assert calls == 1
    calls = 0
    assert current_batch_projection(workspace).phase == "mixed_terminal"
    assert calls == 1

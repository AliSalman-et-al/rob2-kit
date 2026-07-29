from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from rob2_kit.application.preparation import (
    AutonomousPreparation,
    DraftReady,
    IncompleteReason,
    PreparationIncomplete,
    PreparationPlan,
    PreparationStep,
    SubmissionKind,
    TrialFailed,
    TrialFailureReason,
    WorkSubmission,
)
from rob2_kit.domain.revisions import Actor, ActorKind, RecordReference
from rob2_kit.storage import ArtifactStore, WorkflowLedger

NOW = datetime(2026, 7, 29, 12, tzinfo=UTC)
ACTOR = Actor(kind=ActorKind.AGENT, actor_id="actor:test-agent", display_name="Test agent")
HASH = "sha256:" + "a" * 64


def plan(scope: str) -> PreparationPlan:
    return PreparationPlan(
        scope=scope,
        trial_id=scope.replace("scope:", "trial:"),
        steps=(
            PreparationStep(
                step_id="step:search",
                operation="operation:search",
                checkpoint="checkpoint:search",
                submission_kind=SubmissionKind.SEARCH_COVERAGE,
            ),
            PreparationStep(
                step_id="step:assessment",
                operation="operation:assessment",
                checkpoint="checkpoint:assessment",
                submission_kind=SubmissionKind.ASSESSMENT,
            ),
        ),
    )


def protocol(tmp_path: Path, *plans: PreparationPlan) -> AutonomousPreparation:
    ledger = WorkflowLedger(tmp_path / "ledger.sqlite3", ArtifactStore(tmp_path / "artifacts"))
    lease = ledger.acquire_lease("process:test", NOW, timedelta(minutes=5))
    return AutonomousPreparation(ledger, lease, ACTOR, plans)


def submission(
    work_item,
    revision: str,
    *,
    outcome: str = "completed",
    terminal_outcome=None,
) -> WorkSubmission:
    return WorkSubmission(
        work_item_id=work_item.work_item_id,
        operation_key=f"operation-key:{revision}",
        expected_dependency_fingerprint=work_item.dependency_fingerprint,
        submission_kind=work_item.submission_kind,
        entity_id=f"entity:{revision}",
        revision_id=f"revision:{revision}",
        artifact=b'{"ok":true}',
        artifact_media_type="application/json",
        outcome=outcome,
        terminal_outcome=terminal_outcome,
    )


def test_protocol_derives_exact_next_item_and_resumes_after_reopen(tmp_path: Path) -> None:
    first = protocol(tmp_path, plan("scope:a"))
    search = first.next_work_item("scope:a")
    assert search is not None
    assert search.step_id == "step:search"
    assert search.submission_kind is SubmissionKind.SEARCH_COVERAGE

    first.submit(search, submission(search, "search-a"), now=NOW)

    reopened_ledger = WorkflowLedger(first.ledger.path, first.ledger.artifacts)
    reopened = AutonomousPreparation(reopened_ledger, first.lease, ACTOR, (plan("scope:a"),))
    assessment = reopened.next_work_item("scope:a")
    assert assessment is not None
    assert assessment.step_id == "step:assessment"


def test_committed_submission_is_reused_idempotently(tmp_path: Path) -> None:
    coordinator = protocol(tmp_path, plan("scope:a"))
    item = coordinator.next_work_item("scope:a")
    assert item is not None
    request = submission(item, "search-a")

    first = coordinator.submit(item, request, now=NOW)
    second = coordinator.submit(item, request, now=NOW)

    assert first.operation_id == second.operation_id
    assert second.duplicate is True
    assert len(coordinator.ledger.events()) == 1


def test_operation_key_cannot_be_reused_for_different_work(tmp_path: Path) -> None:
    coordinator = protocol(tmp_path, plan("scope:a"))
    item = coordinator.next_work_item("scope:a")
    assert item is not None
    request = submission(item, "search-a")
    coordinator.submit(item, request, now=NOW)

    with pytest.raises(ValueError, match="different work submission"):
        coordinator.submit(
            item,
            request.model_copy(
                update={"entity_id": "entity:other", "revision_id": "revision:other"}
            ),
            now=NOW,
        )


def test_draft_ready_requires_the_submitted_assessment(tmp_path: Path) -> None:
    coordinator = protocol(tmp_path, plan("scope:a"))
    search = coordinator.next_work_item("scope:a")
    assert search is not None

    with pytest.raises(ValueError, match="assessment submission"):
        coordinator.submit(
            search,
            submission(
                search,
                "premature",
                outcome="preparation_outcome_reached",
                terminal_outcome=DraftReady(
                    assessment=RecordReference(
                        entity_id="entity:premature",
                        revision_id="revision:premature",
                        content_hash=HASH,
                    )
                ),
            ),
            now=NOW,
        )


def test_all_terminal_outcomes_stop_only_the_affected_trial(tmp_path: Path) -> None:
    coordinator = protocol(tmp_path, plan("scope:a"), plan("scope:b"), plan("scope:c"))
    for scope in ("scope:a", "scope:b"):
        item = coordinator.next_work_item(scope)
        assert item is not None
        coordinator.submit(item, submission(item, f"search-{scope[-1]}"), now=NOW)
    assessment = coordinator.next_work_item("scope:a")
    incomplete = coordinator.next_work_item("scope:b")
    failed = coordinator.next_work_item("scope:c")
    assert assessment is not None and incomplete is not None and failed is not None
    coordinator.submit(
        assessment,
        submission(
            assessment,
            "assessment-a",
            outcome="preparation_outcome_reached",
            terminal_outcome=DraftReady(
                assessment=RecordReference(
                    entity_id="entity:assessment-a",
                    revision_id="revision:assessment-a",
                    content_hash=HASH,
                )
            ),
        ),
        now=NOW,
    )
    coordinator.submit(
        incomplete,
        submission(
            incomplete,
            "incomplete-b",
            outcome="preparation_outcome_reached",
            terminal_outcome=PreparationIncomplete(
                result_spec=RecordReference(
                    entity_id="result-spec:b",
                    revision_id="revision:result-spec-b",
                    content_hash=HASH,
                ),
                reason=IncompleteReason.MATERIAL_EVIDENCE_GAP,
                detail="Material evidence remains unresolved.",
            ),
        ),
        now=NOW,
    )
    coordinator.submit(
        failed,
        submission(
            failed,
            "failed-c",
            outcome="preparation_outcome_reached",
            terminal_outcome=TrialFailed(
                trial_id="trial:c",
                reason=TrialFailureReason.REQUIRED_PRIMARY_UNRECOVERABLE,
                detail="Bounded recovery was exhausted.",
            ),
        ),
        now=NOW,
    )

    expected = {
        "scope:a": "draft_ready",
        "scope:b": "preparation_incomplete",
        "scope:c": "trial_failed",
    }
    assert coordinator.batch_status() == expected
    assert all(coordinator.next_work_item(scope) is None for scope in expected)


def test_retryable_interruption_is_not_a_checkpoint_or_finding(tmp_path: Path) -> None:
    coordinator = protocol(tmp_path, plan("scope:a"))
    item = coordinator.next_work_item("scope:a")
    assert item is not None

    coordinator.submit(
        item,
        submission(item, "pause", outcome="retryable_interruption"),
        now=NOW,
    )

    retried = coordinator.next_work_item("scope:a")
    assert retried is not None
    assert retried.step_id == item.step_id
    assert coordinator.ledger.checkpoints() == ()


def test_batch_continues_after_trial_problem(tmp_path: Path) -> None:
    coordinator = protocol(tmp_path, plan("scope:a"), plan("scope:b"))
    failed = coordinator.next_work_item("scope:a")
    assert failed is not None
    coordinator.submit(
        failed,
        submission(
            failed,
            "failed",
            outcome="preparation_outcome_reached",
            terminal_outcome=TrialFailed(
                trial_id="trial:a",
                reason=TrialFailureReason.RESULT_UNRECOVERABLE,
                detail="Result identity could not be recovered.",
            ),
        ),
        now=NOW,
    )

    remaining = coordinator.continue_preparation()

    assert [item.scope for item in remaining] == ["scope:b"]

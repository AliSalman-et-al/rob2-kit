import asyncio
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal, cast

import pytest
from fastmcp import Client
from v2_helpers import approved_workspace, completed_workspace

from rob2_kit import judgments
from rob2_kit.batch import ApprovedBatch, current_batch
from rob2_kit.detail import read_record
from rob2_kit.finish import (
    AssessmentFinishOperation,
    ProblemFinishOperation,
    finish_assessment_v2,
    finish_problem_v2,
)
from rob2_kit.judgment_models import (
    DomainCommitCondition,
    DomainCommitConflict,
    DomainCommitSuccess,
    DomainDraftCommitOperation,
    DomainDraftOperation,
    DomainDraftRepairOutcome,
    DomainDraftValidated,
    DomainValidationReceipt,
    DomainWorkflowCondition,
)
from rob2_kit.judgments import judgment_key, validate_domain_draft
from rob2_kit.models import sha256
from rob2_kit.recovery import current_batch_projection
from rob2_kit.server import mcp
from rob2_kit.storage import transaction


def _operation(
    workspace: Path,
    source,
    approved: ApprovedBatch,
    predecessor: str | None,
    domain_id: str = "domain:randomization",
    *,
    limitation: str | None = None,
) -> DomainDraftOperation:
    from v2_helpers import domain_operation

    return domain_operation(
        workspace, source, approved, domain_id, predecessor, limitation=limitation
    )


def _active_hash(workspace: Path, approved: ApprovedBatch, domain_id: str) -> str:
    with transaction(workspace) as connection:
        row = connection.execute(
            "SELECT payload FROM records WHERE name=?",
            (judgment_key(approved.frozen_hash, "t", "r", domain_id),),
        ).fetchone()
    assert row is not None
    return __import__("json").loads(bytes(row[0]))["checkpoint_hash"]


def test_domain_draft_validation_is_compact_and_exactly_replayable(tmp_path: Path) -> None:
    workspace, source = completed_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    operation = _operation(workspace, source, approved, "sha256:" + "0" * 64)
    # The completed fixture has a checkpoint; use its current predecessor.
    from rob2_kit.judgments import judgment_key

    with transaction(workspace) as connection:
        row = connection.execute(
            "SELECT payload FROM records WHERE name=?",
            (judgment_key(approved.frozen_hash, "t", "r", "domain:randomization"),),
        ).fetchone()
        assert row is not None
        checkpoint = __import__("json").loads(bytes(row[0]))["checkpoint_hash"]
    operation = operation.model_copy(update={"expected_predecessor_hash": checkpoint})
    first = validate_domain_draft(workspace, operation)
    second = validate_domain_draft(workspace, operation)
    assert first == second
    assert isinstance(first, DomainDraftValidated)
    assert isinstance(second, DomainDraftValidated)
    assert first.receipt.observed_at == second.receipt.observed_at
    assert "active_answers" not in first.model_dump_json()
    record = read_record(workspace, first.candidate_ref)
    assert isinstance(record, dict)
    assert record["checkpoint_hash"] == first.candidate_hash


def test_domain_scientific_prose_round_trips_without_normalization(tmp_path: Path) -> None:
    workspace, source = approved_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    operation = _operation(workspace, source, approved, None, limitation="  exact limitation  ")
    first_answer = operation.draft.active_answers[0]
    operation = operation.model_copy(
        update={
            "draft": operation.draft.model_copy(
                update={
                    "active_answers": (
                        first_answer.model_copy(update={"rationale": "  exact rationale  "}),
                        *operation.draft.active_answers[1:],
                    )
                }
            )
        }
    )
    validated = validate_domain_draft(workspace, operation)
    assert isinstance(validated, DomainDraftValidated)
    candidate = read_record(workspace, validated.candidate_ref)
    assert isinstance(candidate, dict)
    assert candidate["limitations"] == ["  exact limitation  "]
    assert candidate["active_answers"][0]["rationale"] == "  exact rationale  "


def test_domain_validation_verifies_one_shared_projection_for_all_handles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, source = approved_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    operation = _operation(workspace, source, approved, None)
    from rob2_kit import retrieval

    calls = 0
    original = retrieval.canonical_projection_identity

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(retrieval, "canonical_projection_identity", counted)
    assert isinstance(validate_domain_draft(workspace, operation), DomainDraftValidated)
    assert calls == 1


def test_validate_and_commit_each_verify_source_projection_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, source = approved_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    operation = _operation(workspace, source, approved, None)
    from rob2_kit import text_projection

    calls = 0
    original = text_projection.verified_pages

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(text_projection, "verified_pages", counted)
    validated = validate_domain_draft(workspace, operation)
    assert isinstance(validated, DomainDraftValidated)
    assert calls == 1
    calls = 0
    committed = judgments.commit_domain_draft(
        workspace,
        DomainDraftCommitOperation(
            **operation.model_dump(),
            validation_receipt=validated.receipt,
            reviewed_candidate_hash=validated.candidate_hash,
        ),
    )
    assert isinstance(committed, DomainCommitSuccess)
    assert calls == 1


def test_approval_transition_invalidates_captured_scope_handle_for_domain(
    tmp_path: Path,
) -> None:
    workspace, source = approved_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    from rob2_kit import retrieval

    captured_handle = next(
        handle
        for handle in retrieval._HANDLE_CACHE.values()
        if handle.source_id == source.id and handle.kind == "text"
    )
    operation = _operation(workspace, source, approved, None)
    approved_handle_id = operation.draft.active_answers[0].evidence_uses[0].handle_ids[0]
    assert approved_handle_id != captured_handle.handle_id
    stale_answers = tuple(
        answer.model_copy(
            update={
                "evidence_uses": tuple(
                    use.model_copy(update={"handle_ids": (captured_handle.handle_id,)})
                    for use in answer.evidence_uses
                )
            }
        )
        for answer in operation.draft.active_answers
    )
    stale = operation.model_copy(
        update={"draft": operation.draft.model_copy(update={"active_answers": stale_answers})}
    )
    repaired = validate_domain_draft(workspace, stale)
    assert isinstance(repaired, DomainDraftRepairOutcome)
    assert all(item.invariant == "evidence_integrity" for item in repaired.repairs)
    assert isinstance(validate_domain_draft(workspace, operation), DomainDraftValidated)


@pytest.mark.parametrize("corruption", ["candidate", "receipt"])
def test_validation_retry_rejects_corrupt_observation_content(
    tmp_path: Path, corruption: str
) -> None:
    workspace, source = approved_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    operation = _operation(workspace, source, approved, None)
    first = validate_domain_draft(workspace, operation)
    assert isinstance(first, DomainDraftValidated)
    operation_hash = sha256(operation)
    import json

    with transaction(workspace) as connection:
        key = f"domain_validation_observation:{operation_hash}"
        row = connection.execute("SELECT payload FROM records WHERE name=?", (key,)).fetchone()
        assert row is not None
        value = json.loads(bytes(row[0]))
        if corruption == "candidate":
            value["candidate"]["actor"] = "forged"
        elif corruption == "receipt":
            value["receipt"]["actor"] = "forged"
        connection.execute(
            "UPDATE records SET payload=? WHERE name=?",
            (json.dumps(value, separators=(",", ":")).encode(), key),
        )
    with pytest.raises(ValueError, match="corrupt"):
        validate_domain_draft(workspace, operation)


def test_corrupt_review_is_disposable_for_validation_and_commit(tmp_path: Path) -> None:
    workspace, source = approved_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    operation = _operation(workspace, source, approved, None)
    first = validate_domain_draft(workspace, operation)
    assert isinstance(first, DomainDraftValidated)
    with transaction(workspace) as connection:
        connection.execute(
            "UPDATE records SET payload=? WHERE name=?",
            (b"{}", f"domain_review:{sha256(operation)}"),
        )
    assert validate_domain_draft(workspace, operation) == first
    committed = judgments.commit_domain_draft(
        workspace,
        DomainDraftCommitOperation(
            **operation.model_dump(),
            validation_receipt=first.receipt,
            reviewed_candidate_hash=first.candidate_hash,
        ),
    )
    assert isinstance(committed, DomainCommitSuccess)


@pytest.mark.parametrize("damage", ["primary", "mirror", "both", "corrupt_mirror"])
def test_initial_commit_requires_immutable_validation_observation(
    tmp_path: Path, damage: str
) -> None:
    workspace, source = approved_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    operation = _operation(workspace, source, approved, None)
    validated = validate_domain_draft(workspace, operation)
    assert isinstance(validated, DomainDraftValidated)
    commit = DomainDraftCommitOperation(
        **operation.model_dump(),
        validation_receipt=validated.receipt,
        reviewed_candidate_hash=validated.candidate_hash,
    )
    operation_hash = sha256(operation)
    import json

    with transaction(workspace) as connection:
        primary = f"domain_validation_observation:{operation_hash}"
        row = connection.execute("SELECT payload FROM records WHERE name=?", (primary,)).fetchone()
        assert row is not None
        observation_hash = json.loads(bytes(row[0]))["observation_hash"]
        mirror = f"domain_validation_observation_content:{observation_hash}"
        if damage in {"primary", "both"}:
            connection.execute("DELETE FROM records WHERE name=?", (primary,))
        if damage in {"mirror", "both"}:
            connection.execute("DELETE FROM records WHERE name=?", (mirror,))
        elif damage == "corrupt_mirror":
            connection.execute("UPDATE records SET payload=? WHERE name=?", (b"{}", mirror))
        before = connection.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    result = judgments.commit_domain_draft(workspace, commit)
    assert isinstance(result, DomainCommitCondition)
    assert result.code in {
        "validation_observation_missing",
        "validation_observation_corrupt",
    }
    with transaction(workspace) as connection:
        assert connection.execute("SELECT COUNT(*) FROM records").fetchone()[0] == before
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM records WHERE name LIKE 'domain_judgment:%' "
                "OR name LIKE 'domain_judgment_revision:%'"
            ).fetchone()[0]
            == 0
        )


@pytest.mark.parametrize(
    "remaining",
    [(), ("domain:deviations",), ("domain:selection", "domain:randomization")],
)
def test_validation_retry_rejects_coherently_rehashed_wrong_domain_progress(
    tmp_path: Path, remaining: tuple[str, ...]
) -> None:
    workspace, source = approved_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    operation = _operation(workspace, source, approved, None)
    assert isinstance(validate_domain_draft(workspace, operation), DomainDraftValidated)
    operation_hash = sha256(operation)
    import json

    with transaction(workspace) as connection:
        observation_key = f"domain_validation_observation:{operation_hash}"
        review_key = f"domain_review:{operation_hash}"
        observation_row = connection.execute(
            "SELECT payload FROM records WHERE name=?", (observation_key,)
        ).fetchone()
        review_row = connection.execute(
            "SELECT payload FROM records WHERE name=?", (review_key,)
        ).fetchone()
        assert observation_row is not None and review_row is not None
        observation = json.loads(bytes(observation_row[0]))
        receipt = DomainValidationReceipt.model_validate(observation["receipt"]).model_copy(
            update={"remaining_domains": remaining, "receipt_hash": "pending"}
        )
        receipt = receipt.model_copy(
            update={"receipt_hash": sha256(receipt.model_dump(exclude={"receipt_hash"}))}
        )
        observation["receipt"] = receipt.model_dump(mode="json")
        review = json.loads(bytes(review_row[0]))
        review["receipt"] = observation["receipt"]
        review["observation_hash"] = sha256(observation)
        connection.execute(
            "UPDATE records SET payload=? WHERE name=?",
            (json.dumps(observation, separators=(",", ":")).encode(), observation_key),
        )
        connection.execute(
            "UPDATE records SET payload=? WHERE name=?",
            (json.dumps(review, separators=(",", ":")).encode(), review_key),
        )
    with pytest.raises(ValueError, match="content identity is corrupt"):
        validate_domain_draft(workspace, operation)


def test_corrupt_shared_projection_basis_is_condition_with_zero_writes(
    tmp_path: Path,
) -> None:
    workspace, source = approved_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    operation = _operation(workspace, source, approved, None)
    captured_path = workspace / source.captured_path
    captured_path.write_bytes(captured_path.read_bytes() + b"corrupt")
    with transaction(workspace) as connection:
        before = connection.execute(
            "SELECT COUNT(*) FROM records WHERE name LIKE 'domain_validation_observation:%' "
            "OR name LIKE 'domain_review:%'"
        ).fetchone()[0]
    result = validate_domain_draft(workspace, operation)
    assert isinstance(result, DomainWorkflowCondition)
    assert result.code in {"batch_stale", "projection_unavailable"}
    assert "repairs" not in result.model_dump()
    with transaction(workspace) as connection:
        after = connection.execute(
            "SELECT COUNT(*) FROM records WHERE name LIKE 'domain_validation_observation:%' "
            "OR name LIKE 'domain_review:%'"
        ).fetchone()[0]
    assert after == before


def test_public_commit_persists_next_packet_with_prior_domain_digest(tmp_path: Path) -> None:
    workspace, source = approved_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    operation = _operation(workspace, source, approved, None)

    async def call() -> tuple[dict[str, Any], str]:
        import os

        previous = os.environ.get("ROB2_WORKSPACE")
        os.environ["ROB2_WORKSPACE"] = str(workspace)
        try:
            async with Client(mcp) as client:
                validated = await client.call_tool(
                    "validate_domain_judgment",
                    {"operation": operation.model_dump(mode="json")},
                )
                value = validated.structured_content
                committed = await client.call_tool(
                    "commit_domain_judgment",
                    {
                        "operation": {
                            **operation.model_dump(mode="json"),
                            "validation_receipt": value["receipt"],
                            "reviewed_candidate_hash": value["candidate_hash"],
                        }
                    },
                )
                result = committed.structured_content
                detail = await client.read_resource(result["next_packet_ref"]["uri"])
            return result, detail[0].text
        finally:
            if previous is None:
                os.environ.pop("ROB2_WORKSPACE", None)
            else:
                os.environ["ROB2_WORKSPACE"] = previous

    committed, detail = asyncio.run(call())
    assert committed["status"] == "committed"
    assert committed["next_packet_ref"]["kind"] == "domain"
    packet = __import__("json").loads(detail)
    assert packet["domain_id"] == "domain:deviations"
    assert [item["domain_id"] for item in packet["prior_domains"]] == ["domain:randomization"]
    before = committed["next_packet_ref"]
    with transaction(workspace) as connection:
        connection.execute(
            "DELETE FROM records WHERE name=?",
            (f"detail:domain:{before['identity']}",),
        )
    projection = __import__(
        "rob2_kit.recovery", fromlist=["current_batch_projection"]
    ).current_batch_projection(workspace)
    assert projection.trials[0].recommended_packet_ref is not None
    assert projection.trials[0].recommended_packet_ref.identity == before["identity"]


def test_invalid_domain_draft_aggregates_repairs_without_records(tmp_path: Path) -> None:
    workspace, source = completed_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    operation = _operation(workspace, source, approved, "sha256:" + "0" * 64)
    bad = operation.model_copy(
        update={
            "draft": operation.draft.model_copy(
                update={
                    "active_answers": (
                        operation.draft.active_answers[0].model_copy(update={"question_id": "bad"}),
                        operation.draft.active_answers[0],
                    )
                }
            )
        }
    )
    from rob2_kit.judgments import judgment_key

    with transaction(workspace) as connection:
        before = connection.execute(
            "SELECT COUNT(*) FROM records WHERE name LIKE 'domain_validation_observation:%'"
        ).fetchone()[0]
        row = connection.execute(
            "SELECT payload FROM records WHERE name=?",
            (judgment_key(approved.frozen_hash, "t", "r", "domain:randomization"),),
        ).fetchone()
        assert row is not None
        checkpoint = __import__("json").loads(bytes(row[0]))["checkpoint_hash"]
    bad = bad.model_copy(update={"expected_predecessor_hash": checkpoint})
    result = validate_domain_draft(workspace, bad)
    assert not isinstance(result, tuple)
    assert result.status == "repair"
    assert result.repairs
    with transaction(workspace) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM records WHERE name LIKE 'domain_validation_observation:%'"
            ).fetchone()[0]
            == before
        )


def test_domain_commit_is_exactly_replayable_and_review_is_not_authority(
    tmp_path: Path,
) -> None:
    workspace, source = completed_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    from rob2_kit.judgments import judgment_key

    with transaction(workspace) as connection:
        row = connection.execute(
            "SELECT payload FROM records WHERE name=?",
            (judgment_key(approved.frozen_hash, "t", "r", "domain:randomization"),),
        ).fetchone()
        assert row is not None
        checkpoint = __import__("json").loads(bytes(row[0]))["checkpoint_hash"]
    operation = _operation(workspace, source, approved, checkpoint)
    validated = validate_domain_draft(workspace, operation)
    assert isinstance(validated, DomainDraftValidated)
    commit = DomainDraftCommitOperation(
        **operation.model_dump(),
        validation_receipt=validated.receipt,
        reviewed_candidate_hash=validated.candidate_hash,
    )
    first = __import__("rob2_kit.judgments", fromlist=["commit_domain_draft"]).commit_domain_draft(
        workspace, commit
    )
    assert isinstance(first, DomainCommitSuccess)
    retry = __import__("rob2_kit.judgments", fromlist=["commit_domain_draft"]).commit_domain_draft(
        workspace, commit
    )
    assert retry == first
    with transaction(workspace) as connection:
        connection.execute("DELETE FROM records WHERE name LIKE 'domain_review:%'")
    assert (
        __import__("rob2_kit.judgments", fromlist=["commit_domain_draft"]).commit_domain_draft(
            workspace, commit
        )
        == first
    )
    operation_two = _operation(workspace, source, approved, first.active_hash)
    validated_two = validate_domain_draft(workspace, operation_two)
    assert isinstance(validated_two, DomainDraftValidated)
    commit_two = DomainDraftCommitOperation(
        **operation_two.model_dump(),
        validation_receipt=validated_two.receipt,
        reviewed_candidate_hash=validated_two.candidate_hash,
    )
    second = __import__("rob2_kit.judgments", fromlist=["commit_domain_draft"]).commit_domain_draft(
        workspace, commit_two
    )
    assert isinstance(second, DomainCommitSuccess)
    conflict = __import__(
        "rob2_kit.judgments", fromlist=["commit_domain_draft"]
    ).commit_domain_draft(workspace, commit)
    assert isinstance(conflict, DomainCommitConflict)
    assert conflict.current_active_revision == second.active_revision


@pytest.mark.parametrize(
    "field,value",
    [
        ("active_revision", 99),
        ("remaining_domains", []),
        ("remaining_domains", ["domain:selection", "domain:deviations"]),
        ("domain_id", "domain:missing"),
        ("next_action", "finish_trial"),
    ],
)
def test_domain_commit_retry_rejects_corrupt_persisted_success(
    tmp_path: Path, field: str, value: object
) -> None:
    workspace, source = approved_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    operation = _operation(workspace, source, approved, None)
    validated = validate_domain_draft(workspace, operation)
    assert isinstance(validated, DomainDraftValidated)
    commit = DomainDraftCommitOperation(
        **operation.model_dump(),
        validation_receipt=validated.receipt,
        reviewed_candidate_hash=validated.candidate_hash,
    )
    first = judgments.commit_domain_draft(workspace, commit)
    assert isinstance(first, DomainCommitSuccess)
    import json

    key = f"domain_commit_success:{first.active_hash}"
    with transaction(workspace) as connection:
        row = connection.execute("SELECT payload FROM records WHERE name=?", (key,)).fetchone()
        assert row is not None
        stored = json.loads(bytes(row[0]))
        stored[field] = value
        connection.execute(
            "UPDATE records SET payload=? WHERE name=?",
            (json.dumps(stored, separators=(",", ":")).encode(), key),
        )
    with pytest.raises(ValueError, match="commit success observation is corrupt"):
        judgments.commit_domain_draft(workspace, commit)


def test_domain_receipts_are_scoped_to_one_domain_not_all_domain_progress(tmp_path: Path) -> None:
    workspace, source = completed_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    randomization = _operation(
        workspace,
        source,
        approved,
        _active_hash(workspace, approved, "domain:randomization"),
        limitation="randomization revision",
    )
    validated = validate_domain_draft(workspace, randomization)
    assert isinstance(validated, DomainDraftValidated)

    missing = _operation(
        workspace,
        source,
        approved,
        _active_hash(workspace, approved, "domain:missing"),
        "domain:missing",
        limitation="missing-data revision",
    )
    other_validation = validate_domain_draft(workspace, missing)
    assert isinstance(other_validation, DomainDraftValidated)
    other_commit = DomainDraftCommitOperation(
        **missing.model_dump(),
        validation_receipt=other_validation.receipt,
        reviewed_candidate_hash=other_validation.candidate_hash,
    )
    assert isinstance(judgments.commit_domain_draft(workspace, other_commit), DomainCommitSuccess)

    commit = DomainDraftCommitOperation(
        **randomization.model_dump(),
        validation_receipt=validated.receipt,
        reviewed_candidate_hash=validated.candidate_hash,
    )
    assert isinstance(judgments.commit_domain_draft(workspace, commit), DomainCommitSuccess)


def test_unrelated_first_commit_does_not_invalidate_other_domain_receipt(tmp_path: Path) -> None:
    workspace, source = approved_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    operation_a = _operation(workspace, source, approved, None, "domain:randomization")
    operation_b = _operation(workspace, source, approved, None, "domain:missing")
    validated_a = validate_domain_draft(workspace, operation_a)
    validated_b = validate_domain_draft(workspace, operation_b)
    assert isinstance(validated_a, DomainDraftValidated)
    assert isinstance(validated_b, DomainDraftValidated)
    commit_b = DomainDraftCommitOperation(
        **operation_b.model_dump(),
        validation_receipt=validated_b.receipt,
        reviewed_candidate_hash=validated_b.candidate_hash,
    )
    commit_a = DomainDraftCommitOperation(
        **operation_a.model_dump(),
        validation_receipt=validated_a.receipt,
        reviewed_candidate_hash=validated_a.candidate_hash,
    )
    assert isinstance(judgments.commit_domain_draft(workspace, commit_b), DomainCommitSuccess)
    assert isinstance(judgments.commit_domain_draft(workspace, commit_a), DomainCommitSuccess)


def test_commit_retry_preserves_original_progress_after_unrelated_commit(tmp_path: Path) -> None:
    workspace, source = approved_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    operation_a = _operation(workspace, source, approved, None, "domain:randomization")
    validated_a = validate_domain_draft(workspace, operation_a)
    assert isinstance(validated_a, DomainDraftValidated)
    commit_a = DomainDraftCommitOperation(
        **operation_a.model_dump(),
        validation_receipt=validated_a.receipt,
        reviewed_candidate_hash=validated_a.candidate_hash,
    )
    first = judgments.commit_domain_draft(workspace, commit_a)
    assert isinstance(first, DomainCommitSuccess)
    operation_b = _operation(workspace, source, approved, None, "domain:missing")
    validated_b = validate_domain_draft(workspace, operation_b)
    assert isinstance(validated_b, DomainDraftValidated)
    commit_b = DomainDraftCommitOperation(
        **operation_b.model_dump(),
        validation_receipt=validated_b.receipt,
        reviewed_candidate_hash=validated_b.candidate_hash,
    )
    assert isinstance(judgments.commit_domain_draft(workspace, commit_b), DomainCommitSuccess)
    assert judgments.commit_domain_draft(workspace, commit_a) == first


def test_validation_replay_is_independent_of_unrelated_commit_order(tmp_path: Path) -> None:
    workspace, source = approved_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    operation_b = _operation(workspace, source, approved, None, "domain:deviations")
    operation_a = _operation(workspace, source, approved, None, "domain:randomization")
    validated_b = validate_domain_draft(workspace, operation_b)
    first_a = validate_domain_draft(workspace, operation_a)
    assert isinstance(validated_b, DomainDraftValidated)
    assert isinstance(first_a, DomainDraftValidated)
    assert isinstance(
        judgments.commit_domain_draft(
            workspace,
            DomainDraftCommitOperation(
                **operation_b.model_dump(),
                validation_receipt=validated_b.receipt,
                reviewed_candidate_hash=validated_b.candidate_hash,
            ),
        ),
        DomainCommitSuccess,
    )
    assert validate_domain_draft(workspace, operation_a) == first_a


@pytest.mark.parametrize("missing", ["success", "observation", "both"])
def test_commit_retry_requires_both_immutable_replay_rows(tmp_path: Path, missing: str) -> None:
    workspace, source = approved_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    operation = _operation(workspace, source, approved, None)
    validated = validate_domain_draft(workspace, operation)
    assert isinstance(validated, DomainDraftValidated)
    commit = DomainDraftCommitOperation(
        **operation.model_dump(),
        validation_receipt=validated.receipt,
        reviewed_candidate_hash=validated.candidate_hash,
    )
    success = judgments.commit_domain_draft(workspace, commit)
    assert isinstance(success, DomainCommitSuccess)
    keys = {
        "success": (f"domain_commit_success:{success.active_hash}",),
        "observation": (f"domain_commit_observation:{success.active_hash}",),
        "both": (
            f"domain_commit_success:{success.active_hash}",
            f"domain_commit_observation:{success.active_hash}",
        ),
    }[missing]
    with transaction(workspace) as connection:
        revision_before = connection.execute(
            "SELECT payload FROM records WHERE name LIKE 'domain_judgment_revision:%'"
        ).fetchone()[0]
        count_before = connection.execute("SELECT COUNT(*) FROM records").fetchone()[0]
        for key in keys:
            connection.execute("DELETE FROM records WHERE name=?", (key,))
        expected_count = count_before - len(keys)
    with pytest.raises(ValueError, match="replay observation is incomplete"):
        judgments.commit_domain_draft(workspace, commit)
    with transaction(workspace) as connection:
        assert connection.execute("SELECT COUNT(*) FROM records").fetchone()[0] == expected_count
        assert (
            connection.execute(
                "SELECT payload FROM records WHERE name LIKE 'domain_judgment_revision:%'"
            ).fetchone()[0]
            == revision_before
        )


def test_same_domain_receipts_race_and_receipt_tampering_fails_closed(tmp_path: Path) -> None:
    workspace, source = completed_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    predecessor = _active_hash(workspace, approved, "domain:randomization")
    left = _operation(workspace, source, approved, predecessor, limitation="left")
    right = _operation(workspace, source, approved, predecessor, limitation="right")
    left_validated = validate_domain_draft(workspace, left)
    right_validated = validate_domain_draft(workspace, right)
    assert isinstance(left_validated, DomainDraftValidated)
    assert isinstance(right_validated, DomainDraftValidated)
    left_commit = DomainDraftCommitOperation(
        **left.model_dump(),
        validation_receipt=left_validated.receipt,
        reviewed_candidate_hash=left_validated.candidate_hash,
    )
    right_commit = DomainDraftCommitOperation(
        **right.model_dump(),
        validation_receipt=right_validated.receipt,
        reviewed_candidate_hash=right_validated.candidate_hash,
    )
    cross_used = right_commit.model_copy(
        update={
            "validation_receipt": left_validated.receipt,
            "reviewed_candidate_hash": left_validated.candidate_hash,
        }
    )
    condition = judgments.commit_domain_draft(workspace, cross_used)
    assert condition.status == "condition" and condition.code == "validation_receipt_mismatch"
    assert isinstance(judgments.commit_domain_draft(workspace, left_commit), DomainCommitSuccess)
    assert isinstance(judgments.commit_domain_draft(workspace, right_commit), DomainCommitConflict)

    forged = left_validated.receipt.model_copy(update={"pack_identities_hash": sha256("wrong")})
    forged = forged.model_copy(
        update={"receipt_hash": sha256(forged.model_dump(exclude={"receipt_hash"}))}
    )
    tampered = left_commit.model_copy(update={"validation_receipt": forged})
    condition = judgments.commit_domain_draft(workspace, tampered)
    assert condition.status == "condition" and condition.code == "validation_receipt_mismatch"

    unavailable_handle = (
        left.draft.active_answers[0]
        .evidence_uses[0]
        .model_copy(update={"handle_ids": ("sha256:" + "0" * 64,)})
    )
    invalid_draft = left.model_copy(
        update={
            "draft": left.draft.model_copy(
                update={
                    "active_answers": (
                        left.draft.active_answers[0].model_copy(
                            update={"evidence_uses": (unavailable_handle,)}
                        ),
                    )
                    + left.draft.active_answers[1:]
                }
            )
        }
    )
    invalid_commit = left_commit.model_copy(update={"draft": invalid_draft.draft})
    condition = judgments.commit_domain_draft(workspace, invalid_commit)
    assert condition.status == "condition" and condition.code == "validation_receipt_mismatch"


@pytest.mark.parametrize("terminal", ["assessed", "needs_input", "failed"])
def test_terminal_trial_rejects_domain_validation_and_commit(tmp_path: Path, terminal: str) -> None:
    workspace, source = completed_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    operation = _operation(
        workspace,
        source,
        approved,
        _active_hash(workspace, approved, "domain:randomization"),
        limitation="post-terminal attempt",
    )
    validated = validate_domain_draft(workspace, operation)
    assert isinstance(validated, DomainDraftValidated)
    if terminal == "assessed":
        progress = current_batch_projection(workspace)
        trial = next(item for item in progress.trials if item.trial_id == "t")
        assert trial.synthesis_ref is not None
        finish_assessment_v2(
            workspace,
            AssessmentFinishOperation(
                approved_batch_hash=approved.frozen_hash,
                trial_id="t",
                result_id="r",
                reviewed_synthesis_hash=trial.synthesis_ref.identity,
                actor="finisher",
            ),
        )
    else:
        finish_problem_v2(
            workspace,
            ProblemFinishOperation(
                approved_batch_hash=approved.frozen_hash,
                trial_id="t",
                result_id="r",
                category=cast(Literal["needs_input", "failed"], terminal),
                actor="finisher",
                problems=({"code": "terminal", "detail": "Terminal outcome."},),
            ),
        )
    condition = validate_domain_draft(workspace, operation)
    assert isinstance(condition, DomainWorkflowCondition)
    assert condition.code == "trial_terminal"
    commit = DomainDraftCommitOperation(
        **operation.model_dump(),
        validation_receipt=validated.receipt,
        reviewed_candidate_hash=validated.candidate_hash,
    )
    committed = judgments.commit_domain_draft(workspace, commit)
    assert committed.status == "condition" and committed.code == "trial_terminal"


def test_terminal_winning_before_final_commit_transaction_prevents_revision_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, source = approved_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    operation = _operation(workspace, source, approved, None)
    validated = validate_domain_draft(workspace, operation)
    assert isinstance(validated, DomainDraftValidated)
    original_transaction = judgments.transaction

    @contextmanager
    def terminal_first(root):
        finished = finish_problem_v2(
            workspace,
            ProblemFinishOperation(
                approved_batch_hash=approved.frozen_hash,
                trial_id="t",
                result_id="r",
                category="failed",
                actor="finisher",
                problems=({"code": "race", "detail": "Terminal won the race."},),
            ),
        )
        assert finished.status == "committed"
        with original_transaction(root) as connection:
            yield connection

    monkeypatch.setattr(judgments, "transaction", terminal_first)
    committed = judgments.commit_domain_draft(
        workspace,
        DomainDraftCommitOperation(
            **operation.model_dump(),
            validation_receipt=validated.receipt,
            reviewed_candidate_hash=validated.candidate_hash,
        ),
    )
    assert committed.status == "condition" and committed.code == "trial_terminal"
    with original_transaction(workspace) as connection:
        assert (
            connection.execute(
                "SELECT 1 FROM records WHERE name=?",
                (judgment_key(approved.frozen_hash, "t", "r", "domain:randomization"),),
            ).fetchone()
            is None
        )


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_validation_retry_ensures_readable_candidate_detail(tmp_path: Path, damage: str) -> None:
    workspace, source = approved_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    operation = _operation(workspace, source, approved, None)
    first = validate_domain_draft(workspace, operation)
    assert isinstance(first, DomainDraftValidated)
    key = f"detail:judgment:{first.candidate_hash}"
    with transaction(workspace) as connection:
        if damage == "missing":
            connection.execute("DELETE FROM records WHERE name=?", (key,))
        else:
            connection.execute("UPDATE records SET payload=? WHERE name=?", (b"{}", key))
    retry = validate_domain_draft(workspace, operation)
    if damage == "missing":
        assert retry == first
        assert read_record(workspace, first.candidate_ref)
    else:
        assert isinstance(retry, DomainWorkflowCondition)
        assert retry.code == "judgment_detail_corrupt"


def test_commit_retry_rematerializes_missing_committed_judgment_detail(tmp_path: Path) -> None:
    workspace, source = approved_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    operation = _operation(workspace, source, approved, None)
    validated = validate_domain_draft(workspace, operation)
    assert isinstance(validated, DomainDraftValidated)
    commit = DomainDraftCommitOperation(
        **operation.model_dump(),
        validation_receipt=validated.receipt,
        reviewed_candidate_hash=validated.candidate_hash,
    )
    first = judgments.commit_domain_draft(workspace, commit)
    assert isinstance(first, DomainCommitSuccess)
    with transaction(workspace) as connection:
        connection.execute(
            "DELETE FROM records WHERE name=?",
            (f"detail:judgment:{first.active_hash}",),
        )
    assert judgments.commit_domain_draft(workspace, commit) == first
    assert read_record(workspace, first.candidate_ref)


def test_domain_commit_rolls_back_when_revision_index_write_fails(
    tmp_path: Path, monkeypatch
) -> None:
    workspace, source = completed_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    predecessor = _active_hash(workspace, approved, "domain:randomization")
    operation = _operation(workspace, source, approved, predecessor, limitation="rollback")
    validated = validate_domain_draft(workspace, operation)
    assert isinstance(validated, DomainDraftValidated)
    commit = DomainDraftCommitOperation(
        **operation.model_dump(),
        validation_receipt=validated.receipt,
        reviewed_candidate_hash=validated.candidate_hash,
    )
    original = judgments.canonical_json_bytes

    def fail_index(value: object) -> bytes:
        if isinstance(value, judgments.JudgmentRevisionIndex):
            raise OSError("injected index write failure")
        return original(value)

    monkeypatch.setattr(judgments, "canonical_json_bytes", fail_index)
    with pytest.raises(OSError, match="injected"):
        judgments.commit_domain_draft(workspace, commit)
    assert _active_hash(workspace, approved, "domain:randomization") == predecessor
    with transaction(workspace) as connection:
        key = judgment_key(approved.frozen_hash, "t", "r", "domain:randomization")
        revision_id = sha256({"active_key": key}).removeprefix("sha256:")
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM records WHERE name LIKE ?",
                (f"domain_judgment_revision:{revision_id}:%",),
            ).fetchone()[0]
            == 1
        )

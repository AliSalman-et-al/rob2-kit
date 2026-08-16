from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from v2_helpers import approved_workspace, completed_workspace, domain_operation

from rob2_kit.batch import ApprovedBatch, current_batch
from rob2_kit.detail import read_record
from rob2_kit.judgment_models import (
    DomainDraftCommitOperation,
    DomainDraftValidated,
    DomainJudgment,
)
from rob2_kit.judgments import (
    commit_domain_draft,
    judgment_key,
    validate_domain_draft,
)
from rob2_kit.packets import (
    VerifiedDomainPacketBasis,
    VerifiedSynthesisPacketBasis,
    build_approved_work_packet,
    build_trial_synthesis_packet,
    verify_approved_work_packet,
    verify_trial_synthesis_packet,
)
from rob2_kit.packs import SCIENTIFIC_PACK
from rob2_kit.recovery import current_batch_projection
from rob2_kit.storage import transaction


def _state(tmp_path: Path) -> tuple[ApprovedBatch, tuple[DomainJudgment, ...]]:
    workspace, _source = completed_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    judgments: list[DomainJudgment] = []
    with transaction(workspace) as connection:
        for domain in SCIENTIFIC_PACK.domains:
            row = connection.execute(
                "SELECT payload FROM records WHERE name=?",
                (judgment_key(approved.frozen_hash, "t", "r", domain.id),),
            ).fetchone()
            assert row is not None
            judgments.append(DomainJudgment.model_validate_json(bytes(row[0])))
    return approved, tuple(judgments)


def test_work_and_synthesis_packets_are_deterministic_and_bounded(tmp_path: Path) -> None:
    approved, judgments = _state(tmp_path)
    basis = VerifiedDomainPacketBasis(
        approved_batch=approved,
        trial_id="t",
        result_id="r",
        domain_id=judgments[0].domain_id,
        active_judgment=judgments[0],
        prior_judgments=judgments[1:],
    )
    first = build_approved_work_packet(basis)
    second = build_approved_work_packet(basis)
    assert first == second
    assert first.next_action == "finish_trial"
    assert first.active_question_ids
    assert first.reachable_question_ids
    assert all("captured_path" not in item.model_dump() for item in first.sources)
    assert "quote" not in first.model_dump_json()
    assert "rationale" not in first.model_dump_json()
    assert verify_approved_work_packet(first) == first

    synthesis = build_trial_synthesis_packet(
        VerifiedSynthesisPacketBasis(
            approved_batch=approved,
            trial_id="t",
            result_id="r",
            active_judgments=judgments,
        )
    )
    assert len(synthesis.domains) == 5
    assert "rationale" not in synthesis.model_dump_json()
    assert "quote" not in synthesis.model_dump_json()
    assert verify_trial_synthesis_packet(synthesis) == synthesis


def test_packets_fail_closed_on_corruption_and_stale_pack(tmp_path: Path) -> None:
    approved, judgments = _state(tmp_path)
    forged = approved.model_copy(update={"frozen_hash": "sha256:" + "0" * 64})
    with pytest.raises(ValueError, match="identity"):
        build_approved_work_packet(
            VerifiedDomainPacketBasis(
                approved_batch=forged,
                trial_id="t",
                result_id="r",
                domain_id=judgments[0].domain_id,
                active_judgment=judgments[0],
            )
        )
    packet = build_approved_work_packet(
        VerifiedDomainPacketBasis(
            approved_batch=approved,
            trial_id="t",
            result_id="r",
            domain_id=judgments[0].domain_id,
            active_judgment=judgments[0],
        )
    )
    tampered = packet.model_copy(update={"next_action": "review_correction"})
    with pytest.raises(ValueError, match="corrupt"):
        verify_approved_work_packet(tampered)


def test_correction_packet_preserves_predecessor_basis(tmp_path: Path) -> None:
    approved, judgments = _state(tmp_path)
    packet = build_approved_work_packet(
        VerifiedDomainPacketBasis(
            approved_batch=approved,
            trial_id="t",
            result_id="r",
            domain_id=judgments[0].domain_id,
            active_judgment=judgments[0],
            active_revision=2,
            predecessor_hash="sha256:" + "1" * 64,
        )
    )
    assert packet.next_action == "review_correction"
    assert packet.correction.predecessor_hash == "sha256:" + "1" * 64


def test_detail_rejects_packet_after_checkpoint_progresses(tmp_path: Path) -> None:
    workspace, source = approved_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    first_ref = current_batch_projection(workspace).trials[0].recommended_packet_ref
    assert first_ref is not None
    first_packet = cast(dict[str, object], read_record(workspace, first_ref))
    assert first_packet["domain_id"] == "domain:randomization"

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
    with pytest.raises(ValueError, match="stale"):
        read_record(workspace, first_ref)
    next_ref = current_batch_projection(workspace).trials[0].recommended_packet_ref
    assert next_ref is not None
    next_packet = cast(dict[str, object], read_record(workspace, next_ref))
    prior = cast(list[dict[str, object]], next_packet["prior_domains"])
    assert prior[0]["domain_id"] == "domain:randomization"


def test_commit_exposes_current_correction_packet_and_invalidates_predecessor(
    tmp_path: Path,
) -> None:
    workspace, source = approved_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    operation = domain_operation(workspace, source, approved, "domain:randomization")
    validated = validate_domain_draft(workspace, operation)
    assert isinstance(validated, DomainDraftValidated)
    first = commit_domain_draft(
        workspace,
        DomainDraftCommitOperation(
            **operation.model_dump(),
            validation_receipt=validated.receipt,
            reviewed_candidate_hash=validated.candidate_hash,
        ),
    )
    assert first.status == "committed"
    progress = current_batch_projection(workspace).trials[0]
    correction = next(
        item for item in progress.correction_packet_refs if item.domain_id == operation.domain_id
    )
    first_ref = correction.packet_ref
    packet = cast(dict[str, object], read_record(workspace, first_ref))
    basis = cast(dict[str, object], packet["correction"])
    assert basis["active_revision"] == 1
    assert basis["active_checkpoint_hash"] == first.active_hash
    assert basis["predecessor_hash"] == first.active_hash
    assert basis["evidence_handle_ids"]

    corrected = domain_operation(
        workspace,
        source,
        approved,
        operation.domain_id,
        predecessor=first.active_hash,
        limitation="corrected limitation",
    )
    corrected_validation = validate_domain_draft(workspace, corrected)
    assert isinstance(corrected_validation, DomainDraftValidated)
    second = commit_domain_draft(
        workspace,
        DomainDraftCommitOperation(
            **corrected.model_dump(),
            validation_receipt=corrected_validation.receipt,
            reviewed_candidate_hash=corrected_validation.candidate_hash,
        ),
    )
    assert second.status == "committed"
    new_correction = next(
        item
        for item in current_batch_projection(workspace).trials[0].correction_packet_refs
        if item.domain_id == operation.domain_id
    )
    assert new_correction.packet_ref != first_ref
    assert (
        cast(dict[str, object], read_record(workspace, new_correction.packet_ref))["packet_hash"]
        == new_correction.packet_ref.identity
    )
    with pytest.raises(ValueError, match="stale"):
        read_record(workspace, first_ref)

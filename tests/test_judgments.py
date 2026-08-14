import os
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier, Thread

import pymupdf
import pytest

from rob2_kit.assessment import (
    Arm,
    BatchRequest,
    Comparison,
    OutcomeTarget,
    Proposal,
    Randomization,
    ResultAnchor,
    ResultSpec,
    Trial,
)
from rob2_kit.batch import approve_batch, save_proposal
from rob2_kit.ingestion import ingest_batch
from rob2_kit.judgment_models import (
    ActiveAnswer,
    DomainJudgment,
    EvidenceUse,
    InactiveQuestion,
    Override,
    TextEvidenceRef,
    VisualEvidenceRef,
)
from rob2_kit.judgments import (
    DomainJudgmentPayload,
    JudgmentConflict,
    JudgmentRevised,
    JudgmentSaved,
    JudgmentValidated,
    ScientificPreflight,
    checkpoint_content,
    commit_domain_judgment,
    judgment_key,
    revision_key,
    validate_domain_judgment,
)
from rob2_kit.logic.evaluator import active_questions
from rob2_kit.models import Answer, Judgment, canonical_json_bytes, sha256
from rob2_kit.packs import SCIENTIFIC_PACK
from rob2_kit.rendering import RenderedPage, render_page
from rob2_kit.sources import Source, SourceInput, SourceRole, TrialInput
from rob2_kit.storage import transaction

OBSERVED = datetime(2026, 8, 13, tzinfo=UTC)


def approved_workspace(tmp_path: Path) -> tuple[Path, Source]:
    doc = pymupdf.open()
    try:
        page = doc.new_page()
        page.insert_text((72, 72), "random concealed balanced")
        doc.save(tmp_path / "main.pdf")
    finally:
        doc.close()
    input_source = SourceInput(role=SourceRole.MAIN_ARTICLE, path="main.pdf", label="Main")
    source = (
        ingest_batch(tmp_path, (TrialInput(id="t", label="T", sources=(input_source,)),))
        .trials[0]
        .sources[0]
    )
    proposal = Proposal(
        request=BatchRequest(
            outcome_target=OutcomeTarget(id="o", label="O", description="D"),
            trial_inputs=(TrialInput(id="t", label="T", sources=(input_source,)),),
        ),
        trials=(Trial(id="t", label="T"),),
        result_specs=(
            ResultSpec(
                id="r",
                trial=Trial(id="t", label="T"),
                randomization=Randomization(id="random", description="R"),
                arms=(Arm(id="a", label="A"), Arm(id="b", label="B")),
                comparison=Comparison(intervention_arm_id="a", comparator_arm_id="b"),
                effect_of_interest="x",
                outcome_definition="x",
                measurement="x",
                time_point="x",
                population="x",
                analysis_method="x",
                analysis_choices=("x",),
                effect_measure="RR",
                anchor=ResultAnchor(
                    source_id=source.id,
                    source_sha256=source.sha256,
                    page_number=1,
                    start=0,
                    end=6,
                    quote="random",
                ),
            ),
        ),
        sources=(source,),
    )
    assert save_proposal(tmp_path, proposal).state.status == "proposal"
    assert approve_batch(tmp_path).state.status == "approved"
    return tmp_path, source


def _answers(
    domain_id: str, source: Source
) -> tuple[tuple[ActiveAnswer, ...], tuple[InactiveQuestion, ...]]:
    values = {
        "domain:randomization": {
            "sequence": "yes",
            "concealment": "yes",
            "baseline-imbalance": "no",
        },
        "domain:deviations": {
            "participants-aware": "no",
            "personnel-aware": "no",
            "appropriate-analysis": "yes",
        },
        "domain:missing": {"data-available": "yes"},
        "domain:measurement": {
            "method-inappropriate": "no",
            "differential": "no",
            "assessor-aware": "no",
        },
        "domain:selection": {
            "prespecified-analysis": "yes",
            "multiple-measurements": "no",
            "multiple-analyses": "no",
        },
    }[domain_id]
    mapping = {f"sq:{domain_id.split(':')[1]}:{key}": value for key, value in values.items()}
    ref = TextEvidenceRef(
        source_id=source.id,
        source_sha256=source.sha256,
        page_number=1,
        start=0,
        end=6,
        quote="random",
    )
    use = EvidenceUse(
        relationship="supporting", claim="reported", rationale="direct text", refs=(ref,)
    )
    active = tuple(
        ActiveAnswer(
            question_id=question_id, answer=answer, rationale="reported", evidence_uses=(use,)
        )
        for question_id, answer in mapping.items()
    )
    domain = next(item for item in SCIENTIFIC_PACK.domains if item.id == domain_id)
    inactive = tuple(
        InactiveQuestion(question_id=question_id)
        for question_id in domain.question_ids
        if question_id not in mapping
    )
    assert set(mapping) == set(active_questions(mapping)) & set(domain.question_ids)
    return active, inactive


def _save(
    workspace: Path,
    source: Source,
    domain_id: str = "domain:randomization",
    *,
    trial_id: str = "t",
    result_id: str = "r",
    active_answers: tuple[ActiveAnswer, ...] | None = None,
    inactive_questions: tuple[InactiveQuestion, ...] | None = None,
    final_judgment: Judgment | None = None,
    override: Override | None = None,
    limitations: tuple[str, ...] = (),
    actor: str = "reviewer",
    observed_at: datetime = OBSERVED,
    expected_previous_hash: str | None = None,
):
    active, inactive = _answers(domain_id, source)
    payload = DomainJudgmentPayload(
        trial_id=trial_id,
        result_id=result_id,
        domain_id=domain_id,
        active_answers=active if active_answers is None else active_answers,
        inactive_questions=inactive if inactive_questions is None else inactive_questions,
        final_judgment=final_judgment,
        override=override,
        limitations=limitations,
        actor=actor,
        observed_at=observed_at,
        expected_previous_hash=expected_previous_hash,
    )
    validated = validate_domain_judgment(workspace, payload)
    if not isinstance(validated, JudgmentValidated):
        return validated
    return commit_domain_judgment(
        workspace,
        payload,
        validated.receipt,
        ScientificPreflight(
            payload_final=True,
            citations_checked_against_pages=True,
            contradictions_addressed=True,
            activation_and_partition_reviewed=True,
        ),
    )


@pytest.mark.parametrize("domain_id", [item.id for item in SCIENTIFIC_PACK.domains])
def test_every_domain_requires_exact_active_inactive_partition(
    tmp_path: Path, domain_id: str
) -> None:
    workspace, source = approved_workspace(tmp_path)
    saved = _save(workspace, source, domain_id)
    assert isinstance(saved, JudgmentSaved)
    assert saved.judgment.trial_id == "t"
    active, inactive = _answers(domain_id, source)
    invalid = validate_domain_judgment(
        workspace,
        DomainJudgmentPayload(
            trial_id="t",
            result_id="r",
            domain_id=domain_id,
            active_answers=active,
            inactive_questions=(*inactive, InactiveQuestion(question_id=active[0].question_id)),
            final_judgment=None,
            override=None,
            limitations=(),
            actor="reviewer",
            observed_at=OBSERVED,
        ),
    )
    assert invalid.status == "condition" and invalid.code == "question_partition_invalid"


def test_evidence_is_exact_and_visual_is_attributable(tmp_path: Path) -> None:
    workspace, source = approved_workspace(tmp_path)
    active, inactive = _answers("domain:randomization", source)
    bad_ref = active[0].evidence_uses[0].refs[0].model_copy(update={"quote": "wrong"})
    bad_use = active[0].evidence_uses[0].model_copy(update={"refs": (bad_ref,)})
    invalid = _save(
        workspace,
        source,
        active_answers=(active[0].model_copy(update={"evidence_uses": (bad_use,)}), *active[1:]),
    )
    assert invalid.status == "condition" and invalid.code == "evidence_invalid"
    image = render_page(workspace, source, 1)
    assert isinstance(image, RenderedPage)
    visual = VisualEvidenceRef(
        source_id=source.id,
        source_sha256=source.sha256,
        page_number=1,
        origin="rendered_page",
        region=(0, 0, 1, 1),
        image_sha256=image.sha256,
        transcription="random",
    )
    use = active[0].evidence_uses[0].model_copy(update={"refs": (visual,)})
    assert isinstance(
        _save(
            workspace,
            source,
            active_answers=(active[0].model_copy(update={"evidence_uses": (use,)}), *active[1:]),
        ),
        JudgmentSaved,
    )


def test_identity_conflict_override_and_utc_are_fail_closed(tmp_path: Path) -> None:
    workspace, source = approved_workspace(tmp_path)
    first = _save(workspace, source)
    assert isinstance(first, JudgmentSaved)
    changed, inactive = _answers("domain:randomization", source)
    changed = (*changed[:-1], changed[-1].model_copy(update={"answer": Answer.YES}))
    assert isinstance(
        _save(workspace, source, active_answers=changed, inactive_questions=inactive),
        JudgmentConflict,
    )
    invalid_identity = _save(workspace, source, trial_id="other")
    assert (
        invalid_identity.status == "condition"
        and invalid_identity.code == "result_identity_invalid"
    )
    invalid_override = _save(workspace, source, final_judgment=Judgment.HIGH)
    assert invalid_override.status == "condition" and invalid_override.code == "override_invalid"
    invalid_time = _save(workspace, source, observed_at=datetime(2026, 8, 13))
    assert invalid_time.status == "condition" and invalid_time.code == "judgment_invalid"
    overridden = _save(
        workspace,
        source,
        final_judgment=Judgment.HIGH,
        override=Override(justification="context", actor="reviewer", observed_at=OBSERVED),
        limitations=(" sparse reporting ",),
    )
    assert isinstance(overridden, JudgmentConflict)


def test_persisted_checkpoint_hash_round_trips_and_tampering_fails_closed(tmp_path: Path) -> None:
    workspace, source = approved_workspace(tmp_path)
    saved = _save(workspace, source)
    assert isinstance(saved, JudgmentSaved)
    assert saved.judgment.checkpoint_hash == sha256(checkpoint_content(saved.judgment))
    key = (
        f"domain_judgment:{saved.judgment.approved_batch_hash}:"
        f"{saved.judgment.trial_id}:{saved.judgment.result_id}:{saved.judgment.domain_id}"
    )
    with transaction(workspace) as connection:
        row = connection.execute("SELECT payload FROM records WHERE name=?", (key,)).fetchone()
    assert row is not None
    assert bytes(row[0]) == canonical_json_bytes(saved.judgment)

    for update in ({"actor": "tampered"}, {"checkpoint_hash": "sha256:tampered"}):
        with transaction(workspace) as connection:
            connection.execute(
                "UPDATE records SET payload=? WHERE name=?",
                (canonical_json_bytes(saved.judgment.model_copy(update=update)), key),
            )
        invalid = _save(workspace, source)
        assert invalid.status == "condition" and invalid.code == "revision_history_corrupt"
        with transaction(workspace) as connection:
            connection.execute(
                "UPDATE records SET payload=? WHERE name=?",
                (canonical_json_bytes(saved.judgment), key),
            )


def test_correction_uses_exact_hash_and_preserves_append_only_history(tmp_path: Path) -> None:
    workspace, source = approved_workspace(tmp_path)
    first = _save(workspace, source)
    assert isinstance(first, JudgmentSaved)
    corrected = _save(
        workspace,
        source,
        limitations=("The report did not describe allocation concealment.",),
        expected_previous_hash=first.judgment.checkpoint_hash,
    )
    assert isinstance(corrected, JudgmentRevised)
    assert corrected.active_revision == 2
    assert corrected.remaining_domains == tuple(item.id for item in SCIENTIFIC_PACK.domains[1:])
    stale = _save(
        workspace,
        source,
        limitations=("A competing correction.",),
        expected_previous_hash=first.judgment.checkpoint_hash,
    )
    assert isinstance(stale, JudgmentConflict)
    assert stale.judgment == corrected.judgment and stale.active_revision == 2
    active_key = (
        f"domain_judgment:{corrected.judgment.approved_batch_hash}:t:r:domain:randomization"
    )
    with transaction(workspace) as connection:
        history = connection.execute(
            "SELECT name FROM records WHERE name IN (?,?) ORDER BY name",
            (revision_key(active_key, 1), revision_key(active_key, 2)),
        ).fetchall()
    assert {name for (name,) in history} == {
        revision_key(active_key, 1),
        revision_key(active_key, 2),
    }
    from rob2_kit.recovery import recovery_progress

    assert recovery_progress(workspace).status == "approved"


def test_identical_checkpoint_replays_are_saved_without_new_audit_revision(tmp_path: Path) -> None:
    workspace, source = approved_workspace(tmp_path)
    first = _save(workspace, source)
    assert isinstance(first, JudgmentSaved) and first.active_revision == 1
    replay_without_cas = _save(workspace, source)
    replay_with_cas = _save(workspace, source, expected_previous_hash=first.active_hash)
    assert isinstance(replay_without_cas, JudgmentSaved)
    assert isinstance(replay_with_cas, JudgmentSaved)
    assert replay_without_cas.active_hash == replay_with_cas.active_hash == first.active_hash
    key = judgment_key(first.judgment.approved_batch_hash, "t", "r", first.judgment.domain_id)
    with transaction(workspace) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM records WHERE name=?", (revision_key(key, 1),)
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM records WHERE name=?", (revision_key(key, 2),)
            ).fetchone()[0]
            == 0
        )


def test_lost_response_correction_replays_with_verified_predecessor_hash(tmp_path: Path) -> None:
    workspace, source = approved_workspace(tmp_path)
    first = _save(workspace, source)
    corrected = _save(
        workspace,
        source,
        limitations=("Correction that lost its response.",),
        expected_previous_hash=first.active_hash,
    )
    assert isinstance(corrected, JudgmentRevised) and corrected.active_revision == 2
    replay = _save(
        workspace,
        source,
        limitations=("Correction that lost its response.",),
        expected_previous_hash=first.active_hash,
    )
    assert isinstance(replay, JudgmentSaved)
    assert replay.active_revision == 2 and replay.active_hash == corrected.active_hash
    from rob2_kit.recovery import recovery_progress

    assert recovery_progress(workspace).status == "approved"
    restarted_replay = _save(
        workspace,
        source,
        limitations=("Correction that lost its response.",),
        expected_previous_hash=first.active_hash,
    )
    assert isinstance(restarted_replay, JudgmentSaved)
    conflict = _save(
        workspace,
        source,
        limitations=("Correction that lost its response.",),
        expected_previous_hash="sha256:" + "0" * 64,
    )
    assert isinstance(conflict, JudgmentConflict)
    key = judgment_key(first.judgment.approved_batch_hash, "t", "r", first.judgment.domain_id)
    with transaction(workspace) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM records WHERE name=?", (revision_key(key, 3),)
            ).fetchone()[0]
            == 0
        )


def test_absent_checkpoint_rejects_non_null_compare_and_swap_hash(tmp_path: Path) -> None:
    workspace, source = approved_workspace(tmp_path)
    result = _save(workspace, source, expected_previous_hash="sha256:" + "0" * 64)
    assert result.status == "condition" and result.code == "checkpoint_absent"


def test_validation_is_read_only_and_commit_requires_its_exact_receipt(tmp_path: Path) -> None:
    workspace, source = approved_workspace(tmp_path)
    active, inactive = _answers("domain:randomization", source)
    payload = DomainJudgmentPayload(
        trial_id="t",
        result_id="r",
        domain_id="domain:randomization",
        active_answers=active,
        inactive_questions=inactive,
        final_judgment=None,
        override=None,
        limitations=(),
        actor="reviewer",
        observed_at=OBSERVED,
    )
    validated = validate_domain_judgment(workspace, payload)
    assert isinstance(validated, JudgmentValidated)
    key = judgment_key(validated.judgment.approved_batch_hash, "t", "r", payload.domain_id)
    with transaction(workspace) as connection:
        assert connection.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 1
        assert connection.execute("SELECT 1 FROM records WHERE name=?", (key,)).fetchone() is None
    missing = commit_domain_judgment(workspace, payload, None, None)
    assert missing.status == "condition" and missing.code == "validation_receipt_required"
    for field in ScientificPreflight.model_fields:
        values = {name: True for name in ScientificPreflight.model_fields}
        values[field] = False
        false_preflight = commit_domain_judgment(
            workspace, payload, validated.receipt, ScientificPreflight(**values)
        )
        assert (
            false_preflight.status == "condition"
            and false_preflight.code == "scientific_preflight_invalid"
        )
    changed = payload.model_copy(update={"limitations": ("Reviewed after validation.",)})
    mismatched = commit_domain_judgment(
        workspace,
        changed,
        validated.receipt,
        ScientificPreflight(
            payload_final=True,
            citations_checked_against_pages=True,
            contradictions_addressed=True,
            activation_and_partition_reviewed=True,
        ),
    )
    assert mismatched.status == "condition" and mismatched.code == "validation_receipt_mismatch"
    preflight = ScientificPreflight(
        payload_final=True,
        citations_checked_against_pages=True,
        contradictions_addressed=True,
        activation_and_partition_reviewed=True,
    )
    saved = commit_domain_judgment(workspace, payload, validated.receipt, preflight)
    assert isinstance(saved, JudgmentSaved)
    assert commit_domain_judgment(workspace, payload, validated.receipt, preflight) == saved
    correction = payload.model_copy(
        update={
            "limitations": ("A reviewed correction.",),
            "expected_previous_hash": saved.active_hash,
        }
    )
    revised_validation = validate_domain_judgment(workspace, correction)
    assert isinstance(revised_validation, JudgmentValidated)
    revised = commit_domain_judgment(workspace, correction, revised_validation.receipt, preflight)
    assert isinstance(revised, JudgmentRevised)
    replay = commit_domain_judgment(workspace, correction, revised_validation.receipt, preflight)
    assert isinstance(replay, JudgmentSaved)
    assert (
        replay.active_hash == revised.active_hash
        and replay.active_revision == revised.active_revision
    )


def test_validation_never_creates_or_touches_workspace_storage(tmp_path: Path) -> None:
    payload = DomainJudgmentPayload(
        trial_id="t",
        result_id="r",
        domain_id="domain:randomization",
        active_answers=(),
        inactive_questions=(),
        final_judgment=None,
        override=None,
        limitations=(),
        actor="reviewer",
        observed_at=OBSERVED,
    )
    absent = validate_domain_judgment(tmp_path, payload)
    assert absent.status == "condition" and absent.code == "batch_not_approved"
    assert list(tmp_path.iterdir()) == []

    workspace, source = approved_workspace(tmp_path)
    active, inactive = _answers("domain:randomization", source)
    valid = payload.model_copy(update={"active_answers": active, "inactive_questions": inactive})
    before = {
        path.relative_to(workspace).as_posix(): (path.read_bytes(), os.stat(path).st_mtime_ns)
        for path in workspace.rglob("*")
        if path.is_file()
    }
    assert isinstance(validate_domain_judgment(workspace, valid), JudgmentValidated)
    after = {
        path.relative_to(workspace).as_posix(): (path.read_bytes(), os.stat(path).st_mtime_ns)
        for path in workspace.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_validation_receipt_rejects_drift_and_cross_use(tmp_path: Path) -> None:
    workspace, source = approved_workspace(tmp_path)
    active, inactive = _answers("domain:randomization", source)
    payload = DomainJudgmentPayload(
        trial_id="t",
        result_id="r",
        domain_id="domain:randomization",
        active_answers=active,
        inactive_questions=inactive,
        final_judgment=None,
        override=None,
        limitations=(),
        actor="reviewer",
        observed_at=OBSERVED,
    )
    validated = validate_domain_judgment(workspace, payload)
    assert isinstance(validated, JudgmentValidated)
    preflight = ScientificPreflight(
        payload_final=True,
        citations_checked_against_pages=True,
        contradictions_addressed=True,
        activation_and_partition_reviewed=True,
    )
    for receipt in (
        validated.receipt.model_copy(update={"commit_token": "sha256:" + "0" * 64}),
        validated.receipt.model_copy(update={"approved_batch_hash": "sha256:" + "1" * 64}),
        validated.receipt.model_copy(update={"pack_identities_hash": "sha256:" + "2" * 64}),
        validated.receipt.model_copy(update={"domain_id": "domain:missing"}),
    ):
        result = commit_domain_judgment(workspace, payload, receipt, preflight)
        assert result.status == "condition" and result.code == "validation_receipt_mismatch"

    saved = commit_domain_judgment(workspace, payload, validated.receipt, preflight)
    assert isinstance(saved, JudgmentSaved)
    correction = payload.model_copy(
        update={
            "limitations": ("Validated correction.",),
            "expected_previous_hash": saved.active_hash,
        }
    )
    stale_validation = validate_domain_judgment(workspace, correction)
    assert isinstance(stale_validation, JudgmentValidated)
    competing = correction.model_copy(update={"limitations": ("Competing correction.",)})
    assert isinstance(
        _save(
            workspace,
            source,
            limitations=competing.limitations,
            expected_previous_hash=saved.active_hash,
        ),
        JudgmentRevised,
    )
    stale = commit_domain_judgment(workspace, correction, stale_validation.receipt, preflight)
    assert isinstance(stale, JudgmentConflict)


def test_commit_rolls_back_when_audit_index_write_fails(tmp_path: Path, monkeypatch) -> None:
    workspace, source = approved_workspace(tmp_path)
    first = _save(workspace, source)
    assert isinstance(first, JudgmentSaved)
    payload = DomainJudgmentPayload(
        trial_id="t",
        result_id="r",
        domain_id="domain:randomization",
        active_answers=_answers("domain:randomization", source)[0],
        inactive_questions=_answers("domain:randomization", source)[1],
        final_judgment=None,
        override=None,
        limitations=("Rollback test.",),
        actor="reviewer",
        observed_at=OBSERVED,
        expected_previous_hash=first.active_hash,
    )
    validated = validate_domain_judgment(workspace, payload)
    assert isinstance(validated, JudgmentValidated)
    from rob2_kit import judgments

    original = judgments.canonical_json_bytes

    def fail_index(value: object) -> bytes:
        if isinstance(value, judgments.JudgmentRevisionIndex) and value.active_revision == 2:
            raise OSError("injected index write failure")
        return original(value)

    monkeypatch.setattr(judgments, "canonical_json_bytes", fail_index)
    with pytest.raises(OSError, match="injected"):
        commit_domain_judgment(
            workspace,
            payload,
            validated.receipt,
            ScientificPreflight(
                payload_final=True,
                citations_checked_against_pages=True,
                contradictions_addressed=True,
                activation_and_partition_reviewed=True,
            ),
        )
    key = judgment_key(first.judgment.approved_batch_hash, "t", "r", first.judgment.domain_id)
    with transaction(workspace) as connection:
        active = DomainJudgment.model_validate_json(
            bytes(
                connection.execute("SELECT payload FROM records WHERE name=?", (key,)).fetchone()[0]
            )
        )
        assert active == first.judgment
        assert (
            connection.execute(
                "SELECT 1 FROM records WHERE name=?", (revision_key(key, 2),)
            ).fetchone()
            is None
        )


def test_concurrent_corrections_leave_one_active_revision(tmp_path: Path) -> None:
    workspace, source = approved_workspace(tmp_path)
    first = _save(workspace, source)
    assert isinstance(first, JudgmentSaved)
    start = Barrier(2)
    results: list[JudgmentRevised | JudgmentConflict] = []

    def correct(limitation: str) -> None:
        start.wait()
        result = _save(
            workspace,
            source,
            limitations=(limitation,),
            expected_previous_hash=first.judgment.checkpoint_hash,
        )
        assert isinstance(result, JudgmentRevised | JudgmentConflict)
        results.append(result)

    threads = [
        Thread(target=correct, args=("Correction one.",)),
        Thread(target=correct, args=("Correction two.",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()
    assert sum(isinstance(result, JudgmentRevised) for result in results) == 1
    assert sum(isinstance(result, JudgmentConflict) for result in results) == 1
    assert all(result.active_revision == 2 for result in results)


def test_two_valid_receipts_race_to_one_revision(tmp_path: Path) -> None:
    workspace, source = approved_workspace(tmp_path)
    first = _save(workspace, source)
    assert isinstance(first, JudgmentSaved)
    barrier = Barrier(2)
    results: list[JudgmentRevised | JudgmentConflict] = []
    preflight = ScientificPreflight(
        payload_final=True,
        citations_checked_against_pages=True,
        contradictions_addressed=True,
        activation_and_partition_reviewed=True,
    )

    def commit(limitation: str) -> None:
        active, inactive = _answers("domain:randomization", source)
        payload = DomainJudgmentPayload(
            trial_id="t",
            result_id="r",
            domain_id="domain:randomization",
            active_answers=active,
            inactive_questions=inactive,
            final_judgment=None,
            override=None,
            limitations=(limitation,),
            actor="reviewer",
            observed_at=OBSERVED,
            expected_previous_hash=first.active_hash,
        )
        validated = validate_domain_judgment(workspace, payload)
        assert isinstance(validated, JudgmentValidated)
        barrier.wait()
        result = commit_domain_judgment(workspace, payload, validated.receipt, preflight)
        assert isinstance(result, JudgmentRevised | JudgmentConflict)
        results.append(result)

    threads = [Thread(target=commit, args=(value,)) for value in ("one", "two")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()
    assert sum(isinstance(result, JudgmentRevised) for result in results) == 1
    assert sum(isinstance(result, JudgmentConflict) for result in results) == 1


def test_tampered_approved_identity_fails_every_replay_gate(tmp_path: Path) -> None:
    from rob2_kit.batch import ApprovedBatch, current_batch

    workspace, source = approved_workspace(tmp_path)
    approved = current_batch(workspace)
    assert isinstance(approved, ApprovedBatch)
    tampered = approved.model_copy(
        update={
            "proposal": approved.proposal.model_copy(
                update={
                    "result_specs": (
                        approved.proposal.result_specs[0].model_copy(
                            update={"effect_of_interest": "tampered"}
                        ),
                    )
                }
            )
        }
    )
    with transaction(workspace) as connection:
        connection.execute(
            "UPDATE records SET payload=? WHERE name='active_batch'",
            (canonical_json_bytes(tampered),),
        )
    assert current_batch(workspace).status == "stale"
    assert approve_batch(workspace).state.status == "stale"
    assert save_proposal(workspace, approved.proposal).state.status == "stale"
    active, inactive = _answers("domain:randomization", source)
    validation = validate_domain_judgment(
        workspace,
        DomainJudgmentPayload(
            trial_id="t",
            result_id="r",
            domain_id="domain:randomization",
            active_answers=active,
            inactive_questions=inactive,
            final_judgment=None,
            override=None,
            limitations=(),
            actor="reviewer",
            observed_at=OBSERVED,
        ),
    )
    assert validation.status == "condition" and validation.code == "batch_stale"


def test_revision_key_is_collision_safe_for_composite_identifiers() -> None:
    left = judgment_key("sha256:" + "a" * 64, "trial_a", "result_b", "domain:c")
    right = judgment_key("sha256:" + "a" * 64, "trial", "a:result_b", "domain:c")
    percent = judgment_key("sha256:" + "a" * 64, "trial_%", "result", "domain:c")
    assert len({revision_key(left, 1), revision_key(right, 1), revision_key(percent, 1)}) == 3

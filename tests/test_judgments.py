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
    EvidenceUse,
    InactiveQuestion,
    Override,
    TextEvidenceRef,
    VisualEvidenceRef,
)
from rob2_kit.judgments import (
    JudgmentConflict,
    JudgmentRevised,
    JudgmentSaved,
    checkpoint_content,
    judgment_key,
    revision_key,
    save_domain_judgment,
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
    return save_domain_judgment(
        workspace,
        trial_id,
        result_id,
        domain_id,
        active if active_answers is None else active_answers,
        inactive if inactive_questions is None else inactive_questions,
        final_judgment,
        override,
        limitations,
        actor,
        observed_at,
        expected_previous_hash,
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
    with pytest.raises(ValueError, match="partition"):
        save_domain_judgment(
            workspace,
            "t",
            "r",
            domain_id,
            active,
            (*inactive, InactiveQuestion(question_id=active[0].question_id)),
            None,
            None,
            (),
            actor="reviewer",
            observed_at=OBSERVED,
        )


def test_evidence_is_exact_and_visual_is_attributable(tmp_path: Path) -> None:
    workspace, source = approved_workspace(tmp_path)
    active, inactive = _answers("domain:randomization", source)
    bad_ref = active[0].evidence_uses[0].refs[0].model_copy(update={"quote": "wrong"})
    bad_use = active[0].evidence_uses[0].model_copy(update={"refs": (bad_ref,)})
    with pytest.raises(ValueError, match="coordinates"):
        _save(
            workspace,
            source,
            active_answers=(
                active[0].model_copy(update={"evidence_uses": (bad_use,)}),
                *active[1:],
            ),
        )
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
    with pytest.raises(ValueError, match="ResultSpec"):
        _save(workspace, source, trial_id="other")
    with pytest.raises(ValueError, match="override"):
        _save(workspace, source, final_judgment=Judgment.HIGH)
    with pytest.raises(ValueError, match="UTC"):
        _save(workspace, source, observed_at=datetime(2026, 8, 13))
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
        with pytest.raises(ValueError, match="integrity"):
            _save(workspace, source)
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


def test_revision_key_is_collision_safe_for_composite_identifiers() -> None:
    left = judgment_key("sha256:" + "a" * 64, "trial_a", "result_b", "domain:c")
    right = judgment_key("sha256:" + "a" * 64, "trial", "a:result_b", "domain:c")
    percent = judgment_key("sha256:" + "a" * 64, "trial_%", "result", "domain:c")
    assert len({revision_key(left, 1), revision_key(right, 1), revision_key(percent, 1)}) == 3

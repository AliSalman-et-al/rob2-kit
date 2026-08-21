from __future__ import annotations

import hashlib
import json
import shutil

# ruff: noqa: E501
from pathlib import Path

import pytest

from rob2_kit.application._state import identity, write_jsons
from rob2_kit.application.finalization import (
    FinalizationCounts,
    finalize_batch,
    verify_finalization,
    verify_finalization_result,
)


def _rehash_manifest(bundle: Path) -> None:
    """Make a tampered bundle internally hash-consistent for verifier attacks."""
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = []
    for path in sorted(p for p in bundle.rglob("*") if p.is_file() and p != manifest_path):
        relative = path.relative_to(bundle).as_posix()
        files.append(
            {"path": relative, "sha256": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()}
        )
    base = {"summary_hash": manifest["summary_hash"], "files": files}
    manifest_path.write_text(
        json.dumps(
            {
                **base,
                "manifest_hash": "sha256:"
                + hashlib.sha256(
                    json.dumps(base, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )


def test_application_adverse_events_bundle_is_independently_verified(tmp_path: Path) -> None:
    """The evaluator must accept a complete AE application workflow bundle."""

    # This is intentionally a real application path: capture, Proposal Review,
    # researcher acknowledgment, approval, finalization, then independent verify.
    from test_application_proposal import _card

    from rob2_kit.application.contracts import ReviewAuthority
    from rob2_kit.application.evidence import (
        EvidenceRetrievalRequest,
        ManualSelectionRequest,
        retrieve_evidence,
    )
    from rob2_kit.application.intake import (
        CaptureRequest,
        IntakePlanEntry,
        SourceCriticality,
        SourceDisposition,
        acknowledge_intake,
        capture_batch,
        save_intake_plan,
    )
    from rob2_kit.application.preflight import (
        AuthorizedSourceRoot,
        PreflightRequest,
        preflight_sources,
    )
    from rob2_kit.application.proposal import (
        ApprovalRequest,
        ComparisonGroup,
        EvidenceSet,
        NeedsInputReason,
        OutcomeMeasurementCoverage,
        PopulationAccount,
        PreapprovalNeedsInput,
        ProposalInput,
        ProposalRepairReceipt,
        Quantity,
        ResultTarget,
        acknowledge_proposal,
        approve_batch,
        save_proposal,
    )
    from rob2_kit.evaluation.manifest import CHAARTED_MANIFEST
    from rob2_kit.evaluation.verifier import verify_artifact

    (tmp_path / "article.txt").write_text("docetaxel Grade 3 4 5", encoding="utf-8")
    preflight = preflight_sources(
        tmp_path,
        PreflightRequest(roots=(AuthorizedSourceRoot(alias="trial", path=".", trial_id="chaarted"),)),
    )
    plan = save_intake_plan(
        tmp_path,
        preflight.reference,
        (IntakePlanEntry(candidate_identity=preflight.candidates[0].identity, role="main_article", disposition=SourceDisposition.INCLUDE, criticality=SourceCriticality.REQUIRED),),
    )
    capture_batch(tmp_path, CaptureRequest(plan=plan.plan, acknowledgment=acknowledge_intake(tmp_path, plan.plan, ReviewAuthority.HOST)))
    evidence = retrieve_evidence(tmp_path, EvidenceRetrievalRequest(trial_id="chaarted", manual_selections=(ManualSelectionRequest(kind="manual_selection", source_alias="s1", page=1, start=0, end=9, quote="docetaxel"),))).evidence[0]
    original = _card()
    card = original.model_copy(update={
        "evidence": EvidenceSet(target_basis=(evidence,), reported_values=(evidence,), reported_context=(evidence,), population_basis=(evidence,)),
        "target": ResultTarget(outcome_definition="adverse events during the docetaxel-containing regimen", measurement="CTCAE severity grade", time_point_or_window="during docetaxel-containing regimen follow-up", effect_of_interest="adverse-event profile", comparison_groups=(ComparisonGroup(id="docetaxel", label="ADT plus docetaxel"), ComparisonGroup(id="adt", label="ADT alone")), intended_analysis_population="390 patients receiving the docetaxel-containing regimen with follow-up data", intended_effect_measure="adverse-event profile"),
        "reported": original.reported.model_copy(update={"group_id": "ADT plus docetaxel", "categories": (Quantity(statistic="count", unit="390 docetaxel-cohort patients with follow-up", group_or_category="Grade 3 any event", value="65 (16.7%)"), Quantity(statistic="count", unit="390 docetaxel-cohort patients with follow-up", group_or_category="Grade 4 any event", value="49 (12.6%)"), Quantity(statistic="count", unit="390 docetaxel-cohort patients with follow-up", group_or_category="Grade 5 any event", value="1 (0.3%)"))}),
        "population": PopulationAccount(analyzed_population="390 patients receiving the docetaxel-containing regimen with follow-up data", outcome_measurement_coverage=(OutcomeMeasurementCoverage(group_id="docetaxel", status="measured"), OutcomeMeasurementCoverage(group_id="adt", status="not_measured", explanation="ADT-alone comparator unavailable"))),
    })
    review = save_proposal(tmp_path, ProposalInput(outcome_statement="Adverse events", results=(card,), needs_input=(PreapprovalNeedsInput(trial_id="chaarted", reason=NeedsInputReason.COMPARATOR_UNAVAILABLE, missing_facts=("ADT-alone comparator unavailable",)),)))
    assert not isinstance(review, ProposalRepairReceipt)
    ack = acknowledge_proposal(tmp_path, review.review, caller="server:interactive")
    assert review.transition is not None
    approve_batch(tmp_path, ApprovalRequest(transition=review.transition, acknowledgment=ack))
    finalized = finalize_batch(tmp_path)
    assert finalized.outcome == "success"
    verified = verify_artifact(tmp_path / finalized.artifact.bundle_path, CHAARTED_MANIFEST, "adverse_events")
    assert verified.ok, verified.failures

    bundle = tmp_path / finalized.artifact.bundle_path
    for name in (
        "trial-outcome-chaarted.json",
        "proposal_ack.json",
        "proposal_review.json",
        "finalization-receipt.json",
    ):
        tampered = tmp_path / f"tampered-{name}"
        shutil.copytree(bundle, tampered)
        (tampered / "records" / name).unlink()
        assert not verify_artifact(tampered, CHAARTED_MANIFEST, "adverse_events").ok


def test_application_assessed_bundle_is_independently_verified_and_rejects_missing_basis(
    tmp_path: Path,
) -> None:
    """Exercise the complete assessed application path without manufacturing records."""

    from rob2_kit.application.contracts import ReviewAuthority, TrialDisposition
    from rob2_kit.application.domains import (
        DomainAnswerInput,
        DomainDraftInput,
        DomainEvidenceUseInput,
        DomainValidationRequest,
        commit_domain_judgment,
        prepare_domain_packet,
        validate_domain_judgment,
    )
    from rob2_kit.application.evidence import (
        EvidenceRetrievalRequest,
        ManualSelectionRequest,
        retrieve_evidence,
    )
    from rob2_kit.application.intake import (
        CaptureRequest,
        IntakePlanEntry,
        SourceCriticality,
        SourceDisposition,
        acknowledge_intake,
        capture_batch,
        save_intake_plan,
    )
    from rob2_kit.application.preflight import (
        AuthorizedSourceRoot,
        PreflightRequest,
        preflight_sources,
    )
    from rob2_kit.application.proposal import (
        ApprovalRequest,
        ClarityDeclaration,
        ClarityItem,
        ComparativeEffect,
        ComparisonGroup,
        EvidenceSet,
        OutcomeMeasurementCoverage,
        PopulationAccount,
        ProposalInput,
        ProposalRepairReceipt,
        Quantity,
        ResultCardInput,
        ResultTarget,
        acknowledge_proposal,
        approve_batch,
        save_proposal,
    )
    from rob2_kit.application.trials import (
        TrialFinishCandidate,
        TrialFinishRequest,
        acknowledge_trial_finish,
        finish_trial,
        prepare_trial_finish,
    )
    from rob2_kit.evaluation.manifest import CHAARTED_MANIFEST
    from rob2_kit.evaluation.verifier import verify_artifact
    from rob2_kit.judgment_models import EvidenceRelationship
    from rob2_kit.models import Answer
    from rob2_kit.packs import SCIENTIFIC_PACK

    source = (
        "PFS evidence: time to biochemical, symptomatic, or radiographic progression; "
        "median time to progression; follow-up analysis; randomized patients; "
        "ADT plus docetaxel 20.2 months; ADT alone 11.7 months; "
        "hazard ratio 0.61 (95% CI 0.51 to 0.72; P<0.001). "
        "comparative time-to-event efficacy result."
    )
    (tmp_path / "article.txt").write_text(source, encoding="utf-8")
    preflight = preflight_sources(
        tmp_path,
        PreflightRequest(
            roots=(AuthorizedSourceRoot(alias="trial", path=".", trial_id="chaarted"),)
        ),
    )
    plan = save_intake_plan(
        tmp_path,
        preflight.reference,
        (
            IntakePlanEntry(
                candidate_identity=preflight.candidates[0].identity,
                role="main_article",
                disposition=SourceDisposition.INCLUDE,
                criticality=SourceCriticality.REQUIRED,
            ),
        ),
    )
    intake_ack = acknowledge_intake(tmp_path, plan.plan, ReviewAuthority.HOST)
    capture_batch(tmp_path, CaptureRequest(plan=plan.plan, acknowledgment=intake_ack))
    evidence = retrieve_evidence(
        tmp_path,
        EvidenceRetrievalRequest(
            trial_id="chaarted",
            manual_selections=(
                ManualSelectionRequest(
                    kind="manual_selection", source_alias="s1", page=1,
                    start=0, end=len(source), quote=source,
                ),
            ),
        ),
    ).evidence[0]
    specified = ClarityDeclaration(
        **{
            name: ClarityItem(state="specified")
            for name in (
                "outcome_definition", "measurement", "time_point", "analysis_population",
                "comparison_groups", "effect_measure", "source_table_meaning",
                "choice_among_eligible_results",
            )
        }
    )
    card = ResultCardInput(
        trial_id="chaarted",
        target=ResultTarget(
            outcome_definition="time to biochemical, symptomatic, or radiographic progression",
            measurement="median time to progression",
            time_point_or_window="follow-up analysis",
            effect_of_interest="hazard ratio",
            comparison_groups=(
                ComparisonGroup(id="docetaxel", label="ADT plus docetaxel"),
                ComparisonGroup(id="adt", label="ADT alone"),
            ),
            intended_analysis_population="randomized patients",
            intended_effect_measure="hazard ratio",
        ),
        reported=ComparativeEffect(
            form="comparative_effect",
            effect_measure="hazard ratio",
            effect=Quantity(
                statistic="hazard ratio", unit="time-to-event analysis",
                group_or_category="ADT plus docetaxel versus ADT alone",
                value="0.61 (95% CI 0.51 to 0.72; P<0.001)",
            ),
            comparison_groups=("docetaxel", "adt"),
        ),
        population=PopulationAccount(
            analyzed_population="randomized patients",
            outcome_measurement_coverage=(
                OutcomeMeasurementCoverage(group_id="docetaxel", status="measured"),
                OutcomeMeasurementCoverage(group_id="adt", status="measured"),
            ),
        ),
        source_table_meaning=(
            "comparative time-to-event efficacy result; ADT plus docetaxel median 20.2 months; "
            "ADT alone median 11.7 months"
        ),
        evidence=EvidenceSet(
            target_basis=(evidence,), reported_values=(evidence,),
            reported_context=(evidence,), population_basis=(evidence,),
        ),
        clarity=specified,
    )
    proposal = save_proposal(tmp_path, ProposalInput(outcome_statement="Progression-free survival", results=(card,)))
    assert not isinstance(proposal, ProposalRepairReceipt)
    assert proposal.transition is not None
    proposal_ack = acknowledge_proposal(tmp_path, proposal.review, caller="server:interactive")
    approved = approve_batch(
        tmp_path, ApprovalRequest(transition=proposal.transition, acknowledgment=proposal_ack)
    )

    answer_paths = {
        "domain:randomization": {
            "sq:randomization:sequence": Answer.YES,
            "sq:randomization:concealment": Answer.YES,
            "sq:randomization:baseline-imbalance": Answer.NO,
        },
        "domain:deviations": {
            "sq:deviations:participants-aware": Answer.NO,
            "sq:deviations:personnel-aware": Answer.NO,
            "sq:deviations:appropriate-analysis": Answer.YES,
        },
        "domain:missing": {"sq:missing:data-available": Answer.YES},
        "domain:measurement": {
            "sq:measurement:method-inappropriate": Answer.NO,
            "sq:measurement:differential": Answer.NO,
            "sq:measurement:assessor-aware": Answer.YES,
            "sq:measurement:influence-possible": Answer.NO,
        },
        "domain:selection": {
            "sq:selection:prespecified-analysis": Answer.YES,
            "sq:selection:multiple-measurements": Answer.NO,
            "sq:selection:multiple-analyses": Answer.NO,
        },
    }
    for domain in SCIENTIFIC_PACK.domains:
        packet = prepare_domain_packet(
            tmp_path, approved.approved_batch, trial_id="chaarted", domain_id=domain.id
        )
        draft = DomainDraftInput(
            active_answers=tuple(
                DomainAnswerInput(
                    question_id=question_id, answer=answer,
                    rationale="The captured trial report supports this deterministic answer.",
                    evidence_uses=(
                        DomainEvidenceUseInput(
                                relationship=EvidenceRelationship.SUPPORTING,
                            claim="The captured trial report is the basis for this answer.",
                            rationale="The exact evidence record is in the trial scope.",
                            evidence=(evidence,),
                        ),
                    ),
                )
                for question_id, answer in answer_paths[domain.id].items()
            )
        )
        validated = validate_domain_judgment(
            tmp_path, DomainValidationRequest(packet=packet, draft=draft)
        )
        assert validated.outcome == "success"
        commit_domain_judgment(tmp_path, validated.transition)

    prepared = prepare_trial_finish(
        tmp_path, approved.approved_batch, TrialFinishCandidate(disposition=TrialDisposition.ASSESSED)
    )
    assert prepared.transition is not None and prepared.synthesis is not None
    finish_ack = acknowledge_trial_finish(tmp_path, prepared.transition, caller="server:interactive")
    finished = finish_trial(
        tmp_path,
        TrialFinishRequest(transition=prepared.transition, acknowledgment=finish_ack),
        caller="server:interactive",
    )
    assert finished.disposition is TrialDisposition.ASSESSED
    finalized = finalize_batch(tmp_path)
    assert finalized.outcome == "success"
    bundle = tmp_path / finalized.artifact.bundle_path
    verified = verify_artifact(bundle, CHAARTED_MANIFEST, "pfs")
    assert verified.ok, verified.failures

    missing_evidence = tmp_path / "rehashed-missing-evidence"
    shutil.copytree(bundle, missing_evidence)
    next((missing_evidence / "records").glob("evidence-*.json")).unlink()
    _rehash_manifest(missing_evidence)
    assert not verify_artifact(missing_evidence, CHAARTED_MANIFEST, "pfs").ok

    wrong_pack = tmp_path / "rehashed-wrong-pack"
    shutil.copytree(bundle, wrong_pack)
    observation_path = next((wrong_pack / "records").glob("domain-observation-*.json"))
    observation = json.loads(observation_path.read_text(encoding="utf-8"))
    observation["scientific_pack"] = "sha256:" + "0" * 64
    candidate_fields = (
        "kind", "packet", "trial_id", "result_id", "domain_id", "draft", "proposed_judgment",
        "inactive_questions", "evidence_bindings", "scientific_pack", "policy_pack",
    )
    observation["identity"] = "sha256:" + hashlib.sha256(
        json.dumps(
            {key: observation[key] for key in candidate_fields}, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    observation_path.write_text(json.dumps(observation, sort_keys=True), encoding="utf-8")
    _rehash_manifest(wrong_pack)
    rejected = verify_artifact(wrong_pack, CHAARTED_MANIFEST, "pfs")
    assert not rejected.ok
    assert any("pack" in failure for failure in rejected.failures)

    for record in next((bundle / "records").glob("domain-observation-*.json")), next(
        (bundle / "records").glob("assessment-snapshot-*.json")
    ):
        tampered = tmp_path / f"missing-{record.name}"
        shutil.copytree(bundle, tampered)
        (tampered / "records" / record.name).unlink()
        assert not verify_artifact(tampered, CHAARTED_MANIFEST, "pfs").ok

    # This is not a deletion attack: the snapshot gets a new valid identity and
    # the enclosing manifest is regenerated.  The independent deterministic
    # synthesis/checkpoint chain must still reject the changed final judgment.
    tampered = tmp_path / "rehashed-snapshot"
    shutil.copytree(bundle, tampered)
    snapshot_path = next((tampered / "records").glob("assessment-snapshot-*.json"))
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    snapshot["final_judgment"] = "high"
    payload = {
        key: snapshot[key]
        for key in (
            "synthesis", "checkpoint_hashes", "proposed_overall", "final_judgment", "caller", "observed_at"
        )
    }
    snapshot["identity"] = "sha256:" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    snapshot["snapshot_hash"] = snapshot["identity"]
    snapshot_path.write_text(json.dumps(snapshot, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    _rehash_manifest(tampered)
    assert not verify_artifact(tampered, CHAARTED_MANIFEST, "pfs").ok


def test_finalize_requires_all_terminal_dispositions(tmp_path: Path) -> None:
    approved = identity({"approved": True})
    write_jsons(tmp_path, {"state.json": {"phase": "assessment", "approved_batch_identity": approved, "trial_dispositions": {"trial": "pending"}}})
    result = finalize_batch(tmp_path)
    assert result.outcome == "condition"
    assert "did not occur" in result.detail


def test_finalize_is_idempotent_and_artifact_verification_fails_closed(tmp_path: Path) -> None:
    approved = identity({"approved": True})
    outcome_identity = identity({"trial": "trial", "disposition": "needs_input"})
    write_jsons(tmp_path, {"captured_batch.json": {"kind": "captured_batch", "identity": identity({"captured": True}), "sources": []}, "state.json": {"phase": "ready_to_finalize", "approved_batch_identity": approved, "trial_dispositions": {"trial": "needs_input"}}, "trial-outcome-trial.json": {"kind": "trial_outcome", "identity": outcome_identity, "trial_id": "trial", "disposition": "needs_input", "rationale": "missing result", "synthesis": {"kind": "approved_batch", "identity": approved, "uri": f"rob2://detail/approved_batch/{approved}"}, "snapshot": None, "observed_at": "2026-01-01T00:00:00Z"}})
    first = finalize_batch(tmp_path)
    assert first.outcome == "success"
    second = finalize_batch(tmp_path)
    assert first == second
    assert first.counts.total == 1
    assert "No RoB 2 assessments were completed." in first.presentation.summary
    assert verify_finalization(tmp_path, first.artifact)
    (tmp_path / first.artifact.bundle_path / "summary.json").write_text("{}", encoding="utf-8")
    assert not verify_finalization(tmp_path, first.artifact)
    retry = finalize_batch(tmp_path)
    assert retry.outcome == "condition"
    assert retry.code == "finalization_corrupt"


@pytest.mark.parametrize("field", ("counts", "presentation", "summary", "artifact"))
def test_finalization_result_rejects_every_saved_receipt_field(tmp_path: Path, field: str) -> None:
    approved = identity({"approved": True})
    outcome_identity = identity({"trial": "trial", "disposition": "needs_input"})
    write_jsons(tmp_path, {"captured_batch.json": {"kind": "captured_batch", "identity": identity({"captured": True}), "sources": []}, "state.json": {"phase": "ready_to_finalize", "approved_batch_identity": approved, "trial_dispositions": {"trial": "needs_input"}}, "trial-outcome-trial.json": {"kind": "trial_outcome", "identity": outcome_identity, "trial_id": "trial", "disposition": "needs_input", "synthesis": {"kind": "approved_batch", "identity": approved, "uri": f"rob2://detail/approved_batch/{approved}"}, "snapshot": None, "observed_at": "2026-01-01T00:00:00Z"}})
    saved = finalize_batch(tmp_path)
    assert saved.outcome == "success"
    if field == "counts":
        changed = saved.model_copy(update={"counts": FinalizationCounts(total=9, pending=0, assessed=0, needs_input=9, failed=0)})
    elif field == "presentation":
        changed = saved.model_copy(update={"presentation": saved.presentation.model_copy(update={"summary": "forged"})})
    elif field == "summary":
        changed = saved.model_copy(update={"summary": saved.summary.model_copy(update={"identity": "sha256:" + "0" * 64})})
    else:
        changed = saved.model_copy(update={"artifact": saved.artifact.model_copy(update={"file_count": 99})})
    assert verify_finalization_result(tmp_path, changed) is None

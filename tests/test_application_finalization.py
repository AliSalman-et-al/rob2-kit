from __future__ import annotations

import hashlib
import json
import shutil

# ruff: noqa: E501
from pathlib import Path

import pymupdf
import pytest

from rob2_kit.application._state import identity, read_json, write_jsons
from rob2_kit.application.finalization import (
    FinalizationCounts,
    finalize_batch,
    verify_finalization,
    verify_finalization_result,
)
from rob2_kit.evaluation.trace import TraceEvent
from rob2_kit.reports import application_finalization_report


def test_application_report_uses_persisted_records_and_escapes_content() -> None:
    report = application_finalization_report(
        {
            "identity": "sha256:summary",
            "approved_batch": {"identity": "sha256:batch"},
            "presentation": {
                "code": "finalized_all_assessed",
                "headline": "Complete",
                "summary": "<safe>",
            },
            "trials": [
                {
                    "trial_id": "trial",
                    "disposition": "assessed",
                    "snapshot": {"identity": "sha256:snapshot"},
                }
            ],
        },
        [
            {"kind": "approved_batch", "identity": "sha256:batch", "review": "sha256:proposal"},
            {
                "kind": "proposal_review",
                "identity": "sha256:proposal",
                "results": [
                    {
                        "trial_id": "trial",
                        "target": {
                            "outcome_definition": "survival <script>",
                            "measurement": "time to event",
                            "time_point_or_window": "follow-up",
                            "intended_analysis_population": "randomized participants",
                        },
                        "reported": {
                            "reported_text": "Median survival was <reported>.",
                            "quantities": [
                                {
                                    "group_or_category": "treatment",
                                    "value": "20.2",
                                    "unit": "months",
                                    "denominator_basis": None,
                                }
                            ],
                        },
                        "evidence": {"reported_values": [{"identity": "sha256:proposal-evidence"}]},
                    }
                ],
            },
            {
                "kind": "assessment_snapshot",
                "identity": "sha256:snapshot",
                "trial_id": "trial",
                "checkpoint_hashes": [
                    ["domain:measurement", "sha256:measurement-checkpoint"],
                    ["domain:randomization", "sha256:checkpoint"],
                ],
            },
            {
                "kind": "domain_candidate",
                "active_hash": "sha256:checkpoint",
                "trial_id": "trial",
                "domain_id": "domain:randomization",
                "proposed_judgment": "low",
                "draft": {
                    "active_answers": [
                        {
                            "question_id": "sq:randomization:sequence",
                            "answer": "yes <answer>",
                            "rationale": "Answer rationale & <details>",
                            "evidence_uses": [
                                {
                                    "relationship": "supporting",
                                    "claim": "Claim <claim>",
                                    "rationale": "Evidence-use rationale & <reason>",
                                    "evidence": [
                                        {"kind": "evidence", "identity": "sha256:evidence"},
                                        {"kind": "evidence", "identity": "sha256:evidence"},
                                        {
                                            "kind": "evidence",
                                            "identity": "sha256:missing-evidence",
                                        },
                                    ],
                                }
                            ],
                        }
                    ],
                    "limitations": ["Limitation <note>"],
                },
                "inactive_questions": ["sq:randomization:baseline-imbalance"],
                "evidence_bindings": [
                    {
                        "evidence": {"identity": "sha256:evidence"},
                        "source_id": "<source>",
                        "page": 1,
                        "start": 4,
                        "end": 28,
                        "quote": "Exact <quote> & provenance",
                    }
                ],
            },
            {
                "kind": "domain_candidate",
                "active_hash": "sha256:checkpoint",
                "trial_id": "trial",
                "domain_id": "domain:wrong-domain",
                "proposed_judgment": "high",
                "draft": {
                    "active_answers": [
                        {
                            "question_id": "sq:wrong-domain:unique",
                            "answer": "Wrong-domain answer unique",
                            "rationale": "Wrong-domain rationale unique",
                        }
                    ]
                },
                "evidence_bindings": [],
            },
            {
                "kind": "domain_candidate",
                "active_hash": "sha256:measurement-checkpoint",
                "trial_id": "trial",
                "domain_id": "domain:measurement",
                "proposed_judgment": "low",
                "draft": {"active_answers": []},
                "evidence_bindings": [],
            },
            {
                "kind": "domain_candidate",
                "active_hash": "sha256:superseded",
                "trial_id": "trial",
                "domain_id": "domain:randomization",
                "proposed_judgment": "high",
                "draft": {
                    "active_answers": [
                        {
                            "question_id": "sq:superseded:unique",
                            "answer": "Superseded answer unique",
                            "rationale": "Superseded rationale unique",
                        }
                    ]
                },
                "evidence_bindings": [],
            },
        ],
    )
    assert "sha256:summary" in report
    assert "finalized_all_assessed" in report
    assert "domain:randomization" in report
    assert report.index("domain:measurement") < report.index("domain:randomization")
    assert "sha256:superseded" not in report
    assert "sq:superseded:unique" not in report
    assert "Superseded rationale unique" not in report
    assert "sq:wrong-domain:unique" not in report
    assert "Wrong-domain rationale unique" not in report
    assert "sha256:evidence" in report
    assert "sha256:missing-evidence" in report
    assert "binding unavailable" in report
    assert "sha256:proposal-evidence" in report and "20.2 months" in report
    assert "denominator: None" not in report
    assert "&lt;script&gt;" in report and "&lt;reported&gt;" in report
    assert "&lt;safe&gt;" in report and "&lt;source&gt;" in report
    assert 'class="question"' in report
    assert "sq:randomization:sequence" in report
    assert "yes &lt;answer&gt;" in report
    assert "Answer rationale &amp; &lt;details&gt;" in report
    assert "supporting" in report
    assert "Claim &lt;claim&gt;" in report
    assert "Evidence-use rationale &amp; &lt;reason&gt;" in report
    assert '"Exact &lt;quote&gt; &amp; provenance"' in report
    assert "Source: &lt;source&gt;; page 1; extent [4:28]" in report
    assert report.count('"Exact &lt;quote&gt; &amp; provenance"') == 1
    assert "sq:randomization:baseline-imbalance" in report
    assert "Limitation &lt;note&gt;" in report
    trial_start = report.index("<section><h2>trial</h2>")
    trial_end = report.index("</section>", trial_start)
    trial_section = report[trial_start : trial_end + len("</section>")]
    assert "sq:randomization:sequence" in trial_section
    assert trial_section.count("</section>") == 1


def test_application_report_keeps_problem_terminal_content_without_assessed_metadata() -> None:
    report = application_finalization_report(
        {
            "identity": "sha256:problem-summary",
            "trials": [
                {
                    "trial_id": "problem-trial",
                    "disposition": "needs_input",
                    "outcome": {"identity": "sha256:terminal"},
                }
            ],
        },
        [
            {
                "kind": "trial_terminal",
                "identity": "sha256:terminal",
                "trial_id": "problem-trial",
                "reason": "Outcome is unavailable <reason>",
                "missing_facts": ["Missing fact <detail>"],
                "evidence": [{"identity": "sha256:terminal-evidence"}],
                "acknowledgment": {"identity": "sha256:acknowledgment"},
            }
        ],
    )

    assert "Result: result" not in report
    assert "Assessment snapshot" not in report
    assert "Outcome is unavailable &lt;reason&gt;" in report
    assert "Missing fact &lt;detail&gt;" in report
    assert "sha256:terminal-evidence" in report
    assert "sha256:acknowledgment" in report


def test_application_report_domain_navigation_is_unique_across_trials() -> None:
    report = application_finalization_report(
        {
            "approved_batch": {"identity": "sha256:multi-batch"},
            "trials": [
                {
                    "trial_id": "trial-a",
                    "disposition": "assessed",
                    "snapshot": {"identity": "sha256:snapshot-a"},
                },
                {
                    "trial_id": "trial-b",
                    "disposition": "assessed",
                    "snapshot": {"identity": "sha256:snapshot-b"},
                },
            ],
        },
        [
            {
                "kind": "assessment_snapshot",
                "identity": "sha256:snapshot-a",
                "trial_id": "trial-a",
                "checkpoint_hashes": [["domain:a", "sha256:checkpoint-a"]],
                "final_judgment": "low",
            },
            {
                "kind": "assessment_snapshot",
                "identity": "sha256:snapshot-b",
                "trial_id": "trial-b",
                "checkpoint_hashes": [["domain:b", "sha256:checkpoint-b"]],
                "final_judgment": "low",
            },
            {
                "kind": "domain_candidate",
                "active_hash": "sha256:checkpoint-a",
                "trial_id": "trial-a",
                "domain_id": "domain:a",
                "proposed_judgment": "low",
                "draft": {"active_answers": []},
                "evidence_bindings": [],
            },
            {
                "kind": "domain_candidate",
                "active_hash": "sha256:checkpoint-b",
                "trial_id": "trial-b",
                "domain_id": "domain:b",
                "proposed_judgment": "low",
                "draft": {"active_answers": []},
                "evidence_bindings": [],
            },
        ],
    )

    for anchor in ("domain-1-1", "domain-2-1"):
        assert report.count(f'id="{anchor}"') == 1
        assert report.count(f'href="#{anchor}"') == 1
    assert report.index('href="#domain-1-1"') < report.index('href="#domain-2-1"')


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


def _rebind_packet_and_observation(bundle: Path, packet_path: Path) -> None:
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    previous_identity = packet["identity"]
    packet_fields = (
        "kind",
        "approved_batch",
        "trial_id",
        "result_id",
        "domain_id",
        "active_question_ids",
        "allowed_question_ids",
        "stable_aliases",
        "reusable_evidence",
        "prior_domain_hashes",
        "scientific_pack",
        "policy_pack",
    )
    packet["identity"] = identity({key: packet[key] for key in packet_fields})
    packet_path.write_text(json.dumps(packet, sort_keys=True), encoding="utf-8")
    observation_path = next(
        path
        for path in (bundle / "records").glob("domain-observation-*.json")
        if json.loads(path.read_text(encoding="utf-8")).get("packet", {}).get("identity")
        == previous_identity
    )
    observation = json.loads(observation_path.read_text(encoding="utf-8"))
    observation["packet"] = {
        "kind": "work_packet",
        "identity": packet["identity"],
        "uri": f"rob2://detail/work_packet/{packet['identity']}",
    }
    observation_fields = (
        "kind",
        "packet",
        "trial_id",
        "result_id",
        "domain_id",
        "draft",
        "proposed_judgment",
        "inactive_questions",
        "evidence_bindings",
        "scientific_pack",
        "policy_pack",
    )
    observation["identity"] = identity({key: observation[key] for key in observation_fields})
    observation_path.write_text(json.dumps(observation, sort_keys=True), encoding="utf-8")


def _rebind_text_evidence_coordinates(
    bundle: Path,
    text_path: Path,
    *,
    start: object,
    end: object,
    quote: str | None = None,
) -> None:
    text_record = json.loads(text_path.read_text(encoding="utf-8"))
    previous_identity = text_record["identity"]
    text_record["start"] = start
    text_record["end"] = end
    if quote is not None:
        text_record["quote"] = quote
        text_record["quote_sha256"] = "sha256:" + hashlib.sha256(quote.encode()).hexdigest()
    text_fields = (
        "kind",
        "trial_id",
        "snapshot",
        "source_id",
        "source_sha256",
        "projection_hash",
        "page",
        "start",
        "end",
        "quote",
        "quote_sha256",
    )
    text_record["identity"] = identity({key: text_record[key] for key in text_fields})
    text_path.write_text(json.dumps(text_record, sort_keys=True), encoding="utf-8")
    updated_packets = 0
    for packet_path in (bundle / "records").glob("domain-packet-*.json"):
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        changed = False
        for entry in packet.get("reusable_evidence", {}).get("entries", []):
            reference = entry.get("evidence") if isinstance(entry, dict) else None
            if isinstance(reference, dict) and reference.get("identity") == previous_identity:
                entry["evidence"] = {
                    "kind": "evidence",
                    "identity": text_record["identity"],
                }
                changed = True
        if changed:
            packet_path.write_text(json.dumps(packet, sort_keys=True), encoding="utf-8")
            _rebind_packet_and_observation(bundle, packet_path)
            updated_packets += 1
    assert updated_packets > 0


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
    from rob2_kit.evaluation.trace import TraceEvent
    from rob2_kit.evaluation.verifier import verify_artifact

    ae_report = (
        "Adverse events during the docetaxel-containing regimen; CTCAE severity grade during "
        "docetaxel-containing regimen follow-up; 390 patients receiving the docetaxel-containing "
        "regimen with follow-up data. Comparison groups: ADT plus docetaxel and ADT alone. "
        "The reported adverse-event profile for the ADT plus docetaxel group was Grade 3 any "
        "event count 65 (16.7%) participants, Grade 4 any event count 49 (12.6%) participants, "
        "and Grade 5 any event count 1 (0.3%) participants; each denominator was 390 "
        "docetaxel-cohort patients with follow-up."
    )
    (tmp_path / "article.txt").write_text(ae_report, encoding="utf-8")
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
    capture_batch(
        tmp_path,
        CaptureRequest(
            plan=plan.plan,
            acknowledgment=acknowledge_intake(tmp_path, plan.plan, ReviewAuthority.HOST),
        ),
    )
    evidence = retrieve_evidence(
        tmp_path,
        EvidenceRetrievalRequest(
            trial_id="chaarted",
            manual_selections=(
                ManualSelectionRequest(
                    kind="manual_selection",
                    source_alias="s1",
                    page=1,
                    start=0,
                    end=len(ae_report),
                    quote=ae_report,
                ),
            ),
        ),
    ).evidence[0]
    original = _card()
    card = original.model_copy(
        update={
            "evidence": EvidenceSet(
                target_basis=(evidence,),
                reported_values=(evidence,),
                reported_context=(evidence,),
                population_basis=(evidence,),
            ),
            "target": ResultTarget(
                outcome_definition="adverse events during the docetaxel-containing regimen",
                measurement="CTCAE severity grade",
                time_point_or_window="during docetaxel-containing regimen follow-up",
                effect_of_interest=(
                    "effect on adverse events during the docetaxel-containing regimen"
                ),
                comparison_groups=(
                    ComparisonGroup(id="docetaxel", label="ADT plus docetaxel"),
                    ComparisonGroup(id="adt", label="ADT alone"),
                ),
                intended_effect_measure="adverse-event profile",
                intended_analysis_population="390 patients receiving the docetaxel-containing regimen with follow-up data",
            ),
            "source_table_meaning": "adverse events during the docetaxel-containing regimen",
            "reported": original.reported.model_copy(
                update={
                    "group_id": "docetaxel",
                    "categories": (
                        Quantity(
                            statistic="count",
                            unit="participants",
                            group_or_category="Grade 3 any event",
                            value="65 (16.7%)",
                            denominator_basis="390 docetaxel-cohort patients with follow-up",
                        ),
                        Quantity(
                            statistic="count",
                            unit="participants",
                            group_or_category="Grade 4 any event",
                            value="49 (12.6%)",
                            denominator_basis="390 docetaxel-cohort patients with follow-up",
                        ),
                        Quantity(
                            statistic="count",
                            unit="participants",
                            group_or_category="Grade 5 any event",
                            value="1 (0.3%)",
                            denominator_basis="390 docetaxel-cohort patients with follow-up",
                        ),
                    ),
                }
            ),
            "population": PopulationAccount(
                analyzed_population="390 patients receiving the docetaxel-containing regimen with follow-up data",
                outcome_measurement_coverage=(
                    OutcomeMeasurementCoverage(group_id="docetaxel", status="measured"),
                    OutcomeMeasurementCoverage(
                        group_id="adt",
                        status="not_measured",
                        explanation="ADT-alone comparator unavailable",
                    ),
                ),
            ),
        }
    )
    incompatible = save_proposal(
        tmp_path,
        ProposalInput(
            outcome_statement=("effect on adverse events during the docetaxel-containing regimen"),
            results=(card,),
        ),
    )
    assert isinstance(incompatible, ProposalRepairReceipt)
    assert read_json(tmp_path, "proposal_review.json") is None
    review = save_proposal(
        tmp_path,
        ProposalInput(
            outcome_statement=("effect on adverse events during the docetaxel-containing regimen"),
            results=(card,),
            needs_input=(
                PreapprovalNeedsInput(
                    trial_id="chaarted",
                    reason=NeedsInputReason.COMPARATOR_UNAVAILABLE,
                    missing_facts=("ADT-alone comparator unavailable",),
                    evidence=(evidence,),
                ),
            ),
        ),
    )
    assert not isinstance(review, ProposalRepairReceipt)
    ack = acknowledge_proposal(tmp_path, review.review, caller="server:interactive")
    assert review.transition is not None
    approve_batch(tmp_path, ApprovalRequest(transition=review.transition, acknowledgment=ack))
    finalized = finalize_batch(tmp_path)
    assert finalized.outcome == "success"
    trace = (
        TraceEvent("operation", "clarify_adverse_events", "completed"),
        TraceEvent("operation", "preapproval_terminal", "acknowledged"),
    )
    verified = verify_artifact(
        tmp_path / finalized.artifact.bundle_path,
        CHAARTED_MANIFEST,
        "adverse_events",
        trace=trace,
    )
    assert verified.ok, verified.failures
    missing_clarification = verify_artifact(
        tmp_path / finalized.artifact.bundle_path, CHAARTED_MANIFEST, "adverse_events"
    )
    assert not missing_clarification.ok
    assert "nonempty complete trace is required" in missing_clarification.failures

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

    from rob2_kit.application.contracts import (
        PrepareTrialFinishContinuation,
        ReviewAuthority,
        TrialDisposition,
    )
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
        VisualSelectionRequest,
        retrieve_evidence,
        source_records,
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
        EffectPrecision,
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
    from rob2_kit.application.status import current_status
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
    from rob2_kit.rendering import RenderedPage, render_page

    source = (
        "Secondary endpoint: time to biochemical, symptomatic, or radiographic progression. "
        "Median time to progression at follow-up analysis in randomized patients: ADT plus "
        "docetaxel median 20.2 months (randomized arm); ADT alone median 11.7 months "
        "(randomized arm); hazard ratio 0.61 (95% CI 0.51 to 0.72; P<0.001), with denominator "
        "basis time-to-event analysis. Comparative time-to-event efficacy result."
    )
    document = pymupdf.open()
    page = document.new_page()
    page.insert_textbox(pymupdf.Rect(36, 36, page.rect.width - 36, page.rect.height - 36), source)
    document.save(tmp_path / "article.pdf")
    document.close()
    appendix = pymupdf.open()
    appendix.new_page().insert_text((72, 72), "Supplementary source for the same captured trial.")
    appendix.save(tmp_path / "appendix.pdf")
    appendix.close()
    document = pymupdf.open(tmp_path / "article.pdf")
    source_page = document[0].get_text()
    document.close()
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
            *(
                IntakePlanEntry(
                    candidate_identity=candidate.identity,
                    role="main_article"
                    if candidate.relative_path == "article.pdf"
                    else "supplement",
                    disposition=SourceDisposition.INCLUDE,
                    criticality=SourceCriticality.REQUIRED,
                )
                for candidate in preflight.candidates
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
                    kind="manual_selection",
                    source_alias="s1",
                    page=1,
                    start=0,
                    end=len(source_page),
                    quote=source_page,
                ),
            ),
        ),
    ).evidence[0]
    rendered = render_page(tmp_path, source_records(tmp_path, "chaarted")[0], 1)
    assert isinstance(rendered, RenderedPage)
    visual_evidence = retrieve_evidence(
        tmp_path,
        EvidenceRetrievalRequest(
            trial_id="chaarted",
            visual_selections=(
                VisualSelectionRequest(
                    kind="visual_selection",
                    render={
                        "identity": rendered.render_identity,
                        "uri": f"rob2://render/{rendered.render_identity}",
                    },
                    transcription="The rendered source page contains the reported result.",
                ),
            ),
        ),
    ).evidence[0]
    specified = ClarityDeclaration(
        **{
            name: ClarityItem(state="specified")
            for name in (
                "outcome_definition",
                "measurement",
                "time_point",
                "analysis_population",
                "comparison_groups",
                "effect_measure",
                "source_table_meaning",
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
            effect_of_interest=(
                "effect on time to biochemical, symptomatic, or radiographic progression"
            ),
            comparison_groups=(
                ComparisonGroup(id="docetaxel", label="ADT plus docetaxel"),
                ComparisonGroup(id="adt", label="ADT alone"),
            ),
            intended_effect_measure="hazard ratio",
            intended_analysis_population="randomized patients",
        ),
        reported=ComparativeEffect(
            form="comparative_effect",
            effect_measure="hazard ratio",
            reported_text=source,
            effect=Quantity(
                statistic="hazard ratio",
                unit="ratio",
                group_or_category="docetaxel vs adt",
                value="0.61",
                denominator_basis="time-to-event analysis",
            ),
            quantities=(
                Quantity(
                    statistic="median",
                    unit="months",
                    group_or_category="docetaxel",
                    value="20.2",
                    denominator_basis="randomized arm",
                ),
                Quantity(
                    statistic="median",
                    unit="months",
                    group_or_category="adt",
                    value="11.7",
                    denominator_basis="randomized arm",
                ),
            ),
            comparison_groups=("docetaxel", "adt"),
            precision=EffectPrecision(
                confidence_interval={"level": "95", "lower": "0.51", "upper": "0.72"},
                p_value={"operator": "<", "value": "0.001"},
            ),
        ),
        population=PopulationAccount(
            analyzed_population="randomized patients",
            outcome_measurement_coverage=(
                OutcomeMeasurementCoverage(group_id="docetaxel", status="measured"),
                OutcomeMeasurementCoverage(group_id="adt", status="measured"),
            ),
        ),
        source_table_meaning=(
            "Secondary endpoint: time to biochemical, symptomatic, or radiographic progression"
        ),
        evidence=EvidenceSet(
            target_basis=(evidence,),
            reported_values=(evidence,),
            reported_context=(evidence,),
            population_basis=(evidence,),
        ),
        clarity=specified,
    )
    proposal = save_proposal(
        tmp_path,
        ProposalInput(
            outcome_statement=(
                "effect on time to biochemical, symptomatic, or radiographic progression"
            ),
            results=(card,),
        ),
    )
    assert not isinstance(proposal, ProposalRepairReceipt)
    assert proposal.transition is not None
    proposal_ack = acknowledge_proposal(tmp_path, proposal.review, caller="server:interactive")
    approved = approve_batch(
        tmp_path, ApprovalRequest(transition=proposal.transition, acknowledgment=proposal_ack)
    )
    first_packet = prepare_domain_packet(
        tmp_path,
        approved.approved_batch,
        trial_id="chaarted",
        domain_id="domain:randomization",
    )
    retrieve_evidence(
        tmp_path,
        EvidenceRetrievalRequest(
            trial_id="chaarted",
            manual_selections=(
                ManualSelectionRequest(
                    kind="manual_selection",
                    source_alias="s1",
                    page=1,
                    start=0,
                    end=8,
                    quote=source_page[:8],
                ),
            ),
        ),
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
        packet = (
            first_packet
            if domain.id == "domain:randomization"
            else prepare_domain_packet(
                tmp_path, approved.approved_batch, trial_id="chaarted", domain_id=domain.id
            )
        )
        draft = DomainDraftInput(
            active_answers=tuple(
                DomainAnswerInput(
                    question_id=question_id,
                    answer=answer,
                    rationale="The captured trial report supports this deterministic answer.",
                    evidence_uses=(
                        DomainEvidenceUseInput(
                            relationship=EvidenceRelationship.SUPPORTING,
                            claim="The captured trial report is the basis for this answer.",
                            rationale="The exact evidence record is in the trial scope.",
                            evidence=(visual_evidence,),
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
        committed = commit_domain_judgment(tmp_path, validated.transition)

    restarted = current_status(tmp_path)
    assert isinstance(restarted.continuation, PrepareTrialFinishContinuation)
    assert isinstance(committed.next_action, PrepareTrialFinishContinuation)
    assert restarted.continuation.packet == committed.next_action.packet
    prepared = prepare_trial_finish(
        tmp_path,
        restarted.continuation.packet,
        TrialFinishCandidate(disposition=TrialDisposition.ASSESSED),
    )
    assert prepared.transition is not None and prepared.synthesis is not None
    finish_ack = acknowledge_trial_finish(
        tmp_path, prepared.transition, caller="server:interactive"
    )
    finished = finish_trial(
        tmp_path,
        TrialFinishRequest(transition=prepared.transition, acknowledgment=finish_ack),
        caller="server:interactive",
    )
    assert finished.disposition is TrialDisposition.ASSESSED
    finalized = finalize_batch(tmp_path)
    assert finalized.outcome == "success"
    bundle = tmp_path / finalized.artifact.bundle_path
    verified = verify_artifact(
        bundle,
        CHAARTED_MANIFEST,
        "pfs",
        trace=(TraceEvent("operation", "finalize_batch", "completed"),),
    )
    assert verified.ok, verified.failures

    question_scope_tampered = tmp_path / "rehashed-domain-packet-question-scope"
    shutil.copytree(bundle, question_scope_tampered)
    question_packet_path = next(
        path
        for path in (question_scope_tampered / "records").glob("domain-packet-*.json")
        if json.loads(path.read_text(encoding="utf-8")).get("domain_id") == "domain:randomization"
    )
    question_packet = json.loads(question_packet_path.read_text(encoding="utf-8"))
    question_packet["active_question_ids"] = list(question_packet["active_question_ids"][:-1])
    question_packet_path.write_text(json.dumps(question_packet, sort_keys=True), encoding="utf-8")
    _rebind_packet_and_observation(question_scope_tampered, question_packet_path)
    _rehash_manifest(question_scope_tampered)
    rejected = verify_artifact(question_scope_tampered, CHAARTED_MANIFEST, "pfs")
    assert not rejected.ok
    assert any("question scope" in failure for failure in rejected.failures)

    prior_chain_tampered = tmp_path / "rehashed-domain-packet-prior-chain"
    shutil.copytree(bundle, prior_chain_tampered)
    prior_packet_path = next(
        path
        for path in (prior_chain_tampered / "records").glob("domain-packet-*.json")
        if json.loads(path.read_text(encoding="utf-8")).get("domain_id") == "domain:deviations"
    )
    prior_packet = json.loads(prior_packet_path.read_text(encoding="utf-8"))
    prior_packet["prior_domain_hashes"] = []
    prior_packet_path.write_text(json.dumps(prior_packet, sort_keys=True), encoding="utf-8")
    _rebind_packet_and_observation(prior_chain_tampered, prior_packet_path)
    _rehash_manifest(prior_chain_tampered)
    rejected = verify_artifact(prior_chain_tampered, CHAARTED_MANIFEST, "pfs")
    assert not rejected.ok
    assert any("prior checkpoint chain" in failure for failure in rejected.failures)

    visual_records = [
        path
        for path in (bundle / "records").glob("evidence-*.json")
        if json.loads(path.read_text(encoding="utf-8")).get("kind") == "visual"
    ]
    assert len(visual_records) == 1
    visual_record = visual_records[0]
    for field, value in (
        ("transcription", "tampered transcription"),
        ("source_id", "wrong-source"),
        ("page", 2),
        ("region", [0.0, 0.0, 0.5, 0.5]),
    ):
        tampered = tmp_path / f"visual-{field}"
        shutil.copytree(bundle, tampered)
        path = tampered / "records" / visual_record.name
        record = json.loads(path.read_text(encoding="utf-8"))
        record[field] = value
        path.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
        _rehash_manifest(tampered)
        assert not verify_artifact(tampered, CHAARTED_MANIFEST, "pfs").ok
    malformed_render = tmp_path / "rehashed-malformed-visual-render-reference"
    shutil.copytree(bundle, malformed_render)
    malformed_render_path = malformed_render / "records" / visual_record.name
    malformed_render_record = json.loads(malformed_render_path.read_text(encoding="utf-8"))
    malformed_render_record["render"] = {
        **malformed_render_record["render"],
        "unexpected": True,
    }
    visual_fields = (
        "kind",
        "trial_id",
        "snapshot",
        "source_id",
        "source_sha256",
        "projection_hash",
        "page",
        "region",
        "render",
        "transcription",
    )
    malformed_render_record["identity"] = identity(
        {key: malformed_render_record[key] for key in visual_fields}
    )
    malformed_render_path.write_text(
        json.dumps(malformed_render_record, sort_keys=True), encoding="utf-8"
    )
    _rehash_manifest(malformed_render)
    rejected = verify_artifact(malformed_render, CHAARTED_MANIFEST, "pfs")
    assert any("visual Evidence provenance" in failure for failure in rejected.failures)

    boolean_visual_page = tmp_path / "rehashed-boolean-visual-evidence-page"
    shutil.copytree(bundle, boolean_visual_page)
    boolean_visual_path = boolean_visual_page / "records" / visual_record.name
    boolean_visual_record = json.loads(boolean_visual_path.read_text(encoding="utf-8"))
    boolean_visual_record["page"] = True
    boolean_visual_record["identity"] = identity(
        {key: boolean_visual_record[key] for key in visual_fields}
    )
    boolean_visual_path.write_text(
        json.dumps(boolean_visual_record, sort_keys=True), encoding="utf-8"
    )
    _rehash_manifest(boolean_visual_page)
    rejected = verify_artifact(boolean_visual_page, CHAARTED_MANIFEST, "pfs")
    assert any("visual Evidence provenance" in failure for failure in rejected.failures)
    text_record = next(
        path
        for path in (bundle / "records").glob("evidence-*.json")
        if json.loads(path.read_text(encoding="utf-8")).get("kind") == "text"
    )
    for name, record_path in (
        ("text-extra-key", text_record),
        ("visual-extra-key", visual_record),
    ):
        tampered = tmp_path / name
        shutil.copytree(bundle, tampered)
        path = tampered / "records" / record_path.name
        record = json.loads(path.read_text(encoding="utf-8"))
        record["unexpected"] = True
        path.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
        _rehash_manifest(tampered)
        assert not verify_artifact(tampered, CHAARTED_MANIFEST, "pfs").ok
    packet_record = next((bundle / "records").glob("domain-packet-*.json"))
    tampered = tmp_path / "domain-packet-extra-key"
    shutil.copytree(bundle, tampered)
    path = tampered / "records" / packet_record.name
    record = json.loads(path.read_text(encoding="utf-8"))
    record["unexpected"] = True
    path.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
    _rehash_manifest(tampered)
    assert not verify_artifact(tampered, CHAARTED_MANIFEST, "pfs").ok
    snapshot_tampered = tmp_path / "text-evidence-snapshot"
    shutil.copytree(bundle, snapshot_tampered)
    text_snapshot_path = snapshot_tampered / "records" / text_record.name
    text_snapshot = json.loads(text_snapshot_path.read_text(encoding="utf-8"))
    previous_text_identity = text_snapshot["identity"]
    text_snapshot["snapshot"] = "sha256:" + "0" * 64
    text_fields = (
        "kind",
        "trial_id",
        "snapshot",
        "source_id",
        "source_sha256",
        "projection_hash",
        "page",
        "start",
        "end",
        "quote",
        "quote_sha256",
    )
    text_snapshot["identity"] = identity({key: text_snapshot[key] for key in text_fields})
    text_snapshot_path.write_text(json.dumps(text_snapshot, sort_keys=True), encoding="utf-8")
    updated_packets = 0
    for packet_path in (snapshot_tampered / "records").glob("domain-packet-*.json"):
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        changed = False
        for entry in packet.get("reusable_evidence", {}).get("entries", []):
            reference = entry.get("evidence") if isinstance(entry, dict) else None
            if isinstance(reference, dict) and reference.get("identity") == previous_text_identity:
                entry["evidence"] = {
                    "kind": "evidence",
                    "identity": text_snapshot["identity"],
                }
                changed = True
        if not changed:
            continue
        packet_path.write_text(json.dumps(packet, sort_keys=True), encoding="utf-8")
        _rebind_packet_and_observation(snapshot_tampered, packet_path)
        updated_packets += 1
    assert updated_packets > 0
    _rehash_manifest(snapshot_tampered)
    rejected = verify_artifact(snapshot_tampered, CHAARTED_MANIFEST, "pfs")
    assert not rejected.ok
    assert any("Evidence snapshot binding is invalid" in failure for failure in rejected.failures)
    for name, start, end, quote in (
        ("text-evidence-negative-span", -1, 1, None),
        ("text-evidence-empty-span", 0, 0, ""),
    ):
        coordinates_tampered = tmp_path / name
        shutil.copytree(bundle, coordinates_tampered)
        coordinates_path = coordinates_tampered / "records" / text_record.name
        _rebind_text_evidence_coordinates(
            coordinates_tampered,
            coordinates_path,
            start=start,
            end=end,
            quote=quote,
        )
        _rehash_manifest(coordinates_tampered)
        rejected = verify_artifact(coordinates_tampered, CHAARTED_MANIFEST, "pfs")
        assert not rejected.ok
    malformed_reference = tmp_path / "domain-packet-malformed-reference"
    shutil.copytree(bundle, malformed_reference)
    malformed_packet_path = next((malformed_reference / "records").glob("domain-packet-*.json"))
    malformed_packet = json.loads(malformed_packet_path.read_text(encoding="utf-8"))
    original_reference = malformed_packet["reusable_evidence"]["entries"][0]["evidence"]
    malformed_packet["reusable_evidence"]["entries"][0]["evidence"] = {
        "kind": "wrong-kind",
        "identity": original_reference["identity"],
        "unexpected": True,
    }
    malformed_packet_path.write_text(json.dumps(malformed_packet, sort_keys=True), encoding="utf-8")
    _rebind_packet_and_observation(malformed_reference, malformed_packet_path)
    _rehash_manifest(malformed_reference)
    rejected = verify_artifact(malformed_reference, CHAARTED_MANIFEST, "pfs")
    assert any("Evidence reference is invalid" in failure for failure in rejected.failures)

    malformed_binding = tmp_path / "rehashed-malformed-domain-evidence-binding-reference"
    shutil.copytree(bundle, malformed_binding)
    binding_path = next((malformed_binding / "records").glob("domain-observation-*.json"))
    binding_record = json.loads(binding_path.read_text(encoding="utf-8"))
    original_binding = binding_record["evidence_bindings"][0]["evidence"]
    binding_record["evidence_bindings"][0]["evidence"] = {
        "kind": "evidence",
        "identity": original_binding["identity"],
        "uri": "rob2://detail/evidence/" + original_binding["identity"],
    }
    observation_fields = (
        "kind",
        "packet",
        "trial_id",
        "result_id",
        "domain_id",
        "draft",
        "proposed_judgment",
        "inactive_questions",
        "evidence_bindings",
        "scientific_pack",
        "policy_pack",
    )
    binding_record["identity"] = identity({key: binding_record[key] for key in observation_fields})
    binding_path.write_text(json.dumps(binding_record, sort_keys=True), encoding="utf-8")
    _rehash_manifest(malformed_binding)
    rejected = verify_artifact(malformed_binding, CHAARTED_MANIFEST, "pfs")
    assert any("Domain evidence binding" in failure for failure in rejected.failures)

    malformed_approved_reference = tmp_path / "rehashed-malformed-packet-approved-batch-reference"
    shutil.copytree(bundle, malformed_approved_reference)
    approved_packet_path = next(
        (malformed_approved_reference / "records").glob("domain-packet-*.json")
    )
    approved_packet = json.loads(approved_packet_path.read_text(encoding="utf-8"))
    approved_packet["approved_batch"] = {
        **approved_packet["approved_batch"],
        "unexpected": True,
    }
    approved_packet_path.write_text(json.dumps(approved_packet, sort_keys=True), encoding="utf-8")
    _rebind_packet_and_observation(malformed_approved_reference, approved_packet_path)
    _rehash_manifest(malformed_approved_reference)
    rejected = verify_artifact(malformed_approved_reference, CHAARTED_MANIFEST, "pfs")
    assert any("work packet" in failure.lower() for failure in rejected.failures)

    boolean_catalog_page = tmp_path / "rehashed-boolean-visual-catalog-page"
    shutil.copytree(bundle, boolean_catalog_page)
    boolean_catalog_packet_path = next(
        (boolean_catalog_page / "records").glob("domain-packet-*.json")
    )
    boolean_catalog_packet = json.loads(boolean_catalog_packet_path.read_text(encoding="utf-8"))
    visual_entry = next(
        entry
        for entry in boolean_catalog_packet["reusable_evidence"]["entries"]
        if entry.get("kind") == "visual"
    )
    visual_entry["page"] = True
    boolean_catalog_packet_path.write_text(
        json.dumps(boolean_catalog_packet, sort_keys=True), encoding="utf-8"
    )
    _rebind_packet_and_observation(boolean_catalog_page, boolean_catalog_packet_path)
    _rehash_manifest(boolean_catalog_page)
    rejected = verify_artifact(boolean_catalog_page, CHAARTED_MANIFEST, "pfs")
    assert any("reusable Evidence catalog is unbound" in failure for failure in rejected.failures)

    for name, original_kind, swapped_kind in (
        ("rehashed-visual-catalog-as-text", "visual", "text"),
        ("rehashed-text-catalog-as-visual", "text", "visual"),
    ):
        swapped_catalog = tmp_path / name
        shutil.copytree(bundle, swapped_catalog)
        swapped_packet_path = next((swapped_catalog / "records").glob("domain-packet-*.json"))
        swapped_packet = json.loads(swapped_packet_path.read_text(encoding="utf-8"))
        swapped_entry = next(
            entry
            for entry in swapped_packet["reusable_evidence"]["entries"]
            if entry.get("kind") == original_kind
        )
        swapped_entry["kind"] = swapped_kind
        if original_kind == "visual":
            swapped_entry.pop("region")
            swapped_entry.update({"start": None, "end": None})
        else:
            swapped_entry.pop("start")
            swapped_entry.pop("end")
            swapped_entry["region"] = None
        swapped_packet_path.write_text(json.dumps(swapped_packet, sort_keys=True), encoding="utf-8")
        _rebind_packet_and_observation(swapped_catalog, swapped_packet_path)
        _rehash_manifest(swapped_catalog)
        rejected = verify_artifact(swapped_catalog, CHAARTED_MANIFEST, "pfs")
        assert not rejected.ok
        assert any("reusable Evidence catalog" in failure for failure in rejected.failures)

    invalid_catalog_page = tmp_path / "rehashed-invalid-catalog-continuation"
    shutil.copytree(bundle, invalid_catalog_page)
    invalid_catalog_packet_path = next(
        (invalid_catalog_page / "records").glob("domain-packet-*.json")
    )
    invalid_catalog_packet = json.loads(invalid_catalog_packet_path.read_text(encoding="utf-8"))
    catalog = invalid_catalog_packet["reusable_evidence"]
    original_entries = catalog["entries"]
    catalog["entries"] = [{"kind": "invalid"}]
    catalog["has_more"] = True
    catalog["next_after"] = next(
        entry["evidence"]
        for entry in original_entries
        if isinstance(entry, dict) and "evidence" in entry
    )
    invalid_catalog_packet_path.write_text(
        json.dumps(invalid_catalog_packet, sort_keys=True), encoding="utf-8"
    )
    _rebind_packet_and_observation(invalid_catalog_page, invalid_catalog_packet_path)
    _rehash_manifest(invalid_catalog_page)
    rejected = verify_artifact(invalid_catalog_page, CHAARTED_MANIFEST, "pfs")
    assert not rejected.ok
    assert any("reusable Evidence catalog" in failure for failure in rejected.failures)

    reordered_aliases = tmp_path / "domain-packet-reordered-aliases"
    shutil.copytree(bundle, reordered_aliases)
    reordered_packet_path = next((reordered_aliases / "records").glob("domain-packet-*.json"))
    reordered_packet = json.loads(reordered_packet_path.read_text(encoding="utf-8"))
    assert len(reordered_packet["stable_aliases"]) > 1
    reordered_packet["stable_aliases"] = list(reversed(reordered_packet["stable_aliases"]))
    reordered_packet_path.write_text(json.dumps(reordered_packet, sort_keys=True), encoding="utf-8")
    _rebind_packet_and_observation(reordered_aliases, reordered_packet_path)
    _rehash_manifest(reordered_aliases)
    rejected = verify_artifact(reordered_aliases, CHAARTED_MANIFEST, "pfs")
    assert any("stable aliases are invalid" in failure for failure in rejected.failures)
    from rob2_kit.evaluation.verifier import _Bundle, _captured_snapshot

    verifier_bundle = _Bundle(bundle, [])
    verifier_bundle.load()
    captured = verifier_bundle.names["captured_batch.json"]
    preflight_record = verifier_bundle.names["preflight.json"]
    candidates = {item["identity"]: item for item in preflight_record["candidates"]}
    rows = [item for item in captured["sources"] if item["trial_id"] == "chaarted"]
    sources: dict[str, tuple[str, bytes, tuple[str, ...], str]] = {
        str(item["candidate_identity"]): (
            "chaarted",
            str(item["candidate_identity"]).encode(),
            ("fixture page",),
            f"projection-{index}",
        )
        for index, item in enumerate(rows)
    }
    ordered = sorted(
        rows,
        key=lambda item: (
            int(item["role"] != "main_article"),
            Path(candidates[item["candidate_identity"]]["relative_path"]).name.casefold(),
            item["candidate_identity"],
        ),
    )

    def snapshot_for(order):
        return identity(
            {
                "trial_id": "chaarted",
                "scope_kind": "captured_batch",
                "scope_hash": captured["identity"],
                "source_ids": tuple(item["candidate_identity"] for item in order),
                "source_hashes": tuple(
                    "sha256:" + hashlib.sha256(item["candidate_identity"].encode()).hexdigest()
                    for item in order
                ),
                "projection_hashes": tuple(
                    sources[item["candidate_identity"]][3] for item in order
                ),
                "tokenizer": "unicode61_casefold_no_diacritics_v1",
                "ordering": "authoritative_source_role_label_id_page_v1",
            }
        )

    assert _captured_snapshot(verifier_bundle, sources, "chaarted") == snapshot_for(ordered)
    assert _captured_snapshot(verifier_bundle, sources, "chaarted") != snapshot_for(
        tuple(reversed(ordered))
    )
    tampered = tmp_path / "visual-reordered-snapshot"
    shutil.copytree(bundle, tampered)
    path = tampered / "records" / visual_record.name
    record = json.loads(path.read_text(encoding="utf-8"))
    record["snapshot"] = "sha256:" + "0" * 64
    record["identity"] = identity(
        {key: value for key, value in record.items() if key != "identity"}
    )
    path.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
    _rehash_manifest(tampered)
    rejected = verify_artifact(tampered, CHAARTED_MANIFEST, "pfs")
    assert any("visual Evidence provenance" in failure for failure in rejected.failures)
    for path in (
        next((bundle / "renders").glob("*.png")),
        next((bundle / "records").glob("render-*.json")),
    ):
        tampered = tmp_path / f"missing-{path.name}"
        shutil.copytree(bundle, tampered)
        (tampered / path.parent.name / path.name).unlink()
        assert not verify_artifact(tampered, CHAARTED_MANIFEST, "pfs").ok
    render_record = next((bundle / "records").glob("render-*.json"))
    for field, value in (
        ("recipe", "wrong-recipe"),
        ("media_type", "image/jpeg"),
    ):
        tampered = tmp_path / f"render-{field}"
        shutil.copytree(bundle, tampered)
        path = tampered / "records" / render_record.name
        record = json.loads(path.read_text(encoding="utf-8"))
        record[field] = value
        path.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
        _rehash_manifest(tampered)
        assert not verify_artifact(tampered, CHAARTED_MANIFEST, "pfs").ok
    render_png = next((bundle / "renders").glob("*.png"))
    for name, offset in (("header", 1), ("dimensions", 16)):
        tampered = tmp_path / f"render-{name}"
        shutil.copytree(bundle, tampered)
        path = tampered / "renders" / render_png.name
        image = bytearray(path.read_bytes())
        image[offset] ^= 1
        path.write_bytes(image)
        _rehash_manifest(tampered)
        assert not verify_artifact(tampered, CHAARTED_MANIFEST, "pfs").ok

    missing_evidence = tmp_path / "rehashed-missing-evidence"
    shutil.copytree(bundle, missing_evidence)
    (missing_evidence / "records" / visual_record.name).unlink()
    _rehash_manifest(missing_evidence)
    assert not verify_artifact(missing_evidence, CHAARTED_MANIFEST, "pfs").ok

    wrong_pack = tmp_path / "rehashed-wrong-pack"
    shutil.copytree(bundle, wrong_pack)
    observation_path = next((wrong_pack / "records").glob("domain-observation-*.json"))
    observation = json.loads(observation_path.read_text(encoding="utf-8"))
    observation["scientific_pack"] = "sha256:" + "0" * 64
    candidate_fields = (
        "kind",
        "packet",
        "trial_id",
        "result_id",
        "domain_id",
        "draft",
        "proposed_judgment",
        "inactive_questions",
        "evidence_bindings",
        "scientific_pack",
        "policy_pack",
    )
    missing_bindings = tmp_path / "rehashed-empty-domain-evidence"
    shutil.copytree(bundle, missing_bindings)
    empty_observation_path = next((missing_bindings / "records").glob("domain-observation-*.json"))
    empty_observation = json.loads(empty_observation_path.read_text(encoding="utf-8"))
    empty_observation["evidence_bindings"] = []
    empty_observation["identity"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                {key: empty_observation[key] for key in candidate_fields},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
    )
    empty_observation_path.write_text(
        json.dumps(empty_observation, sort_keys=True), encoding="utf-8"
    )
    _rehash_manifest(missing_bindings)
    rejected = verify_artifact(missing_bindings, CHAARTED_MANIFEST, "pfs")
    assert any("nonempty evidence bindings" in failure for failure in rejected.failures)
    observation["identity"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                {key: observation[key] for key in candidate_fields},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
    )
    observation_path.write_text(json.dumps(observation, sort_keys=True), encoding="utf-8")
    _rehash_manifest(wrong_pack)
    rejected = verify_artifact(wrong_pack, CHAARTED_MANIFEST, "pfs")
    assert not rejected.ok
    assert any("pack" in failure for failure in rejected.failures)

    for record in (
        next((bundle / "records").glob("domain-observation-*.json")),
        next((bundle / "records").glob("assessment-snapshot-*.json")),
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
            "synthesis",
            "checkpoint_hashes",
            "proposed_overall",
            "final_judgment",
            "caller",
            "observed_at",
        )
    }
    snapshot["identity"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    snapshot["snapshot_hash"] = snapshot["identity"]
    snapshot_path.write_text(
        json.dumps(snapshot, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    _rehash_manifest(tampered)
    assert not verify_artifact(tampered, CHAARTED_MANIFEST, "pfs").ok


def test_finalize_requires_all_terminal_dispositions(tmp_path: Path) -> None:
    approved = identity({"approved": True})
    write_jsons(
        tmp_path,
        {
            "state.json": {
                "phase": "assessment",
                "approved_batch_identity": approved,
                "trial_dispositions": {"trial": "pending"},
            }
        },
    )
    result = finalize_batch(tmp_path)
    assert result.outcome == "condition"
    assert "did not occur" in result.detail


def test_finalize_is_idempotent_and_artifact_verification_fails_closed(tmp_path: Path) -> None:
    approved = identity({"approved": True})
    outcome_identity = identity({"trial": "trial", "disposition": "needs_input"})
    write_jsons(
        tmp_path,
        {
            "captured_batch.json": {
                "kind": "captured_batch",
                "identity": identity({"captured": True}),
                "sources": [],
            },
            "state.json": {
                "phase": "ready_to_finalize",
                "approved_batch_identity": approved,
                "trial_dispositions": {"trial": "needs_input"},
            },
            "trial-outcome-trial.json": {
                "kind": "trial_outcome",
                "identity": outcome_identity,
                "trial_id": "trial",
                "disposition": "needs_input",
                "rationale": "missing result",
                "synthesis": {
                    "kind": "approved_batch",
                    "identity": approved,
                    "uri": f"rob2://detail/approved_batch/{approved}",
                },
                "snapshot": None,
                "observed_at": "2026-01-01T00:00:00Z",
            },
        },
    )
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
    write_jsons(
        tmp_path,
        {
            "captured_batch.json": {
                "kind": "captured_batch",
                "identity": identity({"captured": True}),
                "sources": [],
            },
            "state.json": {
                "phase": "ready_to_finalize",
                "approved_batch_identity": approved,
                "trial_dispositions": {"trial": "needs_input"},
            },
            "trial-outcome-trial.json": {
                "kind": "trial_outcome",
                "identity": outcome_identity,
                "trial_id": "trial",
                "disposition": "needs_input",
                "synthesis": {
                    "kind": "approved_batch",
                    "identity": approved,
                    "uri": f"rob2://detail/approved_batch/{approved}",
                },
                "snapshot": None,
                "observed_at": "2026-01-01T00:00:00Z",
            },
        },
    )
    saved = finalize_batch(tmp_path)
    assert saved.outcome == "success"
    if field == "counts":
        changed = saved.model_copy(
            update={
                "counts": FinalizationCounts(
                    total=9, pending=0, assessed=0, needs_input=9, failed=0
                )
            }
        )
    elif field == "presentation":
        changed = saved.model_copy(
            update={"presentation": saved.presentation.model_copy(update={"summary": "forged"})}
        )
    elif field == "summary":
        changed = saved.model_copy(
            update={"summary": saved.summary.model_copy(update={"identity": "sha256:" + "0" * 64})}
        )
    else:
        changed = saved.model_copy(
            update={"artifact": saved.artifact.model_copy(update={"file_count": 99})}
        )
    assert verify_finalization_result(tmp_path, changed) is None

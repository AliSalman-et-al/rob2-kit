# ruff: noqa: E501

import pytest

from rob2_kit.application._state import read_json
from rob2_kit.application.contracts import EvidenceReference, ReviewAuthority
from rob2_kit.application.finalization import finalize_batch
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
    ComparisonGroup,
    Compatibility,
    EvidenceSet,
    NeedsInputReason,
    OutcomeMeasurementCoverage,
    PopulationAccount,
    PreapprovalNeedsInput,
    ProposalInput,
    ProposalRepairReceipt,
    Quantity,
    ResultCardInput,
    ResultTarget,
    SingleGroupCategoryProfile,
    _compatibility,
    acknowledge_proposal,
    approve_batch,
    save_proposal,
)


@pytest.fixture
def pending_proposal(tmp_path):
    (tmp_path / "article.txt").write_text("No outcome was reported.", encoding="utf-8")
    preflight = preflight_sources(
        tmp_path,
        PreflightRequest(roots=(AuthorizedSourceRoot(alias="trial", path=".", trial_id="trial"),)),
    )
    plan = save_intake_plan(
        tmp_path,
        preflight.reference,
        (IntakePlanEntry(candidate_identity=preflight.candidates[0].identity, role="main_article", disposition=SourceDisposition.INCLUDE, criticality=SourceCriticality.REQUIRED),),
    )
    capture_batch(tmp_path, CaptureRequest(plan=plan.plan, acknowledgment=acknowledge_intake(tmp_path, plan.plan, ReviewAuthority.HOST)))
    saved = save_proposal(tmp_path, ProposalInput(outcome_statement="Overall survival", needs_input=(PreapprovalNeedsInput(trial_id="trial", reason=NeedsInputReason.OUTCOME_NOT_REPORTED, missing_facts=("an outcome result",)),)))
    assert not isinstance(saved, ProposalRepairReceipt)
    assert saved.transition is not None
    ack = acknowledge_proposal(tmp_path, saved.review, caller="server:interactive")
    return tmp_path, saved, ack


@pytest.mark.parametrize("mutation", ("authority", "purpose", "kind", "identity", "uri", "caller", "observed_at", "state_identity"))
def test_corrupt_proposal_ack_cannot_unlock_approval(pending_proposal, mutation: str) -> None:
    workspace, saved, acknowledgment = pending_proposal
    if mutation == "state_identity":
        state = read_json(workspace, "state.json")
        assert state is not None
        state["ack_identity"] = "sha256:" + "f" * 64
        from rob2_kit.application._state import write_jsons

        write_jsons(workspace, {"state.json": state})
    else:
        payload = read_json(workspace, "proposal_ack.json")
        assert payload is not None
        payload[mutation] = "tampered"
        from rob2_kit.application._state import write_jsons

        write_jsons(workspace, {"proposal_ack.json": payload})
    status = __import__("rob2_kit.application.status", fromlist=["current_status"]).current_status(workspace)
    assert status.presentation.code != "proposal_approval_ready"
    with pytest.raises((PermissionError, ValueError)):
        approve_batch(workspace, ApprovalRequest(transition=saved.transition, acknowledgment=acknowledgment))
    assert read_json(workspace, "approved_batch.json") is None
    transition = read_json(workspace, f"transition-{saved.transition.identity.removeprefix('sha256:')}.json")
    assert transition is not None and not transition.get("consumed", False)


def _card() -> ResultCardInput:
    evidence = EvidenceReference(kind="evidence", identity="sha256:" + "0" * 64)
    return ResultCardInput(
        trial_id="chaarted",
        target=ResultTarget(
            outcome_definition="Grade 3 or worse toxicity",
            measurement="CTCAE grade",
            time_point_or_window="during docetaxel",
            effect_of_interest="risk ratio",
            comparison_groups=(
                ComparisonGroup(id="docetaxel", label="docetaxel"),
                ComparisonGroup(id="control", label="control"),
            ),
            intended_analysis_population="randomized participants",
            intended_effect_measure="risk ratio",
        ),
        reported=SingleGroupCategoryProfile(
            form="single_group_category_profile",
            group_id="docetaxel",
            categories=(
                Quantity(
                    statistic="count", unit="participants", group_or_category="Grade 3", value=2
                ),
                Quantity(
                    statistic="count", unit="participants", group_or_category="Grade 4", value=1
                ),
                Quantity(
                    statistic="count", unit="participants", group_or_category="Grade 5", value=1
                ),
            ),
        ),
        population=PopulationAccount(
            analyzed_population="docetaxel cohort",
            outcome_measurement_coverage=(
                OutcomeMeasurementCoverage(group_id="docetaxel", status="measured"),
            ),
        ),
        source_table_meaning=(
            "single-group docetaxel-cohort Grade 3/4/5 category profile; "
            "no ADT-alone comparator coverage"
        ),
        evidence=EvidenceSet(
            target_basis=(evidence,),
            reported_values=(evidence,),
            reported_context=(evidence,),
            population_basis=(evidence,),
        ),
        clarity=ClarityDeclaration(
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
        ),
    )


def test_chaarted_single_group_grade_profile_cannot_be_comparative() -> None:
    card = _card()
    finding = _compatibility(card)
    assert finding.status is Compatibility.INCOMPATIBLE
    assert finding.reasons == ("single_group_category_profile_has_no_comparator",)


def test_preapproval_needs_input_is_acknowledged_and_applied_once(tmp_path) -> None:
    (tmp_path / "article.txt").write_text("No outcome was reported.", encoding="utf-8")
    preflight = preflight_sources(
        tmp_path,
        PreflightRequest(roots=(AuthorizedSourceRoot(alias="trial", path=".", trial_id="trial"),)),
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
    saved = save_proposal(
        tmp_path,
        ProposalInput(
            outcome_statement="Overall survival",
            needs_input=(
                PreapprovalNeedsInput(
                    trial_id="trial",
                    reason=NeedsInputReason.OUTCOME_NOT_REPORTED,
                    missing_facts=("an outcome result for the randomized comparison",),
                ),
            ),
        ),
    )
    assert not isinstance(saved, ProposalRepairReceipt)
    assert saved.transition is not None
    acknowledgment = acknowledge_proposal(tmp_path, saved.review, caller="server:interactive")
    request = ApprovalRequest(transition=saved.transition, acknowledgment=acknowledgment)
    approved = approve_batch(tmp_path, request)
    assert approved.trial_dispositions == (("trial", "needs_input"),)
    finalized = finalize_batch(tmp_path)
    assert finalized.outcome == "success"
    assert finalized.counts.assessed == 0
    assert finalized.counts.needs_input == 1
    assert approve_batch(tmp_path, request) == approved


def test_malformed_proposal_returns_aggregated_repairs_without_writing(tmp_path) -> None:
    receipt = save_proposal(
        tmp_path,
        {
            "outcome_statement": "",
            "results": ({"trial_id": 4, "reported": {"form": "not_a_form"}},),
            "needs_input": ({"trial_id": "", "reason": "wrong", "missing_facts": ()},),
            "forbidden": True,
        },
    )
    assert isinstance(receipt, ProposalRepairReceipt)
    assert len(receipt.repairs) >= 5
    assert {repair.pointer for repair in receipt.repairs} >= {
        "/outcome_statement",
        "/results/0/reported",
        "/needs_input/0/reason",
        "/forbidden",
    }
    assert read_json(tmp_path, "proposal_review.json") is None
    assert read_json(tmp_path, "proposal_ack.json") is None

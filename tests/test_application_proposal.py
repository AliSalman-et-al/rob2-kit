# ruff: noqa: E501

import pytest

from rob2_kit.application._state import read_json
from rob2_kit.application.contracts import EvidenceReference, ReviewAuthority
from rob2_kit.application.evidence import (
    EvidenceRetrievalRequest,
    ManualSelectionRequest,
    retrieve_evidence,
)
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
    ComparativeEffect,
    ComparisonGroup,
    Compatibility,
    EvidenceSet,
    GroupBoundValues,
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


def _captured_evidence(
    tmp_path,
    source: str = "Grade 3 2 Grade 4 1 Grade 5 1 median 5 and 3",
    reported_ranges: tuple[tuple[int, int], ...] | None = None,
):
    (tmp_path / "article.txt").write_text(source, encoding="utf-8", newline="")
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
    ranges = reported_ranges or ((0, len(source)),)
    evidence = retrieve_evidence(
        tmp_path,
        EvidenceRetrievalRequest(
            trial_id="chaarted",
            manual_selections=tuple(
                ManualSelectionRequest(
                    kind="manual_selection",
                    source_alias="s1",
                    page=1,
                    start=start,
                    end=end,
                    quote=source[start:end],
                )
                for start, end in ranges
            ),
        ),
    ).evidence
    return EvidenceSet(
        target_basis=(evidence[0],),
        reported_values=tuple(evidence),
        reported_context=(evidence[0],),
        population_basis=(evidence[0],),
    )


def _comparative_result(reported_text: str) -> ComparativeEffect:
    return ComparativeEffect(
        form="comparative_effect",
        effect_measure="risk ratio",
        reported_text=reported_text,
        effect=Quantity(
            statistic="risk ratio",
            unit="ratio",
            group_or_category="docetaxel vs control",
            value="0.5",
            denominator_basis="randomized arm",
        ),
        quantities=(
            Quantity(
                statistic="risk",
                unit="proportion",
                group_or_category="docetaxel",
                value="0.2",
                denominator_basis="randomized arm",
            ),
            Quantity(
                statistic="risk",
                unit="proportion",
                group_or_category="control",
                value="0.4",
                denominator_basis="randomized arm",
            ),
        ),
        comparison_groups=("docetaxel", "control"),
    )


def _comparative_card(
    tmp_path,
    source: str = "Risk ratio 0.5; risks 0.2 and 0.4",
    reported_text: str | None = None,
    reported_ranges: tuple[tuple[int, int], ...] | None = None,
    **updates,
) -> ResultCardInput:
    evidence = _captured_evidence(tmp_path, source, reported_ranges)
    card = _card().model_copy(
        update={
            "trial_id": "chaarted",
            "target": ResultTarget(
                outcome_definition="Overall survival",
                measurement="survival status",
                time_point_or_window="follow-up",
                effect_of_interest="effect on Overall survival",
                comparison_groups=(
                    ComparisonGroup(id="docetaxel", label="docetaxel"),
                    ComparisonGroup(id="control", label="control"),
                ),
                intended_analysis_population="randomized participants",
                intended_effect_measure="risk ratio",
            ),
            "reported": _comparative_result(reported_text or source),
            "population": PopulationAccount(
                analyzed_population="randomized participants",
                outcome_measurement_coverage=(
                    OutcomeMeasurementCoverage(group_id="docetaxel", status="measured"),
                    OutcomeMeasurementCoverage(group_id="control", status="measured"),
                ),
            ),
            "source_table_meaning": "Secondary endpoint: Overall survival",
            "evidence": evidence,
        }
    )
    return card.model_copy(update=updates)


def test_hazard_ratio_structure_requires_ordered_bindings_and_complete_qualifiers(tmp_path) -> None:
    source = "Hazard ratio 0.61 (95% CI 0.51 to 0.72; P<0.001); medians 20.2 and 11.7."
    card = _comparative_card(tmp_path, source=source)
    reported = card.reported
    assert isinstance(reported, ComparativeEffect)
    card = card.model_copy(
        update={
            "target": card.target.model_copy(update={"intended_effect_measure": "hazard ratio"}),
            "reported": reported.model_copy(
                update={
                    "effect_measure": "hazard ratio",
                    "effect": Quantity(
                        statistic="hazard ratio",
                        unit="ratio",
                        group_or_category="control vs docetaxel",
                        value=0.61,
                        denominator_basis="randomized arm",
                    ),
                    "quantities": (reported.quantities[1], reported.quantities[0]),
                }
            ),
        }
    )
    repair = save_proposal(
        tmp_path, ProposalInput(outcome_statement="Overall survival", results=(card,))
    )
    assert isinstance(repair, ProposalRepairReceipt)
    pointers = {item.pointer for item in repair.repairs}
    assert "/results/0/reported/quantities" in pointers
    assert "/results/0/reported/effect/group_or_category" in pointers
    assert "/results/0/reported/effect/denominator_basis" in pointers
    assert "/results/0/reported/effect/value" in pointers


@pytest.mark.parametrize(
    "source",
    (
        "The median time was 20.2 and 11.7 months (hazard ratio in the combination group, "
        "0.61; 95% CI, 0.51 to 0.72; P<0.001).",
        "The median time was 20.2 and 11.7 months (hazard ratio for the combination group, "
        "0.61; 95% CI, 0.51 to 0.72;\nP<0.001).",
    ),
)
def test_hazard_ratio_float_is_repaired_for_retained_source_qualifiers(tmp_path, source: str) -> None:
    card = _comparative_card(tmp_path, source=source)
    reported = card.reported
    assert isinstance(reported, ComparativeEffect)
    card = card.model_copy(
        update={
            "target": card.target.model_copy(update={"intended_effect_measure": "hazard ratio"}),
            "reported": reported.model_copy(
                update={
                    "effect_measure": "hazard ratio",
                    "effect": Quantity(
                        statistic="hazard ratio",
                        unit="ratio",
                        group_or_category="docetaxel vs control",
                        value=0.61,
                        denominator_basis="time-to-event analysis",
                    ),
                }
            ),
        }
    )
    repair = save_proposal(
        tmp_path, ProposalInput(outcome_statement="Overall survival", results=(card,))
    )
    assert isinstance(repair, ProposalRepairReceipt)
    assert any(item.pointer == "/results/0/reported/effect/value" for item in repair.repairs)


def test_comparative_order_rejects_reversed_reported_groups(tmp_path) -> None:
    card = _comparative_card(tmp_path)
    reported = card.reported
    assert isinstance(reported, ComparativeEffect)
    card = card.model_copy(
        update={"reported": reported.model_copy(update={"comparison_groups": ("control", "docetaxel")})}
    )
    repair = save_proposal(
        tmp_path, ProposalInput(outcome_statement="Overall survival", results=(card,))
    )
    assert isinstance(repair, ProposalRepairReceipt)
    assert any(item.pointer == "/results/0/reported/comparison_groups" for item in repair.repairs)


@pytest.mark.parametrize(
    ("reported_text", "detail"),
    (
        ("   \t\n", "reported_text must not be empty"),
        ("risk RATIO 0.5; risks 0.2 and 0.4", "reported_text is not contiguous"),
        ("risk ratio 0.5; risks 0.2 0.4", "reported_text is not contiguous"),
    ),
)
def test_comparative_reported_text_requires_exact_normalized_quote(
    tmp_path, reported_text: str, detail: str
) -> None:
    card = _comparative_card(tmp_path, reported=_comparative_result(reported_text))
    repair = save_proposal(
        tmp_path, ProposalInput(outcome_statement="Overall survival", results=(card,))
    )
    assert isinstance(repair, ProposalRepairReceipt)
    assert repair.repairs[0].pointer == "/results/0/reported/reported_text"
    assert detail in repair.repairs[0].detail


def test_comparative_reported_text_accepts_whitespace_normalization(tmp_path) -> None:
    card = _comparative_card(
        tmp_path,
        reported=_comparative_result("Risk   ratio\t0.5;\nrisks 0.2 and 0.4"),
    )
    receipt = save_proposal(
        tmp_path, ProposalInput(outcome_statement="Overall survival", results=(card,))
    )
    assert not isinstance(receipt, ProposalRepairReceipt)


@pytest.mark.parametrize(
    "source, reported_text",
    (
        ("Risk ratio 0.5; risks 0.2 and 0.4", "  Risk ratio 0.5; risks 0.2 and 0.4  "),
        ("  Risk ratio 0.5; risks 0.2 and 0.4  ", "Risk ratio 0.5; risks 0.2 and 0.4"),
    ),
)
def test_comparative_reported_text_ignores_boundary_whitespace(
    tmp_path, source: str, reported_text: str
) -> None:
    card = _comparative_card(tmp_path, source=source, reported_text=reported_text)

    receipt = save_proposal(
        tmp_path, ProposalInput(outcome_statement="Overall survival", results=(card,))
    )

    assert not isinstance(receipt, ProposalRepairReceipt)


@pytest.mark.parametrize(
    "source",
    (
        "Risk ratio 0.5; 95% CI 0.2 to 0.4; P<0.001 combina-\ntion analysis",
        "Risk ratio 0.5; 95% CI 0.2 to 0.4; P<0.001 combina-\r\ntion analysis",
    ),
)
def test_comparative_reported_text_accepts_pdf_layout_projection(tmp_path, source: str) -> None:
    card = _comparative_card(
        tmp_path,
        source=source,
        reported_text="Risk ratio 0.5; 95% CI 0.2 to 0.4; P<0.001 combination analysis",
    )

    receipt = save_proposal(
        tmp_path, ProposalInput(outcome_statement="Overall survival", results=(card,))
    )

    assert not isinstance(receipt, ProposalRepairReceipt)


@pytest.mark.parametrize(
    "source, reported_text",
    (
        ("Risk ratio 0.5; long-term risks 0.2 and 0.4", "Risk ratio 0.5; longterm risks 0.2 and 0.4"),
        ("Risk ratio 0.5; risks 0.2 and 0.4", "risk ratio 0.5; risks 0.2 and 0.4"),
        ("Risk ratio 0.5; 95% CI 0.2 to 0.4", "Risk ratio 0.5; 95% CI 0.2-0.4"),
        ("Risk ratio 0.5; risks 0.2 and 0.4", "Risk ratio 0.5; risks 0.2 or 0.4"),
    ),
)
def test_comparative_reported_text_preserves_source_lexemes(
    tmp_path, source: str, reported_text: str
) -> None:
    card = _comparative_card(tmp_path, source=source, reported_text=reported_text)

    repair = save_proposal(
        tmp_path, ProposalInput(outcome_statement="Overall survival", results=(card,))
    )

    assert isinstance(repair, ProposalRepairReceipt)
    reported_repair = next(
        item for item in repair.repairs if item.pointer == "/results/0/reported/reported_text"
    )
    assert "single cited reported-values Evidence record" in reported_repair.detail
    assert "preserving case, wording, punctuation, CI, and P-value" in reported_repair.detail


def test_comparative_reported_text_cannot_split_values_across_quotes(tmp_path) -> None:
    source = "Risk ratio 0.5; risks 0.2 and 0.4"
    first_quote_end = source.index(" and")
    card = _comparative_card(
        tmp_path,
        source=source,
        reported_text=source[:first_quote_end],
        reported_ranges=((0, first_quote_end), (first_quote_end, len(source))),
    )

    repair = save_proposal(
        tmp_path, ProposalInput(outcome_statement="Overall survival", results=(card,))
    )

    assert isinstance(repair, ProposalRepairReceipt)
    assert any(
        item.pointer == "/results/0/evidence/reported_values" and "0.4" in item.detail
        for item in repair.repairs
    )


def test_comparative_reported_text_cannot_assemble_a_passage_across_quotes(tmp_path) -> None:
    source = "Risk ratio 0.5; risks 0.2 and 0.4"
    first_quote_end = source.index(" and")
    card = _comparative_card(
        tmp_path,
        source=source,
        reported_text=source,
        reported_ranges=((0, first_quote_end), (first_quote_end, len(source))),
    )

    repair = save_proposal(
        tmp_path, ProposalInput(outcome_statement="Overall survival", results=(card,))
    )

    assert isinstance(repair, ProposalRepairReceipt)
    assert any(
        item.pointer == "/results/0/reported/reported_text"
        and "single cited reported-values Evidence record" in item.detail
        for item in repair.repairs
    )


def test_comparative_reported_text_rejects_numeric_substring_collision(tmp_path) -> None:
    card = _comparative_card(
        tmp_path,
        source="Risk ratio 0.5; risks 0.2 and 10.45",
        reported_text="Risk ratio 0.5; risks 0.2 and 10.45",
    )

    repair = save_proposal(
        tmp_path, ProposalInput(outcome_statement="Overall survival", results=(card,))
    )

    assert isinstance(repair, ProposalRepairReceipt)
    assert any(
        item.pointer == "/results/0/evidence/reported_values" and "0.4" in item.detail
        for item in repair.repairs
    )


@pytest.mark.parametrize("value", ("-0.5", "+2", ".5", "1.", "1e-3", "-2.5E+4"))
def test_comparative_reported_text_accepts_complete_numeric_lexemes(tmp_path, value: str) -> None:
    source = f"Risk ratio {value}; risks 0.2 and 0.4"
    card = _comparative_card(tmp_path, source=source, reported_text=source)
    reported = card.reported
    assert isinstance(reported, ComparativeEffect)
    card = card.model_copy(
        update={"reported": reported.model_copy(update={"effect": reported.effect.model_copy(update={"value": value})})}
    )

    receipt = save_proposal(
        tmp_path, ProposalInput(outcome_statement="Overall survival", results=(card,))
    )

    assert not isinstance(receipt, ProposalRepairReceipt)


def test_comparative_reported_text_rejects_signed_numeric_collision(tmp_path) -> None:
    source = "Risk ratio -10.5; risks 0.2 and 0.4"
    card = _comparative_card(tmp_path, source=source, reported_text=source)
    reported = card.reported
    assert isinstance(reported, ComparativeEffect)
    card = card.model_copy(
        update={"reported": reported.model_copy(update={"effect": reported.effect.model_copy(update={"value": "-.5"})})}
    )

    repair = save_proposal(
        tmp_path, ProposalInput(outcome_statement="Overall survival", results=(card,))
    )

    assert isinstance(repair, ProposalRepairReceipt)
    assert any("-.5" in item.detail for item in repair.repairs)


def test_save_proposal_aggregates_contract_and_source_repairs(tmp_path) -> None:
    card = _comparative_card(
        tmp_path,
        target=ResultTarget(
            outcome_definition="Overall mortality",
            measurement="survival status",
            time_point_or_window="follow-up",
            effect_of_interest="effect on Overall mortality",
            comparison_groups=(
                ComparisonGroup(id="docetaxel", label="docetaxel"),
                ComparisonGroup(id="control", label="control"),
            ),
            intended_analysis_population="randomized participants",
            intended_effect_measure="risk ratio",
        ),
        source_table_meaning="unrelated endpoint",
        reported=_comparative_result("Risk ratio 0.5"),
        population=PopulationAccount(
            analyzed_population="randomized participants",
            outcome_measurement_coverage=(
                OutcomeMeasurementCoverage(group_id="docetaxel", status="measured"),
            ),
        ),
    )

    repair = save_proposal(
        tmp_path, ProposalInput(outcome_statement="Overall survival", results=(card,))
    )

    assert isinstance(repair, ProposalRepairReceipt)
    assert {item.pointer for item in repair.repairs} >= {
        "/results/0/target/outcome_definition",
        "/results/0/target/effect_of_interest",
        "/results/0/source_table_meaning",
        "/results/0/evidence/reported_values",
        "/results/0/population/outcome_measurement_coverage",
    }
    assert sum("reported value" in item.detail for item in repair.repairs) == 2


def test_comparison_coverage_repair_identifies_group_ids_and_current_coverage(tmp_path) -> None:
    card = _comparative_card(tmp_path)
    reported = card.reported
    assert isinstance(reported, ComparativeEffect)
    card = card.model_copy(
        update={
            "reported": reported.model_copy(
                update={"comparison_groups": ("control", "placebo")}
            ),
            "population": PopulationAccount(
                analyzed_population="randomized participants",
                outcome_measurement_coverage=(
                    OutcomeMeasurementCoverage(
                        group_id="docetaxel", status="not_measured", explanation="not reported"
                    ),
                ),
            ),
        }
    )

    repair = save_proposal(
        tmp_path, ProposalInput(outcome_statement="Overall survival", results=(card,))
    )

    assert isinstance(repair, ProposalRepairReceipt)
    details = {item.pointer: item.detail for item in repair.repairs}
    assert details == {
        "/results/0/reported/comparison_groups": (
            "server-derived compatibility: comparison_coverage_incomplete; "
            "target comparison group IDs (ordered): ('docetaxel', 'control'); "
            "reported comparison group IDs: ('control', 'placebo'); "
            "align reported IDs to target IDs only when Evidence supports the target bindings; "
            "otherwise correct target.comparison_groups or use the appropriate needs_input "
            "disposition"
        ),
        "/results/0/population/outcome_measurement_coverage": (
            "server-derived compatibility: comparison_coverage_incomplete; "
            "missing/non-measured target IDs and current statuses: "
            "(('docetaxel', 'not_measured'), ('control', 'missing')); "
            "set each target group to measured only when Evidence supports outcome measurement, "
            "otherwise use the appropriate needs_input disposition"
        ),
    }


@pytest.mark.parametrize(
    ("reported_groups", "coverage", "expected_pointer"),
    (
        (
            ("control", "placebo"),
            ("measured", "measured"),
            "/results/0/reported/comparison_groups",
        ),
        (
            ("docetaxel", "control"),
            ("not_measured", None),
            "/results/0/population/outcome_measurement_coverage",
        ),
    ),
)
def test_comparison_coverage_repairs_only_report_the_affected_pointer(
    tmp_path, reported_groups, coverage, expected_pointer
) -> None:
    card = _comparative_card(tmp_path)
    reported = card.reported
    assert isinstance(reported, ComparativeEffect)
    updates = {"reported": reported.model_copy(update={"comparison_groups": reported_groups})}
    if coverage[0] is None:
        updates["population"] = PopulationAccount(
            analyzed_population="randomized participants"
        )
    else:
        updates["population"] = PopulationAccount(
            analyzed_population="randomized participants",
            outcome_measurement_coverage=tuple(
                OutcomeMeasurementCoverage(
                    group_id=group,
                    status=status,
                    explanation=None if status == "measured" else "not reported",
                )
                for group, status in zip(("docetaxel", "control"), coverage, strict=True)
                if status is not None
            ),
        )
    card = card.model_copy(update=updates)
    repair = save_proposal(
        tmp_path, ProposalInput(outcome_statement="Overall survival", results=(card,))
    )
    assert isinstance(repair, ProposalRepairReceipt)
    assert {item.pointer for item in repair.repairs} == {expected_pointer}


def test_effect_measure_repair_identifies_target_and_reported_values(tmp_path) -> None:
    card = _comparative_card(tmp_path)
    reported = card.reported
    assert isinstance(reported, ComparativeEffect)
    card = card.model_copy(
        update={"reported": reported.model_copy(update={"effect_measure": "odds ratio"})}
    )

    repair = save_proposal(
        tmp_path, ProposalInput(outcome_statement="Overall survival", results=(card,))
    )

    assert isinstance(repair, ProposalRepairReceipt)
    assert {
        (item.pointer, item.detail)
        for item in repair.repairs
        if item.pointer == "/results/0/reported/effect_measure"
    } == {
        (
            "/results/0/reported/effect_measure",
            "server-derived compatibility: effect_measure_mismatch; "
            "target intended effect measure: 'risk ratio'; "
            "reported effect measure: 'odds ratio'; "
            "make reported.effect_measure exactly match target.intended_effect_measure only "
            "when that is the source-reported measure for the requested outcome; otherwise "
            "correct the target or use the appropriate needs_input disposition, preserving "
            "Evidence",
        )
    }


def test_contract_repairs_report_exact_outcome_values_and_closed_source_forms(tmp_path) -> None:
    card = _comparative_card(
        tmp_path,
        source_table_meaning="unrelated endpoint",
        target=ResultTarget(
            outcome_definition="wrong definition",
            measurement="survival status",
            time_point_or_window="follow-up",
            effect_of_interest="wrong effect",
            comparison_groups=(
                ComparisonGroup(id="docetaxel", label="docetaxel"),
                ComparisonGroup(id="control", label="control"),
            ),
            intended_analysis_population="randomized participants",
            intended_effect_measure="risk ratio",
        ),
    )

    repair = save_proposal(
        tmp_path,
        ProposalInput(
            outcome_statement="Overall survival, defined as death from any cause",
            results=(card,),
        ),
    )

    assert isinstance(repair, ProposalRepairReceipt)
    details = {item.pointer: item.detail for item in repair.repairs}
    assert details["/results/0/target/outcome_definition"] == (
        "target outcome definition must be exactly 'death from any cause'"
    )
    assert details["/results/0/target/effect_of_interest"] == (
        "effect of interest must be exactly 'effect on death from any cause'"
    )
    assert details["/results/0/source_table_meaning"] == (
        "source-table meaning must be one of: 'death from any cause', "
        "'Primary endpoint: death from any cause', "
        "'Secondary endpoint: death from any cause', "
        "'Reported outcome: death from any cause', "
        "'Outcome: death from any cause'"
    )


@pytest.mark.parametrize(
    "role", ("target_basis", "reported_values", "reported_context", "population_basis")
)
def test_proposal_repair_mints_evidence_from_unpersisted_reference(tmp_path, role: str) -> None:
    card = _comparative_card(tmp_path)
    missing = EvidenceReference(kind="evidence", identity="sha256:" + "f" * 64)
    evidence = card.evidence.model_copy(update={role: (missing,)})
    card = card.model_copy(update={"evidence": evidence})

    repair = save_proposal(
        tmp_path, ProposalInput(outcome_statement="Overall survival", results=(card,))
    )

    assert isinstance(repair, ProposalRepairReceipt)
    assert any(
        item.pointer == f"/results/0/evidence/{role}"
        and "sha256:" + "f" * 64 in item.detail
        and "not persisted Evidence" in item.detail
        and "retrieve_evidence" in item.detail
        and "exact normal, manual, or visual selection" in item.detail
        and "returned Evidence identity" in item.detail
        for item in repair.repairs
    )


def test_proposal_repair_preserves_corrupt_evidence_detail(tmp_path) -> None:
    card = _comparative_card(tmp_path)
    evidence = card.evidence.target_basis[0]
    raw = read_json(tmp_path, f"evidence-{evidence.identity.removeprefix('sha256:')}.json")
    assert raw is not None
    raw["quote"] = "tampered"
    from rob2_kit.application._state import write_jsons

    write_jsons(tmp_path, {f"evidence-{evidence.identity.removeprefix('sha256:')}.json": raw})

    repair = save_proposal(
        tmp_path, ProposalInput(outcome_statement="Overall survival", results=(card,))
    )

    assert isinstance(repair, ProposalRepairReceipt)
    matching = [
        item for item in repair.repairs if item.pointer == "/results/0/evidence/target_basis"
    ]
    assert matching
    assert any("Evidence identity is corrupt" in item.detail for item in matching)
    assert all("not persisted Evidence" not in item.detail for item in matching)


def test_needs_input_unavailable_evidence_uses_indexed_minting_repair(tmp_path) -> None:
    _comparative_card(tmp_path)
    missing = EvidenceReference(kind="evidence", identity="sha256:" + "e" * 64)
    proposal = ProposalInput(
        outcome_statement="Overall survival",
        needs_input=(
            PreapprovalNeedsInput(
                trial_id="chaarted",
                reason=NeedsInputReason.OUTCOME_NOT_REPORTED,
                missing_facts=("an outcome result",),
                evidence=(missing,),
            ),
        ),
    )

    repair = save_proposal(tmp_path, proposal)

    assert isinstance(repair, ProposalRepairReceipt)
    assert any(
        item.pointer == "/needs_input/0/evidence/0"
        and "not persisted Evidence" in item.detail
        and "retrieve_evidence" in item.detail
        for item in repair.repairs
    )


@pytest.mark.parametrize(
    ("field", "value", "pointer"),
    (
        ("outcome_definition", "Overall mortality", "/results/0/target/outcome_definition"),
        ("effect_of_interest", "effect on Overall mortality", "/results/0/target/effect_of_interest"),
        ("source_table_meaning", "unrelated endpoint", "/results/0/source_table_meaning"),
    ),
)
def test_comparative_contract_repairs_reject_mismatched_target_fields(
    tmp_path, field: str, value: str, pointer: str
) -> None:
    if field == "source_table_meaning":
        card = _comparative_card(tmp_path, source_table_meaning=value)
    else:
        card = _comparative_card(tmp_path)
        card = card.model_copy(update={"target": card.target.model_copy(update={field: value})})
    repair = save_proposal(
        tmp_path, ProposalInput(outcome_statement="Overall survival", results=(card,))
    )
    assert isinstance(repair, ProposalRepairReceipt)
    assert any(item.pointer == pointer for item in repair.repairs)


def test_save_proposal_repairs_keep_original_result_index_when_trials_are_sorted(tmp_path) -> None:
    for trial_id in ("alpha", "zulu"):
        trial_path = tmp_path / trial_id
        trial_path.mkdir()
        (trial_path / "article.txt").write_text("captured result", encoding="utf-8")
    preflight = preflight_sources(
        tmp_path,
        PreflightRequest(
            roots=tuple(
                AuthorizedSourceRoot(alias=trial_id, path=trial_id, trial_id=trial_id)
                for trial_id in ("alpha", "zulu")
            )
        ),
    )
    plan = save_intake_plan(
        tmp_path,
        preflight.reference,
        tuple(
            IntakePlanEntry(
                candidate_identity=candidate.identity,
                role="main_article" if candidate.trial_id == "alpha" else "supplement",
                disposition=SourceDisposition.INCLUDE,
                criticality=SourceCriticality.REQUIRED,
            )
            for candidate in preflight.candidates
        ),
    )
    capture_batch(
        tmp_path,
        CaptureRequest(
            plan=plan.plan,
            acknowledgment=acknowledge_intake(tmp_path, plan.plan, ReviewAuthority.HOST),
        ),
    )
    valid = _card().model_copy(
        update={
            "trial_id": "zulu",
            "reported": _comparative_result("captured result"),
            "target": ResultTarget(
                outcome_definition="Overall survival",
                measurement="survival status",
                time_point_or_window="follow-up",
                effect_of_interest="effect on Overall survival",
                comparison_groups=(
                    ComparisonGroup(id="docetaxel", label="docetaxel"),
                    ComparisonGroup(id="control", label="control"),
                ),
                intended_analysis_population="randomized participants",
                intended_effect_measure="risk ratio",
            ),
            "source_table_meaning": "Secondary endpoint: Overall survival",
        }
    )
    invalid = valid.model_copy(
        update={
            "trial_id": "alpha",
            "target": valid.target.model_copy(update={"outcome_definition": "Overall mortality"}),
        }
    )
    repair = save_proposal(
        tmp_path,
        ProposalInput(
            outcome_statement="Overall survival",
            results=(valid, invalid),
        ),
    )
    assert isinstance(repair, ProposalRepairReceipt)
    assert repair.repairs[0].pointer == "/results/1/target/outcome_definition"


def test_save_proposal_repairs_incompatible_result_before_persisting(tmp_path) -> None:
    card = _card().model_copy(
        update={
            "trial_id": "chaarted",
            "target": _card().target.model_copy(
                update={"effect_of_interest": "effect on Grade 3 or worse toxicity"}
            ),
            "source_table_meaning": "Reported outcome: Grade 3 or worse toxicity",
            "evidence": _captured_evidence(tmp_path),
        }
    )

    repair = save_proposal(
        tmp_path, ProposalInput(outcome_statement="Grade 3 or worse toxicity", results=(card,))
    )

    assert isinstance(repair, ProposalRepairReceipt)
    assert {(item.pointer, item.detail) for item in repair.repairs} == {
        (
            "/results/0/reported",
            "server-derived compatibility: single_group_category_profile_has_no_comparator",
        )
    }
    assert read_json(tmp_path, "proposal_review.json") is None


def test_save_proposal_repairs_review_required_derivation_before_persisting(tmp_path) -> None:
    evidence = _captured_evidence(tmp_path)
    card = _card().model_copy(
        update={
            "trial_id": "chaarted",
            "evidence": evidence,
            "reported": GroupBoundValues(
                form="group_bound_values",
                quantities=(
                    Quantity(
                        statistic="median",
                        unit="months",
                        group_or_category="docetaxel",
                        value=5,
                    ),
                    Quantity(
                        statistic="median",
                        unit="months",
                        group_or_category="control",
                        value=3,
                    ),
                ),
                comparison_groups=("docetaxel", "control"),
            ),
            "population": PopulationAccount(
                analyzed_population="randomized participants",
                outcome_measurement_coverage=(
                    OutcomeMeasurementCoverage(group_id="docetaxel", status="measured"),
                    OutcomeMeasurementCoverage(group_id="control", status="measured"),
                ),
            ),
            "target": ResultTarget(
                outcome_definition="Overall survival",
                measurement="survival status",
                time_point_or_window="follow-up",
                effect_of_interest="effect on Overall survival",
                comparison_groups=(
                    ComparisonGroup(id="docetaxel", label="docetaxel"),
                    ComparisonGroup(id="control", label="control"),
                ),
                intended_analysis_population="randomized participants",
                intended_effect_measure="risk ratio",
            ),
            "source_table_meaning": "Secondary endpoint: Overall survival",
        }
    )

    repair = save_proposal(
        tmp_path, ProposalInput(outcome_statement="Overall survival", results=(card,))
    )

    assert isinstance(repair, ProposalRepairReceipt)
    assert {(item.pointer, item.detail) for item in repair.repairs} == {
        ("/results/0/derived", "server-derived compatibility: derivation_required")
    }
    assert read_json(tmp_path, "proposal_review.json") is None


@pytest.mark.parametrize(
    ("field", "value", "pointer"),
    (
        ("outcome_definition", "Overall mortality", "/results/0/target/outcome_definition"),
        (
            "effect_of_interest",
            "effect on Overall mortality",
            "/results/0/target/effect_of_interest",
        ),
        ("source_table_meaning", "unrelated endpoint", "/results/0/source_table_meaning"),
    ),
)
def test_group_bound_values_contract_rejects_mismatched_target_fields(
    tmp_path, field: str, value: str, pointer: str
) -> None:
    card = _comparative_card(
        tmp_path,
        source="Median 5 and 3",
        reported=GroupBoundValues(
            form="group_bound_values",
            quantities=(
                Quantity(statistic="median", unit="months", group_or_category="docetaxel", value=5),
                Quantity(statistic="median", unit="months", group_or_category="control", value=3),
            ),
            comparison_groups=("docetaxel", "control"),
        ),
    )
    if field == "source_table_meaning":
        card = card.model_copy(update={field: value})
    else:
        card = card.model_copy(update={"target": card.target.model_copy(update={field: value})})

    repair = save_proposal(
        tmp_path, ProposalInput(outcome_statement="Overall survival", results=(card,))
    )

    assert isinstance(repair, ProposalRepairReceipt)
    assert any(item.pointer == pointer for item in repair.repairs)


def test_group_bound_values_contract_accepts_matching_target_fields(tmp_path) -> None:
    card = _comparative_card(
        tmp_path,
        source="Median 5 and 3",
        reported=GroupBoundValues(
            form="group_bound_values",
            quantities=(
                Quantity(statistic="median", unit="months", group_or_category="docetaxel", value=5),
                Quantity(statistic="median", unit="months", group_or_category="control", value=3),
            ),
            comparison_groups=("docetaxel", "control"),
        ),
    )

    repair = save_proposal(
        tmp_path, ProposalInput(outcome_statement="Overall survival", results=(card,))
    )

    assert isinstance(repair, ProposalRepairReceipt)
    assert {(item.pointer, item.detail) for item in repair.repairs} == {
        ("/results/0/derived", "server-derived compatibility: derivation_required")
    }


@pytest.mark.parametrize("denominator_basis", (None, " "))
def test_save_proposal_repairs_comparative_effect_without_denominator_bases(
    tmp_path, denominator_basis: str | None
) -> None:
    card = _card().model_dump(mode="json")
    card["reported"] = {
        "form": "comparative_effect",
        "effect_measure": "risk ratio",
        "reported_text": "risk ratio 0.5; risks 0.2 and 0.4",
        "effect": {
            "statistic": "risk ratio",
            "unit": "ratio",
            "group_or_category": "docetaxel versus control",
            "value": "0.5",
        },
        "quantities": [
            {
                "statistic": "risk",
                "unit": "proportion",
                "group_or_category": "docetaxel",
                "value": "0.2",
            },
            {
                "statistic": "risk",
                "unit": "proportion",
                "group_or_category": "control",
                "value": "0.4",
            },
        ],
        "comparison_groups": ["docetaxel", "control"],
    }
    if denominator_basis is not None:
        reported = card["reported"]
        assert isinstance(reported, dict)
        reported["effect"]["denominator_basis"] = denominator_basis
        for quantity in reported["quantities"]:
            quantity["denominator_basis"] = denominator_basis

    repair = save_proposal(
        tmp_path, {"outcome_statement": "Overall survival", "results": [card]}
    )

    assert isinstance(repair, ProposalRepairReceipt)
    assert any(
        item.pointer.startswith("/results/0/reported") and "denominator basis" in item.detail
        for item in repair.repairs
    )


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

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from support.rob2 import _assessment_workspace, _call, _domain_draft

from rob2_kit.application.domains import _comparison_cards, reconcile_missing_data
from rob2_kit.logic.evaluator import evaluate_domain
from rob2_kit.workflow_models import SourceRole


def _save_domain(
    workspace: Path,
    domain_id: str,
    revision: int,
    evidence: dict[str, object],
) -> int:
    saved = _call(
        workspace,
        "save_domain_judgment",
        _domain_draft("trial", domain_id, revision, evidence),
    )
    assert saved["outcome"] == "success", saved
    return int(saved["head"]["state_revision"])


def test_deviation_card_exposes_provenance_without_classifying_prose(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    revision = _save_domain(workspace, "domain:randomization", revision, evidence)
    searched = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": "requested outcome", "mode": "any", "limit": 1},
    )["data"]

    context = _call(workspace, "get_domain_context", {})["data"]
    first_card = context["comparison_cards"][0]
    assert first_card["question_id"] == "sq:deviations:context-deviations"
    questions_by_id: dict[str, list[dict[str, Any]]] = {}
    for question in context["questions"]:
        questions_by_id.setdefault(question["id"], []).append(question)
    for comparison_card in context["comparison_cards"]:
        assert "question_wording" not in comparison_card
        assert "options" not in comparison_card
        matching_questions = questions_by_id.get(comparison_card["question_id"], [])
        assert len(matching_questions) == 1
    first_question = questions_by_id[first_card["question_id"]][0]
    assert set(first_question["options"]) == {
        "yes",
        "probably_yes",
        "probably_no",
        "no",
        "no_information",
    }
    intended = next(item for item in first_card["slots"] if item["name"] == "intended_intervention")
    assert intended["status"] == "supported"
    assert "a: assigned to intervention" in intended["value"]
    scientific = {
        item["name"]: item
        for item in first_card["slots"]
        if item["name"] != "intended_intervention"
    }
    assert all(item["status"] == "unknown" for item in scientific.values())
    assert all(not item["passages"] for item in scientific.values())
    searched_hit = searched["hits"][0]
    assert any(
        (passage["source_id"], passage["page"], passage["start_line"], passage["end_line"])
        == (
            searched_hit["source_id"],
            searched_hit["page"],
            searched_hit["start_line"],
            searched_hit["end_line"],
        )
        for group in first_card["passage_groups"]
        for passage in group["passages"]
    )
    assert all(group["source_role"] for group in first_card["passage_groups"])
    assert "use the complete official guidance" in first_card["prompt"]


def test_missing_data_card_marks_conflicting_typed_counts(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    revision = _save_domain(workspace, "domain:randomization", revision, evidence)
    revision = _save_domain(workspace, "domain:deviations", revision, evidence)
    draft = _domain_draft("trial", "domain:missing", revision, evidence)
    answer = next(
        item for item in draft["answers"] if item["question_id"] == "sq:missing:data-available"
    )
    row = {
        "arm": "intervention",
        "population": "randomized participants",
        "unit": "participants",
        "time_point": "week 12",
        "randomized": 100,
        "observed": 95,
    }
    answer["missing_data"] = [row, row | {"observed": 94}]
    saved = _call(workspace, "save_domain_judgment", draft)
    assert saved["outcome"] == "success", saved

    context = _call(
        workspace,
        "get_domain_context",
        {"domain_id": "domain:missing"},
    )["data"]
    card = context["comparison_cards"][0]
    slots = {item["name"]: item for item in card["slots"]}
    assert slots["approved_outcome"]["status"] == "supported"
    assert slots["randomized"]["status"] == "supported"
    assert slots["observed"]["status"] == "conflicted"
    assert card["missing_data"]["conflicts"]
    assert slots["randomized"]["passages"]
    assert slots["follow_up_availability"]["status"] == "unknown"


def test_missing_data_arithmetic_never_combines_incompatible_scopes() -> None:
    rows = [
        {
            "arm": "intervention",
            "population": "randomized participants",
            "unit": "participants",
            "time_point": "week 12",
            "randomized": 100,
            "observed": 95,
        },
        {
            "arm": "intervention",
            "population": "per-protocol participants",
            "unit": "participants",
            "time_point": "week 24",
            "randomized": 80,
            "observed": 60,
        },
    ]

    reconciled = reconcile_missing_data(rows)

    assert sorted(item["missing"] for item in reconciled["rows"]) == [5, 20]
    assert not reconciled["conflicts"]
    assert len({tuple(item["scope"].values()) for item in reconciled["rows"]}) == 2


def test_selection_card_exposes_result_but_not_plan_correspondence(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    for domain_id in (
        "domain:randomization",
        "domain:deviations",
        "domain:missing",
        "domain:measurement",
    ):
        revision = _save_domain(workspace, domain_id, revision, evidence)

    card = _call(workspace, "get_domain_context", {})["data"]["comparison_cards"][0]
    slots = {item["name"]: item for item in card["slots"]}
    assert slots["reported_result"]["status"] == "supported"
    assert "group_bound_values" in slots["reported_result"]["value"]
    assert slots["analysis_plan"]["status"] == "unknown"
    assert slots["correspondence"]["status"] == "unknown"


@pytest.mark.parametrize(
    "case",
    json.loads(
        Path("eval/d5-correspondence-presentation-controls.json").read_text(encoding="utf-8")
    )["cases"],
    ids=lambda case: case["id"],
)
def test_selection_comparison_preserves_neutral_method_change_evidence(
    case: dict[str, Any],
) -> None:
    source_id = "source_" + "a" * 64
    catalog = {
        "sha256:" + str(index) * 64: {
            "identity": "sha256:" + str(index) * 64,
            "handle": "eh_" + str(index) * 16,
            "kind": "narrative",
            "source_id": source_id,
            "page": index,
            "start_line": 1,
            "end_line": 3,
            "quote": case[key],
        }
        for index, key in enumerate(("reported", "planned", "change"), start=1)
    }
    evidence = catalog["sha256:" + "1" * 64]
    result = {
        "kind": "assessable",
        "target": {},
        "reported": {
            "form": "comparative_effect",
            "endpoint": {"name": "Fixed endpoint"},
            "analysis_population": "All randomized participants",
            "effect_measure": "Ratio",
            "estimate": "0.8",
            "precision": "95% CI 0.6 to 1.1",
            "group_values": [],
        },
        "evidence": [{"handle": evidence["handle"], "identity": evidence["identity"]}],
        "bindings": [{"field": {"path": "/reported"}, "evidence_index": 0}],
    }
    checkpoint = [
        {"question_id": "sq:selection:prespecified-analysis", "unknowns": case["unknowns"]}
    ]
    sources = [{"id": source_id, "role": "protocol", "label": "combined.pdf"}]
    inputs = deepcopy((result, catalog, checkpoint, sources))
    card = _comparison_cards("domain:selection", result, catalog, checkpoint, sources)[0]

    assert (result, catalog, checkpoint, sources) == inputs
    assert card["reported_result"] == result["reported"]
    assert [slot["name"] for slot in card["slots"]] == [
        "reported_result",
        "analysis_plan",
        "correspondence",
        "amendment",
        "unblinded_access",
    ]
    assert card["slots"][0]["passages"][0]["handle"] == evidence["handle"]
    assert all(slot["status"] == "unknown" for slot in card["slots"][1:])
    assert {ref["handle"] for ref in card["passage_groups"][0]["passages"]} == {
        value["handle"] for value in catalog.values()
    }
    assert (
        not {"answers", "judgment", "expected_answer", "expected_judgment", "propositions"}
        & card.keys()
    )
    assert "source conflicts" in card["prompt"]


def test_result_slot_uses_only_field_bound_passages() -> None:
    source_a = "source_" + "a" * 64
    source_b = "source_" + "b" * 64
    evidence_a = {"handle": "eh_" + "1" * 16, "identity": "sha256:" + "1" * 64}
    evidence_b = {"handle": "eh_" + "2" * 16, "identity": "sha256:" + "2" * 64}
    catalog = {
        evidence_a["identity"]: {
            **evidence_a,
            "kind": "narrative",
            "source_id": source_a,
            "page": 1,
            "start_line": 1,
            "end_line": 1,
        },
        evidence_b["identity"]: {
            **evidence_b,
            "kind": "narrative",
            "source_id": source_b,
            "page": 2,
            "start_line": 3,
            "end_line": 3,
        },
    }
    result = {
        "kind": "assessable",
        "target": {},
        "reported": {
            "form": "group_bound_values",
            "endpoint": {"name": "bound endpoint"},
        },
        "evidence": [evidence_a, evidence_b],
        "bindings": [
            {
                "field": {"path": "/reported/endpoint/name"},
                "evidence_index": 1,
                "value_digest": "sha256:" + "3" * 64,
            }
        ],
    }
    sources = [
        {"id": source_a, "role": "main_article", "label": "main"},
        {"id": source_b, "role": "protocol", "label": "protocol"},
    ]

    card = _comparison_cards("domain:selection", result, catalog, [], sources)[0]
    slot = next(item for item in card["slots"] if item["name"] == "reported_result")

    assert [item["handle"] for item in slot["passages"]] == [evidence_b["handle"]]


def test_card_keeps_reported_completers_distinct_from_randomized_target() -> None:
    result = {
        "kind": "assessable",
        "relation": "narrower",
        "target": {
            "outcome_definition": "Disability at one year",
            "measurement": {"method": "Disability questionnaire"},
            "time_point_or_window": {"description": "One year"},
            "intended_analysis_population": "All randomized participants",
            "intended_effect_measure": "Between-group comparison",
            "comparison_groups": [
                {"id": "a", "assignment": "Intervention"},
                {"id": "b", "assignment": "Placebo"},
            ],
        },
        "reported": {
            "form": "group_bound_values",
            "endpoint": {"name": "Disability score"},
            "analysis_population": "One-year completers: 144 of 162 randomized participants",
            "group_values": [
                {"group_id": "a", "statistic": "median", "value": "7", "unit": "points"},
                {"group_id": "b", "statistic": "median", "value": "14", "unit": "points"},
            ],
        },
        "evidence": [],
    }

    for domain in ("domain:deviations", "domain:missing", "domain:selection"):
        card = _comparison_cards(domain, result, {}, [], [])[0]
        assert card["result_scope"]["scope_basis"] == "assessment_target"
        assert card["result_scope"]["population"] == "All randomized participants"
        assert card["reported_result"] == result["reported"]
        assert card["target_relation"] == "narrower"
        assert "definition" not in card["reported_result"]["endpoint"]
        assert "effect_measure" not in card["reported_result"]
        assert "propositions" not in card
        assert card["participant_flow"] == []


def test_selection_card_keeps_unopened_supplement_and_combined_protocol_navigable() -> None:
    def source(source_id: str, role: str, logical_path: str) -> dict[str, object]:
        return {
            "id": source_id,
            "role": role,
            "label": logical_path,
            "logical_path": logical_path,
            "page_count": 12,
            "sha256": "sha256:" + source_id[-1] * 64,
            "projection_hash": "sha256:" + source_id[-1] * 64,
        }

    sources = [
        source("source_main", "main_article", "main.txt"),
        source("source_supplement", "supplement", "supplement.pdf"),
        source("source_protocol", "protocol", "combined-protocol.pdf"),
    ]
    card = _comparison_cards(
        "domain:selection",
        {"kind": "assessable", "target": {}, "reported": {}, "evidence": []},
        {},
        [],
        sources,
    )[0]

    groups = {item["source_id"]: item for item in card["passage_groups"]}
    assert set(groups) == {item["id"] for item in sources}
    assert groups["source_supplement"]["logical_path"] == "supplement.pdf"
    assert groups["source_protocol"]["logical_path"] == "combined-protocol.pdf"
    assert all(not item["passages"] for item in groups.values())
    # The inventory adds bounded metadata, not captured source text.
    serialized = json.dumps(card, ensure_ascii=False, separators=(",", ":"))
    baseline = _comparison_cards("domain:selection", {}, {}, [], [])[0]
    baseline_size = len(json.dumps(baseline, ensure_ascii=False, separators=(",", ":")))
    assert 0 < len(serialized) - baseline_size < 2_000


def test_unopened_irrelevant_source_is_a_control_not_evidence() -> None:
    source = {
        "id": "source_irrelevant",
        "role": "supplement",
        "label": "unrelated-supplement.pdf",
        "logical_path": "unrelated-supplement.pdf",
        "page_count": 4,
        "sha256": "sha256:" + "a" * 64,
        "projection_hash": "sha256:" + "b" * 64,
    }
    card = _comparison_cards(
        "domain:selection",
        {"kind": "assessable", "target": {}, "reported": {}, "evidence": []},
        {},
        [],
        [source],
    )[0]

    group = card["passage_groups"][0]
    assert group["source_id"] == source["id"]
    assert group["passages"] == []
    assert all(slot["status"] == "unknown" for slot in card["slots"])


def test_contrast_fixture_is_paired_traceable_and_development_only() -> None:
    fixture = json.loads(Path("eval/synthetic-contrast-cards.json").read_text(encoding="utf-8"))
    assert fixture["schema"] == "rob2-kit.contrast-fixtures.v0.5"
    assert fixture["purpose"] == "development_only"
    assert "requires_independent_expert_review" in fixture["reference_status"]
    assert fixture["experimental_arms"] == [
        "current_domain_context",
        "assembled_passages",
        "assembled_passages_with_comparison_layout",
        "assembled_passages_with_minimal_typed_classification",
    ]
    cases = fixture["cases"]
    assert {case["pair_id"] for case in cases} == {
        "d2-trial-context-cause",
        "d3-outcome-availability",
        "d5-plan-correspondence",
    }
    assert all(sum(item["pair_id"] == case["pair_id"] for item in cases) == 2 for case in cases)
    assert {case["expected_judgment"] for case in cases} == {"low", "some_concerns", "high"}
    assert {answer for case in cases for answer in case["expected_answer_path"].values()} == {
        "yes",
        "probably_yes",
        "probably_no",
        "no",
        "no_information",
    }

    passage_ids = {passage["passage_id"] for case in cases for passage in case["passages"]}
    assert len(passage_ids) == sum(len(case["passages"]) for case in cases)
    assert all(any(passage["hard_negative"] for passage in case["passages"]) for case in cases)
    assert all(
        passage["source_role"] in {role.value for role in SourceRole}
        for case in cases
        for passage in case["passages"]
    )
    for case in cases:
        evaluation = evaluate_domain(case["domain_id"], case["expected_answer_path"])
        assert evaluation.judgment.value == case["expected_judgment"]
        for premise in case["premises"]:
            assert premise["rationale"]
            assert premise["status"] in {
                "full",
                "partial",
                "unsupported",
                "conflicted",
                "genuinely_unavailable",
            }
            assert all(
                evidence_id in passage_ids
                for evidence_set in premise["acceptable_evidence_sets"]
                for evidence_id in evidence_set
            )


def test_comparison_navigation_does_not_add_scientific_dependencies() -> None:
    from rob2_kit.application.domains import _official_guidance_recovery
    from rob2_kit.interfaces.mcp.contracts import ComparisonCard
    from rob2_kit.packs import SCIENTIFIC_PACK

    questions = {q.id: q for q in SCIENTIFIC_PACK.questions}
    for domain in ("deviations", "missing", "measurement", "selection"):
        card = _comparison_cards("domain:" + domain, {}, {}, [], [])[0]
        ComparisonCard.model_validate(card)
        assert card["slots"]
        assert not {"propositions", "paired_examples", "answers", "judgment"} & card.keys()
        core = _official_guidance_recovery("domain:" + domain)
        assert core["complete"]
        assert core["sections"]
    # D5 selection questions stay independent of plan availability; D2 impact
    # stays conditional on an inappropriate or unknown assignment analysis.
    for qid in ("sq:selection:multiple-measurements", "sq:selection:multiple-analyses"):
        assert questions[qid].activation.model_dump(mode="json") == {"kind": "always"}
    assert questions["sq:deviations:substantial-impact"].activation.model_dump(mode="json") != {
        "kind": "always"
    }


def test_native_completion_preview_and_save_preserve_unknown_observation(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    for domain in ("domain:randomization", "domain:deviations"):
        revision = _save_domain(workspace, domain, revision, evidence)
    row = {
        "arm": "intervention",
        "population": "randomized participants",
        "unit": "participants",
        "time_point": "week 12",
        "randomized": 100,
        "completed": 95,
        "analyzed": 100,
        "basis": [evidence["handle"]],
        "semantics": {
            "population_role": "follow_up",
            "outcome_status": "unknown",
            "censoring": {"kind": "administrative", "timing": "common cutoff"},
        },
    }
    before = _call(workspace, "get_status", {})["head"]["state_revision"]
    preview = _call(
        workspace,
        "get_domain_context",
        {
            "domain_id": "domain:missing",
            "missing_data": [row],
        },
    )
    assert preview["outcome"] == "success", preview
    assert _call(workspace, "get_status", {})["head"]["state_revision"] == before
    card = preview["data"]["comparison_cards"][0]
    flow = {item["kind"]: item for item in card["participant_flow"]}
    assert flow["completed"]["value"] == 95
    assert flow["observed"]["value"] is None and flow["observed"]["status"] == "unknown"
    assert flow["completed"]["result_identity"] == card["result_identity"]
    assert flow["completed"]["scope"]["arm"] == "intervention"
    assert flow["completed"]["passages"]
    assert flow["completed"]["semantics"]["censoring"]["kind"] == "administrative"
    assert card["missing_data"]["rows"][0]["missing"] is None

    draft = _domain_draft("trial", "domain:missing", revision, evidence)
    next(a for a in draft["answers"] if a["question_id"] == "sq:missing:data-available")[
        "missing_data"
    ] = [row]
    saved = _call(workspace, "save_domain_judgment", draft)
    assert saved["outcome"] == "success", saved
    restored = _call(workspace, "get_domain_context", {"domain_id": "domain:missing"})
    persisted = restored["data"]["comparison_cards"][0]["missing_data"]["rows"][0]
    assert persisted["completed"] == 95 and persisted["observed"] is None
    assert persisted["result_identity"] == card["result_identity"]


@pytest.mark.parametrize("domain_id", ["domain:deviations", "domain:missing"])
def test_flow_card_retains_visual_basis_and_uncertainty(domain_id: str) -> None:
    from rob2_kit.interfaces.mcp.contracts import ParticipantFlowProjection

    identity = "sha256:" + "a" * 64
    figure = {
        "kind": "figure",
        "identity": identity,
        "handle": "eh_" + "a" * 16,
        "source_id": "sh_" + "b" * 16,
        "render": {
            "identity": "sha256:" + "c" * 64,
            "source_id": "sh_" + "b" * 16,
            "page": 2,
            "png_sha256": "sha256:" + "d" * 64,
            "recipe": "pymupdf-1.5",
        },
        "delivery_receipt": "sha256:" + "e" * 64,
        "region": [0.1, 0.2, 0.8, 0.9],
        "provenance": "host_visual",
        "uncertainty": "The completion label is legible; endpoint ascertainment is unresolved.",
        "transcription": "Completed follow-up: 90.",
    }
    flow = reconcile_missing_data(
        [
            {
                "arm": "A",
                "population": "randomized participants",
                "unit": "participants",
                "time_point": "final follow-up",
                "randomized": 100,
                "completed": 90,
                "basis": [identity],
            }
        ]
    )
    card = _comparison_cards(domain_id, {}, {identity: figure}, [], [], participant_flow_data=flow)[
        0
    ]
    completed = next(row for row in card["participant_flow"] if row["kind"] == "completed")
    projected = ParticipantFlowProjection.model_validate(completed).model_dump(mode="json")
    assert projected["passages"] == []
    assert projected["figures"] == [
        {
            key: value
            for key, value in figure.items()
            if key
            in {
                "handle",
                "source_id",
                "render",
                "delivery_receipt",
                "region",
                "provenance",
                "uncertainty",
            }
        }
    ]
    assert projected["value"] == 90
    observed = next(row for row in card["participant_flow"] if row["kind"] == "observed")
    assert observed["value"] is None
    assert observed["status"] == "unknown"
    assert flow["rows"][0]["missing"] is None
    assert flow["rows"][0]["imputed"] is None

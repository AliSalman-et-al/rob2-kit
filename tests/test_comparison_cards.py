from __future__ import annotations

import json
from pathlib import Path

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
    card = context["comparison_cards"][0]

    assert card["question_id"] == "sq:deviations:context-deviations"
    assert card["question_wording"]
    assert {option["official_answer"] for option in card["options"]} == {
        "yes",
        "probably_yes",
        "probably_no",
        "no",
        "no_information",
    }
    intended = next(item for item in card["slots"] if item["name"] == "intended_intervention")
    assert intended["status"] == "supported"
    assert "a: assigned to intervention" in intended["value"]
    scientific = {
        item["name"]: item for item in card["slots"] if item["name"] != "intended_intervention"
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
        for group in card["passage_groups"]
        for passage in group["passages"]
    )
    assert all(group["source_role"] for group in card["passage_groups"])
    assert "do not infer causation" in card["prompt"]


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

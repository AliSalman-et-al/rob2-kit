from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from support.rob2 import (
    _assessment_workspace,
    _call,
    _domain_draft,
    _prepared_evidence,
    _proposal_args,
    _read_required_main_reports,
    _result,
    _review,
    _workspace,
)

from rob2_kit.application._state import internal_path
from rob2_kit.application.domains import _comparison_cards, reconcile_missing_data
from rob2_kit.application.evidence import _source_search_previews, list_sources
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
    assert {option["official_answer"] for option in first_question["options"]} == {
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
    assert "do not infer causation" in first_card["prompt"]


def _preview_workspace(tmp_path: Path) -> tuple[Path, dict[str, Any], int]:
    workspace = _workspace(tmp_path)
    trial = workspace / "input" / "trial"
    (trial / "supplement.txt").write_text(
        "The intention-to-treat analysis included all randomized patients.\n",
        encoding="utf-8",
    )
    (trial / "protocol.txt").write_text(
        "The per protocol analysis was a sensitivity analysis.\n",
        encoding="utf-8",
    )
    (trial / "analysis-plan.txt").write_text(
        "The per protocol analysis was prespecified.\n",
        encoding="utf-8",
    )
    (trial / "sources.toml").write_text(
        'roles = { "supplement.txt" = "supplement", "protocol.txt" = "protocol", '
        '"analysis-plan.txt" = "sap" }\n',
        encoding="utf-8",
    )
    evidence = _prepared_evidence(workspace)
    _call(workspace, "save_proposal", _proposal_args(workspace, [_result(evidence)]))
    _review(workspace)
    _read_required_main_reports(workspace)
    revision = int(_call(workspace, "get_domain_context", {})["head"]["state_revision"])
    return workspace, evidence, revision


def test_active_d2_question_gets_bounded_uninspected_source_previews(tmp_path: Path) -> None:
    workspace, evidence, revision = _preview_workspace(tmp_path)
    saved = _call(
        workspace,
        "save_domain_judgment",
        _domain_draft("trial", "domain:randomization", revision, evidence),
    )
    assert saved["outcome"] == "success", saved

    context = _call(workspace, "get_domain_context", {})["data"]
    question = next(
        item for item in context["questions"] if item["id"] == "sq:deviations:appropriate-analysis"
    )
    previews = question["search_previews"]
    assert 1 <= len(previews) <= 3
    assert len({item["source_id"] for item in previews}) == len(previews)
    assert all(item["notice"] == "search preview—inspect before citing" for item in previews)
    assert all(item["source_sha256"].startswith("sha256:") for item in previews)
    assert all(item["projection_hash"].startswith("sha256:") for item in previews)
    assert all(len(item["preview"]) <= 512 for item in previews)


def test_source_preview_disappears_after_corresponding_passages_are_inspected(
    tmp_path: Path,
) -> None:
    workspace, evidence, revision = _preview_workspace(tmp_path)
    saved = _call(
        workspace,
        "save_domain_judgment",
        _domain_draft("trial", "domain:randomization", revision, evidence),
    )
    assert saved["outcome"] == "success", saved
    context = _call(workspace, "get_domain_context", {})["data"]
    question = next(
        item for item in context["questions"] if item["id"] == "sq:deviations:appropriate-analysis"
    )
    for preview in question["search_previews"]:
        response = _call(
            workspace,
            "read_pages",
            {
                "trial_id": "trial",
                "windows": [
                    {
                        "source_id": preview["source_id"],
                        "page": preview["page"],
                        "start_line": preview["start_line"],
                        "end_line": preview["end_line"],
                    }
                ],
            },
        )
        assert response["outcome"] == "success", response
    refreshed = _call(workspace, "get_domain_context", {})["data"]
    refreshed_question = next(
        item
        for item in refreshed["questions"]
        if item["id"] == "sq:deviations:appropriate-analysis"
    )
    assert refreshed_question["search_previews"] == []


def test_source_preview_fails_closed_when_captured_source_version_is_stale(
    tmp_path: Path,
) -> None:
    workspace, _evidence, _revision = _preview_workspace(tmp_path)
    source = next(
        item
        for item in list_sources(workspace, "trial")["sources"]
        if item["label"] == "supplement.txt"
    )
    internal_path(
        workspace.resolve(),
        "sources",
        "trial",
        f"{source['id']}.bin",
    ).write_bytes(b"stale")
    with pytest.raises(ValueError, match="captured Source bytes do not match"):
        _source_search_previews(
            workspace,
            "trial",
            [{"query": "intention-to-treat", "mode": "phrase"}],
        )


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
    assert len(serialized) < 5_000


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

from __future__ import annotations

import json
from pathlib import Path

from support.rob2 import _assessment_workspace, _call

from rob2_kit.application.domains import get_domain_context
from rob2_kit.packs import SCIENTIFIC_PACK
from rob2_kit.packs.d3_authoritative import D3_QUESTION_GUIDANCE, D3_SHARED_GUIDANCE

RECORD = Path(__file__).parents[1] / "docs/evaluation/2026-10-04-d3-authoritative-prototype"


def test_complete_official_text_matches_independent_transcription() -> None:
    captured = json.loads((RECORD / "transcription.json").read_text(encoding="utf-8"))
    assert {key: source.source_excerpt for key, source in D3_QUESTION_GUIDANCE.items()} == captured[
        "questions"
    ]
    assert [source.source_excerpt for source in D3_SHARED_GUIDANCE] == [
        captured["responses"],
        captured["scope"],
        captured["judgment"],
    ]
    # Full text retains nuance omitted by the historic compact official excerpts.
    assert "Only answer ‘No information’" in captured["questions"]["sq:missing:data-available"]
    assert "CONSORT flow diagrams" in captured["questions"]["sq:missing:true-value-dependent"]
    assert (
        "Answer ‘No’ if the analysis accounted"
        in captured["questions"]["sq:missing:likely-dependent"]
    )


def test_prototype_replaces_rules_preserves_identity_and_recovery(tmp_path: Path) -> None:
    workspace, _, _ = _assessment_workspace(tmp_path)
    before = get_domain_context(workspace, domain_id="domain:missing")
    after = get_domain_context(
        workspace, domain_id="domain:missing", guidance_profile="official_d3_prototype"
    )
    for key in before:
        if key not in {
            "questions",
            "official_guidance",
            "response_framework",
            "guidance",
            "traps",
            "comparison_cards",
        }:
            assert after[key] == before[key], key
    assert after["response_framework"] is None
    assert after["guidance_profile"] == "official_d3_prototype"
    for old, new in zip(before["questions"], after["questions"], strict=True):
        for key in (
            "id",
            "wording",
            "options",
            "activation",
            "activation_status",
            "query_suggestions",
        ):
            assert new[key] == old[key]
        assert (
            not {
                "decision_rule",
                "answer_anchors",
                "evidence_needed",
                "considerations",
                "invalid_shortcuts",
                "no_information_rule",
                "bias_construct",
            }
            & new.keys()
        )
        matching = [
            s
            for s in after["official_guidance"]["sections"]
            if s["source_locator"] == new["guidance_locator"]
        ]
        assert len(matching) == 1
        assert matching[0]["question_ids"] == (new["id"],)
        assert matching[0]["excerpt"] == D3_QUESTION_GUIDANCE[new["id"]].source_excerpt
    for old, new in zip(before["comparison_cards"], after["comparison_cards"], strict=True):
        assert new["slots"] == old["slots"]
        assert new["participant_flow"] == old["participant_flow"]
        assert new["passage_groups"] == old["passage_groups"]
        assert not new["propositions"] and not new["paired_examples"]
    assert "firm evidence" in after["official_guidance"]["sections"][0]["excerpt"]
    assert all("A definitive yes or no needs" not in s for s in after["guidance"])


def test_other_domain_contexts_are_unchanged(tmp_path: Path) -> None:
    workspace, _, _ = _assessment_workspace(tmp_path)
    for domain in ("domain:deviations", "domain:selection"):
        assert get_domain_context(workspace, domain_id=domain) == get_domain_context(
            workspace,
            domain_id=domain,
            guidance_profile="official_d3_prototype",
        )
    # Canonical options and algorithms remain in the existing scientific pack.
    assert next(
        q for q in SCIENTIFIC_PACK.questions if q.id == "sq:missing:evidence-unbiased"
    ).allowed_answers


def test_mcp_prototype_continuation_keeps_complete_core(tmp_path: Path) -> None:
    workspace, _, _ = _assessment_workspace(tmp_path)
    response = _call(
        workspace,
        "get_domain_context",
        {
            "domain_id": "domain:missing",
            "guidance_profile": "official_d3_prototype",
            "max_response_bytes": 32768,
        },
    )
    assert response["outcome"] == "success", response
    first = response["data"]
    assert first["official_guidance"]["complete"]
    questions = list(first["questions"])
    page = first["context_page"]
    while page["next_cursor"] is not None:
        continued = _call(workspace, "get_domain_context", {"cursor": page["next_cursor"]})
        assert "official_guidance" not in continued["data"]
        questions.extend(continued["data"].get("questions", []))
        page = continued["data"]["context_page"]
    assert len(questions) == 4
    assert all("decision_rule" not in q for q in questions)
    recovered = _call(
        workspace,
        "get_domain_context",
        {
            "cursor": first["context_page"]["stable_recovery"]["cursor"],
        },
    )
    assert recovered["data"]["official_guidance"] == first["official_guidance"]
    assert recovered["data"]["guidance_profile"] == "official_d3_prototype"

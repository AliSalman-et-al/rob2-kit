"""Official source fidelity and native delivery of corrected scientific qualifications."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from support.rob2 import _assessment_workspace, _call, _domain_draft

from rob2_kit.packs import SCIENTIFIC_PACK

FIXTURE = Path(__file__).parent / "fixtures/official-guidance-audit-2019"


def test_complete_elaborations_match_independently_captured_official_blocks() -> None:
    source = json.loads((FIXTURE / "elaborations.json").read_text(encoding="utf-8"))
    questions = {q.id: q for q in SCIENTIFIC_PACK.questions}
    for captured in source["questions"]:
        guidance = questions[captured["question_id"]].guidance.official
        extracted = re.sub(r"\s+", " ", "".join(b["text"] for b in captured["blocks"])).strip()
        assert captured["normalized_excerpt"] == extracted
        assert guidance.source_excerpt == extracted
        assert guidance.source_sha256 == source["source_sha256"]
        assert guidance.version == source["version"]
        assert guidance.source_locator == captured["source_locator"]


def test_question_options_dependencies_and_wording_are_unchanged() -> None:
    baseline = json.loads((FIXTURE / "question-contract-before.json").read_text(encoding="utf-8"))
    assert [
        {
            "id": q.id,
            "wording": q.wording,
            "options": [answer.value for answer in q.allowed_answers],
            "activation": q.activation.model_dump(mode="json"),
        }
        for q in SCIENTIFIC_PACK.questions
    ] == baseline


def test_native_context_preserves_both_sides_of_official_qualifications(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    cards: dict[str, Any] = {}
    official: dict[str, str] = {}
    for domain in ["randomization", "deviations", "missing", "measurement"]:
        domain_id = "domain:" + domain
        context = _call(
            workspace, "get_domain_context", {"trial_id": "trial", "domain_id": domain_id}
        )
        assert context["outcome"] == "success"
        cards.update({card["id"]: card for card in context["data"]["questions"]})
        official.update(
            {
                qid: section["excerpt"]
                for section in context["data"]["official_guidance"]["sections"]
                for qid in section["question_ids"]
            }
        )
        if domain != "measurement":
            saved = _call(
                workspace,
                "save_domain_judgment",
                _domain_draft("trial", domain_id, revision, evidence),
            )
            assert saved["outcome"] == "success"
            revision = int(saved["head"]["state_revision"])

    sequence = official["sq:randomization:sequence"]
    assert "experienced clinical trials unit" in sequence
    assert "no random element was used" in sequence
    assert "should generally be considered to be random" in sequence

    mitigation = official["sq:missing:evidence-unbiased"]
    assert "range of plausible assumptions" in mitigation
    assert "multiple imputation based only on intervention group" in mitigation
    assert "no_information" not in cards["sq:missing:evidence-unbiased"]["options"]

    influence = official["sq:measurement:influence-possible"]
    assert "all-cause mortality" in influence
    assert "participant-reported outcomes" in influence
    card = cards["sq:measurement:influence-possible"]
    assert card["activation"] == next(
        q.activation.model_dump(mode="json")
        for q in SCIENTIFIC_PACK.questions
        if q.id == card["id"]
    )
    assert all(
        not {"decision_rule", "answer_anchors", "official_guidance"} & c.keys()
        for c in cards.values()
    )

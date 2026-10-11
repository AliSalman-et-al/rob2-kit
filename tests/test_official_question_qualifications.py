"""Official source fidelity and native delivery of corrected scientific qualifications."""

from __future__ import annotations

import json
import re
from pathlib import Path

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

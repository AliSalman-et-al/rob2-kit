"""Offline focus prototype preserves source/result/dependency recovery exactly."""

import hashlib
import json
import runpy
from pathlib import Path

import pytest

_ROOT = (
    Path(__file__).parents[1] / "docs/archive/evaluation/2026-10-03-active-question-architecture"
)
_PROJECT = runpy.run_path(str(_ROOT / "prototype.py"))["project_active_questions"]


@pytest.mark.parametrize("case", ["award-10", "host-exam"])
def test_default_preserving_projection_retains_exact_scientific_context(case: str) -> None:
    full = json.loads((_ROOT / case / "full-context.json").read_text())
    unchanged = json.dumps(full, sort_keys=True)
    assert _PROJECT(full) == full
    focused = _PROJECT(full, enabled=True)
    assert json.dumps(full, sort_keys=True) == unchanged
    for key in (
        "result",
        "evidence",
        "comparison_cards",
        "answers",
        "investigation",
        "reading_recovery",
        "evidence_workspace",
        "coverage",
        "response_framework",
    ):
        assert focused[key] == full[key]
    expected = [
        q
        for q in full["questions"]
        if q["activation_status"] in {"always_active", "active_in_saved_checkpoint"}
    ]
    assert focused["questions"] == expected
    index = focused["question_view"]["index"]
    assert {q["id"] for q in index} == {q["id"] for q in full["questions"]}
    for entry, question in zip(index, full["questions"], strict=True):
        assert all(entry[key] == question[key] for key in entry)
    digest = hashlib.sha256(
        json.dumps(full, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    assert focused["question_view"]["full_guidance_recovery"]["full_context_sha256"] == digest
    assert focused["question_view"]["official_source_index"] == [
        {key: value for key, value in section.items() if key != "excerpt"}
        for section in full["official_guidance"]["sections"]
    ]


def test_d5_does_not_hide_other_always_active_questions() -> None:
    full = json.loads((_ROOT / "host-exam/full-context.json").read_text())
    focused = _PROJECT(full, enabled=True)
    assert focused["questions"] == full["questions"]
    assert len(focused["questions"]) == 3

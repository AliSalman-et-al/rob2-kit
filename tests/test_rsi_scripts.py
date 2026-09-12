from __future__ import annotations

import json
import runpy
from pathlib import Path

_structured_response = runpy.run_path(
    str(Path(__file__).parents[1] / "scripts" / "summarize_rsi_case.py")
)["_structured_response"]


def _receipt() -> dict[str, object]:
    return {
        "head": {"next_action": {"operation": "get_domain_context"}},
        "data": {
            "result": {"kind": "assessable"},
            "questions": [{"id": "q1", "options": [{"id": "opt1"}]}],
            "comparison_cards": [{"question_id": "q1", "passage_groups": []}],
            "evidence": [{"handle": "eh_0123456789abcdef"}],
            "evidence_workspace": {"recovery": {"operation": "read_pages"}},
            "reading_recovery": {"windows": []},
        },
    }


def test_structured_response_prefers_one_complete_structured_envelope() -> None:
    receipt = _receipt()
    item = {
        "result": {
            "structuredContent": receipt,
            "content": [{"type": "text", "text": json.dumps({"questions": []})}],
        }
    }

    assert _structured_response(item) == receipt


def test_structured_response_parses_one_json_text_fallback() -> None:
    receipt = _receipt()
    item = {"result": {"content": [{"type": "text", "text": json.dumps(receipt)}]}}

    assert _structured_response(item) == receipt

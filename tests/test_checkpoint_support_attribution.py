"""Sourced host uncertainty must not become absent attribution at the save seam."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from rob2_kit.application.domains import _host_asserted_sufficiency
from rob2_kit.interfaces.mcp.contracts import normalize


@pytest.mark.parametrize("status", ["supported", "indirect", "unresolved"])
def test_save_attributes_host_relationship_without_changing_sufficiency(status: str) -> None:
    audit = (
        Path(__file__).resolve().parents[1]
        / "tests/fixtures/historical-evaluation/2026-10-03-d31-impact-warrant"
    )
    record = json.loads((audit / "committed-domain.json").read_text())
    record["evidence_sufficiency"]["claims"][0]["status"] = status
    value = {
        "outcome": "success",
        "phase": "assessment",
        "state_revision": 14,
        "checkpoint": record,
        "trial_ready_for_review": False,
        "retry": False,
    }
    before = copy.deepcopy(value)
    saved = normalize("save_domain_judgment", value)["data"]["checkpoint"]
    assert saved["evidence_sufficiency"] == json.loads(
        json.dumps(_host_asserted_sufficiency(record["evidence_sufficiency"], record["answers"]))
    )
    claim = saved["evidence_sufficiency"]["claims"][0]
    assert claim["support_attribution"] == "host_asserted"
    assert claim["status"] == status
    assert (
        claim["unresolved_premises"]
        == record["evidence_sufficiency"]["claims"][0]["unresolved_premises"]
    )
    assert saved["identity"] == record["identity"] and saved["judgment"] == "low"
    assert value == before


@pytest.mark.parametrize("answer", ["yes", "probably_yes", "probably_no", "no", "no_information"])
@pytest.mark.parametrize(
    "unknowns", [[], ["Outcome availability among excluded people is unknown."]]
)
def test_receipt_keeps_declared_unknowns_without_reinterpreting_answer(
    answer: str, unknowns: list[str]
) -> None:
    question_id = "sq:deviations:appropriate-analysis"
    summary = {
        "identity": "sha256:" + "a" * 64,
        "claims": [
            {
                "question_id": question_id,
                "status": "supported",
                "evidence": ["sha256:" + "b" * 64],
                "search_receipts": [],
                "unresolved_premises": [],
            }
        ],
    }
    answers = [{"question_id": question_id, "answer": answer, "unknowns": unknowns}]
    before = copy.deepcopy((summary, answers))
    projected = _host_asserted_sufficiency(summary, answers)
    assert projected is not None
    claim = projected["claims"][0]
    assert claim["declared_unknowns"] == tuple(unknowns)
    assert claim["status"] == "supported" and claim["unresolved_premises"] == []
    assert projected["identity"] == summary["identity"]
    assert (summary, answers) == before


def test_receipt_does_not_transfer_unknowns_between_questions() -> None:
    summary = {
        "identity": "sha256:" + "a" * 64,
        "claims": [{"question_id": "sq:deviations:appropriate-analysis", "status": "indirect"}],
    }
    projected = _host_asserted_sufficiency(
        summary,
        [{"question_id": "sq:deviations:participants-aware", "unknowns": ["Unrelated gap."]}],
    )
    assert projected is not None
    assert projected["claims"][0]["declared_unknowns"] == ()

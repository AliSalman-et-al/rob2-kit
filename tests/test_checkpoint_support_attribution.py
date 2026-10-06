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
        json.dumps(_host_asserted_sufficiency(record["evidence_sufficiency"]))
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

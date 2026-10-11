"""Sourced host uncertainty must not become absent attribution at the save seam."""

from __future__ import annotations

from rob2_kit.application.domains import _host_asserted_sufficiency


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

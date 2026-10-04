"""Offline prototype must preserve all claims and their existing citation bindings."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from scripts.export_factual_audit import export_packet

BUNDLE = (
    Path(__file__).parents[1]
    / "docs/evaluation/2026-10-04-gupta-fork-continuation"
    / "caf5f259a9f5eef456a05a6543fac933aa9bcbc55a99ba4b03430da8b760ab2d.rob2.zip"
)


def test_all_domain_claims_and_only_existing_citations_are_exported_without_mutation():
    before = hashlib.sha256(BUNDLE.read_bytes()).hexdigest()
    with zipfile.ZipFile(BUNDLE) as archive:
        canonical = json.loads(archive.read("canonical.json"))
    saved = canonical["domain_records"]["gupta-2024:domain:measurement"]["answers"]
    packet = export_packet(BUNDLE, "gupta-2024", "domain:measurement")
    assert packet == export_packet(BUNDLE, "gupta-2024", "domain:measurement")
    assert [claim["question_id"] for claim in packet["claims"]] == [
        answer["question_id"] for answer in saved
    ]
    for claim, answer in zip(packet["claims"], saved, strict=True):
        assert claim["justification"] == answer["justification"]
        assert claim["unknowns"] == answer["unknowns"]
        assert claim["counterevidence"] == answer["counterevidence"]
        assert claim["citations"] == [
            {"evidence_identity": basis["evidence"], "asserted_role": basis["kind"]}
            for basis in answer["bases"]
        ]
    assert {span["evidence_identity"] for span in packet["cited_spans"]} == {
        basis["evidence"] for answer in saved for basis in answer["bases"]
    }
    assert all(
        len(span["numbered_text"].splitlines()) == span["end_line"] - span["start_line"] + 1
        for span in packet["cited_spans"]
    )
    assert hashlib.sha256(BUNDLE.read_bytes()).hexdigest() == before


def test_invalid_bundle_and_missing_domain_cannot_produce_an_audit(tmp_path):
    invalid = tmp_path / "invalid.zip"
    invalid.write_bytes(b"unverified content")
    with pytest.raises(ValueError, match="verification failed"):
        export_packet(invalid, "gupta-2024", "domain:measurement")
    with pytest.raises(ValueError, match="No saved domain"):
        export_packet(BUNDLE, "gupta-2024", "domain:absent")

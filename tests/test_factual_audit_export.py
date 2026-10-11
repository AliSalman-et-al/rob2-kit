"""Offline prototype must preserve all claims and their existing citation bindings."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from support.rob2 import _assessed_artifact, _workspace

from scripts.export_factual_audit import export_packet


@pytest.fixture
def bundle(tmp_path: Path) -> tuple[Path, str]:
    artifact = _assessed_artifact(_workspace(tmp_path))
    with zipfile.ZipFile(artifact) as archive:
        trial_id = json.loads(archive.read("canonical.json"))["batch"]["trials"][0]["id"]
    return artifact, trial_id


def test_all_domain_claims_and_only_existing_citations_are_exported_without_mutation(
    bundle: tuple[Path, str],
) -> None:
    BUNDLE, trial_id = bundle
    before = hashlib.sha256(BUNDLE.read_bytes()).hexdigest()
    with zipfile.ZipFile(BUNDLE) as archive:
        canonical = json.loads(archive.read("canonical.json"))
    saved = canonical["domain_records"][f"{trial_id}:domain:measurement"]["answers"]
    packet = export_packet(BUNDLE, trial_id, "domain:measurement")
    assert packet == export_packet(BUNDLE, trial_id, "domain:measurement")
    assert len(packet["questions"]) == len(saved)
    assert all(claim["question_id"] and claim["official_guidance"] for claim in packet["questions"])
    for claim, answer in zip(packet["questions"], saved, strict=True):
        assert claim["assessment"] == answer
    assert {span["evidence_identity"] for span in packet["cited_spans"]} == {
        basis["evidence"] for answer in saved for basis in answer["bases"]
    }
    assert all(
        len(span["numbered_text"].splitlines()) == span["end_line"] - span["start_line"] + 1
        for span in packet["cited_spans"]
    )
    assert hashlib.sha256(BUNDLE.read_bytes()).hexdigest() == before


def test_invalid_bundle_and_missing_domain_cannot_produce_an_audit(
    tmp_path: Path, bundle: tuple[Path, str]
) -> None:
    BUNDLE, trial_id = bundle
    invalid = tmp_path / "invalid.zip"
    invalid.write_bytes(b"unverified content")
    with pytest.raises(ValueError, match="verification failed"):
        export_packet(invalid, trial_id, "domain:measurement")
    with pytest.raises(ValueError, match="No saved domain"):
        export_packet(BUNDLE, trial_id, "domain:absent")

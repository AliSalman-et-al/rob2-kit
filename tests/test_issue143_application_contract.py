"""Application persistence and question-scoped navigation attack checks."""

from __future__ import annotations

from pathlib import Path

from rob2_kit.application.contracts import SearchEvidenceRequest, SubmitEvidenceReviewRequest
from rob2_kit.application.evidence_navigation import V3EvidenceNavigationStore
from rob2_kit.domain.canonical import canonical_hash

ZERO = "sha256:" + "0" * 64
ONE = "sha256:" + "1" * 64


def test_navigation_store_keys_each_exact_question_revision(tmp_path: Path) -> None:
    store = V3EvidenceNavigationStore(tmp_path)
    common = dict(
        run_id="run:test",
        result_id="result:test",
        domain_id="domain:test",
        obligation_hash=ZERO,
        inventory_snapshot_hash=ONE,
    )
    first = store._path(question_id="sq:test:first", **common)
    second = store._path(question_id="sq:test:second", **common)
    revised = store._path(
        question_id="sq:test:first",
        **(common | {"obligation_hash": canonical_hash({"revision": 2})}),
    )
    assert len({first, second, revised}) == 3
    assert all(path.parent == store.root for path in (first, second, revised))


def test_navigation_store_hashes_hostile_identifiers_instead_of_using_paths(tmp_path: Path) -> None:
    store = V3EvidenceNavigationStore(tmp_path)
    path = store._path(
        run_id="run:..",
        result_id="result:..",
        domain_id="domain:..",
        question_id="sq:../../outside",
        obligation_hash=ZERO,
        inventory_snapshot_hash=ONE,
    )
    assert path.parent == store.root
    assert ".." not in path.name


def test_search_contract_requires_question_session_and_issued_stage_identity() -> None:
    required = SearchEvidenceRequest.model_json_schema()["required"]
    assert {
        "question_id",
        "session_content_hash",
        "proposition_id",
        "pass_id",
        "stage_id",
        "intent_id",
        "attempt_id",
    } <= set(required)


def test_review_contract_is_question_scoped_and_uses_v3_triage() -> None:
    schema = SubmitEvidenceReviewRequest.model_json_schema()
    assert schema["properties"]["contract_version"]["const"] == "3.0.0"
    assert {"question_id", "session_content_hash", "expected_navigation_state_hash"} <= set(
        schema["required"]
    )
    assert schema["properties"]["triage_revisions"]["items"]["$ref"].endswith(
        "/V3CandidateTriageRevision"
    )

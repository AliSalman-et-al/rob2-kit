from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import httpx
import pytest

from rob2_kit.application import intake
from rob2_kit.application._state import _state
from rob2_kit.application.contracts import WorkflowConflict
from rob2_kit.application.intake import prepare_batch
from rob2_kit.workflow_models import ReviewAcknowledgment, TrialDeclaration


def _prepare(tmp_path: Path, *, manifest: str | None = None) -> Path:
    trial = tmp_path / "input" / "trial"
    trial.mkdir(parents=True)
    (trial / "main.txt").write_text(
        "The requested outcome was not reported; only an alternate endpoint was measured. "
        "death ascertainment; end of follow-up; assigned to intervention; assigned to control; "
        "randomized population; risk ratio; The requested outcome was "
        "measured in the analyzed population.; risk; 1; events; 2.\n",
        encoding="utf-8",
    )
    if manifest is not None:
        (trial / "sources.toml").write_text(manifest, encoding="utf-8")
    prepare_batch(
        tmp_path,
        [TrialDeclaration(id="trial", label="trial", requested_outcome="outcome")],
        expected_revision=0,
    )
    return tmp_path


def test_state_restart_rejects_mutable_projection_tampering(tmp_path: Path) -> None:
    workspace = _prepare(tmp_path)
    database = workspace / ".rob2-kit" / "canonical.sqlite3"
    with sqlite3.connect(database) as connection:
        row = connection.execute("SELECT payload FROM records WHERE name='state'").fetchone()
        assert row is not None
        payload = json.loads(bytes(row[0]))
        payload["phase"] = "finalized"
        connection.execute(
            "UPDATE records SET payload=? WHERE name='state'",
            (json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),),
        )
    with pytest.raises(ValueError, match="workflow state projection is corrupt"):
        _state(workspace)


def test_state_restart_rejects_workflow_head_payload_tampering(tmp_path: Path) -> None:
    workspace = _prepare(tmp_path)
    database = workspace / ".rob2-kit" / "canonical.sqlite3"
    with sqlite3.connect(database) as connection:
        row = connection.execute("SELECT payload FROM workflow_head WHERE singleton=1").fetchone()
        assert row is not None
        payload = json.loads(bytes(row[0]))
        payload["phase"] = "finalized"
        changed = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        connection.execute("UPDATE workflow_head SET payload=? WHERE singleton=1", (changed,))
    with pytest.raises(ValueError, match="canonical record integrity check failed"):
        _state(workspace)


def test_valid_nct_is_not_fabricated_as_a_match(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(*_args: Any, **_kwargs: Any) -> httpx.Response:
        return httpx.Response(503, request=httpx.Request("GET", "https://example.test"))

    monkeypatch.setattr(intake.httpx, "get", unavailable)
    capture = intake._registry_record("NCT00000001")
    assert capture.outcome["kind"] == "unavailable"
    assert capture.content is None


def test_manifest_matched_claim_cannot_bypass_provider_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(*_args: Any, **_kwargs: Any) -> httpx.Response:
        return httpx.Response(503, request=httpx.Request("GET", "https://example.test"))

    monkeypatch.setattr(intake.httpx, "get", unavailable)
    capture = intake._registry_record("NCT00000001")
    assert capture.outcome["kind"] == "unavailable"
    assert capture.content is None


def test_registry_fetch_accepts_only_exact_provider_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "protocolSection": {
            "identificationModule": {
                "nctId": "NCT00000001",
                "officialTitle": "Example randomized trial",
            }
        }
    }

    def response(*_args: Any, **_kwargs: Any) -> httpx.Response:
        return httpx.Response(
            200,
            json=payload,
            request=httpx.Request("GET", "https://clinicaltrials.gov/api/v2/studies/NCT00000001"),
        )

    monkeypatch.setattr(intake.httpx, "get", response)
    capture = intake._registry_record("NCT00000001")
    assert capture.outcome["kind"] == "matched"
    assert capture.outcome["registry_id"] == "NCT00000001"
    assert capture.outcome["title"] == "Example randomized trial"
    assert json.loads(capture.content or b"") == payload


def test_manifest_rejects_competing_registry_identifier_spellings(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="ambiguous registry identifier"):
        _prepare(tmp_path, manifest='nct = "NCT00000001"\nnct_id = "NCT00000001"\n')


def test_manifest_rejects_unknown_source_role(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="main_article, registry"):
        _prepare(tmp_path, manifest='[roles]\n"main.txt" = "primary_publication"\n')


def test_review_acknowledgment_requires_nonnegative_revision() -> None:
    base = {
        "review_identity": "sha256:" + "0" * 64,
        "purpose": "proposal",
        "caller": "cli",
        "method": "cli",
        "observed_at": "2026-08-25T00:00:00+00:00",
        "workflow_basis": 3,
    }
    accepted = ReviewAcknowledgment.model_validate(base)
    assert accepted.workflow_basis == 3
    with pytest.raises(ValueError):
        ReviewAcknowledgment.model_validate({**base, "workflow_basis": "3"})


def test_proposal_approval_does_not_clobber_a_concurrent_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from support.rob2 import _call, _prepared_evidence, _proposal_args, _result

    workspace = tmp_path
    trial = workspace / "input" / "trial"
    trial.mkdir(parents=True)
    (trial / "main.txt").write_text(
        "The requested outcome was not reported; only an alternate endpoint was measured. "
        "death ascertainment; end of follow-up; assigned to intervention; assigned to control; "
        "randomized population; risk ratio; The requested outcome was "
        "measured in the analyzed population.; risk; 1; events; 2.\n",
        encoding="utf-8",
    )
    evidence = _prepared_evidence(workspace)
    saved = _call(workspace, "save_proposal", _proposal_args(workspace, [_result(evidence)]))
    assert saved["outcome"] == "review_required"
    review_identity = _state(workspace)["review"]["identity"]
    original = intake._commit_records

    def race(
        root: Path,
        state: dict[str, Any],
        expected: int | None,
        records: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        assert expected == state["revision"]
        original(root, {**state, "concurrent_marker": True}, expected, {})
        return original(root, state, expected, records)

    monkeypatch.setattr(intake, "_commit_records", race)
    with pytest.raises(WorkflowConflict):
        intake.approve_review(workspace, review_identity)
    assert _state(workspace).get("concurrent_marker") is True

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import httpx
import pytest

from rob2_kit.application import intake
from rob2_kit.application._state import _state
from rob2_kit.application.intake import prepare_batch
from rob2_kit.workflow_models import TrialDeclaration


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


def test_manifest_rejects_competing_registry_identifier_spellings(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="ambiguous registry identifier"):
        _prepare(tmp_path, manifest='nct = "NCT00000001"\nnct_id = "NCT00000001"\n')


def test_manifest_rejects_unknown_source_role(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="main_article, registry"):
        _prepare(tmp_path, manifest='[roles]\n"main.txt" = "primary_publication"\n')

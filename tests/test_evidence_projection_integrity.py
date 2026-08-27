from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

import pymupdf
import pytest
from fastmcp import Client

from rob2_kit.application._state import _identity, _state, canonical_json_bytes
from rob2_kit.application.evidence import (
    _evidence_catalog,
    _search_receipt,
    list_sources,
    read_pages,
    render_page,
    search_sources,
    select_text_evidence,
    select_visual_evidence,
)
from rob2_kit.application.intake import prepare_batch
from rob2_kit.application.proposal import save_proposal
from rob2_kit.interfaces.mcp.server import mcp
from rob2_kit.workflow_models import ProposalDraft, TrialDeclaration


def _workspace(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    trial = tmp_path / "input" / "trial"
    trial.mkdir(parents=True)
    (trial / "main.txt").write_text(
        "The reported endpoint was overall survival at final follow-up.\n",
        encoding="utf-8",
    )
    prepare_batch(
        tmp_path,
        [TrialDeclaration(id="trial", label="trial", requested_outcome="overall survival")],
        expected_revision=0,
    )
    source = json.loads(json.dumps(list_sources(tmp_path, "trial")["sources"][0]))
    return tmp_path, source


def _selected(workspace: Path, source: dict[str, object]) -> dict[str, object]:
    return select_text_evidence(
        workspace,
        "trial",
        str(source["id"]),
        1,
        "The reported endpoint was overall survival at final follow-up.",
    )["evidence"]


def _replace_evidence(workspace: Path, item: dict[str, object]) -> None:
    payload = canonical_json_bytes(item)
    with sqlite3.connect(workspace / ".rob2-kit" / "derivative.sqlite3") as connection:
        connection.execute("DELETE FROM evidence_handles")
        connection.execute("INSERT INTO evidence_handles VALUES (?,?)", (item["identity"], payload))


def _replace_search_receipt(workspace: Path, item: dict[str, object]) -> None:
    payload = canonical_json_bytes(item)
    with sqlite3.connect(workspace / ".rob2-kit" / "derivative.sqlite3") as connection:
        connection.execute("DELETE FROM search_receipts")
        connection.execute("INSERT INTO search_receipts VALUES (?,?)", (item["identity"], payload))


def test_unmodified_selected_evidence_stays_promotable(tmp_path: Path) -> None:
    workspace, source = _workspace(tmp_path)
    evidence = _selected(workspace, source)

    catalog = _evidence_catalog(workspace)

    assert catalog[str(evidence["identity"])] == evidence


def test_rehashed_narrative_handle_cannot_promote_fabricated_quote(tmp_path: Path) -> None:
    workspace, source = _workspace(tmp_path)
    evidence = _selected(workspace, source)
    tampered = {**evidence, "quote": "fabricated endpoint"}
    tampered["identity"] = _identity(
        {key: value for key, value in tampered.items() if key not in {"identity", "handle"}}
    )
    tampered["handle"] = "eh_" + str(tampered["identity"]).removeprefix("sha256:")[:16]
    _replace_evidence(workspace, tampered)

    with pytest.raises(ValueError, match="outside the captured page projection"):
        _evidence_catalog(workspace)


def test_tampered_evidence_returns_typed_status_condition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, source = _workspace(tmp_path)
    evidence = _selected(workspace, source)
    tampered = {**evidence, "quote": "fabricated endpoint"}
    tampered["identity"] = _identity(
        {key: value for key, value in tampered.items() if key not in {"identity", "handle"}}
    )
    tampered["handle"] = "eh_" + str(tampered["identity"]).removeprefix("sha256:")[:16]
    _replace_evidence(workspace, tampered)
    monkeypatch.setenv("ROB2_WORKSPACE", os.fspath(workspace))

    async def call_status() -> dict[str, Any]:
        async with Client(mcp) as client:
            result = await client.call_tool("get_status", {}, raise_on_error=False)
            return dict(result.structured_content or {})

    receipt = asyncio.run(call_status())
    assert receipt["outcome"] == "condition"
    assert receipt["condition"]["code"] == "invalid_request"


def test_rehashed_narrative_handle_is_rejected_before_proposal_commit(tmp_path: Path) -> None:
    workspace, source = _workspace(tmp_path)
    evidence = _selected(workspace, source)
    tampered = {**evidence, "quote": "fabricated endpoint"}
    tampered["identity"] = _identity(
        {key: value for key, value in tampered.items() if key not in {"identity", "handle"}}
    )
    tampered["handle"] = "eh_" + str(tampered["identity"]).removeprefix("sha256:")[:16]
    _replace_evidence(workspace, tampered)
    proposal = ProposalDraft.model_validate(
        {
            "expected_revision": _state(workspace)["revision"],
            "results": [
                {
                    "kind": "unavailable",
                    "trial_id": "trial",
                    "relation": "unavailable",
                    "missing_facts": [
                        {
                            "fact": "the endpoint result",
                            "basis": {
                                "kind": "missing_reporting",
                                "evidence": tampered["handle"],
                            },
                        }
                    ],
                }
            ],
        }
    )

    with pytest.raises(ValueError, match="outside the captured page projection"):
        save_proposal(workspace, proposal)
    assert _state(workspace).get("proposal") is None


def test_source_index_and_cached_pages_cannot_replace_canonical_source(tmp_path: Path) -> None:
    workspace, source = _workspace(tmp_path)
    derivative = workspace / ".rob2-kit" / "derivative.sqlite3"
    altered_source = {**source, "projection_hash": "sha256:" + "f" * 64}
    with sqlite3.connect(derivative) as connection:
        connection.execute(
            "UPDATE source_index SET payload=? WHERE source_id=?",
            (canonical_json_bytes(altered_source), source["id"]),
        )
        connection.execute(
            "UPDATE pages SET text=? WHERE source_id=? AND page=1",
            ("fabricated page text", source["id"]),
        )

    with pytest.raises(ValueError, match="source index payload"):
        read_pages(workspace, "trial", str(source["id"]), [1])


def test_live_search_rejects_tampered_fts_projection(tmp_path: Path) -> None:
    workspace, source = _workspace(tmp_path)
    with sqlite3.connect(workspace / ".rob2-kit" / "derivative.sqlite3") as connection:
        connection.execute(
            "UPDATE pages_fts SET raw_text=? WHERE source_id=? AND page=1",
            ("fabricated search result", source["id"]),
        )

    with pytest.raises(ValueError, match="text search projection is corrupt"):
        search_sources(workspace, "trial", "fabricated")


def test_rehashed_search_receipt_cannot_omit_results(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "trial"
    trial.mkdir(parents=True)
    (trial / "first.txt").write_text("overall survival result", encoding="utf-8")
    (trial / "second.txt").write_text("overall survival follow-up", encoding="utf-8")
    prepare_batch(
        tmp_path,
        [TrialDeclaration(id="trial", label="trial", requested_outcome="overall survival")],
        expected_revision=0,
    )
    receipt = search_sources(tmp_path, "trial", "overall", limit=20)["search_receipt"]
    assert len(receipt["hits"]) == 2
    tampered = {**receipt, "hits": receipt["hits"][:1]}
    tampered["identity"] = _identity(
        {key: value for key, value in tampered.items() if key not in {"identity", "handle"}}
    )
    tampered["handle"] = "sr_" + str(tampered["identity"]).removeprefix("sha256:")[:16]
    _replace_search_receipt(tmp_path, tampered)

    with pytest.raises(ValueError, match="results do not match"):
        _search_receipt(tmp_path, str(tampered["handle"]))


def test_rehashed_no_hit_search_receipt_cannot_gain_a_result(tmp_path: Path) -> None:
    workspace, source = _workspace(tmp_path)
    receipt = search_sources(workspace, "trial", "absent term")["search_receipt"]
    tampered = {
        **receipt,
        "hits": [{"source_id": source["id"], "page": 1}],
        "total_matches": 1,
        "condition": None,
    }
    tampered["identity"] = _identity(
        {key: value for key, value in tampered.items() if key not in {"identity", "handle"}}
    )
    tampered["handle"] = "sr_" + str(tampered["identity"]).removeprefix("sha256:")[:16]
    _replace_search_receipt(workspace, tampered)

    with pytest.raises(ValueError, match="results do not match"):
        _search_receipt(workspace, str(tampered["handle"]))


def test_rehashed_visual_handle_cannot_replace_cached_render_projection(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "trial"
    trial.mkdir(parents=True)
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Overall survival")
    document.save(trial / "main.pdf")
    document.close()
    prepare_batch(
        tmp_path,
        [TrialDeclaration(id="trial", label="trial", requested_outcome="overall survival")],
        expected_revision=0,
    )
    source = list_sources(tmp_path, "trial")["sources"][0]
    rendered = render_page(tmp_path, "trial", str(source["id"]), 1)["render"]
    evidence = select_visual_evidence(
        tmp_path,
        "trial",
        str(source["id"]),
        str(rendered["identity"]),
        "Overall survival",
        [0.1, 0.1, 0.9, 0.9],
    )["evidence"]
    tampered = {**evidence, "render": {**evidence["render"], "png_sha256": "sha256:" + "f" * 64}}
    tampered["identity"] = _identity(
        {key: value for key, value in tampered.items() if key not in {"identity", "handle"}}
    )
    tampered["handle"] = "eh_" + str(tampered["identity"]).removeprefix("sha256:")[:16]
    _replace_evidence(tmp_path, tampered)

    with pytest.raises(ValueError, match="cached render projection"):
        _evidence_catalog(tmp_path)


def test_coordinated_cached_render_and_visual_evidence_tampering_fails(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "trial"
    trial.mkdir(parents=True)
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Overall survival")
    document.save(trial / "main.pdf")
    document.close()
    prepare_batch(
        tmp_path,
        [TrialDeclaration(id="trial", label="trial", requested_outcome="overall survival")],
        expected_revision=0,
    )
    source = list_sources(tmp_path, "trial")["sources"][0]
    rendered = render_page(tmp_path, "trial", str(source["id"]), 1)["render"]
    evidence = select_visual_evidence(
        tmp_path,
        "trial",
        str(source["id"]),
        str(rendered["identity"]),
        "Overall survival",
        [0.1, 0.1, 0.9, 0.9],
    )["evidence"]
    fabricated_png = b"fabricated-png"
    fabricated_hash = "sha256:" + hashlib.sha256(fabricated_png).hexdigest()
    tampered_render = {**rendered, "png_sha256": fabricated_hash}
    with sqlite3.connect(tmp_path / ".rob2-kit" / "derivative.sqlite3") as connection:
        connection.execute(
            "UPDATE renders SET payload=?,png=? WHERE identity=?",
            (canonical_json_bytes(tampered_render), fabricated_png, rendered["identity"]),
        )
    tampered = {**evidence, "render": tampered_render, "transcription": "Fabricated result"}
    tampered["identity"] = _identity(
        {key: value for key, value in tampered.items() if key not in {"identity", "handle"}}
    )
    tampered["handle"] = "eh_" + str(tampered["identity"]).removeprefix("sha256:")[:16]
    _replace_evidence(tmp_path, tampered)

    with pytest.raises(ValueError, match="captured PDF render"):
        _evidence_catalog(tmp_path)

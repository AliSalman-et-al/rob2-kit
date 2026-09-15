from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import runpy
from pathlib import Path

from fastmcp import Client
from support.rob2 import (
    _call,
    _prepared_evidence,
    _proposal_args,
    _result,
    _review,
    _workspace,
)

from rob2_kit.application._state import _identity, _state
from rob2_kit.interfaces.mcp.server import mcp

_rsi_helpers = runpy.run_path(
    str(Path(__file__).parents[1] / "scripts" / "prepare_rsi_workspace.py")
)
prepare_workspace = _rsi_helpers["prepare_workspace"]
approved_scope_record = _rsi_helpers["approved_scope_record"]

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


def test_prepared_assessment_tools_see_only_allowlisted_sources_and_scope(
    tmp_path: Path, monkeypatch
) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    source = b"captured source bytes, including its exact spacing.\n"
    registry = b'{"protocolSection":{"identificationModule":{"nctId":"NCT00000001"}}}\n'
    (case_dir / "article.txt").write_bytes(source)
    (case_dir / "registry-capture.json").write_bytes(registry)
    (case_dir / "prior-answer.json").write_text(
        '{"domain_1":"High","private_marker":"ANSWER_LABEL_MUST_NOT_LEAK"}',
        encoding="utf-8",
    )
    case = {
        "schema": "rob2-kit.rsi-case.v1",
        "trial": "Trial-A",
        "requested_outcome": "Progression-Free Survival",
        "approved_scope": "progression-free survival at the reported timepoint",
        "sources": [{"path": "article.txt", "name": "main-article.txt", "role": "main_article"}],
        "registry_capture": {
            "path": "registry-capture.json",
            "captured_at": "2026-08-01T12:30:00Z",
            "sha256": hashlib.sha256(registry).hexdigest(),
            "provenance": "captured from the baseline ClinicalTrials.gov response",
        },
    }
    case_path = case_dir / "case.json"
    case_path.write_text(json.dumps(case), encoding="utf-8")
    workspace = tmp_path / "run" / "workspace"

    manifest = prepare_workspace(case_path, workspace)
    input_trial = workspace / "input" / "Trial-A"
    assert (input_trial / "main-article.txt").read_bytes() == source
    assert (input_trial / "registry.json").read_bytes() == registry
    assert not (input_trial / "prior-answer.json").exists()
    assert manifest["registry_capture"]["captured_at"] == "2026-08-01T12:30:00Z"
    assert manifest["registry_capture"]["sha256"] == hashlib.sha256(registry).hexdigest()
    assert (
        manifest["registry_capture"]["replayed_at"] != manifest["registry_capture"]["captured_at"]
    )

    async def inspect_assessment_tools() -> list[str]:
        monkeypatch.setenv("ROB2_WORKSPACE", str(workspace))
        async with Client(mcp) as client:
            await client.call_tool(
                "prepare_batch",
                {
                    "requested_outcome": case["requested_outcome"],
                    "expected_revision": 0,
                    "trial_labels": ["Trial-A"],
                },
            )
            sources = await client.call_tool("list_sources", {})
            search = await client.call_tool(
                "search_sources",
                {
                    "trial_id": "trial-a",
                    "query": "unlisted-answer-file-content-marker",
                    "mode": "phrase",
                },
            )
            assert search.structured_content["data"]["total_matches"] == 0
            status = await client.call_tool("get_status", {})
            return [
                json.dumps(sources.structured_content, sort_keys=True),
                json.dumps(search.structured_content, sort_keys=True),
                json.dumps(status.structured_content, sort_keys=True),
            ]

    outputs = asyncio.run(inspect_assessment_tools())
    tool_text = "\n".join(outputs)
    assert "main-article.txt" in tool_text
    assert "registry.json" in tool_text
    assert "ANSWER_LABEL_MUST_NOT_LEAK" not in tool_text
    assert "prior-answer.json" not in tool_text
    assert "High" not in tool_text


def test_prepare_workspace_allows_sources_elsewhere_under_eval_root(tmp_path: Path) -> None:
    eval_root = tmp_path / "eval"
    case_dir = eval_root / "runs" / "case-a"
    source_dir = eval_root / "reference" / "sources"
    case_dir.mkdir(parents=True)
    source_dir.mkdir(parents=True)
    source = b"shared evaluation corpus bytes\n"
    (source_dir / "article.txt").write_bytes(source)
    case = {
        "schema": "rob2-kit.rsi-case.v1",
        "trial": "Trial-A",
        "requested_outcome": "Progression-Free Survival",
        "sources": [
            {
                "path": "../../reference/sources/article.txt",
                "name": "main-article.txt",
                "role": "main_article",
            }
        ],
    }
    case_path = case_dir / "case.json"
    case_path.write_text(json.dumps(case), encoding="utf-8")

    manifest = prepare_workspace(case_path, tmp_path / "run" / "workspace")

    assert manifest["sources"][0]["name"] == "main-article.txt"
    assert (
        tmp_path / "run" / "workspace" / "input" / "Trial-A" / "main-article.txt"
    ).read_bytes() == source


def test_reference_catalog_separates_completed_and_labeled_denominators() -> None:
    catalog = Path(__file__).parents[1] / "eval" / "reference" / "catalog"
    with (catalog / "outcomes.csv").open(encoding="utf-8", newline="") as stream:
        rows = {row["outcome"]: row for row in csv.DictReader(stream)}

    assert {
        outcome: (int(row["baseline_completed"]), int(row["reference_labeled"]))
        for outcome, row in rows.items()
    } == {
        "Progression-Free Survival": (8, 10),
        "Adverse Events": (10, 8),
        "Overall Survival": (9, 10),
    }
    with (catalog / "trials.csv").open(encoding="utf-8", newline="") as stream:
        trials = list(csv.DictReader(stream))
    assert len(trials) == 10
    assert all(
        row["source_directory"] == f"eval/reference/sources/{row['trial_slug']}" for row in trials
    )


def test_post_approval_record_fingerprints_actual_result_scope_outside_workspace(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    workspace = run_dir / "workspace"
    workspace.mkdir(parents=True)
    _workspace(workspace)
    evidence = _prepared_evidence(workspace)
    result = _result(evidence)
    saved = _call(workspace, "save_proposal", _proposal_args(workspace, [result]))
    assert saved["outcome"] == "review_required"
    assert approved_scope_record(workspace, "frozen requested scope") is None
    _review(workspace)

    state = _state(workspace)
    approved_result = state["proposal"]["payload"]["results"][0]
    record = approved_scope_record(workspace, "frozen requested scope")
    assert record is not None
    assert record["case_requested_scope"] == "frozen requested scope"
    assert record["proposal_identity"] == state["proposal"]["identity"]
    assert record["approval_identity"] == state["proposal_acknowledgment"]["identity"]
    assert record["results"] == [
        {
            "identity": _identity(approved_result),
            "trial_id": approved_result["trial_id"],
            "kind": approved_result["kind"],
            "target_scope_identity": _identity(approved_result["target"]),
            "reported_scope_identity": _identity(approved_result["reported"]),
        }
    ]
    assert "definition" not in json.dumps(record)

    record_path = run_dir / "approved-scope.json"
    record_path.write_text(json.dumps(record), encoding="utf-8")
    assert not (workspace / record_path.name).exists()
    visible = json.dumps(_call(workspace, "get_status", {}), sort_keys=True)
    assert record["proposal_identity"] not in visible
    assert record["results"][0]["identity"] not in visible
    assert record["approval_identity"] not in visible
    assert record["results"][0]["target_scope_identity"] not in visible
    assert record["results"][0]["reported_scope_identity"] not in visible

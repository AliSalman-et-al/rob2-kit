from __future__ import annotations

import asyncio
import hashlib
import json
import runpy
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from rob2_kit.evaluation.adjudication import SCHEMA, write_sidecar
from rob2_kit.interfaces.mcp.server import mcp

SCRIPTS = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _runner() -> dict[str, Any]:
    return runpy.run_path(str(SCRIPTS / "run_rsi_case.py"))


def _collector() -> dict[str, Any]:
    return runpy.run_path(str(SCRIPTS / "collect_rsi_benchmark.py"))


def _tools_list_response() -> dict[str, Any]:
    tools = asyncio.run(mcp.list_tools())
    return {
        "tools": [
            {
                "name": tool.name,
                "title": tool.title,
                "description": tool.description,
                "inputSchema": json.loads(json.dumps(tool.parameters)),
                "outputSchema": json.loads(json.dumps(tool.output_schema)),
                "annotations": {
                    "readOnlyHint": bool(tool.annotations and tool.annotations.read_only_hint),
                    "destructiveHint": bool(
                        tool.annotations and tool.annotations.destructive_hint
                    ),
                    "idempotentHint": bool(tool.annotations and tool.annotations.idempotent_hint),
                    "openWorldHint": bool(tool.annotations and tool.annotations.open_world_hint),
                },
            }
            for tool in tools
        ]
    }


def test_runtime_evidence_requires_a_completed_rob2_response(tmp_path: Path) -> None:
    contract = runpy.run_path(str(SCRIPTS / "benchmark_contract.py"))
    has_evidence = contract["trace_has_rob2_runtime_evidence"]
    trace = tmp_path / "phase.jsonl"
    base = {
        "item": {
            "type": "mcp_tool_call",
            "server": "rob2",
            "tool": "get_status",
            "status": "completed",
            "error": None,
            "result": {"isError": True, "content": [{"type": "text", "text": "invalid request"}]},
        }
    }

    for event in (
        None,
        [],
        {**base, "type": "item.started"},
        {
            "type": "item.completed",
            "item": {**base["item"], "status": "in_progress", "result": None},
        },
        {
            "type": "item.completed",
            "item": {**base["item"], "error": "transport failed", "result": None},
        },
    ):
        trace.write_text(json.dumps(event) + "\n", encoding="utf-8")
        assert has_evidence(trace) is False

    trace.write_text(json.dumps({**base, "type": "item.completed"}) + "\n", encoding="utf-8")
    assert has_evidence(trace) is True


def test_execution_record_binds_campaign_and_rejects_duplicate_phase(tmp_path: Path) -> None:
    runner = _runner()
    run_dir = tmp_path / "campaign" / "outcome" / "Trial-A"
    prompt = tmp_path / "prompt.txt"
    case = tmp_path / "case.json"
    prompt.write_text("prompt", encoding="utf-8")
    case.write_text("{}", encoding="utf-8")
    inputs = {"trial": "Trial-A", "requested_outcome": "Overall Survival"}
    identity = runner["_execution_identity"](run_dir, inputs)
    assert identity == {
        "campaign_id": "campaign",
        "case_id": "campaign-overallsurvival-triala",
        "trial_id": "Trial-A",
        "outcome": "Overall Survival",
    }

    load = runner["_load_or_create_execution"]
    record = load(
        run_dir,
        identity,
        run_inputs=inputs,
        case_file=case,
        prompt_file=prompt,
        phase=1,
        session=None,
    )
    assert record["state"] == "queued"
    assert record["phases"][0]["phase"] == 1
    assert record["phases"][0]["state"] == "queued"
    assert json.loads((run_dir / "execution.json").read_text(encoding="utf-8"))["state"] == "queued"
    runner["_mark_execution_running"](run_dir, record, 1)
    assert record["state"] == "running"
    assert record["attempts"][0]["state"] == "running"

    (run_dir / "phase-1.jsonl").write_text(
        json.dumps({"thread_id": "session-1"}) + "\n", encoding="utf-8"
    )
    record["state"] = "resumable"
    runner["_atomic_json"](run_dir / "execution.json", record)
    runner["_release_execution_lock"](run_dir)
    resumed = load(
        run_dir,
        identity,
        run_inputs=inputs,
        case_file=case,
        prompt_file=prompt,
        phase=2,
        session="session-1",
    )
    assert resumed["phases"][-1]["phase"] == 2
    assert resumed["continuation"]["lineage"][-1] == {"phase": 2, "session": "session-1"}
    runner["_release_execution_lock"](run_dir)

    with pytest.raises(ValueError, match="already recorded"):
        load(
            run_dir,
            identity,
            run_inputs=inputs,
            case_file=case,
            prompt_file=prompt,
            phase=2,
            session="session-1",
        )


def test_infrastructure_retry_gets_a_new_attempt_but_resumption_keeps_its_id(
    tmp_path: Path,
) -> None:
    runner = _runner()
    run_dir = tmp_path / "campaign" / "outcome" / "Trial-A"
    prompt = tmp_path / "prompt.txt"
    case = tmp_path / "case.json"
    prompt.write_text("prompt", encoding="utf-8")
    case.write_text("{}", encoding="utf-8")
    inputs = {
        "trial": "Trial-A",
        "requested_outcome": "Overall Survival",
        "expected_result": {"trial": "Trial-A", "estimate": "HR 0.75"},
    }
    identity = runner["_execution_identity"](run_dir, inputs)
    load = runner["_load_or_create_execution"]
    first = load(
        run_dir,
        identity,
        run_inputs=inputs,
        case_file=case,
        prompt_file=prompt,
        phase=1,
        session=None,
    )
    first_id = first["attempt_id"]
    assert first["expected_result_sha256"] == runner["_json_sha256"](inputs["expected_result"])
    (run_dir / "phase-1.jsonl").write_text(
        json.dumps({"type": "thread.started", "thread_id": "session-1"}) + "\n",
        encoding="utf-8",
    )
    first["state"] = "failed_infrastructure"
    first["attempts"][0]["state"] = "failed_infrastructure"
    original_attempt = json.loads(json.dumps(first["attempts"][0]))
    runner["_atomic_json"](run_dir / "execution.json", first)
    runner["_release_execution_lock"](run_dir)

    retried = load(
        run_dir,
        identity,
        run_inputs=inputs,
        case_file=case,
        prompt_file=prompt,
        phase=2,
        session="session-1",
    )
    assert retried["attempt_id"] != first_id
    assert retried["attempts"][0] == original_attempt
    assert retried["selection_policy"]["selected_attempt_id"] == retried["attempt_id"]
    assert "selected" not in retried["attempts"][1]
    assert retried["attempts"][1]["kind"] == "infrastructure_retry"
    retry_id = retried["attempt_id"]
    runner["_release_execution_lock"](run_dir)

    retried["state"] = "resumable"
    runner["_atomic_json"](run_dir / "execution.json", retried)
    runner["_release_execution_lock"](run_dir)
    resumed = load(
        run_dir,
        identity,
        run_inputs=inputs,
        case_file=case,
        prompt_file=prompt,
        phase=3,
        session="session-1",
    )
    assert resumed["attempt_id"] == retry_id
    assert resumed["phases"][-1]["attempt_id"] == retry_id
    runner["_release_execution_lock"](run_dir)


def test_generic_nonzero_codex_exit_does_not_prove_infrastructure_retry(
    tmp_path: Path,
) -> None:
    runner = _runner()
    run_dir = tmp_path / "campaign" / "runs" / "trial"
    trace = run_dir / "phase-1.jsonl"
    trace.parent.mkdir(parents=True)
    trace.write_text("{}\n", encoding="utf-8")
    record = {
        "state": "running",
        "attempts": [{"attempt_id": "attempt-1", "phase": 1, "state": "running"}],
        "phases": [{"attempt_id": "attempt-1", "phase": 1, "state": "running"}],
    }

    runner["_finish_execution"](run_dir, record, 1, 17)

    assert record["state"] == "resumable"
    assert record["attempts"][0]["state"] == "resumable"
    index_path = run_dir.parent.parent / "index.json"
    index_path.write_text("{}", encoding="utf-8")
    contract = runpy.run_path(str(SCRIPTS / "benchmark_contract.py"))
    assert not contract["infrastructure_failure_proven"](
        index_path,
        {"trial": "trial", "outcome": "Overall Survival", "run_dir": str(run_dir)},
    )


def test_launcher_retry_requires_predecessor_summary_and_exact_run_directory(
    tmp_path: Path,
) -> None:
    contract = runpy.run_path(str(SCRIPTS / "benchmark_contract.py"))
    campaign = tmp_path / "campaign"
    campaign.mkdir()
    index_path = campaign / "index.json"
    index_path.write_text("{}", encoding="utf-8")
    expected_run = campaign / "runs" / "trial"
    other_run = campaign / "runs" / "other"
    row = {
        "trial": "trial",
        "outcome": "Overall Survival",
        "run_dir": str(expected_run),
    }
    result = {
        "trial": "trial",
        "outcome": "Overall Survival",
        "run_dir": str(other_run),
        "phase": 1,
        "exit_code": 2,
        "diagnosis": {"code": "launcher_future_failed", "detail": "fixture"},
        "benchmark_index_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
    }
    summary = campaign / "phase-1-launcher-summary.json"
    summary.write_text(json.dumps([result]), encoding="utf-8")

    assert not contract["infrastructure_failure_proven"](index_path, row)
    result["run_dir"] = str(expected_run)
    result["diagnosis"] = {
        "code": "launcher_process_start_failed",
        "failure_kind": "process_start",
        "exception_type": "FileNotFoundError",
        "detail": "runner executable was not found",
    }
    summary.write_text(json.dumps([result]), encoding="utf-8")
    unrelated = tmp_path / "unrelated-summary.json"
    unrelated.write_text(json.dumps([result]), encoding="utf-8")
    assert not contract["infrastructure_failure_proven"](index_path, row, unrelated)
    assert contract["infrastructure_failure_proven"](index_path, row)
    result["diagnosis"] = {"code": "launcher_future_failed", "detail": "fixture"}
    summary.write_text(json.dumps([result]), encoding="utf-8")
    assert not contract["infrastructure_failure_proven"](index_path, row)


def test_attempt_identity_binds_every_runtime_input() -> None:
    runner = _runner()
    identity = {
        "campaign_id": "campaign",
        "case_id": "campaign-outcome-trial",
        "trial_id": "Trial-A",
        "outcome": "Overall Survival",
    }
    base_runtime = {
        "build_sha256": "build-a",
        "skill_sha256": "skill-a",
        "pack": "pack-a",
        "contract": "contract-a",
        "host": {"platform": "test", "os_name": "test"},
        "expected_tool_inventory": ["get_status", "save_working_checkpoint"],
        "tool_inventory_version": "rob2-kit.mcp-tools.v1",
    }
    common = {
        "run_input_sha256": "run-a",
        "prompt_sha256": "prompt-a",
        "manifest_sha256": "manifest-a",
        "model": "model-a",
        "effort": "medium",
        "selection_policy": "declared",
        "retry": 0,
    }
    original = runner["_attempt_identity"](identity, runtime_inputs=base_runtime, **common)

    for field in base_runtime:
        changed = dict(base_runtime)
        if field == "host":
            changed[field] = {"platform": "changed", "os_name": "test"}
        elif field == "expected_tool_inventory":
            changed[field] = ["get_status", "changed_tool"]
        else:
            changed[field] = f"changed-{field}"
        assert runner["_attempt_identity"](identity, runtime_inputs=changed, **common) != original


def test_success_requires_verified_bundle_and_preserves_phase_provenance(tmp_path: Path) -> None:
    runner = _runner()
    run_dir = tmp_path / "campaign" / "outcome" / "Trial-A"
    record = {
        "attempt_id": "attempt-1",
        "state": "running",
        "phases": [{"phase": 1, "attempt_id": "attempt-1", "session": None}],
        "attempts": [{"attempt_id": "attempt-1", "phase": 1}],
    }
    trace = run_dir / "phase-1.jsonl"
    artifact = run_dir / "workspace" / "result.rob2.zip"
    trace.parent.mkdir(parents=True)
    artifact.parent.mkdir(parents=True)
    trace.write_text("{}\n", encoding="utf-8")
    artifact_identity = "sha256:" + "0" * 64
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"identity": artifact_identity}))

    original = runner["_finish_execution"].__globals__["runpy"].run_path
    runner["_finish_execution"].__globals__["runpy"].run_path = lambda path: {
        "verify": lambda candidate: (True, "verified")
    }
    try:
        runner["_finish_execution"](
            run_dir,
            record,
            1,
            0,
            artifact={"path": "result.rob2.zip", "identity": artifact_identity},
        )
    finally:
        runner["_finish_execution"].__globals__["runpy"].run_path = original

    assert record["state"] == "succeeded"
    assert record["attempts"][0]["state"] == "succeeded"
    assert record["artifact"]["verified"] is True
    assert record["artifact"]["sha256"] == hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert record["phases"][0]["trace_sha256"] == runner["_sha256_file"](trace)


def test_finish_rejects_artifact_receipt_identity_that_differs_from_manifest(
    tmp_path: Path,
) -> None:
    runner = _runner()
    run_dir = tmp_path / "campaign" / "outcome" / "Trial-A"
    trace = run_dir / "phase-1.jsonl"
    artifact = run_dir / "workspace" / "result.rob2.zip"
    trace.parent.mkdir(parents=True)
    artifact.parent.mkdir(parents=True)
    trace.write_text("{}\n", encoding="utf-8")
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"identity": "sha256:" + "a" * 64}))
    record = {"state": "running", "phases": [{"phase": 1}]}

    with pytest.raises(ValueError, match="artifact identity mismatch"):
        runner["_finish_execution"](
            run_dir,
            record,
            1,
            0,
            artifact={"path": "result.rob2.zip", "identity": "sha256:" + "b" * 64},
        )

    assert record["state"] == "resumable"
    assert "artifact" not in record


def test_collector_binds_adjudication_to_checkpoint_domain_question_and_label(
    tmp_path: Path,
) -> None:
    collector = _collector()
    trial_dir = tmp_path / "campaign" / "outcome" / "Trial-A"
    sidecar_path = trial_dir / "adjudications" / "one.json"
    sidecar_path.parent.mkdir(parents=True)
    bundle = trial_dir / "workspace" / "result.rob2.zip"
    bundle.parent.mkdir(parents=True)
    result_identity = "sha256:" + "1" * 64
    checkpoint_identity = "sha256:" + "2" * 64
    source_id = "source_" + "a" * 64
    canonical = {
        "snapshots": {
            "Trial-A": {"checkpoints": [checkpoint_identity]},
        },
        "batch": {
            "trials": [{"id": "Trial-A", "sources": [{"id": source_id}]}],
        },
        "domain_records": {
            "Trial-A:domain:missing": {
                "identity": checkpoint_identity,
                "trial_id": "Trial-A",
                "domain_id": "domain:missing",
                "judgment": "low",
                "answers": [
                    {
                        "question_id": "sq:missing:data-available",
                        "answer": "yes",
                    }
                ],
            }
        },
    }
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("canonical.json", json.dumps(canonical))

    raw = {
        "schema": SCHEMA,
        "run_identity": "campaign",
        "case_identity": "campaign-case",
        "result_identity": result_identity,
        "domain_identity": "domain:missing",
        "question_identity": "sq:missing:data-available",
        "checkpoint_identity": checkpoint_identity,
        "source_identities": (source_id,),
        "reference_label": "low",
        "model_label": "Low",
        "provisional_label": "low",
        "classification": "agreement",
        "rationale": "The checkpoint and source support the reviewed label.",
        "reviewer_identity": "reviewer-1",
        "reviewer_role": "adjudicator",
        "adjudication_version": "2026-09-20",
        "reviewed_at": datetime(2026, 9, 20, 12, 0, tzinfo=UTC),
        "confidence": 1.0,
    }
    write_sidecar(sidecar_path, raw)
    accepted = collector["_case_adjudications"](
        trial_dir,
        case_id="campaign-case",
        trial_id="Trial-A",
        campaign_id="campaign",
        bundle=bundle,
        result_identity=result_identity,
    )
    assert accepted[0]["schema"] == SCHEMA

    for field, value, message in (
        ("domain_identity", "domain:measurement", "domain identity"),
        ("question_identity", "sq:missing:not-a-question", "question identity"),
        ("model_label", "high", "model label"),
    ):
        write_sidecar(sidecar_path, {**raw, field: value})
        with pytest.raises(ValueError, match=message):
            collector["_case_adjudications"](
                trial_dir,
                case_id="campaign-case",
                trial_id="Trial-A",
                campaign_id="campaign",
                bundle=bundle,
                result_identity=result_identity,
            )


def test_trace_artifact_recovery_finds_nested_finalize_receipt(tmp_path: Path) -> None:
    runner = _runner()
    trace = tmp_path / "phase-2.jsonl"
    trace.write_text(
        json.dumps(
            {
                "item": {
                    "result": {
                        "structured_content": {
                            "data": {
                                "artifact": {
                                    "path": ".rob2-kit/finalized/x.rob2.zip",
                                    "sha256": "sha256:" + "a" * 64,
                                }
                            }
                        }
                    }
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert runner["_trace_artifact"](tmp_path, 2) == {
        "path": ".rob2-kit/finalized/x.rob2.zip",
        "sha256": "sha256:" + "a" * 64,
    }


def test_trace_session_recovery_supports_current_thread_event_and_legacy_event(
    tmp_path: Path,
) -> None:
    runner = _runner()
    current = tmp_path / "current.jsonl"
    current.write_text(
        json.dumps({"type": "thread.started", "thread_id": "current-thread"}) + "\n",
        encoding="utf-8",
    )
    assert runner["_trace_session_id"](current) == "current-thread"

    legacy = tmp_path / "legacy.jsonl"
    legacy.write_text(
        json.dumps({"type": "session_id", "session_id": "legacy-session"}) + "\n",
        encoding="utf-8",
    )
    assert runner["_trace_session_id"](legacy) == "legacy-session"


def _probe_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tools_response: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    contract = runpy.run_path(str(SCRIPTS / "benchmark_contract.py"))
    tools_response = tools_response or _tools_list_response()
    stdout = "\n".join(
        (
            json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"name": "rob2"}}}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "result": tools_response}),
        )
    )
    monkeypatch.setattr(
        contract["subprocess"],
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=stdout, stderr=""),
    )
    command = tmp_path / "rob2"
    command.touch()
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    return contract, contract["probe_server_advertised_inventory"](command, workspace)


def _write_frozen_inventory(
    run_dir: Path,
    inventory: dict[str, Any],
    expected: tuple[str, ...],
    *,
    session_event: dict[str, object] | None = None,
) -> None:
    contract = runpy.run_path(str(SCRIPTS / "benchmark_contract.py"))
    runtime = {
        "expected_tool_inventory": list(expected),
        "tool_inventory_version": contract["TOOL_INVENTORY_VERSION"],
        "tool_inventory": contract["tool_inventory_provenance"](),
        "server_advertised_inventory": inventory,
        "codex_registered_mcp": inventory["server_binding"],
    }
    trace = run_dir / "phase-1.jsonl"
    trace.write_text(
        "\n".join(
            (
                json.dumps(
                    session_event
                    or {"type": "thread.started", "thread_id": "session-1"}
                ),
                json.dumps({
                    "type": "item.completed",
                    "item": {
                        "type": "mcp_tool_call", "server": "rob2", "tool": "get_status",
                        "status": "completed", "error": None, "result": {"structured_content": {}},
                    },
                }),
                json.dumps({
                    "type": "item.completed",
                    "item": {
                        "type": "mcp_tool_call", "server": "rob2", "tool": "search_sources",
                        "status": "completed", "error": None, "arguments": {"query": "trial"},
                        "result": {"structured_content": {}},
                    },
                }),
            )
        ) + "\n",
        encoding="utf-8",
    )
    trace_sha256 = hashlib.sha256(trace.read_bytes()).hexdigest()
    runtime_hash = hashlib.sha256(
        json.dumps(runtime, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    (run_dir / "execution.json").write_text(
        json.dumps(
            {
                "runtime_inputs": runtime,
                "runtime_inputs_sha256": runtime_hash,
                "phases": [{
                    "phase": 1,
                    "trace_sha256": trace_sha256,
                    "codex_session_id": "session-1",
                }],
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "phase-1.meta.json").write_text(
        json.dumps({
            "server_advertised_inventory": inventory,
            "trace_sha256": trace_sha256,
            "codex_session_id": "session-1",
        }),
        encoding="utf-8",
    )


def test_tools_list_preflight_checks_schemas_and_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    contract, inventory = _probe_inventory(tmp_path, monkeypatch)

    assert inventory["status"] == "verified"
    assert inventory["source"] == "stdio tools/list"
    assert inventory["tool_count"] == len(contract["public_tool_inventory"]())
    assert inventory["server_info"]["name"] == "rob2"

    payload = _tools_list_response()
    status = next(item for item in payload["tools"] if item["name"] == "get_status")
    status["inputSchema"]["properties"]["unexpected"] = {"type": "string"}
    altered_stdout = "\n".join(
        (
            json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"name": "rob2"}}}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "result": payload}),
        )
    )
    monkeypatch.setattr(
        contract["subprocess"],
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0, stdout=altered_stdout, stderr=""
        ),
    )
    with pytest.raises(ValueError, match="get_status.schema_sha256"):
        contract["probe_server_advertised_inventory"](
            tmp_path / "rob2", tmp_path / "workspace"
        )


def test_continuation_requires_matching_server_preflight_not_a_jsonl_event(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    phase_runner = runpy.run_path(str(SCRIPTS / "run_benchmark_phase.py"))
    runner = _runner()
    _contract, inventory = _probe_inventory(tmp_path, monkeypatch)
    expected = tuple(runner["EXPECTED_TOOL_INVENTORY"])
    trace = tmp_path / "phase-1.jsonl"
    trace.write_text(
        json.dumps({"type": "thread.started", "thread_id": "session-1"}) + "\n",
        encoding="utf-8",
    )
    _write_frozen_inventory(tmp_path, inventory, expected)

    assert runner["_validate_tool_inventory"](
        tmp_path, 1, server_inventory=inventory
    ) == tuple(sorted(expected))
    assert phase_runner["_continuation_diagnosis"](tmp_path, 2) is None

    changed = dict(inventory)
    changed["inventory_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="differs from the frozen attempt"):
        runner["_validate_tool_inventory"](tmp_path, 2, server_inventory=changed)

    (tmp_path / "phase-1.meta.json").write_text(
        json.dumps({"server_advertised_inventory": changed}), encoding="utf-8"
    )
    assert "does not bind the verified server-advertised inventory" in (
        phase_runner["_continuation_diagnosis"](tmp_path, 2) or ""
    )


def test_continuation_requires_hash_bound_same_session_typed_calls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    phase_runner = runpy.run_path(str(SCRIPTS / "run_benchmark_phase.py"))
    runner = _runner()
    _contract, inventory = _probe_inventory(tmp_path, monkeypatch)
    _write_frozen_inventory(tmp_path, inventory, tuple(runner["EXPECTED_TOOL_INVENTORY"]))

    trace = tmp_path / "phase-1.jsonl"
    trace.write_text(
        json.dumps({"type": "thread.started", "thread_id": "session-1"}) + "\n",
        encoding="utf-8",
    )
    record_path = tmp_path / "execution.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    trace_hash = hashlib.sha256(trace.read_bytes()).hexdigest()
    record["phases"][0].update(
        {"trace_sha256": trace_hash, "codex_session_id": "session-1"}
    )
    record_path.write_text(json.dumps(record), encoding="utf-8")
    metadata_path = tmp_path / "phase-1.meta.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata.update({"trace_sha256": trace_hash, "codex_session_id": "session-1"})
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    diagnosis = phase_runner["_continuation_diagnosis"](tmp_path, 2)

    assert diagnosis["code"] == "host_delivery_call_missing"
    assert "get_status" in diagnosis["detail"]
    with pytest.raises(ValueError, match="host_delivery_call_missing"):
        runner["_validate_tool_inventory"](
            tmp_path, 1, server_inventory=inventory
        )


def test_scientific_terminal_status_requires_explicit_operator_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = _runner()
    run_dir = tmp_path / "case"
    run_dir.mkdir()
    execution_path = run_dir / "execution.json"
    execution_path.write_text(
        json.dumps({"state": "resumable", "phases": [{"phase": 1, "state": "resumable"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPTS / "run_rsi_case.py"),
            "--run-dir",
            str(run_dir),
            "--mark-scientific-terminal",
            "--terminal-reason",
            "The retained evidence cannot resolve the prespecified population.",
        ],
    )

    runner["main"]()

    record = json.loads(execution_path.read_text(encoding="utf-8"))
    assert record["state"] == "scientific_failed"
    assert record["terminal_classification_source"] == "explicit operator command"
    assert record["terminal_reason"].startswith("The retained evidence")
    assert record["phases"][0]["state"] == "scientific_failed"
    assert record["phases"][0]["state_before_classification"] == "resumable"
    assert record["terminal_classification_history"][0]["prior_state"] == "resumable"


@pytest.mark.parametrize(
    "state",
    ["running", "succeeded", "scientific_failed", "expired", "cancelled", "failed_infrastructure"],
)
def test_scientific_terminal_classification_preserves_terminal_execution_states(
    tmp_path: Path, state: str
) -> None:
    runner = _runner()
    run_dir = tmp_path / state
    run_dir.mkdir()
    path = run_dir / "execution.json"
    original = {"state": state, "phases": [{"phase": 1, "state": state}]}
    path.write_text(json.dumps(original), encoding="utf-8")

    with pytest.raises(ValueError, match="only a resumable or waiting execution"):
        runner["_mark_scientific_terminal"](run_dir, "A reviewer classified the case terminal.")

    assert json.loads(path.read_text(encoding="utf-8")) == original


def test_codex_timeout_kills_child_and_is_reported_to_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner()

    class TimedOutProcess:
        pid = 123
        returncode = None

        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            self.killed = False

        def communicate(self, *, input: bytes, timeout: float | None) -> tuple[bytes, bytes]:
            assert input == b"prompt"
            assert timeout == 0.25
            raise subprocess.TimeoutExpired("codex", timeout or 0)

        def poll(self) -> int | None:
            return self.returncode

        def kill(self) -> None:
            self.killed = True
            self.returncode = -9

        def wait(self) -> int:
            return int(self.returncode or 0)

    spawned: list[TimedOutProcess] = []

    def popen(*args: Any, **kwargs: Any) -> TimedOutProcess:
        process = TimedOutProcess(*args, **kwargs)
        spawned.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", popen)
    runner["_run_owned_codex"].__globals__["_windows_job_guard"] = lambda _process: None
    with pytest.raises(subprocess.TimeoutExpired):
        runner["_run_owned_codex"](
            ["codex", "exec"],
            cwd=tmp_path,
            prompt=b"prompt",
            trace=tmp_path / "phase.jsonl",
            stderr=tmp_path / "phase.stderr",
            environment={},
            timeout_seconds=0.25,
        )

    assert len(spawned) == 1
    assert spawned[0].killed is True


def test_timeout_terminates_owned_posix_process_group_and_waits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner()

    class Child:
        pid = 456

        def __init__(self) -> None:
            self.waits: list[float | None] = []

        def wait(self, timeout: float | None = None) -> int:
            self.waits.append(timeout)
            return 0

    child = Child()
    signals: list[tuple[int, int]] = []
    os_module = runner["_terminate_owned_process"].__globals__["os"]
    monkeypatch.setattr(
        os_module,
        "killpg",
        lambda pid, signal: signals.append((pid, signal)),
        raising=False,
    )

    runner["_terminate_owned_process"](child, process_group=True)

    signal_module = runner["_terminate_owned_process"].__globals__["signal"]
    assert signals == [(456, signal_module.SIGTERM), (456, getattr(signal_module, "SIGKILL", 9))]
    assert child.waits == [5, None]


def test_phase_runner_passes_declared_timeout_to_case_launcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    phase_runner = runpy.run_path(str(SCRIPTS / "run_benchmark_phase.py"))
    case = tmp_path / "case.json"
    case.write_text("{}", encoding="utf-8")
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Assess.", encoding="utf-8")
    run_dir = tmp_path / "run"
    captured: dict[str, Any] = {}

    def fake_run(command: list[str], **_kwargs: Any) -> SimpleNamespace:
        captured["command"] = command
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(phase_runner["_run_one"].__globals__["subprocess"], "run", fake_run)
    result = phase_runner["_run_one"](
        Path(__file__).parents[1],
        {
            "outcome": "Overall Survival",
            "trial": "Trial-A",
            "case": str(case),
            "prompt": str(prompt),
            "run_dir": str(run_dir),
        },
        1,
        prompt,
        model="gpt-6-luna",
        effort="medium",
        manifest_model="gpt-6-luna",
        manifest_effort="medium",
        timeout_seconds=90.5,
        require_isolated_host=False,
    )

    command = captured["command"]
    assert command[command.index("--timeout-seconds") + 1] == "90.5"
    assert result["exit_code"] == 0


def test_phase_launcher_binds_strict_mode_and_index_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    phase_runner = runpy.run_path(str(SCRIPTS / "run_benchmark_phase.py"))
    case = tmp_path / "case.json"
    prompt = tmp_path / "prompt.txt"
    run_dir = tmp_path / "runs" / "outcome" / "Trial-A"
    expected = {"trial": "Trial-A", "endpoint_definition": "death"}
    campaign_id = "campaign-frozen-72a"
    case.write_text(
        json.dumps(
            {
                "trial": "Trial-A",
                "requested_outcome": "Overall Survival",
                "campaign_id": campaign_id,
                "expected_result": expected,
            }
        ),
        encoding="utf-8",
    )
    prompt.write_text("Assess.", encoding="utf-8")
    row = {
        "outcome": "Overall Survival",
        "trial": "Trial-A",
        "campaign_id": campaign_id,
        "run_dir": str(run_dir),
        "case": str(case),
        "prompt": str(prompt),
        "expected_result": expected,
    }
    index = tmp_path / "index.json"
    index.write_text(
        json.dumps(
            {
                "schema": "rob2-kit.fresh-benchmark-index.v1",
                "campaign_id": campaign_id,
                "cases": [row],
            }
        ),
        encoding="utf-8",
    )
    index_sha256 = hashlib.sha256(index.read_bytes()).hexdigest()
    captured: dict[str, Any] = {}

    def fake_run(command: list[str], **_kwargs: Any) -> SimpleNamespace:
        captured["command"] = command
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(phase_runner["_run_one"].__globals__["subprocess"], "run", fake_run)
    phase_runner["_run_one"](
        Path(__file__).parents[1],
        row,
        1,
        prompt,
        model="gpt-6-luna",
        effort="medium",
        manifest_model="gpt-6-luna",
        manifest_effort="medium",
        require_isolated_host=True,
        index_path=index,
        index_sha256=index_sha256,
    )

    command = captured["command"]
    assert "--require-isolated-host" in command
    assert command[command.index("--benchmark-index") + 1] == str(index)
    assert command[command.index("--benchmark-index-sha256") + 1] == index_sha256


def test_phase_runner_records_a_future_exception_in_final_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    phase_runner = runpy.run_path(str(SCRIPTS / "run_benchmark_phase.py"))
    root = tmp_path / "campaign"
    root.mkdir()
    index = root / "index.json"
    (root / "continuation.txt").write_text("Continue.", encoding="utf-8")
    index.write_text(
        json.dumps(
            {
                "model": "gpt-6-luna",
                "reasoning_effort": "medium",
                "cases": [{"outcome": "Overall Survival", "trial": "Trial-A", "run_dir": "x"}],
            }
        ),
        encoding="utf-8",
    )
    phase_runner["main"].__globals__["_run_one"] = lambda *_args, **_kwargs: (
        (_ for _ in ()).throw(RuntimeError("synthetic worker failure"))
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_benchmark_phase.py",
            "--index",
            str(index),
            "--phase",
            "1",
            "--non-strict-exploratory",
        ],
    )

    with pytest.raises(SystemExit, match="1 benchmark phases failed"):
        phase_runner["main"]()

    summary = json.loads((root / "phase-1-launcher-summary.json").read_text(encoding="utf-8"))
    assert summary[0]["diagnosis"]["code"] == "launcher_future_failed"
    assert summary[0]["diagnosis"]["detail"] == "RuntimeError: synthetic worker failure"
    assert summary[0]["benchmark_index_sha256"] == hashlib.sha256(index.read_bytes()).hexdigest()


def test_phase_launcher_keeps_phase_one_summary_immutable_and_names_continuation_reruns(
    tmp_path: Path,
) -> None:
    phase_runner = runpy.run_path(str(SCRIPTS / "run_benchmark_phase.py"))
    index = tmp_path / "index.json"
    index.write_text("{}", encoding="utf-8")
    first = phase_runner["_launcher_summary_path"](index, 1)
    first.write_text("original draw", encoding="utf-8")

    with pytest.raises(SystemExit, match="use a predeclared replacement index"):
        phase_runner["_launcher_summary_path"](index, 1)
    assert first.read_text(encoding="utf-8") == "original draw"

    phase_two = phase_runner["_launcher_summary_path"](index, 2)
    phase_two.write_text("first continuation draw", encoding="utf-8")
    rerun = phase_runner["_launcher_summary_path"](index, 2)

    assert rerun.name == "phase-2-rerun-2-launcher-summary.json"
    assert rerun != phase_two


def test_host_delivery_observation_is_same_session_and_distinct_from_inventory(
    tmp_path: Path,
) -> None:
    contract = runpy.run_path(str(SCRIPTS / "benchmark_contract.py"))
    trace = tmp_path / "phase-1.jsonl"
    trace.write_text(
        "\n".join(
            (
                json.dumps({"type": "thread.started", "thread_id": "session-1"}),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "mcp_tool_call",
                            "server": "rob2",
                            "tool": "get_status",
                            "status": "completed",
                            "error": None,
                            "result": {"structured_content": {"outcome": "success"}},
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "mcp_tool_call",
                            "server": "rob2",
                            "tool": "search_sources",
                            "arguments": {"query": "randomized"},
                            "status": "completed",
                            "error": None,
                            "result": {"structured_content": {"outcome": "success"}},
                        },
                    }
                ),
            )
        )
        + "\n",
        encoding="utf-8",
    )

    observed = contract["host_delivery_observed"](trace, "session-1")

    assert observed["status"] == "observed"
    assert observed["get_status_call"] is True
    assert observed["typed_call"] is True
    assert observed["tools"] == ["get_status", "search_sources"]
    assert contract["host_delivery_observed"](trace, "different-session")["status"] == "unavailable"


@pytest.mark.parametrize(
    "session_event",
    [
        {"type": "thread.started", "thread_id": "session-1"},
        {"type": "session.started", "session_id": "session-1"},
        {"type": "session_id", "session_id": "session-1"},
        {"type": "session.created", "thread": {"id": "session-1"}},
        {"session_id": "session-1"},
        {"item": {"type": "thread.started", "thread_id": "session-1"}},
    ],
)
def test_continuation_accepts_shared_legacy_session_envelopes_with_typed_calls(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    session_event: dict[str, object],
) -> None:
    phase_runner = runpy.run_path(str(SCRIPTS / "run_benchmark_phase.py"))
    runner = _runner()
    _contract, inventory = _probe_inventory(tmp_path, monkeypatch)
    _write_frozen_inventory(
        tmp_path,
        inventory,
        tuple(runner["EXPECTED_TOOL_INVENTORY"]),
        session_event=session_event,
    )

    assert phase_runner["_continuation_diagnosis"](tmp_path, 2) is None
    assert phase_runner["_session_id"](tmp_path, 2) == "session-1"


def test_collector_requires_explicit_legacy_manifest_for_missing_attempt_history(
    tmp_path: Path,
) -> None:
    collector = _collector()
    trial_dir = tmp_path / "case"
    trial_dir.mkdir()
    identity = {
        "campaign_id": "campaign",
        "case_id": "campaign-overallsurvival-triala",
        "trial_id": "Trial-A",
        "outcome": "Overall Survival",
    }
    (trial_dir / "execution.json").write_text(
        json.dumps(
            {
                "schema": "rob2-kit.rsi-execution.v1",
                "identity": identity,
                "state": "succeeded",
                "phases": [{"phase": 1, "state": "succeeded"}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="attempt history is missing"):
        collector["_execution"](trial_dir, identity, legacy_read_only=False)

    execution = collector["_execution"](
        trial_dir,
        identity,
        legacy_read_only=False,
        allow_historical_missing_attempts=True,
    )

    assert execution is not None
    assert execution["compatibility"] == {
        "mode": "historical-unqualified",
        "schema": "rob2-kit.rsi-execution.v1",
        "reason": "immutable attempt identity was not recorded",
    }


def test_collector_rejects_malformed_or_inconsistent_v1_attempt_history(tmp_path: Path) -> None:
    collector = _collector()
    trial_dir = tmp_path / "case"
    trial_dir.mkdir()
    identity = {
        "campaign_id": "campaign",
        "case_id": "campaign-overallsurvival-triala",
        "trial_id": "Trial-A",
        "outcome": "Overall Survival",
    }
    path = trial_dir / "execution.json"
    base = {
        "schema": "rob2-kit.rsi-execution.v1",
        "identity": identity,
        "state": "succeeded",
        "attempts": [{"attempt_id": "attempt-a", "phase": 1, "selected": True}],
        "selected_attempt_rule": "declared",
        "selection_policy": {"rule": "declared", "selected_attempt_id": "attempt-b"},
    }
    path.write_text(json.dumps(base), encoding="utf-8")
    with pytest.raises(ValueError, match="selected attempt is missing or inconsistent"):
        collector["_execution"](trial_dir, identity, legacy_read_only=False)

    base["attempts"] = [None]
    path.write_text(json.dumps(base), encoding="utf-8")
    with pytest.raises(ValueError, match="missing an immutable identity"):
        collector["_execution"](trial_dir, identity, legacy_read_only=False)


def test_collector_rejects_unclaimed_or_moved_bundles(tmp_path: Path) -> None:
    collector = _collector()
    bundle = tmp_path / "case" / "workspace" / "result.rob2.zip"
    bundle.parent.mkdir(parents=True)
    identity = "sha256:" + "1" * 64
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"identity": identity}))
    execution = {
        "state": "succeeded",
        "artifact": {
            "path": "workspace/result.rob2.zip",
            "sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
            "verified": True,
            "identity": identity,
        },
    }
    assert collector["_bundle"](bundle.parents[1], execution) == bundle

    execution["artifact"]["path"] = "workspace/moved.rob2.zip"
    with pytest.raises(ValueError, match="stale or moved"):
        collector["_bundle"](bundle.parents[1], execution)

    execution["artifact"]["path"] = "workspace/result.rob2.zip"
    execution["state"] = "failed_infrastructure"
    with pytest.raises(ValueError, match="unclaimed bundle"):
        collector["_bundle"](bundle.parents[1], execution)


def test_no_hit_search_is_unresolved_not_scientific_absence() -> None:
    from rob2_kit.application.domains import _evidence_sufficiency

    summary = _evidence_sufficiency(
        [
            {
                "question_id": "sq:test",
                "bases": [
                    {
                        "kind": "absence",
                        "search_receipt": "receipt-1",
                    }
                ],
            }
        ],
        {
            "receipt-1": {
                "truncated": False,
                "total_matches": 0,
                "condition": "no_hits",
                "ranking_complete": True,
                "exhausted": True,
            }
        },
    )

    assert summary["claims"][0]["status"] == "unresolved"


def test_continuation_session_is_recovered_from_a_crashed_phase_trace(tmp_path: Path) -> None:
    runner = _runner()
    run_dir = tmp_path / "campaign" / "outcome" / "Trial-A"
    prompt = tmp_path / "prompt.txt"
    case = tmp_path / "case.json"
    prompt.write_text("prompt", encoding="utf-8")
    case.write_text("{}", encoding="utf-8")
    inputs = {"trial": "Trial-A", "requested_outcome": "Overall Survival"}
    identity = runner["_execution_identity"](run_dir, inputs)
    runner["_load_or_create_execution"](
        run_dir,
        identity,
        run_inputs=inputs,
        case_file=case,
        prompt_file=prompt,
        phase=1,
        session=None,
    )
    (run_dir / "phase-1.jsonl").write_text(
        json.dumps({"session_id": "authoritative-session"}) + "\n", encoding="utf-8"
    )
    record = json.loads((run_dir / "execution.json").read_text(encoding="utf-8"))
    record["state"] = "resumable"
    runner["_atomic_json"](run_dir / "execution.json", record)
    runner["_release_execution_lock"](run_dir)

    with pytest.raises(ValueError, match="does not match"):
        runner["_load_or_create_execution"](
            run_dir,
            identity,
            run_inputs=inputs,
            case_file=case,
            prompt_file=prompt,
            phase=2,
            session="wrong-session",
        )
    resumed = runner["_load_or_create_execution"](
        run_dir,
        identity,
        run_inputs=inputs,
        case_file=case,
        prompt_file=prompt,
        phase=2,
        session="authoritative-session",
    )
    assert resumed["codex_session_id"] == "authoritative-session"
    runner["_release_execution_lock"](run_dir)


def test_continuation_rejects_changed_runtime_inputs(tmp_path: Path) -> None:
    runner = _runner()
    run_dir = tmp_path / "campaign" / "outcome" / "Trial-A"
    prompt = tmp_path / "prompt.txt"
    case = tmp_path / "case.json"
    prompt.write_text("prompt", encoding="utf-8")
    case.write_text("{}", encoding="utf-8")
    inputs = {"trial": "Trial-A", "requested_outcome": "Overall Survival"}
    identity = runner["_execution_identity"](run_dir, inputs)
    runtime_inputs = {
        "build_sha256": "build-a",
        "skill_sha256": "skill-a",
        "pack": "pack-a",
        "contract": "contract-a",
        "host": {"platform": "test", "os_name": "test"},
        "expected_tool_inventory": ["get_status"],
    }
    runner["_load_or_create_execution"](
        run_dir,
        identity,
        run_inputs=inputs,
        case_file=case,
        prompt_file=prompt,
        phase=1,
        session=None,
        runtime_inputs=runtime_inputs,
    )
    (run_dir / "phase-1.jsonl").write_text(
        json.dumps({"session_id": "authoritative-session"}) + "\n", encoding="utf-8"
    )
    record = json.loads((run_dir / "execution.json").read_text(encoding="utf-8"))
    record["state"] = "resumable"
    runner["_atomic_json"](run_dir / "execution.json", record)
    runner["_release_execution_lock"](run_dir)

    changed_runtime = dict(runtime_inputs)
    changed_runtime["pack"] = "pack-b"
    with pytest.raises(ValueError, match="runtime input mismatch"):
        runner["_load_or_create_execution"](
            run_dir,
            identity,
            run_inputs=inputs,
            case_file=case,
            prompt_file=prompt,
            phase=2,
            session="authoritative-session",
            runtime_inputs=changed_runtime,
        )
    runner["_release_execution_lock"](run_dir)


def test_collector_binds_bundle_sources_to_frozen_run_inputs(tmp_path: Path) -> None:
    collector = _collector()
    trial_dir = tmp_path / "case"
    trial_dir.mkdir()
    source_hash = "a" * 64
    run_inputs = {
        "trial": "Trial-A",
        "requested_outcome": "Overall Survival",
        "sources": [{"role": "main_article", "sha256": source_hash, "name": "main.pdf"}],
    }
    (trial_dir / "run-inputs.json").write_text(
        json.dumps(run_inputs, sort_keys=True), encoding="utf-8"
    )
    execution = {
        "run_input_sha256": hashlib.sha256(
            json.dumps(run_inputs, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    }
    bundle = trial_dir / "bundle.rob2.zip"
    canonical = {
        "batch": {
            "trials": [
                {
                    "id": "trial-a",
                    "requested_outcome": "Any treatment-emergent adverse event",
                    "sources": [{"role": "main_article", "sha256": "sha256:" + source_hash}],
                }
            ]
        }
    }
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("canonical.json", json.dumps(canonical))
    with pytest.raises(ValueError, match="requested outcome mismatch"):
        collector["_validate_execution_inputs"](
            trial_dir,
            execution,
            trial="Trial-A",
            outcome="Overall Survival",
            manifest_row=None,
            bundle=bundle,
        )
    canonical["batch"]["trials"][0]["requested_outcome"] = "Overall Survival"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("canonical.json", json.dumps(canonical))
    collector["_validate_execution_inputs"](
        trial_dir,
        execution,
        trial="Trial-A",
        outcome="Overall Survival",
        manifest_row=None,
        bundle=bundle,
    )
    canonical["batch"]["trials"][0]["sources"][0]["sha256"] = "sha256:" + "b" * 64
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("canonical.json", json.dumps(canonical))
    with pytest.raises(ValueError, match="source inventory/content hashes"):
        collector["_validate_execution_inputs"](
            trial_dir,
            execution,
            trial="Trial-A",
            outcome="Overall Survival",
            manifest_row=None,
            bundle=bundle,
        )

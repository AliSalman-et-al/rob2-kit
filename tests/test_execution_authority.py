from __future__ import annotations

import hashlib
import json
import runpy
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from rob2_kit.evaluation.adjudication import SCHEMA, write_sidecar

SCRIPTS = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _runner() -> dict[str, Any]:
    return runpy.run_path(str(SCRIPTS / "run_rsi_case.py"))


def _collector() -> dict[str, Any]:
    return runpy.run_path(str(SCRIPTS / "collect_rsi_benchmark.py"))


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
    assert record["state"] == "running"
    assert record["phases"][0]["phase"] == 1

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
        "state": "running",
        "phases": [{"phase": 1, "session": None}],
        "attempts": [],
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

    assert record["state"] == "failed_infrastructure"
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


def test_continuation_tool_inventory_requires_exact_recovery_surface(tmp_path: Path) -> None:
    runner = _runner()
    contract = json.loads(
        (Path(__file__).parents[1] / "docs" / "release" / "public-contract.json").read_text(
            encoding="utf-8"
        )
    )
    advertised = tuple(tool["name"] for tool in contract["tools"])
    assert runner["EXPECTED_TOOL_INVENTORY"] == advertised
    assert "save_working_checkpoint" in runner["EXPECTED_TOOL_INVENTORY"]

    trace = tmp_path / "phase-1.jsonl"
    trace.write_text(
        json.dumps(
            {
                "type": "mcp_list_tools",
                "tools": [{"name": name} for name in runner["EXPECTED_TOOL_INVENTORY"]],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "execution.json").write_text(
        json.dumps(
            {
                "runtime_inputs": {
                    "expected_tool_inventory": list(runner["EXPECTED_TOOL_INVENTORY"]),
                    "tool_inventory_version": "rob2-kit.mcp-tools.v1",
                }
            }
        ),
        encoding="utf-8",
    )
    assert runner["_validate_tool_inventory"](tmp_path, 1) == tuple(
        sorted(runner["EXPECTED_TOOL_INVENTORY"])
    )

    trace.write_text(
        json.dumps({"type": "mcp_list_tools", "tools": [{"name": "get_status"}]}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="smallest valid recovery|fresh benchmark attempt"):
        runner["_validate_tool_inventory"](tmp_path, 1, expected=("get_status", "search_sources"))


def test_continuation_accepts_trace_without_inventory_when_launch_record_is_frozen(
    tmp_path: Path,
) -> None:
    runner = _runner()
    expected = tuple(runner["EXPECTED_TOOL_INVENTORY"])
    (tmp_path / "phase-1.jsonl").write_text(
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
            )
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "execution.json").write_text(
        json.dumps(
            {
                "runtime_inputs": {
                    "expected_tool_inventory": list(expected),
                    "tool_inventory_version": "rob2-kit.mcp-tools.v1",
                    "tool_inventory": {
                        "names": list(expected),
                        "version": "rob2-kit.mcp-tools.v1",
                        "source": "docs/release/public-contract.json",
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    assert runner["_validate_tool_inventory"](tmp_path, 1) == tuple(sorted(expected))

    (tmp_path / "phase-1.jsonl").write_text(
        json.dumps({"type": "thread.started", "thread_id": "session-1"}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="runtime availability is unverified"):
        runner["_validate_tool_inventory"](tmp_path, 1)

    (tmp_path / "execution.json").write_text(
        json.dumps({"runtime_inputs": {"tool_inventory_version": "rob2-kit.mcp-tools.v1"}}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="frozen launch tool inventory is unavailable"):
        runner["_validate_tool_inventory"](tmp_path, 1)


def test_collector_keeps_legacy_execution_without_attempt_id_unqualified(
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

    execution = collector["_execution"](trial_dir, identity, legacy_read_only=False)

    assert execution is not None
    assert execution["compatibility"] == {
        "mode": "historical-unqualified",
        "schema": "rob2-kit.rsi-execution.v1",
        "reason": "immutable attempt identity was not recorded",
    }


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

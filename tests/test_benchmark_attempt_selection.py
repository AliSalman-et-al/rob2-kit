from __future__ import annotations

import csv
import hashlib
import json
import runpy
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest
from support.rob2 import _assessed_artifact, _workspace

ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

contract = runpy.run_path(str(SCRIPTS / "benchmark_contract.py"))
collector = runpy.run_path(str(SCRIPTS / "collect_rsi_benchmark.py"))
_result_dimensions = runpy.run_path(str(SCRIPTS / "score_trial_benchmark.py"))["_result_dimensions"]
_execution_identity = runpy.run_path(str(SCRIPTS / "run_rsi_case.py"))["_execution_identity"]


def _write_reference(reference: Path) -> None:
    catalog = reference / "catalog"
    labels = catalog / "provisional-labels"
    labels.mkdir(parents=True)
    (catalog / "trials.csv").write_text(
        "trial_label,trial_slug,source_directory,nct_number,outcomes\n"
        "trial,trial,sources/trial,NCT00000001,Overall Survival\n",
        encoding="utf-8",
    )
    for filename in (
        "overall-survival.csv",
        "progression-free-survival.csv",
        "adverse-events.csv",
    ):
        with (labels / filename).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["Trial", "D1", "D2", "D3", "D4", "D5", "Overall Risk"])
            writer.writerow(["trial", "L", "S", "L", "S", "L", "Some Concerns"])


def _scope() -> dict[str, Any]:
    return {"trial": "trial", "endpoint_definition": "death from any cause"}


def test_execution_identity_uses_unique_frozen_campaign_id(tmp_path: Path) -> None:
    first = _execution_identity(
        tmp_path / "runs" / "outcome" / "trial",
        {
            "campaign_id": "campaign-first-72a",
            "trial": "trial",
            "requested_outcome": "Overall Survival",
        },
    )
    second = _execution_identity(
        tmp_path / "runs" / "outcome" / "trial",
        {
            "campaign_id": "campaign-second-73b",
            "trial": "trial",
            "requested_outcome": "Overall Survival",
        },
    )

    assert first["campaign_id"] != second["campaign_id"]
    assert first["case_id"] != second["case_id"]


def _index_row(
    *, run_dir: Path, case: Path, prompt: Path, expected: dict[str, Any], attempt: int = 1
) -> dict[str, Any]:
    return {
        "outcome": "Overall Survival",
        "trial": "trial",
        "run_dir": str(run_dir),
        "case": str(case),
        "prompt": str(prompt),
        "expected_result": expected,
        "attempt": attempt,
    }


def _execution(
    run_dir: Path,
    *,
    expected: dict[str, Any],
    case: Path,
    prompt: Path,
    run_inputs: dict[str, Any],
    state: str,
    attempt_id: str,
    artifact: Path | None = None,
    bundle_sources: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    run_dir.mkdir(parents=True, exist_ok=True)
    campaign_id = run_inputs.get("campaign_id")
    if not isinstance(campaign_id, str):
        campaign_id = run_dir.parents[2].name if len(run_dir.parents) > 2 else "runs"
    run_inputs = {
        **run_inputs,
        "campaign_id": campaign_id,
        "sources": bundle_sources or [],
    }
    (run_dir / "run-inputs.json").write_text(json.dumps(run_inputs), encoding="utf-8")
    input_hash = hashlib.sha256(
        json.dumps(run_inputs, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    prompt_hash = hashlib.sha256(prompt.read_bytes()).hexdigest()
    phases = [
        {
            "phase": 1,
            "attempt_id": attempt_id,
            "state": state,
            "exit_code": 0 if state == "succeeded" else 1,
            "prompt_sha256": prompt_hash,
        }
    ]
    (run_dir / "phase-1.meta.json").write_text(
        json.dumps({"prompt_file": str(prompt), "prompt_sha256": prompt_hash}),
        encoding="utf-8",
    )
    execution: dict[str, Any] = {
        "schema": "rob2-kit.rsi-execution.v1",
        "identity": {
            "campaign_id": campaign_id,
            "case_id": f"{campaign_id}-overallsurvival-trial",
            "trial_id": "trial",
            "outcome": "Overall Survival",
        },
        "state": state,
        "selected_attempt_rule": "infrastructure_only",
        "selection_policy": {"rule": "infrastructure_only", "selected_attempt_id": attempt_id},
        "attempts": [{"attempt_id": attempt_id, "phase": 1, "state": state, "retry": 0}],
        "phases": phases,
        "prompt_sha256_by_phase": {"1": prompt_hash},
        "run_input_sha256": input_hash,
        "expected_result_sha256": hashlib.sha256(
            json.dumps(expected, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "manifest_sha256": hashlib.sha256(case.read_bytes()).hexdigest(),
        "prompt_sha256": prompt_hash,
        "model": "gpt-6-luna",
        "reasoning_effort": "medium",
        "runtime_inputs": {
            "build_sha256": "build-v1",
            "skill_sha256": "skill-v1",
            "pack": "2019.1",
            "contract": "2019",
            "host": {"platform": "test", "os_name": "test"},
            "expected_tool_inventory": ["get_status"],
            "tool_inventory_version": "rob2-kit.mcp-tools.v1",
            "tool_inventory": {
                "names": ["get_status"],
                "version": "rob2-kit.mcp-tools.v1",
                "contract_sha256": "contract-v1",
            },
            "server_advertised_inventory": {
                "status": "verified",
                "inventory_sha256": "server-tools-v1",
                "contract_version": "2019",
                "contract_sha256": "contract-v1",
            },
            "codex_registered_mcp": {
                "server": "rob2",
                "command": "rob2",
                "args": ["mcp"],
            },
            "timeout_seconds": 3600,
            "host_isolation_required": False,
        },
    }
    execution["runtime_inputs_sha256"] = hashlib.sha256(
        json.dumps(execution["runtime_inputs"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if artifact is not None:
        artifact_manifest_identity = contract["artifact_manifest_identity"]
        execution["artifact"] = {
            "path": artifact.relative_to(run_dir).as_posix(),
            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            "identity": artifact_manifest_identity(artifact),
            "verified": True,
            "attempt_id": attempt_id,
        }
    (run_dir / "execution.json").write_text(json.dumps(execution), encoding="utf-8")
    return execution


def _bind_index(run_dir: Path, index_path: Path) -> None:
    index = json.loads(index_path.read_text(encoding="utf-8"))
    row = index["cases"][0]
    runtime = json.loads((run_dir / "execution.json").read_text(encoding="utf-8"))
    runtime_inputs = runtime["runtime_inputs"]
    runtime_inputs["benchmark_index"] = contract["execution_index_binding"](
        index_path,
        hashlib.sha256(index_path.read_bytes()).hexdigest(),
        row,
        run_dir,
        row.get("attempt", index.get("attempt", 1)),
    )
    runtime["runtime_inputs"] = runtime_inputs
    runtime["runtime_inputs_sha256"] = hashlib.sha256(
        json.dumps(runtime_inputs, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    (run_dir / "execution.json").write_text(json.dumps(runtime), encoding="utf-8")


def test_collection_retains_queued_attempt_without_bundle(tmp_path: Path) -> None:
    outcome = "Overall Survival"
    run_root = tmp_path / "campaign" / "runs" / "overall-survival"
    trial_dir = run_root / "trial"
    run_root.mkdir(parents=True)
    reference = tmp_path / "reference"
    _write_reference(reference)
    case = tmp_path / "case.json"
    prompt = tmp_path / "prompt.txt"
    expected = _scope()
    case.write_text(json.dumps({"expected_result": expected}), encoding="utf-8")
    prompt.write_text("Assess.\n", encoding="utf-8")
    row = _index_row(run_dir=trial_dir, case=case, prompt=prompt, expected=expected)
    run_inputs = {"trial": "trial", "requested_outcome": outcome, "expected_result": expected}
    _execution(
        trial_dir,
        expected=expected,
        case=case,
        prompt=prompt,
        run_inputs=run_inputs,
        state="queued",
        attempt_id="attempt-queued",
    )
    (tmp_path / "phase-1-rerun-2-launcher-summary.json").write_text(
        json.dumps(
            [
                {
                    "outcome": outcome,
                    "trial": "trial",
                    "phase": 1,
                    "exit_code": 127,
                    "run_dir": str(trial_dir),
                    "launcher_invocation_id": "prelaunch-failure-1",
                    "diagnosis": {
                        "code": "launcher_process_start_failed",
                        "failure_kind": "process_start",
                    },
                }
            ]
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / "index.json"
    manifest.write_text(json.dumps({"rows": [row]}), encoding="utf-8")

    sidecar, details = collector["collect"](reference, run_root, outcome, manifest=manifest)

    case_result = sidecar["cases"][0]
    assert case_result["completion"] == "incomplete"
    assert case_result["attempts"][0]["status"] == "queued"
    assert case_result["selected_attempt_id"] == "attempt-queued"
    assert {attempt["status"] for attempt in case_result["attempts"]} == {
        "queued",
        "launcher_process_start_failed",
    }
    assert sum(attempt["selected"] for attempt in case_result["attempts"]) == 1
    assert any(
        attempt["attempt_id"] == "launcher-prelaunch-failure-1-attempt-1-phase-1"
        for attempt in case_result["attempts"]
    )
    assert details["cases"][0]["bundle"] is None


def test_collection_retains_wrong_result_artifact_as_unscored(tmp_path: Path) -> None:
    outcome = "Overall Survival"
    run_root = tmp_path / "campaign" / "runs" / "overall-survival"
    trial_dir = run_root / "trial"
    reference = tmp_path / "reference"
    _write_reference(reference)
    workspace = _workspace(trial_dir / "workspace", outcome)
    bundle = _assessed_artifact(workspace, outcome)
    with zipfile.ZipFile(bundle) as archive:
        canonical = json.loads(archive.read("canonical.json"))
    result = canonical["proposal"]["payload"]["results"][0]
    expected = _result_dimensions(result, "trial")
    expected["endpoint_definition"] = "a different endpoint"
    case = tmp_path / "case.json"
    case.write_text(
        json.dumps({"trial": "trial", "requested_outcome": outcome, "expected_result": expected}),
        encoding="utf-8",
    )
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Assess.\n", encoding="utf-8")
    batch_trial = canonical["batch"]["trials"][0]
    run_inputs = {
        "campaign_id": "campaign",
        "trial": "trial",
        "requested_outcome": outcome,
        "expected_result": expected,
    }
    _execution(
        trial_dir,
        expected=expected,
        case=case,
        prompt=prompt,
        run_inputs=run_inputs,
        state="succeeded",
        attempt_id="attempt-wrong-result",
        artifact=bundle,
        bundle_sources=batch_trial["sources"],
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "rob2-kit.benchmark-manifest.v2",
                "rows": [
                    _index_row(run_dir=trial_dir, case=case, prompt=prompt, expected=expected)
                ],
            }
        ),
        encoding="utf-8",
    )

    sidecar, details = collector["collect"](reference, run_root, outcome, manifest=manifest)

    case_result = sidecar["cases"][0]
    assert case_result["scope"] == "scope_uncertain"
    assert case_result["scope_comparable"] == {f"D{i}": False for i in range(1, 6)}
    assert details["cases"][0]["result_scope_status"] == "mismatch"
    assert details["cases"][0]["result_scope_details"]["code"] == "result_scope_mismatch"
    assert details["cases"][0]["bundle"] == str(bundle)


def test_launcher_draws_discover_reruns_and_require_fresh_index_hash(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "outcome" / "trial"
    row = {
        "outcome": "Overall Survival",
        "trial": "trial",
        "run_dir": str(run_dir),
        "attempt": 2,
    }
    index = tmp_path / "replacement-index.json"
    index.write_text(
        json.dumps(
            {
                "schema": "rob2-kit.fresh-benchmark-index.v1",
                "campaign_id": "campaign-1",
                "cases": [row],
            }
        ),
        encoding="utf-8",
    )
    index_sha256 = hashlib.sha256(index.read_bytes()).hexdigest()
    summary = tmp_path / "phase-1-rerun-2-launcher-summary.json"
    summary.write_text(
        json.dumps(
            [
                {
                    "outcome": row["outcome"],
                    "trial": row["trial"],
                    "run_dir": row["run_dir"],
                    "phase": 1,
                    "exit_code": 127,
                    "diagnosis": {"code": "launcher_process_start_failed"},
                    "launcher_invocation_id": "rerun-id",
                    "benchmark_index_sha256": index_sha256,
                }
            ]
        ),
        encoding="utf-8",
    )

    draws = collector["_launcher_draws"](index, row, attempt_number=2)
    assert len(draws) == 1
    assert draws[0]["attempt_id"] == "launcher-rerun-id-attempt-2-phase-1"

    index.write_text(index.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="launcher summary index hash mismatch"):
        collector["_launcher_draws"](index, row, attempt_number=2)


def test_execution_draw_retains_phase_failure_without_a_second_attempt_draw() -> None:
    attempts = [
        {"attempt_id": "same-attempt", "phase": 1, "state": "resumable"},
        {"attempt_id": "same-attempt", "phase": 2, "state": "succeeded"},
    ]
    execution = {
        "attempts": attempts,
        "selection_policy": {"selected_attempt_id": "same-attempt"},
        "phases": [
            {"attempt_id": "same-attempt", "phase": 1, "state": "resumable", "exit_code": 1},
            {"attempt_id": "same-attempt", "phase": 2, "state": "succeeded", "exit_code": 0},
        ],
    }

    draws, selected = collector["_execution_draws"](execution, observed={"D1": "L"})

    assert selected == "same-attempt"
    assert len(draws) == 1
    assert draws[0]["selected"] is True
    assert draws[0]["phase_failures"] == [{"phase": 1, "state": "resumable", "exit_code": 1}]


def test_collection_uses_typed_launcher_draw_when_execution_was_never_created(
    tmp_path: Path,
) -> None:
    outcome = "Overall Survival"
    run_root = tmp_path / "campaign" / "runs" / "overall-survival"
    trial_dir = run_root / "trial"
    run_root.mkdir(parents=True)
    reference = tmp_path / "reference"
    _write_reference(reference)
    case = tmp_path / "case.json"
    prompt = tmp_path / "prompt.txt"
    expected = _scope()
    case.write_text(json.dumps({"expected_result": expected}), encoding="utf-8")
    prompt.write_text("Assess.\n", encoding="utf-8")
    row = _index_row(run_dir=trial_dir, case=case, prompt=prompt, expected=expected)
    manifest = tmp_path / "index.json"
    manifest.write_text(json.dumps({"rows": [row]}), encoding="utf-8")
    (tmp_path / "phase-1-launcher-summary.json").write_text(
        json.dumps(
            [
                {
                    "outcome": outcome,
                    "trial": "trial",
                    "phase": 1,
                    "exit_code": 2,
                    "run_dir": str(trial_dir),
                    "diagnosis": {"code": "case_unreadable", "detail": "missing case"},
                }
            ]
        ),
        encoding="utf-8",
    )

    sidecar, details = collector["collect"](reference, run_root, outcome, manifest=manifest)

    case_result = sidecar["cases"][0]
    assert case_result["completion"] == "failed"
    assert case_result["attempts"][0]["status"] == "case_unreadable"
    assert case_result["attempts"][0]["exit_code"] == 2
    assert details["cases"][0]["operational_state"] == "case_unreadable"
    assert details["cases"][0]["execution"] is None


@pytest.mark.parametrize("replacement_state", ["succeeded", "expired"])
def test_collection_and_merge_retain_failed_original_and_selected_replacement(
    tmp_path: Path, replacement_state: str
) -> None:
    outcome, trial = "Overall Survival", "trial"
    reference = tmp_path / "reference"
    _write_reference(reference)
    original_root = tmp_path / "original" / "runs" / "overall-survival"
    original_run = original_root / trial
    replacement_root = tmp_path / "replacement" / "runs" / "overall-survival"
    replacement_run = replacement_root / trial
    case = tmp_path / "case.json"
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Assess.\n", encoding="utf-8")
    replacement_workspace = _workspace(
        replacement_run / "workspace"
        if replacement_state == "succeeded"
        else tmp_path / "expected-workspace",
        outcome,
    )
    bundle = _assessed_artifact(replacement_workspace, outcome)
    with zipfile.ZipFile(bundle) as archive:
        canonical = json.loads(archive.read("canonical.json"))
    result = canonical["proposal"]["payload"]["results"][0]
    expected = _result_dimensions(result, trial)
    case.write_text(
        json.dumps({"trial": trial, "requested_outcome": outcome, "expected_result": expected}),
        encoding="utf-8",
    )
    batch_trial = canonical["batch"]["trials"][0]
    run_inputs = {
        "campaign_id": "frozen-campaign-27f36d",
        "trial": trial,
        "requested_outcome": outcome,
        "expected_result": expected,
    }
    _execution(
        original_run,
        expected=expected,
        case=case,
        prompt=prompt,
        run_inputs=run_inputs,
        state="failed_infrastructure",
        attempt_id="attempt-one",
    )
    _execution(
        replacement_run,
        expected=expected,
        case=case,
        prompt=prompt,
        run_inputs=run_inputs,
        state=replacement_state,
        attempt_id="attempt-two",
        artifact=bundle if replacement_state == "succeeded" else None,
        bundle_sources=batch_trial["sources"] if replacement_state == "succeeded" else None,
    )

    original_index_path = tmp_path / "original" / "index.json"
    original_case_row = _index_row(
        run_dir=original_run, case=case, prompt=prompt, expected=expected
    )
    original_case_row["campaign_id"] = "frozen-campaign-27f36d"
    base_index = {
        "schema": "rob2-kit.fresh-benchmark-index.v1",
        "campaign_id": "frozen-campaign-27f36d",
        "model": "gpt-6-luna",
        "reasoning_effort": "medium",
        "attempt_policy": contract["ATTEMPT_POLICY"],
        "cases": [original_case_row],
    }
    original_index_path.write_text(json.dumps(base_index), encoding="utf-8")
    replacement_index_path = tmp_path / "replacement" / "index.json"
    replacement_index = {
        **base_index,
        "attempt": 2,
        "retry_of": str(original_index_path.resolve()),
        "retry_of_sha256": hashlib.sha256(original_index_path.read_bytes()).hexdigest(),
        "cases": [
            {
                **_index_row(
                    run_dir=replacement_run,
                    case=case,
                    prompt=prompt,
                    expected=expected,
                    attempt=2,
                ),
                "campaign_id": "frozen-campaign-27f36d",
            }
        ],
    }
    replacement_index_path.write_text(json.dumps(replacement_index), encoding="utf-8")
    _bind_index(original_run, original_index_path)
    _bind_index(replacement_run, replacement_index_path)
    original_execution = json.loads((original_run / "execution.json").read_text())
    original_execution["attempts"][0]["state"] = "failed_infrastructure"
    original_execution["phases"][0]["state"] = "failed_infrastructure"
    (original_run / "execution.json").write_text(json.dumps(original_execution), encoding="utf-8")
    replacement_execution_path = replacement_run / "execution.json"
    replacement_execution = json.loads(replacement_execution_path.read_text(encoding="utf-8"))
    replacement_runtime_inputs = dict(replacement_execution["runtime_inputs"])
    replacement_runtime_inputs["build_sha256"] = "different-build"
    replacement_execution["runtime_inputs"] = replacement_runtime_inputs
    replacement_execution["runtime_inputs_sha256"] = hashlib.sha256(
        json.dumps(replacement_runtime_inputs, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    replacement_execution_path.write_text(json.dumps(replacement_execution), encoding="utf-8")
    transition = contract["_execution_build_transition"](original_execution, replacement_execution)
    assert transition == {
        "from_build_sha256": "build-v1",
        "to_build_sha256": "different-build",
        "reason": (
            "Predeclared infrastructure-only replacement used a different build; "
            "all other execution conditions matched."
        ),
    }
    changed_runtime = dict(replacement_runtime_inputs)
    changed_runtime["pack"] = "different-pack"
    changed_execution = dict(replacement_execution)
    changed_execution["runtime_inputs"] = changed_runtime
    changed_execution["runtime_inputs_sha256"] = hashlib.sha256(
        json.dumps(changed_runtime, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    (replacement_run / "execution.json").write_text(json.dumps(changed_execution), encoding="utf-8")
    with pytest.raises(ValueError, match="changed fields: build_sha256, pack"):
        contract["validate_replacement_case"](
            original_index_path,
            json.loads(original_index_path.read_text(encoding="utf-8")),
            replacement_index_path,
            json.loads(replacement_index_path.read_text(encoding="utf-8")),
            ("overallsurvival", "trial"),
            require_success=False,
        )
    replacement_run_execution = dict(replacement_execution)
    replacement_run_execution["runtime_inputs"] = replacement_runtime_inputs
    replacement_run_execution["runtime_inputs_sha256"] = hashlib.sha256(
        json.dumps(replacement_runtime_inputs, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    replacement_execution_path.write_text(json.dumps(replacement_run_execution), encoding="utf-8")

    merge = runpy.run_path(str(SCRIPTS / "merge_benchmark_attempts.py"))
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "merge_benchmark_attempts.py",
            "--index",
            str(original_index_path),
            "--replacement",
            str(replacement_index_path),
            "--output",
            str(tmp_path / "selected"),
        ],
    )
    try:
        merge["main"]()
    finally:
        monkeypatch.undo()
    selected_index = tmp_path / "selected" / "index.json"
    selected_payload = json.loads(selected_index.read_text(encoding="utf-8"))
    assert selected_payload["cases"][0]["execution_build_transition"] == transition
    sidecar, details = collector["collect"](
        reference, original_root, outcome, manifest=selected_index
    )

    case_result = sidecar["cases"][0]
    assert [item["status"] for item in case_result["attempts"]] == [
        "failed_infrastructure",
        replacement_state,
    ]
    assert [item["selected"] for item in case_result["attempts"]] == [False, True]
    assert len(details["cases"][0]["attempts"]) == 2
    assert case_result["case_id"] == "frozen-campaign-27f36d-overallsurvival-trial"


def test_merge_rejects_replacement_without_predeclared_policy(tmp_path: Path) -> None:
    original = tmp_path / "index.json"
    replacement = tmp_path / "replacement.json"
    row = _index_row(
        run_dir=tmp_path / "run",
        case=tmp_path / "case.json",
        prompt=tmp_path / "prompt.txt",
        expected=_scope(),
    )
    original.write_text(json.dumps({"cases": [row]}), encoding="utf-8")
    replacement.write_text(
        json.dumps(
            {
                "retry_of": str(original.resolve()),
                "retry_of_sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
                "attempt": 2,
                "cases": [row],
            }
        ),
        encoding="utf-8",
    )
    merge = runpy.run_path(str(SCRIPTS / "benchmark_contract.py"))
    with pytest.raises(ValueError, match="predeclared infrastructure-only policy"):
        merge["validate_replacement_case"](
            original,
            json.loads(original.read_text()),
            replacement,
            json.loads(replacement.read_text()),
            ("overallsurvival", "trial"),
        )

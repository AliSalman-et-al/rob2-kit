"""Shared benchmark metadata derived from the maintained public contract."""

from __future__ import annotations

import hashlib
import json
import os
import queue
import runpy
import subprocess
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path

PUBLIC_CONTRACT = Path(__file__).resolve().parents[1] / "docs" / "release" / "public-contract.json"
RECOVERY_EXEC_ALLOWLIST = Path(__file__).with_name("benchmark_recovery_exec_allowlist.json")
TOOL_INVENTORY_VERSION = "rob2-kit.mcp-tools.v1"
PUBLIC_CONTRACT_SOURCE = "docs/release/public-contract.json"
ATTEMPT_POLICY = {
    "schema": "rob2-kit.benchmark-attempt-policy.v1",
    "max_attempts": 2,
    "rule": "infrastructure_only",
    "selection": "latest_eligible_replacement",
}
COMPLETION_RECONCILIATION_SCHEMA = "rob2-kit.completion-reconciliation.v1"
COMPLETION_RECONCILIATION_FILENAME = "completion-reconciliation.json"


def _case_key(row: object) -> tuple[str, str] | None:
    if not isinstance(row, dict):
        return None
    outcome, trial = row.get("outcome"), row.get("trial")
    if not isinstance(outcome, str) or not isinstance(trial, str):
        return None
    def normalize(value: str) -> str:
        return "".join(c for c in value.casefold() if c.isalnum())

    return normalize(outcome), normalize(trial)


def _unique_case(index: dict[str, object], key: tuple[str, str]) -> dict[str, object]:
    rows = index.get("cases")
    matches = [row for row in rows if _case_key(row) == key] if isinstance(rows, list) else []
    if len(matches) != 1 or not isinstance(matches[0], dict):
        raise ValueError(f"benchmark index must contain one matching case: {key}")
    return matches[0]


def _attempt_number(index: dict[str, object], row: dict[str, object]) -> int:
    value = row.get("attempt", index.get("attempt", 1))
    if isinstance(value, str) and value.isdecimal():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("benchmark attempt number must be a positive integer")
    return value


def execution_index_binding(
    index_path: Path,
    expected_index_sha256: str,
    row: dict[str, object],
    run_dir: Path,
    attempt: int,
) -> dict[str, str]:
    """Bind a launch to the exact frozen index bytes and case row."""
    index_path = index_path.resolve(strict=True)
    index_bytes = index_path.read_bytes()
    index_sha256 = hashlib.sha256(index_bytes).hexdigest()
    if index_sha256 != expected_index_sha256:
        raise ValueError("benchmark index changed after the launcher froze its digest")
    try:
        index = json.loads(index_bytes)
    except json.JSONDecodeError as error:
        raise ValueError("benchmark index is invalid JSON") from error
    if not isinstance(index, dict) or index.get("schema") != "rob2-kit.fresh-benchmark-index.v1":
        raise ValueError("benchmark index does not use the fresh-run schema")
    key = _case_key(row)
    if key is None:
        raise ValueError("benchmark launch case identity is malformed")
    indexed_row = _unique_case(index, key)
    if _attempt_number(index, indexed_row) != attempt:
        raise ValueError("benchmark launch attempt differs from the frozen index")
    row_run_dir = indexed_row.get("run_dir")
    if not isinstance(row_run_dir, str) or Path(row_run_dir).resolve() != run_dir.resolve():
        raise ValueError("benchmark launch run directory differs from the frozen index")
    for field in ("expected_result", "scope_unresolved", "campaign_id"):
        if field in row and indexed_row.get(field) != row.get(field):
            raise ValueError(f"benchmark launch {field} differs from the frozen index")
    campaign_id = index.get("campaign_id")
    if not isinstance(campaign_id, str) or not campaign_id.strip():
        raise ValueError("benchmark index campaign_id is missing")
    if indexed_row.get("campaign_id") != campaign_id:
        raise ValueError("benchmark case campaign_id differs from the frozen index")
    case_sha256 = hashlib.sha256(
        json.dumps(indexed_row, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "path": str(index_path),
        "sha256": index_sha256,
        "case_sha256": case_sha256,
        "campaign_id": campaign_id,
    }


def validate_execution_index_binding(
    index_path: Path, row: dict[str, object], execution: dict[str, object]
) -> None:
    runtime = execution.get("runtime_inputs")
    binding = runtime.get("benchmark_index") if isinstance(runtime, dict) else None
    if not isinstance(binding, dict):
        raise ValueError("fresh execution is not bound to its prelaunch benchmark index")
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("retained benchmark index is unavailable") from error
    if not isinstance(index, dict):
        raise ValueError("retained benchmark index is malformed")
    key = _case_key(row)
    if key is None:
        raise ValueError("retained benchmark case identity is malformed")
    indexed_row = _unique_case(index, key)
    indexed_run_dir = indexed_row.get("run_dir")
    if not isinstance(indexed_run_dir, str):
        raise ValueError("retained benchmark case run directory is missing")
    expected = execution_index_binding(
        index_path,
        str(binding.get("sha256", "")),
        row,
        Path(indexed_run_dir),
        _attempt_number(index, indexed_row),
    )
    if binding != expected:
        raise ValueError("execution benchmark index binding does not match the retained index")


def _file_sha256(row: dict[str, object], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"benchmark case is missing {field}")
    path = Path(value).resolve(strict=True)
    if not path.is_file():
        raise ValueError(f"benchmark {field} is not a file: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _launcher_infrastructure_failure(
    index_path: Path, row: dict[str, object], summary_path: Path | None = None
) -> bool:
    expected_summary = index_path.resolve().parent / "phase-1-launcher-summary.json"
    summary = summary_path or expected_summary
    if summary.resolve() != expected_summary.resolve():
        return False
    if not summary.is_file():
        return False
    try:
        rows = json.loads(summary.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    key = _case_key(row)
    if not isinstance(rows, list):
        return False
    matches = [result for result in rows if _case_key(result) == key]
    if len(matches) != 1 or not isinstance(matches[0], dict):
        return False
    result = matches[0]
    expected_index_sha256 = hashlib.sha256(index_path.read_bytes()).hexdigest()
    if result.get("benchmark_index_sha256") != expected_index_sha256:
        return False
    row_run_dir = row.get("run_dir")
    result_run_dir = result.get("run_dir")
    if not isinstance(row_run_dir, str) or not isinstance(result_run_dir, str):
        return False
    if Path(row_run_dir).resolve() != Path(result_run_dir).resolve():
        return False
    diagnosis = result.get("diagnosis")
    return (
        result.get("phase") == 1
        and result.get("exit_code") != 0
        and isinstance(diagnosis, dict)
        and diagnosis.get("code") == "launcher_process_start_failed"
        and diagnosis.get("failure_kind") == "process_start"
        and diagnosis.get("exception_type")
        in {"OSError", "FileNotFoundError", "PermissionError", "NotADirectoryError"}
        and isinstance(diagnosis.get("detail"), str)
        and bool(diagnosis["detail"].strip())
    )


def infrastructure_failure_proven(
    index_path: Path, row: dict[str, object], summary_path: Path | None = None
) -> bool:
    expected_summary = index_path.resolve().parent / "phase-1-launcher-summary.json"
    if summary_path is not None and summary_path.resolve() != expected_summary.resolve():
        return False
    run_dir_value = row.get("run_dir")
    if isinstance(run_dir_value, str) and run_dir_value:
        path = Path(run_dir_value) / "execution.json"
        if path.is_file():
            try:
                execution = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return False
            attempts = execution.get("attempts") if isinstance(execution, dict) else None
            return (
                isinstance(execution, dict)
                and execution.get("state") in {"failed_infrastructure", "expired"}
                and isinstance(attempts, list)
                and any(
                    isinstance(attempt, dict)
                    and attempt.get("state") in {"failed_infrastructure", "expired"}
                    for attempt in attempts
                )
            )
    return _launcher_infrastructure_failure(index_path, row, summary_path)


def _validate_execution_binding(
    index_path: Path,
    index: dict[str, object],
    row: dict[str, object],
    execution: dict[str, object],
) -> None:
    run_dir = row.get("run_dir")
    if not isinstance(run_dir, str):
        raise ValueError("benchmark case run directory is missing")
    run_inputs_path = Path(run_dir) / "run-inputs.json"
    try:
        run_inputs = json.loads(run_inputs_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("attempt run inputs are missing or invalid") from error
    if not isinstance(run_inputs, dict):
        raise ValueError("attempt run inputs are malformed")
    run_input_hash = hashlib.sha256(
        json.dumps(run_inputs, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if execution.get("run_input_sha256") != run_input_hash:
        raise ValueError("attempt run inputs do not match their execution record")
    if (
        run_inputs.get("trial") != row.get("trial")
        or run_inputs.get("requested_outcome") != row.get("outcome")
        or run_inputs.get("expected_result") != row.get("expected_result")
        or run_inputs.get("scope_unresolved") != row.get("scope_unresolved")
        or run_inputs.get("campaign_id") != index.get("campaign_id")
    ):
        raise ValueError("attempt inputs differ from the predeclared Result scope")
    key = _case_key(row)
    campaign_id = index.get("campaign_id")
    expected_identity = {
        "campaign_id": campaign_id,
        "case_id": f"{campaign_id}-{key[0]}-{key[1]}" if key else None,
        "trial_id": row.get("trial"),
        "outcome": row.get("outcome"),
    }
    if execution.get("identity") != expected_identity:
        raise ValueError("attempt execution identity differs from the frozen campaign case")
    for field, index_field in (("model", "model"), ("reasoning_effort", "reasoning_effort")):
        declared = row.get(index_field, index.get(index_field))
        if declared is not None and execution.get(field) != declared:
            raise ValueError(f"attempt {field} differs from the predeclared configuration")
    for field, hash_field in (("case", "manifest_sha256"), ("prompt", "prompt_sha256")):
        if _file_sha256(row, field) != execution.get(hash_field):
            raise ValueError(f"attempt {field} does not match its execution record")
    expected = row.get("expected_result")
    if isinstance(expected, dict):
        expected_hash = hashlib.sha256(
            json.dumps(expected, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if execution.get("expected_result_sha256") != expected_hash:
            raise ValueError("attempt execution has a different frozen Result scope")
    elif execution.get("scope_unresolved") != row.get("scope_unresolved"):
        raise ValueError("attempt execution has a different unresolved-scope reason")
    if index.get("schema") == "rob2-kit.fresh-benchmark-index.v1":
        validate_execution_index_binding(index_path, row, execution)


def _execution_condition(execution: dict[str, object]) -> dict[str, object]:
    runtime = execution.get("runtime_inputs")
    if not isinstance(runtime, dict):
        raise ValueError("replacement launch provenance is missing")
    runtime_hash = hashlib.sha256(
        json.dumps(runtime, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if execution.get("runtime_inputs_sha256") != runtime_hash:
        raise ValueError("replacement launch provenance hash is invalid")
    inventory = runtime.get("tool_inventory")
    advertised = runtime.get("server_advertised_inventory")
    binding = runtime.get("codex_registered_mcp")
    if not isinstance(inventory, dict) or not isinstance(advertised, dict):
        raise ValueError("replacement tool inventory provenance is incomplete")
    if not isinstance(binding, dict):
        raise ValueError("replacement Codex server binding is missing")
    required = (
        "build_sha256",
        "skill_sha256",
        "pack",
        "contract",
        "host",
        "expected_tool_inventory",
        "tool_inventory_version",
        "timeout_seconds",
        "host_isolation_required",
    )
    if any(key not in runtime for key in required):
        raise ValueError("replacement launch provenance is incomplete")
    if (
        advertised.get("status") != "verified"
        or not isinstance(advertised.get("inventory_sha256"), str)
        or not isinstance(advertised.get("contract_sha256"), str)
        or not isinstance(binding.get("command"), str)
        or not isinstance(binding.get("args"), list)
    ):
        raise ValueError("replacement host/tool provenance is incomplete")
    return {
        **{key: runtime[key] for key in required},
        "tool_inventory": inventory,
        "server_inventory": {
            key: advertised.get(key)
            for key in ("inventory_sha256", "contract_version", "contract_sha256")
        },
        "codex_registered_mcp": {
            key: binding.get(key) for key in ("server", "command", "args")
        },
    }


def _execution_build_transition(
    original_execution: dict[str, object], replacement_execution: dict[str, object]
) -> dict[str, str] | None:
    original = _execution_condition(original_execution)
    replacement = _execution_condition(replacement_execution)
    changed = sorted(key for key in original if original[key] != replacement[key])
    if not changed:
        return None
    if changed != ["build_sha256"]:
        raise ValueError(
            "replacement execution condition differs from predecessor "
            f"(changed fields: {', '.join(changed)})"
        )
    previous_build = original["build_sha256"]
    replacement_build = replacement["build_sha256"]
    if not all(isinstance(value, str) and value for value in (previous_build, replacement_build)):
        raise ValueError("replacement build transition is missing a build hash")
    return {
        "from_build_sha256": previous_build,
        "to_build_sha256": replacement_build,
        "reason": (
            "Predeclared infrastructure-only replacement used a different build; "
            "all other execution conditions matched."
        ),
    }


def _execution_build_transition_for_rows(
    original_row: dict[str, object], replacement_row: dict[str, object]
) -> dict[str, str] | None:
    executions: list[dict[str, object]] = []
    for row in (original_row, replacement_row):
        run_dir = row.get("run_dir")
        path = Path(run_dir) / "execution.json" if isinstance(run_dir, str) else None
        try:
            execution = json.loads(path.read_text(encoding="utf-8")) if path and path.is_file() else None
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("replacement execution record is invalid") from error
        if not isinstance(execution, dict):
            return None
        executions.append(execution)
    return _execution_build_transition(executions[0], executions[1])


def validate_replacement_case(
    original_index_path: Path,
    original_index: dict[str, object],
    replacement_index_path: Path,
    replacement_index: dict[str, object],
    key: tuple[str, str],
    *,
    require_success: bool = False,
) -> tuple[dict[str, object], dict[str, object]]:
    """Validate that a replacement is predeclared and follows an eligible failure."""

    policy = original_index.get("attempt_policy")
    if policy != ATTEMPT_POLICY or replacement_index.get("attempt_policy") != policy:
        raise ValueError("replacement requires a matching predeclared infrastructure-only policy")
    if replacement_index.get("retry_of") != str(original_index_path.resolve()):
        raise ValueError("replacement index is not bound to its declared predecessor index")
    expected_index_hash = hashlib.sha256(original_index_path.read_bytes()).hexdigest()
    if replacement_index.get("retry_of_sha256") != expected_index_hash:
        raise ValueError("replacement predecessor index hash does not match")
    original_row = _unique_case(original_index, key)
    replacement_row = _unique_case(replacement_index, key)
    previous_attempt = _attempt_number(original_index, original_row)
    replacement_attempt = _attempt_number(replacement_index, replacement_row)
    if (
        replacement_attempt != previous_attempt + 1
        or replacement_attempt > int(ATTEMPT_POLICY["max_attempts"])
    ):
        raise ValueError("replacement attempt is outside the predeclared attempt policy")
    failure_summary_value = replacement_index.get("predecessor_failure_summary")
    failure_summary = (
        Path(failure_summary_value).resolve(strict=True)
        if isinstance(failure_summary_value, str)
        else None
    )
    if failure_summary is not None:
        expected_summary_hash = replacement_index.get("predecessor_failure_summary_sha256")
        if (
            not isinstance(expected_summary_hash, str)
            or hashlib.sha256(failure_summary.read_bytes()).hexdigest() != expected_summary_hash
        ):
            raise ValueError("replacement predecessor failure summary hash does not match")
    if not infrastructure_failure_proven(original_index_path, original_row, failure_summary):
        raise ValueError("replacement predecessor is not a proven infrastructure failure")
    original_run_dir = original_row.get("run_dir")
    original_execution_path = (
        Path(original_run_dir) / "execution.json" if isinstance(original_run_dir, str) else None
    )
    original_execution: dict[str, object] | None = None
    if original_execution_path is not None and original_execution_path.is_file():
        try:
            original_execution = json.loads(original_execution_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("replacement predecessor execution is invalid") from error
        if not isinstance(original_execution, dict):
            raise ValueError("replacement predecessor execution is malformed")
        _validate_execution_binding(
            original_index_path, original_index, original_row, original_execution
        )
    for field in (
        "model",
        "reasoning_effort",
        "timeout_seconds",
        "attempt_policy",
        "campaign_id",
    ):
        if original_index.get(field) != replacement_index.get(field):
            raise ValueError(f"replacement {field} differs from predecessor configuration")
    for field in ("outcome", "trial", "expected_result", "scope_unresolved", "campaign_id"):
        if original_row.get(field) != replacement_row.get(field):
            raise ValueError(f"replacement case {field} differs from predecessor scope")
    for field in ("case", "prompt"):
        if _file_sha256(original_row, field) != _file_sha256(replacement_row, field):
            raise ValueError(f"replacement {field} differs from predecessor")
    run_dir = replacement_row.get("run_dir")
    path = Path(run_dir) / "execution.json" if isinstance(run_dir, str) else None
    try:
        execution = json.loads(path.read_text(encoding="utf-8")) if path and path.is_file() else None
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("replacement execution record is invalid") from error
    if require_success and not isinstance(execution, dict):
        raise ValueError("replacement execution record is missing or invalid")
    if isinstance(execution, dict):
        if require_success and execution.get("state") != "succeeded":
            raise ValueError("replacement attempt did not succeed")
        _validate_execution_binding(
            replacement_index_path, replacement_index, replacement_row, execution
        )
    if original_execution is not None and isinstance(execution, dict):
        _execution_build_transition(original_execution, execution)
    return original_row, replacement_row


def _load_public_contract() -> dict[str, object]:
    try:
        contract = json.loads(PUBLIC_CONTRACT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"public MCP contract is unreadable: {PUBLIC_CONTRACT}") from error
    if not isinstance(contract, dict):
        raise RuntimeError(f"public MCP contract is not an object: {PUBLIC_CONTRACT}")
    return contract


def public_contract_version() -> str:
    """Return the advertised release contract version."""

    contract = _load_public_contract()
    version = contract.get("contract_version")
    if not isinstance(version, str) or not version.strip():
        raise RuntimeError(f"public MCP contract has no version: {PUBLIC_CONTRACT}")
    return version.strip()


def public_tool_inventory() -> tuple[str, ...]:
    """Return the exact public MCP tool names advertised by the release contract."""

    tools = _load_public_contract().get("tools")
    if not isinstance(tools, list) or not tools:
        raise RuntimeError(f"public MCP contract has no tool inventory: {PUBLIC_CONTRACT}")
    names: list[str] = []
    for tool in tools:
        name = tool.get("name") if isinstance(tool, dict) else None
        if not isinstance(name, str) or not name.strip():
            raise RuntimeError(f"public MCP contract contains an invalid tool: {PUBLIC_CONTRACT}")
        names.append(name.strip())
    if len(set(names)) != len(names):
        raise RuntimeError(f"public MCP contract contains duplicate tools: {PUBLIC_CONTRACT}")
    return tuple(names)


def public_contract_sha256() -> str:
    """Return the frozen contract bytes used to derive the public inventory."""

    try:
        payload = PUBLIC_CONTRACT.read_bytes()
    except OSError as error:
        raise RuntimeError(f"public MCP contract is unreadable: {PUBLIC_CONTRACT}") from error
    return hashlib.sha256(payload).hexdigest()


def tool_inventory_provenance() -> dict[str, object]:
    """Return the inventory plus enough provenance to replay its launch binding."""

    return {
        "names": list(public_tool_inventory()),
        "version": TOOL_INVENTORY_VERSION,
        "source": PUBLIC_CONTRACT_SOURCE,
        "contract_version": public_contract_version(),
        "contract_sha256": public_contract_sha256(),
    }


def _schema_sha256(schema: object) -> str:
    encoded = json.dumps(
        schema, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def missing_result_scope_dimensions(expected: dict[str, object]) -> list[str]:
    """Return required frozen scope fields missing from a Result projection."""

    endpoint = expected.get("endpoint")
    endpoint = endpoint if isinstance(endpoint, dict) else {}
    reported = expected.get("reported_scope")
    explicit_report = isinstance(reported, dict)
    reported = reported if isinstance(reported, dict) else {}
    comparison = expected.get("comparison", expected.get("comparison_groups"))
    core = {
        "trial": expected.get("trial", expected.get("trial_id")),
        "comparison": comparison,
        "endpoint_definition": expected.get(
            "endpoint_definition", expected.get("definition", endpoint.get("definition"))
        ),
        "population": expected.get(
            "population",
            expected.get("intended_analysis_population", reported.get("analysis_population")),
        ),
        "window": expected.get(
            "window",
            expected.get(
                "window_or_cutoff", expected.get("cutoff", expected.get("time_point_or_window"))
            ),
        ),
    }

    def present(value: object) -> bool:
        return value is not None and value != "" and value != [] and value != {}

    missing = [name for name, value in core.items() if not present(value)]
    if (
        not isinstance(comparison, list)
        or len(comparison) < 2
        or any(
            not isinstance(group, dict)
            or not present(group.get("id"))
            or not present(group.get("assignment"))
            for group in comparison
        )
    ) and "comparison" not in missing:
        missing.append("comparison")
    if not explicit_report:
        missing.append("reported_scope")
    form = reported.get("form")
    reported_endpoint = reported.get("endpoint")
    reported_endpoint = reported_endpoint if isinstance(reported_endpoint, dict) else {}
    if not present(reported.get("analysis_population")):
        missing.append("reported_scope.analysis_population")
    if not present(reported_endpoint.get("definition")) and not present(
        reported_endpoint.get("name")
    ):
        missing.append("reported_scope.endpoint")
    if form == "comparative_effect":
        values = {
            "estimate": reported.get("estimate"),
            "effect_measure": reported.get("effect_measure"),
        }
        missing.extend(name for name, value in values.items() if not present(value))
        if "precision" not in reported:
            missing.append("precision")
    elif form == "group_bound_values":
        rows = reported.get("group_values")
        group_ids = (
            {group.get("id") for group in comparison if isinstance(group, dict)}
            if isinstance(comparison, list)
            else set()
        )
        value_group_ids = {
            row.get("group_id") for row in rows if isinstance(row, dict)
        } if isinstance(rows, list) else set()
        if (
            not isinstance(rows, list)
            or len(rows) < 2
            or value_group_ids != group_ids
            or any(
                not isinstance(row, dict)
                or any(
                    not present(row.get(field))
                    for field in ("group_id", "statistic", "value", "unit")
                )
                for row in rows
            )
        ):
            missing.append("reported_scope.group_values")
    elif form == "single_group_category_profile":
        values = {
            "group_id": reported.get("group_id"),
            "denominator_basis": reported.get("denominator_basis"),
            "category_axis_names": reported.get("category_axis_names"),
            "categories": reported.get("categories"),
        }
        missing.extend(name for name, value in values.items() if not present(value))
    elif form == "unavailable":
        values = {"reason": reported.get("reason"), "explanation": reported.get("explanation")}
        missing.extend(name for name, value in values.items() if not present(value))
    else:
        missing.append("reported_scope.form")
    return missing


def contradictory_result_scope_dimensions(expected: dict[str, object]) -> list[str]:
    """Return duplicated comparative fields that disagree with reported_scope."""
    reported = expected.get("reported_scope")
    if not isinstance(reported, dict) or reported.get("form") != "comparative_effect":
        return []
    return [
        f"{field} conflicts with reported_scope.{field}"
        for field in ("estimate", "precision")
        if expected.get(field) is not None and expected.get(field) != reported.get(field)
    ]


def probe_server_advertised_inventory(command: Path, workspace: Path) -> dict[str, object]:
    """Verify the configured rob2 process advertises the complete frozen MCP surface."""

    command = command.resolve(strict=True)
    workspace = workspace.resolve(strict=True)
    initialize_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "rob2-rsi-preflight", "version": "1"},
        },
    }
    initialized_notification = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    tools_request = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    environment = os.environ.copy()
    environment["ROB2_WORKSPACE"] = str(workspace)
    process: subprocess.Popen[str] | None = None
    stdout_thread: threading.Thread | None = None
    stderr_thread: threading.Thread | None = None
    stderr_lines: list[str] = []
    stdout_lines: queue.Queue[str | None] = queue.Queue()
    handshake_deadline = 0.0
    shutdown_grace_seconds = 5
    cleanup_status = "graceful_exit"
    preflight_error: OSError | subprocess.TimeoutExpired | None = None

    def drain_stdout() -> None:
        assert process is not None and process.stdout is not None
        try:
            for line in process.stdout:
                stdout_lines.put(line)
        except (OSError, ValueError):
            pass
        finally:
            stdout_lines.put(None)

    def drain_stderr() -> None:
        assert process is not None and process.stderr is not None
        try:
            stderr_lines.extend(process.stderr)
        except (OSError, ValueError):
            pass

    def response_for(request_id: int) -> dict[str, object]:
        while True:
            remaining = handshake_deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired([str(command), "mcp"], 30)
            try:
                line = stdout_lines.get(timeout=remaining)
            except queue.Empty as error:
                raise subprocess.TimeoutExpired([str(command), "mcp"], 30) from error
            if line is None:
                detail = "".join(stderr_lines).strip()[-1000:]
                raise ValueError(
                    "rob2 MCP tools/list preflight exited before its response"
                    + (f": {detail}" if detail else "")
                )
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(message, dict) and message.get("id") == request_id:
                return message

    try:
        process = subprocess.Popen(
            [str(command), "mcp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
        )
        handshake_deadline = time.monotonic() + 30
        stdout_thread = threading.Thread(target=drain_stdout, daemon=True)
        stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
        stdout_thread.start()
        stderr_thread.start()

        if process.stdin is None:
            raise ValueError("rob2 MCP tools/list preflight has no stdin pipe")
        process.stdin.write(json.dumps(initialize_request) + "\n")
        process.stdin.flush()
        initialize_response = response_for(1)
        initialize_value = initialize_response.get("result")
        initialize_result = initialize_value if isinstance(initialize_value, dict) else None

        process.stdin.write(
            "\n".join(
                json.dumps(item) for item in (initialized_notification, tools_request)
            )
            + "\n"
        )
        process.stdin.flush()
        response = response_for(2)
        process.stdin.close()
        try:
            returncode = process.wait(timeout=shutdown_grace_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired as error:
                raise ValueError(
                    "rob2 MCP tools/list response was valid, but its probe process "
                    "could not be reaped after termination"
                ) from error
            cleanup_status = "forced_kill"
        else:
            if returncode != 0:
                detail = "".join(stderr_lines).strip()[-1000:]
                raise ValueError(
                    "rob2 MCP tools/list preflight failed"
                    + (f": {detail}" if detail else f" (exit {returncode})")
                )
    except (OSError, subprocess.TimeoutExpired) as error:
        preflight_error = error
    finally:
        if process is not None:
            if process.stdin is not None and not process.stdin.closed:
                try:
                    process.stdin.close()
                except (OSError, ValueError):
                    pass
            if process.poll() is None:
                try:
                    process.kill()
                except OSError:
                    pass
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    cleanup_status = "kill_timeout"
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    try:
                        stream.close()
                    except (OSError, ValueError):
                        pass
        for thread in (stdout_thread, stderr_thread):
            if thread is not None:
                thread.join(timeout=1)

    if preflight_error is not None:
        detail = "".join(stderr_lines).strip()[-1000:]
        raise ValueError(
            f"rob2 MCP tools/list preflight failed: {preflight_error}"
            + (f"; {detail}" if detail else "")
        ) from preflight_error
    if cleanup_status == "kill_timeout":
        raise ValueError(
            "rob2 MCP tools/list preflight could not reap its terminated probe process"
        )

    result = response.get("result") if isinstance(response, dict) else None
    tools = result.get("tools") if isinstance(result, dict) else None
    if not isinstance(tools, list):
        raise ValueError("rob2 MCP tools/list preflight returned no complete tool catalog")

    contract = _load_public_contract()
    expected_tools = contract.get("tools")
    if not isinstance(expected_tools, list):
        raise RuntimeError(f"public MCP contract has no tool inventory: {PUBLIC_CONTRACT}")

    def normalized(tool: object) -> dict[str, object]:
        if not isinstance(tool, dict):
            raise ValueError("rob2 MCP tools/list returned a malformed tool entry")
        annotations = tool.get("annotations")
        annotations = annotations if isinstance(annotations, dict) else {}
        input_schema = tool.get("inputSchema")
        output_schema = tool.get("outputSchema")
        if not isinstance(input_schema, dict) or not isinstance(output_schema, dict):
            raise ValueError(
                f"rob2 MCP tool {tool.get('name')!r} is missing an input or output schema"
            )
        name = tool.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("rob2 MCP tools/list returned a tool without a name")
        description = tool.get("description")
        title = tool.get("title")
        return {
            "name": name,
            "title": title.strip() if isinstance(title, str) else "",
            "description": description.strip() if isinstance(description, str) else "",
            "read_only": bool(annotations.get("readOnlyHint", False)),
            "destructive": bool(annotations.get("destructiveHint", False)),
            "idempotent": bool(annotations.get("idempotentHint", False)),
            "open_world": annotations.get("openWorldHint"),
            "schema_sha256": _schema_sha256(input_schema),
            "output_schema_sha256": _schema_sha256(output_schema),
        }

    actual_entries = [normalized(tool) for tool in tools]
    expected_entries = [dict(item) for item in expected_tools if isinstance(item, dict)]
    if len(expected_entries) != len(expected_tools):
        raise RuntimeError(f"public MCP contract contains a malformed tool: {PUBLIC_CONTRACT}")
    actual_names = [
        name for item in actual_entries if isinstance((name := item.get("name")), str)
    ]
    if len(set(actual_names)) != len(actual_names):
        raise ValueError("rob2 MCP tools/list returned duplicate tool names")
    expected_by_name: dict[str, dict[str, object]] = {
        name: item for item in expected_entries if isinstance((name := item.get("name")), str)
    }
    actual_by_name: dict[str, dict[str, object]] = {
        name: item for item in actual_entries if isinstance((name := item.get("name")), str)
    }
    differences: list[str] = []
    for name in sorted(set(expected_by_name) | set(actual_by_name)):
        if name not in expected_by_name:
            differences.append(f"unexpected tool {name}")
        elif name not in actual_by_name:
            differences.append(f"missing tool {name}")
        else:
            for field in expected_by_name[name]:
                if actual_by_name[name].get(field) != expected_by_name[name].get(field):
                    differences.append(f"{name}.{field}")
    if differences:
        raise ValueError(
            "rob2 MCP tools/list differs from the frozen public contract: "
            + ", ".join(differences[:24])
        )

    canonical_inventory = json.dumps(
        sorted(actual_entries, key=lambda item: str(item["name"])),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    server_info = (
        initialize_result.get("serverInfo") if isinstance(initialize_result, dict) else None
    )
    binding = {
        "server": "rob2",
        "command": str(command),
        "args": ["mcp"],
        "workspace_sha256": hashlib.sha256(str(workspace).encode("utf-8")).hexdigest(),
    }
    binding_sha256 = hashlib.sha256(
        json.dumps(binding, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "status": "verified",
        "source": "stdio tools/list",
        "server": "rob2",
        "tool_count": len(actual_entries),
        "names": sorted(actual_by_name),
        "inventory_sha256": hashlib.sha256(canonical_inventory).hexdigest(),
        "contract_version": contract.get("contract_version"),
        "contract_sha256": public_contract_sha256(),
        "server_info": server_info if isinstance(server_info, dict) else {},
        "probe_cleanup": cleanup_status,
        "server_binding": binding,
        "server_binding_sha256": binding_sha256,
    }


def _valid_status_head(value: object) -> bool:
    """Recognize the server-owned status shape carried by a typed receipt."""

    return (
        isinstance(value, dict)
        and isinstance(value.get("phase"), str)
        and bool(value["phase"].strip())
        and isinstance(value.get("state_revision"), int)
        and not isinstance(value.get("state_revision"), bool)
        and isinstance(value.get("next_action"), dict)
    )


def host_delivery_observed(path: Path, expected_session: str | None = None) -> dict[str, object]:
    """Summarize completed rob2 calls from one Codex CLI trace, without inferring inventory."""

    sessions = set(trace_session_ids(path))
    tools: set[str] = set()
    status_call = False
    typed_call = False
    status_head = False
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        item = event.get("item")
        if not (
            event.get("type") == "item.completed"
            and isinstance(item, dict)
            and item.get("type") == "mcp_tool_call"
            and item.get("server") == "rob2"
            and item.get("status") == "completed"
            and item.get("error") is None
            and item.get("result") is not None
            and isinstance(item.get("tool"), str)
        ):
            continue
        tool = item["tool"]
        result = item.get("result")
        typed_receipt = (
            tool in set(public_tool_inventory())
            and isinstance(item.get("arguments"), dict)
            and isinstance(result, dict)
        )
        tools.add(tool)
        if tool == "get_status":
            status_call = True
        elif typed_receipt:
            typed_call = True
        structured = result.get("structured_content") if isinstance(result, dict) else None
        head = structured.get("head") if isinstance(structured, dict) else None
        if typed_receipt and _valid_status_head(head):
            status_head = True
    session_matches = (
        len(sessions) == 1
        and (expected_session is None or next(iter(sessions)) == expected_session)
    )
    return {
        "status": "observed" if session_matches and tools else "unavailable",
        "same_session": session_matches,
        "get_status_call": status_call and session_matches,
        "typed_call": typed_call and session_matches,
        "status_head_observed": status_head and session_matches,
        "tools": sorted(tools) if session_matches else [],
        "session_id_sha256": (
            hashlib.sha256(next(iter(sessions)).encode("utf-8")).hexdigest()
            if session_matches
            else None
        ),
    }


def rob2_call_diagnostics(path: Path) -> dict[str, tuple[str, ...]]:
    """Separate outstanding Rob2 calls from completed tool timeout errors."""

    started: dict[str, str] = {}
    timed_out: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {"incomplete": (), "timed_out": ()}
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        item_id = item.get("id")
        if not isinstance(item_id, str):
            continue
        if (
            event.get("type") == "item.started"
            and item.get("type") == "mcp_tool_call"
            and item.get("server") == "rob2"
            and isinstance(item.get("tool"), str)
        ):
            started[item_id] = item["tool"]
        elif event.get("type") in {"item.completed", "item.failed"}:
            tool = started.pop(item_id, None)
            error = item.get("error")
            message = error.get("message") if isinstance(error, dict) else error
            if (
                tool is not None
                and isinstance(message, str)
                and "timed out awaiting tools/call" in message.casefold()
            ):
                timed_out.add(tool)
    return {
        "incomplete": tuple(sorted(set(started.values()))),
        "timed_out": tuple(sorted(timed_out)),
    }


def trace_session_ids(path: Path) -> tuple[str, ...]:
    """Extract session ids from the current and supported legacy Codex trace envelopes."""

    if not path.is_file():
        return ()
    sessions: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ()
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        event_type = event.get("type")
        if event_type in {
            "thread.started",
            "session.started",
            "session.created",
            "session_id",
        } or (event_type is None and any(key in event for key in ("thread_id", "session_id"))):
            for field in ("thread_id", "session_id"):
                value = event.get(field)
                if isinstance(value, str) and value.strip():
                    sessions.add(value.strip())
            thread = event.get("thread")
            if isinstance(thread, dict) and isinstance(thread.get("id"), str):
                value = thread["id"].strip()
                if value:
                    sessions.add(value)
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") in {
            "thread.started",
            "session.started",
            "session.created",
            "session_id",
        }:
            for field in ("thread_id", "session_id"):
                value = item.get(field)
                if isinstance(value, str) and value.strip():
                    sessions.add(value.strip())
    return tuple(sorted(session for session in sessions if session))


def host_delivery_diagnosis(
    path: Path,
    *,
    expected_sha256: str | None,
    expected_session: str | None,
) -> dict[str, str] | None:
    """Require hash-bound same-session status evidence and a typed rob2 call before resume."""

    def blocked(code: str, detail: str) -> dict[str, str]:
        return {
            "code": code,
            "detail": detail,
            "recovery": (
                "Keep this phase resumable and start a fresh case or repair the retained trace."
            ),
        }

    if not isinstance(expected_sha256, str) or not expected_sha256:
        return blocked(
            "host_delivery_trace_unbound",
            "The prior phase has no recorded JSONL trace hash.",
        )
    try:
        observed_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return blocked("host_delivery_trace_unavailable", "The prior phase JSONL trace is missing.")
    if observed_sha256 != expected_sha256:
        return blocked(
            "host_delivery_trace_hash_mismatch",
            "The prior phase JSONL trace no longer matches its recorded SHA-256.",
        )
    if not isinstance(expected_session, str) or not expected_session:
        return blocked(
            "host_delivery_session_unbound",
            "The prior phase has no authoritative Codex session identifier.",
        )
    observed = host_delivery_observed(path, expected_session)
    if observed.get("same_session") is not True:
        return blocked(
            "host_delivery_session_mismatch",
            "The prior trace does not prove calls came from the selected Codex session.",
        )
    if (
        observed.get("typed_call") is not True
        or (
            observed.get("get_status_call") is not True
            and observed.get("status_head_observed") is not True
        )
    ):
        return blocked(
            "host_delivery_call_missing",
            "The prior trace lacks a completed typed rob2 call and either a completed get_status "
            "call or a valid status head in a typed receipt.",
        )
    return None


def host_tools_infrastructure_recovery_diagnosis(
    run_dir: Path, phase: int
) -> dict[str, str] | None:
    """Validate an audited, non-mutating no-progress turn before resuming its session."""

    def blocked(code: str, detail: str) -> dict[str, str]:
        return {
            "code": code,
            "detail": detail,
            "recovery": "Retain the no-tool phase and inspect its recovery evidence.",
        }

    if phase == 3:
        recovery = audited_no_progress_continuation_diagnosis(run_dir, phase)
        if (
            isinstance(recovery, dict)
            and recovery.get("code") == "no_progress_trace_invalid"
        ):
            return audited_status_only_no_progress_continuation_diagnosis(run_dir, phase)
        return recovery
    if phase == 4:
        return audited_finalization_no_progress_continuation_diagnosis(run_dir, phase)
    sidecar_path = run_dir / f"phase-{phase}.infrastructure.json"
    if phase != 2:
        return blocked(
            "host_tools_recovery_phase_unsupported",
            "Only the audited Phase 2 delivery failure or separate Phase 3 no-progress audit can use this recovery.",
        )
    try:
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        execution = json.loads((run_dir / "execution.json").read_text(encoding="utf-8"))
        phase_meta_path = run_dir / f"phase-{phase}.meta.json"
        phase_meta = json.loads(phase_meta_path.read_text(encoding="utf-8"))
        run_inputs = json.loads((run_dir / "run-inputs.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return blocked("host_tools_recovery_unavailable", str(error))
    if not all(isinstance(value, dict) for value in (sidecar, execution, phase_meta, run_inputs)):
        return blocked("host_tools_recovery_malformed", "Recovery inputs must be JSON objects.")
    if (
        sidecar.get("schema") != "rob2-kit.host-tools-infrastructure-recovery.v2"
        or sidecar.get("reason") != "rob2_tools_unavailable"
        or sidecar.get("phase") != phase
    ):
        return blocked("host_tools_recovery_malformed", "Recovery sidecar identity is invalid.")
    phases = execution.get("phases")
    phase_rows = {
        row.get("phase"): row
        for row in phases
        if isinstance(row, dict) and isinstance(row.get("phase"), int)
    } if isinstance(phases, list) else {}
    prior = phase_rows.get(phase)
    first = phase_rows.get(1)
    if not isinstance(prior, dict):
        return blocked("host_tools_recovery_unbound", "The failed phase is absent from execution.json.")
    if not isinstance(first, dict):
        return blocked("host_tools_recovery_unbound", "Phase 1 is absent from execution.json.")
    if execution.get("state") != "resumable" or prior.get("state") != "resumable":
        return blocked("host_tools_recovery_state_changed", "The execution is no longer resumable.")
    trace_path = run_dir / f"phase-{phase}.jsonl"
    first_trace_path = run_dir / "phase-1.jsonl"
    first_meta_path = run_dir / "phase-1.meta.json"
    try:
        trace_bytes = trace_path.read_bytes()
        first_trace_bytes = first_trace_path.read_bytes()
        first_meta = json.loads(first_meta_path.read_text(encoding="utf-8"))
        phase_meta_bytes = phase_meta_path.read_bytes()
        phase_record_sha256 = hashlib.sha256(
            json.dumps(prior, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    except OSError as error:
        return blocked("host_tools_recovery_unavailable", str(error))
    trace_sha256 = hashlib.sha256(trace_bytes).hexdigest()
    session = prior.get("codex_session_id")
    if (
        not isinstance(session, str)
        or session != first.get("codex_session_id")
        or session != execution.get("codex_session_id")
        or session != sidecar.get("codex_session_id")
        or first.get("attempt_id") != prior.get("attempt_id")
        or execution.get("attempt_id") != prior.get("attempt_id")
        or sidecar.get("trace_sha256") != trace_sha256
        or prior.get("trace_sha256") != trace_sha256
        or sidecar.get("phase_meta_sha256")
        != hashlib.sha256(phase_meta_bytes).hexdigest()
        or phase_meta.get("trace_sha256") != trace_sha256
        or sidecar.get("phase_record_sha256") != phase_record_sha256
        or phase_meta.get("codex_session_id") != session
        or phase_meta.get("session") != session
        or phase_meta.get("phase") != phase
        or phase_meta.get("trial") != run_inputs.get("trial")
        or phase_meta.get("exit_code") != 0
        or phase_meta.get("execution_state") != "resumable"
        or prior.get("exit_code") != 0
        or first.get("exit_code") != 0
        or first.get("trace_sha256")
        != hashlib.sha256(first_trace_bytes).hexdigest()
        or not isinstance(first_meta, dict)
        or first_meta.get("trace_sha256") != hashlib.sha256(first_trace_bytes).hexdigest()
        or first_meta.get("codex_session_id") != session
        or trace_session_ids(first_trace_path) != (session,)
        or sidecar.get("attempt_id") != prior.get("attempt_id")
        or sidecar.get("expected_result_sha256") != prior.get("expected_result_sha256")
    ):
        return blocked("host_tools_recovery_binding_mismatch", "Trace, session, or phase identity changed.")
    if trace_session_ids(trace_path) != (session,):
        return blocked("host_tools_recovery_session_mismatch", "Phase trace belongs to another session.")
    if prior.get("started_at") is None or prior.get("finished_at") is None:
        return blocked("host_tools_recovery_turn_unbound", "Phase timestamps are unavailable.")
    expected_result = run_inputs.get("expected_result")
    if (
        not isinstance(expected_result, dict)
        or hashlib.sha256(
            json.dumps(expected_result, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        != prior.get("expected_result_sha256")
    ):
        return blocked("host_tools_recovery_scope_mismatch", "The frozen result scope changed.")
    approved_scope_path = run_dir / "approved-scope.json"
    try:
        approved_scope_bytes = approved_scope_path.read_bytes()
        approved_scope_record_data = json.loads(approved_scope_bytes)
        approved_scope_sha256 = hashlib.sha256(approved_scope_bytes).hexdigest()
        # Re-read the approval from workspace state; the copied file hash alone is not authority.
        from prepare_rsi_workspace import approved_scope_record

        canonical_scope = approved_scope_record(
            run_dir / "workspace", run_inputs.get("approved_scope")
        )
    except (ImportError, OSError, ValueError, json.JSONDecodeError):
        return blocked("host_tools_recovery_approval_missing", "Approved scope is unavailable.")
    if (
        sidecar.get("approved_scope_sha256") != approved_scope_sha256
        or canonical_scope is None
        or canonical_scope != approved_scope_record_data
    ):
        return blocked("host_tools_recovery_approval_mismatch", "The approved scope changed.")

    delivery = host_delivery_observed(trace_path, session)
    if (
        delivery.get("same_session") is not True
        or delivery.get("typed_call") is not False
        or delivery.get("get_status_call") is not False
        or delivery.get("status_head_observed") is not False
        or delivery.get("tools") != []
    ):
        return blocked("host_tools_recovery_has_tool_activity", "The failed phase was not a no-tool turn.")
    phase_resource_counts = _read_only_codex_tool_counts(trace_bytes, session)
    if phase_resource_counts is None:
        return blocked(
            "host_tools_recovery_trace_invalid",
            "The failed phase contains a malformed, incomplete, or unapproved event.",
        )

    runtime_inputs = phase_meta.get("runtime_inputs")
    phase_runtime_inputs = prior.get("runtime_inputs")
    runtime_inputs_sha256 = (
        hashlib.sha256(
            json.dumps(runtime_inputs, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if isinstance(runtime_inputs, dict)
        else None
    )
    if (
        not isinstance(runtime_inputs, dict)
        or phase_runtime_inputs != runtime_inputs
        or execution.get("runtime_inputs") != runtime_inputs
        or runtime_inputs_sha256 is None
        or phase_meta.get("runtime_inputs_sha256") != runtime_inputs_sha256
        or prior.get("runtime_inputs_sha256") != runtime_inputs_sha256
        or execution.get("runtime_inputs_sha256") != runtime_inputs_sha256
    ):
        return blocked("host_tools_recovery_runtime_mismatch", "Phase runtime inputs are not bound to the execution record.")
    codex_home = (
        Path(runtime_inputs["codex_home_path"])
        if isinstance(runtime_inputs, dict)
        and isinstance(runtime_inputs.get("codex_home_path"), str)
        else None
    )
    rollout = sidecar.get("codex_rollout")
    relative_rollout = rollout.get("path") if isinstance(rollout, dict) else None
    byte_count = rollout.get("byte_count") if isinstance(rollout, dict) else None
    turn_id = rollout.get("turn_id") if isinstance(rollout, dict) else None
    if (
        codex_home is None
        or not isinstance(relative_rollout, str)
        or isinstance(byte_count, bool)
        or not isinstance(byte_count, int)
        or byte_count <= 0
        or not isinstance(turn_id, str)
        or not turn_id
    ):
        return blocked("host_tools_recovery_rollout_missing", "Codex rollout binding is absent.")
    relative_path = Path(relative_rollout)
    if (
        relative_path.is_absolute()
        or relative_path.drive
        or relative_path.root
        or ".." in relative_path.parts
    ):
        return blocked("host_tools_recovery_rollout_invalid", "Codex rollout must remain inside its private home.")
    try:
        codex_home = codex_home.resolve(strict=True)
        rollout_path = (codex_home / relative_path).resolve(strict=True)
        if not rollout_path.is_relative_to(codex_home):
            return blocked("host_tools_recovery_rollout_invalid", "Codex rollout must remain inside its private home.")
        with rollout_path.open("rb") as rollout_file:
            rollout_prefix = rollout_file.read(byte_count)
    except (OSError, RuntimeError):
        return blocked("host_tools_recovery_rollout_missing", "Codex rollout is unavailable.")
    if len(rollout_prefix) != byte_count:
        return blocked("host_tools_recovery_rollout_mismatch", "Codex rollout prefix is incomplete.")
    try:
        phase_start = _parse_aware_datetime(prior["started_at"])
        phase_finish = _parse_aware_datetime(prior["finished_at"])
    except ValueError:
        return blocked("host_tools_recovery_turn_unbound", "Phase timestamps are invalid.")
    if (
        not isinstance(rollout.get("sha256"), str)
        or hashlib.sha256(rollout_prefix).hexdigest() != rollout.get("sha256")
    ):
        return blocked("host_tools_recovery_rollout_mismatch", "Codex rollout lacks bound missing-tool evidence.")
    benchmark_index = runtime_inputs.get("benchmark_index")
    campaign_id = benchmark_index.get("campaign_id") if isinstance(benchmark_index, dict) else None
    evidence_subtype = _codex_rollout_proves_rob2_tools_unavailable(
        rollout_prefix,
        turn_id,
        session,
        phase_start,
        phase_finish,
        campaign_id,
        trace_sha256,
        phase_resource_counts,
        run_dir,
        run_inputs,
    )
    if evidence_subtype is None or sidecar.get("evidence_subtype") != evidence_subtype:
        return blocked("host_tools_recovery_rollout_mismatch", "Codex rollout lacks bound missing-tool evidence.")

    binding = (
        runtime_inputs.get("codex_registered_mcp")
        if isinstance(runtime_inputs, dict)
        else None
    )
    command = binding.get("command") if isinstance(binding, dict) else None
    if not isinstance(command, str):
        return blocked("host_tools_recovery_status_unavailable", "Frozen rob2 command is unavailable.")
    try:
        status = subprocess.run(
            [command, "status", "--workspace", str(run_dir / "workspace")],
            capture_output=True,
            check=False,
            timeout=30,
        )
        status_data = json.loads(status.stdout) if status.returncode == 0 else None
        projection = _workspace_status_projection(status_data)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, ValueError):
        return blocked("host_tools_recovery_status_unavailable", "Current workspace status is unavailable.")
    if sidecar.get("workspace_status_projection") != projection:
        return blocked("host_tools_recovery_status_changed", "The approved assessment state changed after the no-tool turn.")
    return None


def _no_progress_status_projection(value: object, trial: str) -> dict[str, object]:
    """Project the finalization-ready state exposed by status and resource reads."""

    if not isinstance(value, dict) or value.get("outcome") != "success":
        raise ValueError("status did not succeed")
    head = value.get("head") if isinstance(value.get("head"), dict) else value
    data = value.get("data") if isinstance(value.get("data"), dict) else value
    phase = head.get("phase")
    revision = head.get("state_revision")
    next_action = head.get("next_action")
    if next_action is None and head is value:
        next_action = value.get("continuation")
    if (
        phase != "ready_to_finalize"
        or isinstance(revision, bool)
        or not isinstance(revision, int)
        or not isinstance(next_action, dict)
        or next_action.get("authority") != "host"
        or next_action.get("operation") != "finalize_batch"
        or next_action.get("expected_revision") != revision
    ):
        raise ValueError("status is not the audited finalization-ready state")
    trial_id = trial.casefold()
    dispositions = data.get("trial_dispositions")
    counts = data.get("terminal_counts")
    conditions = data.get("conditions")
    expected_counts = {
        "assessed": 1,
        "failed": 0,
        "needs_input": 0,
        "pending": 0,
        "reviewable": 0,
        "unsupported_design": 0,
    }
    if (
        not isinstance(dispositions, dict)
        or dispositions != {trial_id: "assessed"}
        or counts != expected_counts
        or conditions != []
    ):
        raise ValueError("status does not prove that the scientific work is complete")
    return {
        "phase": phase,
        "state_revision": revision,
        "continuation": {
            "authority": "host",
            "operation": "finalize_batch",
            "expected_revision": revision,
        },
        "trial_dispositions": dispositions,
        "terminal_counts": counts,
        "conditions": conditions,
    }


def _resource_read_status(result: object) -> dict[str, object]:
    """Decode the JSON status document returned through read_mcp_resource."""

    if not isinstance(result, dict):
        raise ValueError("resource read has no result object")
    content = result.get("content")
    if not isinstance(content, list) or len(content) != 1 or not isinstance(content[0], dict):
        raise ValueError("resource read content is malformed")
    envelope_text = content[0].get("text")
    if not isinstance(envelope_text, str):
        raise ValueError("resource read has no text payload")
    envelope = json.loads(envelope_text)
    if (
        not isinstance(envelope, dict)
        or envelope.get("server") != "rob2"
        or envelope.get("uri") != "rob2://current-batch"
    ):
        raise ValueError("resource read is not the current rob2 batch resource")
    contents = envelope.get("contents")
    if not isinstance(contents, list) or len(contents) != 1 or not isinstance(contents[0], dict):
        raise ValueError("resource read envelope is malformed")
    status_text = contents[0].get("text")
    if not isinstance(status_text, str):
        raise ValueError("resource read contains no status document")
    status = json.loads(status_text)
    if not isinstance(status, dict):
        raise ValueError("resource read status is not an object")
    return status


def _no_progress_trace_audit(
    trace: bytes, expected_session: str, trial: str
) -> dict[str, object] | None:
    """Accept exactly the read-only diagnostics observed in the audited Phase 3 turn."""

    try:
        events = [json.loads(line) for line in trace.decode("utf-8").splitlines()]
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not events or not all(isinstance(event, dict) for event in events):
        return None
    state = "thread"
    pending: dict[str, tuple[str, str]] = {}
    calls: list[tuple[str, str]] = []
    call_records: list[dict[str, object]] = []
    read_status: dict[str, object] | None = None
    messages: list[str] = []
    completed_ids: set[str] = set()
    for event in events:
        event_type = event.get("type")
        if event_type == "thread.started":
            if state != "thread" or event.get("thread_id") != expected_session:
                return None
            state = "turn"
            continue
        if event_type == "turn.started":
            if state != "turn":
                return None
            state = "active"
            continue
        if event_type == "turn.completed":
            if state != "active" or pending:
                return None
            state = "finished"
            continue
        if state != "active" or event_type not in {"item.started", "item.completed"}:
            return None
        item = event.get("item")
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            return None
        item_id = item["id"]
        item_type = item.get("type")
        if item_type == "agent_message":
            if event_type != "item.completed" or not isinstance(item.get("text"), str):
                return None
            messages.append(item["text"])
            continue
        if item_type != "mcp_tool_call":
            return None
        server = item.get("server")
        tool = item.get("tool")
        if server not in {"codex", "rob2"} or not isinstance(tool, str):
            return None
        allowed = (
            server == "codex"
            and tool in {"list_mcp_resources", "list_mcp_resource_templates"}
        ) or (server == "rob2" and tool == "read_mcp_resource")
        if not allowed or not isinstance(item.get("arguments"), dict):
            return None
        if event_type == "item.started":
            if item_id in pending:
                return None
            pending[item_id] = (server, tool)
            continue
        if item_id in completed_ids or pending.pop(item_id, None) != (server, tool):
            return None
        if item.get("status") != "completed" or item.get("error") is not None:
            return None
        if item.get("result") is None:
            return None
        completed_ids.add(item_id)
        calls.append((server, tool))
        call_records.append(
            {
                "server": server,
                "tool": tool,
                "arguments": item["arguments"],
                "result": item["result"],
            }
        )
        if server == "rob2":
            arguments = item["arguments"]
            if arguments != {"server": "rob2", "uri": "rob2://current-batch"}:
                return None
            try:
                read_status = _resource_read_status(item["result"])
            except (ValueError, TypeError, json.JSONDecodeError):
                return None
    if (
        state != "finished"
        or pending
        or calls
        != [
            ("codex", "list_mcp_resources"),
            ("codex", "list_mcp_resource_templates"),
            ("rob2", "read_mcp_resource"),
        ]
        or len(messages) != 3
        or not messages[-1].count("ready_to_finalize")
        or "assessed" not in messages[-1]
        or read_status is None
        or "read_mcp_resource" in set(public_tool_inventory())
    ):
        return None
    try:
        projection = _no_progress_status_projection(read_status, trial)
    except ValueError:
        return None
    return {
        "status_projection": projection,
        "mcp_calls": call_records,
        "messages": messages,
        "workflow_methods_called": [],
        "read_only_diagnostics": [tool for _, tool in calls],
        "resource_probes": [tool for server, tool in calls if server == "codex" or tool == "read_mcp_resource"],
    }


def _status_only_no_progress_trace_audit(
    trace: bytes, expected_session: str, trial: str
) -> dict[str, object] | None:
    """Accept exactly one successful public get_status call in a completed turn."""

    try:
        events = [json.loads(line) for line in trace.decode("utf-8").splitlines()]
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not events or not all(isinstance(event, dict) for event in events):
        return None
    state = "thread"
    pending: tuple[str, str] | None = None
    status: dict[str, object] | None = None
    status_result: dict[str, object] | None = None
    calls: list[str] = []
    messages: list[str] = []
    message_ids: set[str] = set()
    for event in events:
        event_type = event.get("type")
        if event_type == "thread.started":
            if state != "thread" or event.get("thread_id") != expected_session:
                return None
            state = "turn"
        elif event_type == "turn.started":
            if state != "turn":
                return None
            state = "active"
        elif event_type == "turn.completed":
            if state != "active" or pending is not None:
                return None
            state = "finished"
        elif event_type in {"item.started", "item.completed"}:
            if state != "active":
                return None
            item = event.get("item")
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                return None
            item_id = item["id"]
            if item.get("type") == "agent_message":
                if (
                    event_type != "item.completed"
                    or item_id in message_ids
                    or not isinstance(item.get("text"), str)
                ):
                    return None
                message_ids.add(item_id)
                messages.append(item["text"])
                continue
            if item.get("type") != "mcp_tool_call":
                return None
            if (
                item.get("server") != "rob2"
                or item.get("tool") != "get_status"
                or item.get("arguments") != {}
            ):
                return None
            if event_type == "item.started":
                if pending is not None or item_id in message_ids:
                    return None
                pending = (item_id, "get_status")
                continue
            if pending != (item_id, "get_status") or item.get("status") != "completed":
                return None
            if item.get("error") is not None or not isinstance(item.get("result"), dict):
                return None
            result = item["result"].get("structured_content")
            if not isinstance(result, dict) or result.get("outcome") != "success":
                return None
            try:
                status = _no_progress_status_projection(result, trial)
            except ValueError:
                return None
            status_result = item["result"]
            calls.append("get_status")
            pending = None
        else:
            return None
    if (
        state != "finished"
        or pending is not None
        or calls != ["get_status"]
        or status is None
        or status_result is None
    ):
        return None
    return {
        "status_projection": status,
        "status_result": status_result,
        "messages": messages,
        "workflow_methods_called": ["get_status"],
        "read_only_methods_called": ["get_status"],
        "read_only_diagnostics": [],
        "resource_probes": [],
    }


def _rollout_text_values(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for child in value.values() for text in _rollout_text_values(child)]
    if isinstance(value, list):
        return [text for child in value for text in _rollout_text_values(child)]
    return []


def _rollout_call_output_texts(value: object) -> list[str]:
    texts = _rollout_text_values(value)
    return [text.rsplit("Output:\n", 1)[1] if "Output:\n" in text else text for text in texts]


def _mcp_results_match(left: object, right: object) -> bool:
    """Compare CLI and Codex rollout MCP envelopes across their casing differences."""

    if not isinstance(left, dict) or not isinstance(right, dict):
        return False

    def normalized(value: dict[str, object]) -> tuple[object, object] | None:
        error = value.get("isError", value.get("is_error"))
        if error not in {None, False}:
            return None
        structured = value.get("structuredContent", value.get("structured_content"))
        return value.get("content"), structured

    return normalized(left) is not None and normalized(left) == normalized(right)


def _rollout_turn_actions(
    turn_events: list[dict[str, object]], expected_session: str
) -> dict[str, object] | None:
    """Parse only known inert rollout events plus paired exec and MCP calls."""

    thread_ids: set[str] = set()
    mcp_calls: list[dict[str, object]] = []
    exec_calls: list[tuple[str, str]] = []
    exec_outputs: dict[str, dict[str, object]] = {}
    inert_items = {"UserMessage", "AgentMessage", "Reasoning", "ContextCompaction"}
    inert_rollout_types = {"turn_context", "token_usage_record", "compacted", "world_state"}

    for event in turn_events:
        event_type = event.get("type")
        payload = event.get("payload")
        if isinstance(payload, dict) and isinstance(payload.get("thread_id"), str):
            thread_ids.add(payload["thread_id"])
        if event_type in inert_rollout_types:
            continue
        if event_type == "event_msg" and isinstance(payload, dict):
            payload_type = payload.get("type")
            if payload_type in {"task_started", "task_complete", "token_count", "thread_settings_applied"}:
                continue
            if payload_type != "item_completed" or not isinstance(payload.get("item"), dict):
                return None
            item = payload["item"]
            item_type = item.get("type")
            if item_type in inert_items:
                continue
            if item_type != "McpToolCall":
                return None
            if (
                item.get("status") != "completed"
                or item.get("error") is not None
                or not isinstance(item.get("server"), str)
                or not isinstance(item.get("tool"), str)
                or not isinstance(item.get("arguments"), dict)
                or not isinstance(item.get("result"), dict)
            ):
                return None
            mcp_calls.append(
                {
                    "server": item["server"],
                    "tool": item["tool"],
                    "arguments": item["arguments"],
                    "result": item["result"],
                    "readOnlyHint": item.get("readOnlyHint"),
                }
            )
            continue
        if event_type == "response_item" and isinstance(payload, dict):
            payload_type = payload.get("type")
            if payload_type in {"message", "reasoning"}:
                continue
            if payload_type == "custom_tool_call":
                call_id, source = payload.get("call_id"), payload.get("input")
                if (
                    payload.get("name") != "exec"
                    or payload.get("status") != "completed"
                    or not isinstance(call_id, str)
                    or not call_id
                    or not isinstance(source, str)
                    or any(existing_id == call_id for existing_id, _ in exec_calls)
                ):
                    return None
                exec_calls.append((call_id, source))
                continue
            if payload_type == "custom_tool_call_output":
                call_id = payload.get("call_id")
                if (
                    not isinstance(call_id, str)
                    or not call_id
                    or call_id in exec_outputs
                    or payload.get("output") is None
                    or payload.get("isError") is True
                ):
                    return None
                exec_outputs[call_id] = payload
                continue
            return None
        return None

    if thread_ids != {expected_session} or set(exec_outputs) != {call_id for call_id, _ in exec_calls}:
        return None
    return {"mcp_calls": mcp_calls, "exec_calls": exec_calls, "exec_outputs": exec_outputs}


_RESOURCE_NO_PROGRESS_EXEC_SOURCES = (
    "const [res,tpls]=await Promise.all([tools.list_mcp_resources({}),tools.list_mcp_resource_templates({})]);\n"
    "text(JSON.stringify({resources:res,templates:tpls}));\n",
    'const r = await tools.read_mcp_resource({server:"rob2", uri:"rob2://current-batch"});\ntext(r);\n',
    'text(ALL_TOOLS.filter(x=>/rob2|finaliz|batch|invariant/i.test(x.name+" "+x.description)));\n',
    'text(ALL_TOOLS.map(x=>x.name).filter(n=>n.startsWith("mcp__rob2__")));\n',
)


def _rollout_no_progress_candidates(
    codex_home: Path,
    expected_session: str,
    phase_start: datetime,
    phase_finish: datetime,
    trace_calls: list[dict[str, object]],
    expected_status_projection: dict[str, object],
    trial: str,
) -> list[dict[str, object]]:
    """Bind resource diagnostics to the exact read-only calls retained in the CLI trace."""

    expected_inventory = sorted("mcp__rob2__" + name for name in public_tool_inventory())
    candidates: list[dict[str, object]] = []
    try:
        rollout_paths = sorted(codex_home.rglob("rollout-*.jsonl"))
    except OSError:
        return []
    for rollout_path in rollout_paths:
        try:
            rollout_bytes = rollout_path.read_bytes()
            events = [json.loads(line) for line in rollout_bytes.decode("utf-8").splitlines()]
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        turns: list[tuple[str, datetime, datetime, list[dict[str, object]]]] = []
        active: dict[str, object] | None = None
        malformed = False
        for event in events:
            if not isinstance(event, dict):
                malformed = True
                break
            payload = event.get("payload")
            if event.get("type") == "event_msg" and isinstance(payload, dict) and payload.get("type") == "task_started":
                try:
                    started_at = _parse_aware_datetime(event.get("timestamp"))
                except ValueError:
                    malformed = True
                    break
                turn_id = payload.get("turn_id")
                if not isinstance(turn_id, str) or not turn_id:
                    malformed = True
                    break
                active = {"turn_id": turn_id, "started_at": started_at, "events": [event]}
                continue
            if active is None:
                continue
            active["events"].append(event)
            if (
                event.get("type") == "event_msg"
                and isinstance(payload, dict)
                and payload.get("type") == "task_complete"
                and payload.get("turn_id") == active["turn_id"]
            ):
                try:
                    finished_at = _parse_aware_datetime(event.get("timestamp"))
                except ValueError:
                    malformed = True
                    break
                turns.append((active["turn_id"], active["started_at"], finished_at, active["events"]))
                active = None
        if malformed:
            continue
        for turn_id, started_at, finished_at, turn_events in turns:
            if not (phase_start <= started_at <= finished_at <= phase_finish):
                continue
            actions = _rollout_turn_actions(turn_events, expected_session)
            if not isinstance(actions, dict):
                continue
            raw_calls = actions["mcp_calls"]
            if len(raw_calls) != len(trace_calls) or any(
                raw.get("server") != expected.get("server")
                or raw.get("tool") != expected.get("tool")
                or raw.get("arguments") != expected.get("arguments")
                or not _mcp_results_match(raw.get("result"), expected.get("result"))
                for raw, expected in zip(raw_calls, trace_calls)
            ):
                continue
            exec_calls = actions["exec_calls"]
            if [source for _, source in exec_calls] != list(_RESOURCE_NO_PROGRESS_EXEC_SOURCES):
                continue
            outputs = actions["exec_outputs"]
            output_texts = [
                _rollout_call_output_texts(outputs[call_id].get("output"))
                for call_id, _ in exec_calls
            ]
            if any(not texts for texts in output_texts):
                continue
            try:
                resource_probe_output = json.loads(output_texts[0][-1].strip())
                resource_read_output = json.loads(output_texts[1][-1].strip())
                inventory_text = output_texts[3][-1].strip()
                if inventory_text.startswith("Warning: truncated output"):
                    marker = inventory_text.find("\n\n")
                    if marker < 0:
                        continue
                    inventory_text = inventory_text[marker + 2 :]
                inventory_output = json.loads(inventory_text)
            except (IndexError, json.JSONDecodeError):
                continue
            if (
                not isinstance(resource_probe_output, dict)
                or set(resource_probe_output) != {"resources", "templates"}
                or not _mcp_results_match(resource_probe_output.get("resources"), raw_calls[0].get("result"))
                or not _mcp_results_match(resource_probe_output.get("templates"), raw_calls[1].get("result"))
                or not _mcp_results_match(resource_read_output, raw_calls[2].get("result"))
                or not isinstance(inventory_output, list)
                or not all(isinstance(item, str) for item in inventory_output)
                or sorted(inventory_output) != expected_inventory
            ):
                continue
            try:
                raw_status = _resource_read_status(raw_calls[2]["result"])
                status_projection = _no_progress_status_projection(raw_status, trial)
            except (KeyError, ValueError, TypeError, json.JSONDecodeError):
                continue
            if status_projection != expected_status_projection:
                continue
            candidates.append(
                {
                    "path": rollout_path,
                    "sha256": hashlib.sha256(rollout_bytes).hexdigest(),
                    "byte_count": len(rollout_bytes),
                    "turn_id": turn_id,
                    "exec_source_sha256s": [
                        hashlib.sha256(source.encode("utf-8")).hexdigest()
                        for _, source in exec_calls
                    ],
                    "exec_call_ids": [call_id for call_id, _ in exec_calls],
                    "exec_output_sha256s": [
                        hashlib.sha256(
                            json.dumps(
                                outputs[call_id].get("output"),
                                sort_keys=True,
                                separators=(",", ":"),
                            ).encode("utf-8")
                        ).hexdigest()
                        for call_id, _ in exec_calls
                    ],
                    "status_projection": status_projection,
                }
            )
    return candidates


_STATUS_ONLY_EXEC_SOURCES = {
    3: (
        "const r=await tools.mcp__rob2__get_status({});text(r.structuredContent ?? r.content);\n",
        'const hits = ALL_TOOLS.filter(x => /rob2/i.test(x.name+" "+x.description) && /reopen|recover|reset|discard|trial|batch|finaliz/i.test(x.name+" "+x.description));\ntext(hits);\n',
    ),
    4: (
        'const paths = ALL_TOOLS.filter(x => /mcp__rob2__/.test(x.name)).map(x=>x.name);\ntext(paths);\n',
        "const r = await tools.mcp__rob2__get_status({});\ntext(r);\n",
    ),
}


def _rollout_status_only_candidates(
    codex_home: Path,
    expected_session: str,
    phase_start: datetime,
    phase_finish: datetime,
    *,
    phase: int,
    trial: str,
    trace_status_result: dict[str, object],
    expected_status_projection: dict[str, object],
) -> list[dict[str, object]]:
    """Bind a Phase 3 or 4 status-only turn to its exact CLI call and paired reads."""

    allowed_sources = _STATUS_ONLY_EXEC_SOURCES.get(phase)
    if allowed_sources is None:
        return []
    candidates: list[dict[str, object]] = []
    try:
        rollout_paths = sorted(codex_home.rglob("rollout-*.jsonl"))
    except OSError:
        return []
    for rollout_path in rollout_paths:
        try:
            rollout_bytes = rollout_path.read_bytes()
            events = [json.loads(line) for line in rollout_bytes.decode("utf-8").splitlines()]
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        active: dict[str, object] | None = None
        turns: list[tuple[str, datetime, datetime, list[dict[str, object]]]] = []
        malformed = False
        for event in events:
            if not isinstance(event, dict):
                malformed = True
                break
            payload = event.get("payload")
            if event.get("type") == "event_msg" and isinstance(payload, dict) and payload.get("type") == "task_started":
                try:
                    started_at = _parse_aware_datetime(event.get("timestamp"))
                except ValueError:
                    malformed = True
                    break
                turn_id = payload.get("turn_id")
                if not isinstance(turn_id, str) or not turn_id:
                    malformed = True
                    break
                active = {"turn_id": turn_id, "started_at": started_at, "events": [event]}
                continue
            if active is None:
                continue
            active["events"].append(event)
            if (
                event.get("type") == "event_msg"
                and isinstance(payload, dict)
                and payload.get("type") == "task_complete"
                and payload.get("turn_id") == active["turn_id"]
            ):
                try:
                    finished_at = _parse_aware_datetime(event.get("timestamp"))
                except ValueError:
                    malformed = True
                    break
                turns.append((active["turn_id"], active["started_at"], finished_at, active["events"]))
                active = None
        if malformed:
            continue
        for turn_id, started_at, finished_at, turn_events in turns:
            if not (phase_start <= started_at <= finished_at <= phase_finish):
                continue
            actions = _rollout_turn_actions(turn_events, expected_session)
            if not isinstance(actions, dict):
                continue
            mcp_calls = actions["mcp_calls"]
            if (
                len(mcp_calls) != 1
                or mcp_calls[0].get("server") != "rob2"
                or mcp_calls[0].get("tool") != "get_status"
                or mcp_calls[0].get("arguments") != {}
                or mcp_calls[0].get("readOnlyHint") is not True
                or not _mcp_results_match(mcp_calls[0].get("result"), trace_status_result)
            ):
                continue
            exec_calls = actions["exec_calls"]
            if [source for _, source in exec_calls] != list(allowed_sources):
                continue
            outputs = actions["exec_outputs"]
            output_texts = [
                _rollout_call_output_texts(outputs[call_id].get("output"))
                for call_id, _ in exec_calls
            ]
            if any(not texts for texts in output_texts):
                continue
            status_index = 0 if phase == 3 else 1
            inventory_index = 1 - status_index
            try:
                status_output = json.loads(output_texts[status_index][-1].strip())
                if phase == 3:
                    status_matches = status_output == trace_status_result.get("structured_content")
                else:
                    status_matches = _mcp_results_match(status_output, trace_status_result)
                status_value = trace_status_result.get("structured_content")
                if not isinstance(status_value, dict):
                    continue
                status_projection = _no_progress_status_projection(status_value, trial)
            except (IndexError, json.JSONDecodeError, ValueError, TypeError):
                continue
            if not status_matches or status_projection != expected_status_projection:
                continue
            inventory_text = output_texts[inventory_index][-1].strip()
            if not inventory_text:
                continue
            candidates.append(
                {
                    "path": rollout_path,
                    "sha256": hashlib.sha256(rollout_bytes).hexdigest(),
                    "byte_count": len(rollout_bytes),
                    "turn_id": turn_id,
                    "exec_source_sha256s": [
                        hashlib.sha256(source.encode("utf-8")).hexdigest()
                        for _, source in exec_calls
                    ],
                    "exec_call_ids": [call_id for call_id, _ in exec_calls],
                    "exec_output_sha256s": [
                        hashlib.sha256(
                            json.dumps(
                                outputs[call_id].get("output"),
                                sort_keys=True,
                                separators=(",", ":"),
                            ).encode("utf-8")
                        ).hexdigest()
                        for call_id, _ in exec_calls
                    ],
                    "status_projection": status_projection,
                }
            )
    return candidates


_FINALIZATION_REVIEW_EXEC_SOURCE = (
    'text(ALL_TOOLS.find(x=>x.name==="mcp__rob2__review_trial")?.description);\n'
)
_FINALIZATION_REVIEW_EXEC_SOURCE_SHA256 = (
    "f17821a2a605a92e648d1587951a78b73522913ee8deb9b3d9a4543659a5fbee"
)


def _finalization_no_progress_trace_audit(
    trace: bytes, expected_session: str
) -> dict[str, object] | None:
    """Accept only the retained Phase 4 completed turn with no tool calls."""

    try:
        events = [json.loads(line) for line in trace.decode("utf-8").splitlines()]
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not events or not all(isinstance(event, dict) for event in events):
        return None
    state = "thread"
    messages: list[str] = []
    message_ids: set[str] = set()
    for event in events:
        event_type = event.get("type")
        if event_type == "thread.started":
            if state != "thread" or event.get("thread_id") != expected_session:
                return None
            state = "turn"
            continue
        if event_type == "turn.started":
            if state != "turn":
                return None
            state = "active"
            continue
        if event_type == "turn.completed":
            if state != "active":
                return None
            state = "finished"
            continue
        if state != "active" or event_type != "item.completed":
            return None
        item = event.get("item")
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("id"), str)
            or item.get("type") != "agent_message"
            or item.get("id") in message_ids
            or not isinstance(item.get("text"), str)
        ):
            return None
        message_ids.add(item["id"])
        messages.append(item["text"])
    if state != "finished" or len(messages) != 2:
        return None
    return {
        "messages": messages,
        "workflow_methods_called": [],
        "read_only_methods_called": [],
    }


def _rollout_finalization_no_progress_candidates(
    codex_home: Path,
    expected_session: str,
    phase_start: datetime,
    phase_finish: datetime,
) -> list[dict[str, object]]:
    """Find one rollout turn with the exact diagnostic exec and no hidden calls."""

    candidates: list[dict[str, object]] = []
    try:
        rollout_paths = sorted(codex_home.rglob("rollout-*.jsonl"))
    except OSError:
        return []
    for rollout_path in rollout_paths:
        try:
            rollout_bytes = rollout_path.read_bytes()
            events = [json.loads(line) for line in rollout_bytes.decode("utf-8").splitlines()]
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        active: dict[str, object] | None = None
        turns: list[tuple[str, datetime, datetime, list[dict[str, object]]]] = []
        for event in events:
            if not isinstance(event, dict):
                continue
            payload = event.get("payload")
            if not isinstance(payload, dict) or event.get("type") != "event_msg":
                if active is not None:
                    active["events"].append(event)
                continue
            payload_type = payload.get("type")
            if payload_type == "task_started":
                try:
                    started_at = _parse_aware_datetime(event.get("timestamp"))
                except ValueError:
                    active = None
                    continue
                turn_id = payload.get("turn_id")
                if not isinstance(turn_id, str) or not turn_id:
                    active = None
                    continue
                active = {"turn_id": turn_id, "started_at": started_at, "events": [event]}
                continue
            if active is None:
                continue
            active["events"].append(event)
            if payload_type == "task_complete" and payload.get("turn_id") == active["turn_id"]:
                try:
                    finished_at = _parse_aware_datetime(event.get("timestamp"))
                except ValueError:
                    active = None
                    continue
                turns.append((active["turn_id"], active["started_at"], finished_at, active["events"]))
                active = None
        for turn_id, started_at, finished_at, turn_events in turns:
            if not (phase_start <= started_at <= finished_at <= phase_finish):
                continue
            thread_ids = {
                event.get("payload", {}).get("thread_id")
                for event in turn_events
                if isinstance(event.get("payload"), dict)
                and isinstance(event["payload"].get("thread_id"), str)
            }
            if thread_ids != {expected_session}:
                continue
            exec_calls: list[tuple[str, str]] = []
            exec_outputs: dict[str, object] = {}
            hidden_call = False
            for event in turn_events:
                if event.get("type") == "token_usage_record":
                    continue
                payload = event.get("payload")
                if not isinstance(payload, dict):
                    continue
                payload_type = payload.get("type")
                if payload_type in {"function_call", "function_call_output", "item_started", "command_execution"}:
                    hidden_call = True
                    break
                if payload_type == "custom_tool_call":
                    call_id, source = payload.get("call_id"), payload.get("input")
                    if (
                        payload.get("name") != "exec"
                        or payload.get("status") not in {None, "completed"}
                        or not isinstance(call_id, str)
                        or not isinstance(source, str)
                        or source != _FINALIZATION_REVIEW_EXEC_SOURCE
                    ):
                        hidden_call = True
                        break
                    exec_calls.append((call_id, source))
                    continue
                if payload_type == "custom_tool_call_output":
                    call_id = payload.get("call_id")
                    if not isinstance(call_id, str) or call_id in exec_outputs:
                        hidden_call = True
                        break
                    exec_outputs[call_id] = payload
                    continue
                if payload_type == "item_completed":
                    item = payload.get("item")
                    if not isinstance(item, dict) or item.get("type") not in {
                        "UserMessage",
                        "AgentMessage",
                        "Reasoning",
                        "ContextCompaction",
                    }:
                        hidden_call = True
                        break
                    continue
                if payload_type in {"task_started", "task_complete", "token_count"}:
                    continue
                if event.get("type") == "turn_context" or payload_type in {
                    "message",
                    "reasoning",
                    "token_usage_record",
                }:
                    continue
                hidden_call = True
                break
            if (
                hidden_call
                or len(exec_calls) != 1
                or set(exec_outputs) != {exec_calls[0][0]}
                or hashlib.sha256(exec_calls[0][1].encode("utf-8")).hexdigest()
                != _FINALIZATION_REVIEW_EXEC_SOURCE_SHA256
            ):
                continue
            output_payload = exec_outputs[exec_calls[0][0]]
            if not isinstance(output_payload.get("output"), list) or not output_payload["output"]:
                continue
            candidates.append(
                {
                    "path": rollout_path,
                    "sha256": hashlib.sha256(rollout_bytes).hexdigest(),
                    "byte_count": len(rollout_bytes),
                    "turn_id": turn_id,
                    "started_at": started_at.isoformat(),
                    "finished_at": finished_at.isoformat(),
                    "exec_source_sha256": _FINALIZATION_REVIEW_EXEC_SOURCE_SHA256,
                    "exec_call_id": exec_calls[0][0],
                    "exec_output_sha256": hashlib.sha256(
                        json.dumps(
                            output_payload["output"],
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    ).hexdigest(),
                }
            )
    return candidates


def audited_no_progress_continuation_diagnosis(
    run_dir: Path, phase: int
) -> dict[str, str] | None:
    """Validate the separate audited Phase 3 no-progress continuation path."""

    def blocked(code: str, detail: str) -> dict[str, str]:
        return {
            "code": code,
            "detail": detail,
            "recovery": "Retain Phase 3 as failed infrastructure and inspect the audit evidence.",
        }

    if phase != 3:
        return blocked(
            "no_progress_phase_unsupported",
            "The audited no-progress continuation is defined only for the retained Phase 3 trace.",
        )
    try:
        execution = json.loads((run_dir / "execution.json").read_text(encoding="utf-8"))
        run_inputs = json.loads((run_dir / "run-inputs.json").read_text(encoding="utf-8"))
        phase_meta = json.loads((run_dir / "phase-3.meta.json").read_text(encoding="utf-8"))
        trace = (run_dir / "phase-3.jsonl").read_bytes()
        phase_2_trace = (run_dir / "phase-2.jsonl").read_bytes()
    except (OSError, json.JSONDecodeError) as error:
        return blocked("no_progress_inputs_unavailable", str(error))
    if not all(isinstance(value, dict) for value in (execution, run_inputs, phase_meta)):
        return blocked("no_progress_inputs_malformed", "No-progress audit inputs must be JSON objects.")
    phases = execution.get("phases")
    phase_rows = {
        row.get("phase"): row
        for row in phases
        if isinstance(row, dict) and isinstance(row.get("phase"), int)
    } if isinstance(phases, list) else {}
    failed = phase_rows.get(3)
    scientific = phase_rows.get(2)
    session = failed.get("codex_session_id") if isinstance(failed, dict) else None
    trace_sha256 = hashlib.sha256(trace).hexdigest()
    runtime = execution.get("runtime_inputs")
    runtime_sha256 = (
        hashlib.sha256(json.dumps(runtime, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        if isinstance(runtime, dict)
        else None
    )
    phase_runtime = failed.get("runtime_inputs") if isinstance(failed, dict) else None
    phase_runtime_sha256 = (
        hashlib.sha256(
            json.dumps(phase_runtime, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if isinstance(phase_runtime, dict)
        else None
    )
    expected_result = run_inputs.get("expected_result")
    expected_result_sha256 = (
        hashlib.sha256(
            json.dumps(expected_result, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if isinstance(expected_result, dict)
        else None
    )
    phase_diagnosis = phase_meta.get("host_delivery_diagnosis")
    if (
        execution.get("state") != "failed_infrastructure"
        or not isinstance(failed, dict)
        or failed.get("state") != "failed_infrastructure"
        or failed.get("exit_code") != 75
        or failed.get("trace_sha256") != trace_sha256
        or phase_meta.get("phase") != 3
        or phase_meta.get("execution_state") != "failed_infrastructure"
        or phase_meta.get("exit_code") != 75
        or phase_meta.get("codex_exit_code") != 0
        or phase_meta.get("trace_sha256") != trace_sha256
        or failed.get("runtime_inputs_sha256") != phase_runtime_sha256
        or phase_meta.get("runtime_inputs") != phase_runtime
        or phase_meta.get("runtime_inputs_sha256") != phase_runtime_sha256
        or execution.get("runtime_inputs_sha256") != runtime_sha256
        or failed.get("expected_result_sha256") != expected_result_sha256
        or not isinstance(session, str)
        or not session
        or failed.get("codex_session_id") != execution.get("codex_session_id")
        or phase_meta.get("codex_session_id") != session
        or phase_meta.get("session") != session
        or not isinstance(scientific, dict)
        or scientific.get("state") not in {"resumable", "waiting_for_user"}
        or scientific.get("exit_code") != 0
        or scientific.get("codex_session_id") != session
        or not isinstance(phase_diagnosis, dict)
        or phase_diagnosis.get("code") != "host_delivery_call_missing"
    ):
        return blocked("no_progress_binding_mismatch", "Phase 3 is not the retained audited no-progress failure.")
    if trace_session_ids(run_dir / "phase-3.jsonl") != (session,):
        return blocked("no_progress_session_mismatch", "Phase 3 trace belongs to another Codex session.")
    if not isinstance(runtime, dict) or runtime_sha256 != execution.get("runtime_inputs_sha256"):
        return blocked("no_progress_runtime_missing", "The current Codex runtime binding is unavailable.")
    if not isinstance(phase_runtime, dict) or not isinstance(phase_runtime.get("codex_home_path"), str):
        return blocked("no_progress_runtime_missing", "The frozen Codex runtime binding is unavailable.")
    try:
        phase_start = _parse_aware_datetime(failed["started_at"])
        phase_finish = _parse_aware_datetime(failed["finished_at"])
    except (KeyError, ValueError):
        return blocked("no_progress_turn_unbound", "Phase 3 timestamps are unavailable or invalid.")
    trace_audit = _no_progress_trace_audit(trace, session, str(run_inputs.get("trial", "")))
    if trace_audit is None:
        return blocked(
            "no_progress_trace_invalid",
            "Phase 3 is not exactly one completed turn containing only the approved read-only diagnostics.",
        )
    try:
        current_status = subprocess.run(
            [
                str(phase_runtime["codex_registered_mcp"]["command"]),
                "status",
                "--workspace",
                str(run_dir / "workspace"),
            ],
            capture_output=True,
            check=False,
            timeout=30,
        )
        status_data = json.loads(current_status.stdout) if current_status.returncode == 0 else None
        status_projection = _no_progress_status_projection(status_data, str(run_inputs["trial"]))
    except (KeyError, OSError, subprocess.TimeoutExpired, json.JSONDecodeError, ValueError, TypeError):
        return blocked("no_progress_status_unavailable", "Current workspace status is unavailable.")
    if status_projection != trace_audit["status_projection"]:
        return blocked("no_progress_status_changed", "Workspace state or revision changed after Phase 3.")
    try:
        codex_home = Path(str(phase_runtime["codex_home_path"])).resolve(strict=True)
    except (OSError, RuntimeError):
        return blocked("no_progress_rollout_missing", "The private Codex rollout directory is unavailable.")
    candidates = _rollout_no_progress_candidates(
        codex_home,
        session,
        phase_start,
        phase_finish,
        trace_audit["mcp_calls"],
        trace_audit["status_projection"],
        str(run_inputs["trial"]),
    )
    if len(candidates) != 1:
        return blocked("no_progress_rollout_mismatch", "The Phase 3 trace does not bind to exactly one audited rollout turn.")
    approved_scope_path = run_dir / "approved-scope.json"
    try:
        approved_scope = json.loads(approved_scope_path.read_text(encoding="utf-8"))
        from prepare_rsi_workspace import approved_scope_record

        canonical_scope = approved_scope_record(run_dir / "workspace", run_inputs.get("approved_scope"))
    except (ImportError, OSError, ValueError, json.JSONDecodeError):
        return blocked("no_progress_approval_missing", "Approved scope is unavailable.")
    if canonical_scope is None or approved_scope != canonical_scope:
        return blocked("no_progress_approval_mismatch", "The approved scope changed after Phase 3.")
    phase2_hash = scientific.get("trace_sha256")
    if not isinstance(phase2_hash, str) or hashlib.sha256(phase_2_trace).hexdigest() != phase2_hash:
        return blocked("no_progress_prior_work_unbound", "Completed prior scientific work is not hash-bound.")
    return None


def audited_status_only_no_progress_continuation_diagnosis(
    run_dir: Path, phase: int
) -> dict[str, str] | None:
    """Validate the separate status-only no-progress continuation path."""

    def blocked(code: str, detail: str) -> dict[str, str]:
        return {
            "code": code,
            "detail": detail,
            "recovery": "Retain the failed status-only phase and inspect its bound rollout evidence.",
        }

    if phase != 3:
        return blocked("status_only_phase_unsupported", "The status-only audit is defined for Phase 3 only.")
    try:
        execution = json.loads((run_dir / "execution.json").read_text(encoding="utf-8"))
        run_inputs = json.loads((run_dir / "run-inputs.json").read_text(encoding="utf-8"))
        phase_meta = json.loads((run_dir / "phase-3.meta.json").read_text(encoding="utf-8"))
        trace = (run_dir / "phase-3.jsonl").read_bytes()
        phase_2_trace = (run_dir / "phase-2.jsonl").read_bytes()
    except (OSError, json.JSONDecodeError) as error:
        return blocked("status_only_inputs_unavailable", str(error))
    if not all(isinstance(value, dict) for value in (execution, run_inputs, phase_meta)):
        return blocked("status_only_inputs_malformed", "Status-only audit inputs must be JSON objects.")
    phases = execution.get("phases")
    phase_rows = {
        row.get("phase"): row
        for row in phases
        if isinstance(row, dict) and isinstance(row.get("phase"), int)
    } if isinstance(phases, list) else {}
    failed = phase_rows.get(3)
    scientific = phase_rows.get(2)
    session = failed.get("codex_session_id") if isinstance(failed, dict) else None
    runtime = execution.get("runtime_inputs")
    runtime_sha256 = (
        hashlib.sha256(json.dumps(runtime, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        if isinstance(runtime, dict)
        else None
    )
    phase_runtime = failed.get("runtime_inputs") if isinstance(failed, dict) else None
    phase_runtime_sha256 = (
        hashlib.sha256(
            json.dumps(phase_runtime, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if isinstance(phase_runtime, dict)
        else None
    )
    run_input_sha256 = hashlib.sha256(
        json.dumps(run_inputs, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    expected_result = run_inputs.get("expected_result")
    expected_result_sha256 = (
        hashlib.sha256(json.dumps(expected_result, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        if isinstance(expected_result, dict)
        else None
    )
    trace_sha256 = hashlib.sha256(trace).hexdigest()
    phase_diagnosis = phase_meta.get("host_delivery_diagnosis")
    if (
        execution.get("state") != "failed_infrastructure"
        or not isinstance(failed, dict)
        or failed.get("state") != "failed_infrastructure"
        or failed.get("exit_code") != 75
        or failed.get("trace_sha256") != trace_sha256
        or phase_meta.get("phase") != 3
        or phase_meta.get("execution_state") != "failed_infrastructure"
        or phase_meta.get("exit_code") != 75
        or phase_meta.get("codex_exit_code") != 0
        or phase_meta.get("trace_sha256") != trace_sha256
        or execution.get("run_input_sha256") != run_input_sha256
        or phase_meta.get("run_inputs_sha256") != run_input_sha256
        or failed.get("runtime_inputs_sha256") != phase_runtime_sha256
        or phase_meta.get("runtime_inputs") != phase_runtime
        or phase_meta.get("runtime_inputs_sha256") != phase_runtime_sha256
        or execution.get("runtime_inputs_sha256") != runtime_sha256
        or failed.get("expected_result_sha256") != expected_result_sha256
        or execution.get("expected_result_sha256") != expected_result_sha256
        or not isinstance(session, str)
        or not session
        or failed.get("codex_session_id") != execution.get("codex_session_id")
        or phase_meta.get("codex_session_id") != session
        or phase_meta.get("session") != session
        or not isinstance(scientific, dict)
        or scientific.get("state") not in {"resumable", "waiting_for_user"}
        or scientific.get("exit_code") != 0
        or scientific.get("codex_session_id") != session
        or not isinstance(phase_diagnosis, dict)
        or phase_diagnosis.get("code") != "host_delivery_call_missing"
    ):
        return blocked("status_only_binding_mismatch", "Phase 3 is not the retained status-only failure.")
    if (
        not isinstance(runtime, dict)
        or runtime_sha256 != execution.get("runtime_inputs_sha256")
        or not isinstance(phase_runtime, dict)
        or not isinstance(phase_runtime.get("codex_home_path"), str)
    ):
        return blocked("status_only_runtime_missing", "The frozen Codex runtime binding is unavailable.")
    if trace_session_ids(run_dir / "phase-3.jsonl") != (session,):
        return blocked("status_only_session_mismatch", "Phase 3 trace belongs to another Codex session.")
    trace_audit = _status_only_no_progress_trace_audit(trace, session, str(run_inputs.get("trial", "")))
    if trace_audit is None:
        return blocked("status_only_trace_invalid", "Phase 3 is not exactly one successful get_status turn.")
    try:
        current_status = subprocess.run(
            [
                str(phase_runtime["codex_registered_mcp"]["command"]),
                "status",
                "--workspace",
                str(run_dir / "workspace"),
            ],
            capture_output=True,
            check=False,
            timeout=30,
        )
        status_data = json.loads(current_status.stdout) if current_status.returncode == 0 else None
        status_projection = _no_progress_status_projection(status_data, str(run_inputs["trial"]))
    except (KeyError, OSError, subprocess.TimeoutExpired, json.JSONDecodeError, ValueError, TypeError):
        return blocked("status_only_status_unavailable", "Current workspace status is unavailable.")
    if status_projection != trace_audit["status_projection"]:
        return blocked("status_only_status_changed", "Workspace state or revision changed after Phase 3.")
    try:
        phase_start = _parse_aware_datetime(failed["started_at"])
        phase_finish = _parse_aware_datetime(failed["finished_at"])
        codex_home = Path(str(phase_runtime["codex_home_path"])).resolve(strict=True)
    except (KeyError, OSError, RuntimeError, ValueError):
        return blocked("status_only_rollout_missing", "The frozen Codex rollout binding is unavailable.")
    rollout_candidates = _rollout_status_only_candidates(
        codex_home,
        session,
        phase_start,
        phase_finish,
        phase=3,
        trial=str(run_inputs["trial"]),
        trace_status_result=trace_audit["status_result"],
        expected_status_projection=trace_audit["status_projection"],
    )
    if len(rollout_candidates) != 1 or rollout_candidates[0].get("status_projection") != status_projection:
        return blocked(
            "status_only_rollout_mismatch",
            "The status-only trace does not bind to one rollout turn without hidden calls.",
        )
    approved_scope_path = run_dir / "approved-scope.json"
    try:
        approved_scope = json.loads(approved_scope_path.read_text(encoding="utf-8"))
        from prepare_rsi_workspace import approved_scope_record

        canonical_scope = approved_scope_record(run_dir / "workspace", run_inputs.get("approved_scope"))
    except (ImportError, OSError, ValueError, json.JSONDecodeError):
        return blocked("status_only_approval_missing", "Approved scope is unavailable.")
    if canonical_scope is None or approved_scope != canonical_scope:
        return blocked("status_only_approval_mismatch", "The approved scope changed after Phase 3.")
    phase2_hash = scientific.get("trace_sha256")
    if not isinstance(phase2_hash, str) or hashlib.sha256(phase_2_trace).hexdigest() != phase2_hash:
        return blocked("status_only_prior_work_unbound", "Completed prior scientific work is not hash-bound.")
    return None


def _finalization_no_progress_continuation_guard(
    run_dir: Path,
) -> tuple[dict[str, object] | None, tuple[str, str] | None]:
    def blocked(code: str, detail: str) -> tuple[None, tuple[str, str]]:
        return None, (code, detail)

    try:
        execution = json.loads((run_dir / "execution.json").read_text(encoding="utf-8"))
        run_inputs = json.loads((run_dir / "run-inputs.json").read_text(encoding="utf-8"))
        phase_3_meta = json.loads((run_dir / "phase-3.meta.json").read_text(encoding="utf-8"))
        phase_4_meta = json.loads((run_dir / "phase-4.meta.json").read_text(encoding="utf-8"))
        phase_3_trace = (run_dir / "phase-3.jsonl").read_bytes()
        phase_4_trace = (run_dir / "phase-4.jsonl").read_bytes()
    except (OSError, json.JSONDecodeError) as error:
        return blocked("finalization_no_progress_inputs_unavailable", str(error))
    if not all(
        isinstance(value, dict)
        for value in (execution, run_inputs, phase_3_meta, phase_4_meta)
    ):
        return blocked(
            "finalization_no_progress_inputs_malformed",
            "Finalization no-progress audit inputs must be JSON objects.",
        )
    phases = execution.get("phases")
    phase_rows = {
        row.get("phase"): row
        for row in phases
        if isinstance(row, dict) and isinstance(row.get("phase"), int)
    } if isinstance(phases, list) else {}
    phase_3 = phase_rows.get(3)
    phase_4 = phase_rows.get(4)
    if not isinstance(phase_3, dict) or not isinstance(phase_4, dict):
        return blocked(
            "finalization_no_progress_phase_unbound",
            "The retained Phase 3 and Phase 4 rows are unavailable.",
        )
    phase_3_runtime = phase_3.get("runtime_inputs")
    phase_4_runtime = phase_4.get("runtime_inputs")
    current_runtime = execution.get("runtime_inputs")
    phase_3_runtime_sha256 = (
        hashlib.sha256(
            json.dumps(phase_3_runtime, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if isinstance(phase_3_runtime, dict)
        else None
    )
    phase_4_runtime_sha256 = (
        hashlib.sha256(
            json.dumps(phase_4_runtime, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if isinstance(phase_4_runtime, dict)
        else None
    )
    current_runtime_sha256 = (
        hashlib.sha256(
            json.dumps(current_runtime, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if isinstance(current_runtime, dict)
        else None
    )
    trace_sha256 = hashlib.sha256(phase_4_trace).hexdigest()
    run_inputs_sha256 = hashlib.sha256(
        json.dumps(run_inputs, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    expected_result = run_inputs.get("expected_result")
    expected_result_sha256 = (
        hashlib.sha256(
            json.dumps(expected_result, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if isinstance(expected_result, dict)
        else None
    )
    session = phase_4.get("codex_session_id")
    transition = phase_4.get("runtime_transition")
    phase_4_diagnosis = phase_4_meta.get("host_delivery_diagnosis")
    if (
        execution.get("state") != "failed_infrastructure"
        or phase_3.get("state") != "failed_infrastructure"
        or phase_4.get("state") != "failed_infrastructure"
        or phase_4.get("exit_code") != 75
        or phase_4.get("trace_sha256") != trace_sha256
        or phase_4_meta.get("phase") != 4
        or phase_4_meta.get("execution_state") != "failed_infrastructure"
        or phase_4_meta.get("exit_code") != 75
        or phase_4_meta.get("codex_exit_code") != 0
        or phase_4_meta.get("trace_sha256") != trace_sha256
        or execution.get("run_input_sha256") != run_inputs_sha256
        or phase_4_meta.get("run_inputs_sha256") != run_inputs_sha256
        or phase_4.get("expected_result_sha256") != expected_result_sha256
        or not isinstance(session, str)
        or not session
        or phase_3.get("codex_session_id") != session
        or phase_4_meta.get("codex_session_id") != session
        or phase_4_meta.get("session") != session
        or execution.get("codex_session_id") != session
        or not isinstance(phase_4_diagnosis, dict)
        or phase_4_diagnosis.get("code") != "host_delivery_call_missing"
        or not isinstance(phase_3_runtime, dict)
        or phase_3.get("runtime_inputs_sha256") != phase_3_runtime_sha256
        or phase_3_meta.get("runtime_inputs") != phase_3_runtime
        or phase_3_meta.get("runtime_inputs_sha256") != phase_3_runtime_sha256
        or not isinstance(phase_4_runtime, dict)
        or phase_4.get("runtime_inputs_sha256") != phase_4_runtime_sha256
        or phase_4_meta.get("runtime_inputs") != phase_4_runtime
        or phase_4_meta.get("runtime_inputs_sha256") != phase_4_runtime_sha256
        or not isinstance(current_runtime, dict)
        or current_runtime != phase_4_runtime
        or execution.get("runtime_inputs_sha256") != current_runtime_sha256
        or current_runtime_sha256 != phase_4_runtime_sha256
        or not isinstance(transition, dict)
        or phase_4_meta.get("runtime_transition") != transition
    ):
        return blocked(
            "finalization_no_progress_binding_mismatch",
            "Phase 4 is not the retained finalization no-progress failure.",
        )
    try:
        expected_transition = _execution_build_transition(
            {"runtime_inputs": phase_3_runtime, "runtime_inputs_sha256": phase_3_runtime_sha256},
            {"runtime_inputs": phase_4_runtime, "runtime_inputs_sha256": phase_4_runtime_sha256},
        )
    except ValueError as error:
        return blocked("finalization_no_progress_transition_invalid", str(error))
    if (
        expected_transition is None
        or transition.get("kind") != "build_sha256_only"
        or transition.get("old_build_sha256") != phase_3_runtime.get("build_sha256")
        or transition.get("new_build_sha256") != phase_4_runtime.get("build_sha256")
        or transition.get("prior_phase_runtime_inputs_sha256") != phase_3_runtime_sha256
        or transition.get("prior_runtime_inputs_sha256") != phase_3_runtime_sha256
        or transition.get("new_runtime_inputs_sha256") != phase_4_runtime_sha256
        or expected_transition.get("from_build_sha256") != transition.get("old_build_sha256")
        or expected_transition.get("to_build_sha256") != transition.get("new_build_sha256")
    ):
        return blocked(
            "finalization_no_progress_transition_invalid",
            "Phase 4 is not bound to the recorded build-only transition from Phase 3.",
        )
    if trace_session_ids(run_dir / "phase-4.jsonl") != (session,):
        return blocked(
            "finalization_no_progress_session_mismatch",
            "Phase 4 trace belongs to another Codex session.",
        )
    phase_4_trace_audit = _finalization_no_progress_trace_audit(phase_4_trace, session)
    if phase_4_trace_audit is None:
        phase_4_trace_audit = _status_only_no_progress_trace_audit(
            phase_4_trace, session, str(run_inputs.get("trial", ""))
        )
    if phase_4_trace_audit is None:
        return blocked(
            "finalization_no_progress_trace_invalid",
            "Phase 4 is not an audited completed read-only turn.",
        )
    phase_3_recovery = audited_no_progress_continuation_diagnosis(run_dir, 3)
    if isinstance(phase_3_recovery, dict) and phase_3_recovery.get("code") == "no_progress_trace_invalid":
        phase_3_recovery = audited_status_only_no_progress_continuation_diagnosis(run_dir, 3)
    if phase_3_recovery is not None:
        return blocked(
            "finalization_no_progress_phase3_audit_invalid",
            str(phase_3_recovery.get("detail", "Phase 3 no-progress audit failed.")),
        )
    phase_3_audit = _no_progress_trace_audit(
        phase_3_trace, session, str(run_inputs.get("trial", ""))
    ) or _status_only_no_progress_trace_audit(
        phase_3_trace, session, str(run_inputs.get("trial", ""))
    )
    if phase_3_audit is None:
        return blocked(
            "finalization_no_progress_phase3_audit_invalid",
            "Phase 3 has no recoverable status projection.",
        )
    if not isinstance(phase_4_runtime.get("codex_registered_mcp"), dict):
        return blocked(
            "finalization_no_progress_runtime_missing",
            "The Phase 4 Codex runtime binding is unavailable.",
        )
    try:
        phase_start = _parse_aware_datetime(phase_4["started_at"])
        phase_finish = _parse_aware_datetime(phase_4["finished_at"])
        status = subprocess.run(
            [
                str(phase_4_runtime["codex_registered_mcp"]["command"]),
                "status",
                "--workspace",
                str(run_dir / "workspace"),
            ],
            capture_output=True,
            check=False,
            timeout=30,
        )
        status_data = json.loads(status.stdout) if status.returncode == 0 else None
        status_projection = _no_progress_status_projection(status_data, str(run_inputs["trial"]))
    except (KeyError, OSError, subprocess.TimeoutExpired, json.JSONDecodeError, ValueError, TypeError):
        return blocked(
            "finalization_no_progress_status_unavailable",
            "Current workspace status is unavailable.",
        )
    if status_projection != phase_3_audit["status_projection"]:
        return blocked(
            "finalization_no_progress_status_changed",
            "Workspace state or revision changed after Phase 3.",
        )
    if (
        phase_4_trace_audit.get("status_projection") is not None
        and phase_4_trace_audit["status_projection"] != status_projection
    ):
        return blocked(
            "finalization_no_progress_trace_status_mismatch",
            "Phase 4 raw status differs from the unchanged workspace status.",
        )
    try:
        codex_home = Path(str(phase_4_runtime["codex_home_path"])).resolve(strict=True)
    except (KeyError, OSError, RuntimeError):
        return blocked(
            "finalization_no_progress_rollout_missing",
            "The private Codex rollout directory is unavailable.",
        )
    if phase_4_trace_audit.get("workflow_methods_called") == ["get_status"]:
        candidates = _rollout_status_only_candidates(
            codex_home,
            session,
            phase_start,
            phase_finish,
            phase=4,
            trial=str(run_inputs["trial"]),
            trace_status_result=phase_4_trace_audit["status_result"],
            expected_status_projection=status_projection,
        )
    else:
        candidates = _rollout_finalization_no_progress_candidates(
            codex_home, session, phase_start, phase_finish
        )
    if len(candidates) != 1:
        return blocked(
            "finalization_no_progress_rollout_mismatch",
            "Phase 4 does not bind to exactly one audited diagnostic rollout turn.",
        )
    approved_scope_path = run_dir / "approved-scope.json"
    try:
        approved_scope = json.loads(approved_scope_path.read_text(encoding="utf-8"))
        from prepare_rsi_workspace import approved_scope_record

        canonical_scope = approved_scope_record(run_dir / "workspace", run_inputs.get("approved_scope"))
    except (ImportError, OSError, ValueError, json.JSONDecodeError):
        return blocked(
            "finalization_no_progress_approval_missing",
            "Approved scope is unavailable.",
        )
    if canonical_scope is None or approved_scope != canonical_scope:
        return blocked(
            "finalization_no_progress_approval_mismatch",
            "The approved scope changed after Phase 3.",
        )
    return {
        "phase": 4,
        "codex_session_id": session,
        "trace_sha256": trace_sha256,
        "phase_started_at": phase_4["started_at"],
        "phase_finished_at": phase_4["finished_at"],
        "status_projection": status_projection,
        "runtime_inputs_sha256": phase_4_runtime_sha256,
        "runtime_transition": transition,
        "rollout": candidates[0],
        "trace_audit": phase_4_trace_audit,
    }, None


def finalization_no_progress_continuation_audit(
    run_dir: Path,
) -> dict[str, object] | None:
    """Return the bound Phase 4 no-progress evidence when the guard passes."""

    evidence, _ = _finalization_no_progress_continuation_guard(run_dir)
    return evidence


def audited_finalization_no_progress_continuation_diagnosis(
    run_dir: Path, phase: int
) -> dict[str, str] | None:
    """Validate the narrow Phase 4 finalization no-progress continuation path."""

    if phase != 4:
        return {
            "code": "finalization_no_progress_phase_unsupported",
            "detail": "The finalization no-progress audit is defined only for Phase 4.",
            "recovery": "Retain Phase 4 as failed infrastructure and inspect the audit evidence.",
        }
    _, failure = _finalization_no_progress_continuation_guard(run_dir)
    if failure is None:
        return None
    code, detail = failure
    return {
        "code": code,
        "detail": detail,
        "recovery": "Retain Phase 4 as failed infrastructure and inspect the audit evidence.",
    }


def _parse_aware_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be text")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed


def _read_only_codex_tool_counts(trace: bytes, expected_session: str) -> dict[str, int] | None:
    allowed_tools = {"list_mcp_resources", "list_mcp_resource_templates"}
    state = "thread"
    seen_item_ids: set[str] = set()
    pending_calls: dict[str, str] = {}
    counts: dict[str, int] = {}
    try:
        lines = trace.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return None
    for line in lines:
        if not line.strip():
            return None
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return None
        if not isinstance(event, dict):
            return None
        event_type = event.get("type")
        if state == "finished":
            return None
        if event_type == "thread.started":
            if state != "thread" or event.get("thread_id") != expected_session:
                return None
            state = "turn"
        elif event_type == "turn.started":
            if state != "turn":
                return None
            state = "active"
        elif event_type == "turn.completed":
            if state != "active" or pending_calls:
                return None
            state = "finished"
        elif event_type in {"item.started", "item.completed"}:
            item = event.get("item")
            if state != "active" or not isinstance(item, dict):
                return None
            item_id = item.get("id")
            if not isinstance(item_id, str) or not item_id:
                return None
            item_type = item.get("type")
            if item_type == "agent_message":
                if (
                    event_type != "item.completed"
                    or item_id in seen_item_ids
                    or not isinstance(item.get("text"), str)
                ):
                    return None
                seen_item_ids.add(item_id)
                continue
            tool = item.get("tool")
            if (
                item_type != "mcp_tool_call"
                or item.get("server") != "codex"
                or not isinstance(tool, str)
                or tool not in allowed_tools
                or item.get("arguments") != {}
                or item.get("error") is not None
            ):
                return None
            if event_type == "item.started":
                if (
                    item_id in seen_item_ids
                    or item.get("status") != "in_progress"
                    or item.get("result") is not None
                ):
                    return None
                seen_item_ids.add(item_id)
                pending_calls[item_id] = tool
            else:
                if (
                    pending_calls.get(item_id) != tool
                    or item.get("status") != "completed"
                    or item.get("result") is None
                ):
                    return None
                pending_calls.pop(item_id)
                counts[tool] = counts.get(tool, 0) + 1
        else:
            return None
    return counts if state == "finished" and not pending_calls else None


def _codex_rollout_proves_rob2_tools_unavailable(
    content: bytes,
    turn_id: str,
    session: str,
    phase_start: datetime,
    phase_finish: datetime,
    campaign_id: object,
    phase_trace_sha256: str,
    phase_resource_counts: dict[str, int],
    run_dir: Path,
    run_inputs: dict[str, object],
) -> str | None:
    try:
        allowlist = json.loads(RECOVERY_EXEC_ALLOWLIST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if (
        not isinstance(allowlist, dict)
        or allowlist.get("schema") != "rob2-kit.codex-recovery-exec-source-allowlist.v1"
        or allowlist.get("campaign_id") != campaign_id
        or isinstance(allowlist.get("turn_count"), bool)
        or allowlist.get("turn_count") != len(allowlist.get("turns", []))
        or not isinstance(allowlist.get("cells"), list)
        or not isinstance(allowlist.get("turns"), list)
    ):
        return None
    matching_turns = [
        row for row in allowlist["turns"]
        if isinstance(row, dict)
        and row.get("turn_id") == turn_id
        and row.get("session_id") == session
        and row.get("trace_sha256") == phase_trace_sha256
    ]
    if len(matching_turns) != 1:
        return None
    turn_record = matching_turns[0]
    case_path = turn_record.get("case")
    case_parts = case_path.split("/") if isinstance(case_path, str) else []
    if (
        not case_parts
        or case_path.startswith("/")
        or "\\" in case_path
        or ":" in case_path
        or any(part in {"", ".", ".."} for part in case_parts)
    ):
        return None
    try:
        run_parts = tuple(part.casefold() for part in run_dir.resolve().parts)
    except (OSError, RuntimeError):
        return None
    case_parts_folded = tuple(part.casefold() for part in case_parts)
    trial = run_inputs.get("trial")
    outcome = run_inputs.get("requested_outcome")
    if (
        len(case_parts_folded) > len(run_parts)
        or run_parts[-len(case_parts_folded) :] != case_parts_folded
        or not isinstance(trial, str)
        or not isinstance(outcome, str)
        or len(case_parts_folded) < 2
        or case_parts_folded[-2:]
        != (outcome.casefold().replace(" ", "-"), trial.casefold())
    ):
        return None
    turn_source_hashes = turn_record.get("exec_source_sha256s")
    if (
        not isinstance(turn_source_hashes, list)
        or not turn_source_hashes
        or not all(isinstance(value, str) for value in turn_source_hashes)
        or len(turn_source_hashes) != len(set(turn_source_hashes))
    ):
        return None
    turn_source_hash_set = set(turn_source_hashes)
    allowed_cells: dict[str, dict[str, object]] = {}
    registry_proof_cells = 0
    for row in allowlist["cells"]:
        source = row.get("source") if isinstance(row, dict) else None
        digest = row.get("sha256") if isinstance(row, dict) else None
        kind = row.get("kind") if isinstance(row, dict) else None
        if (
            not isinstance(source, str)
            or not isinstance(digest, str)
            or hashlib.sha256(source.encode("utf-8")).hexdigest() != digest
            or kind
            not in {
                "missing_rob2_method",
                "inventory_method_lookup",
                "tool_inventory_probe",
                "read_only_mcp_resource_probe",
            }
            or digest in allowed_cells
        ):
            return None
        if row.get("proof") == "rob2_tool_names":
            registry_proof_cells += 1
            if kind != "tool_inventory_probe":
                return None
        allowed_cells[digest] = row
    if registry_proof_cells != 1 or not turn_source_hash_set.issubset(allowed_cells):
        return None
    allowed_cells = {
        digest: allowed_cells[digest]
        for digest in turn_source_hash_set
    }
    if not content.endswith((b"\n", b"\r")):
        return None
    raw_lines = content.splitlines()
    if not raw_lines:
        return None
    try:
        final_event = json.loads(raw_lines[-1])
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    final_payload = final_event.get("payload") if isinstance(final_event, dict) else None
    if not (
        isinstance(final_payload, dict)
        and final_event.get("type") == "event_msg"
        and final_payload.get("type") == "task_complete"
        and final_payload.get("turn_id") == turn_id
    ):
        return None
    inventory_calls: dict[str, dict[str, object]] = {}
    inventory_results: dict[str, set[str] | None] = {}
    method_lookups: dict[str, str] = {}
    resource_calls: set[str] = set()
    resource_methods: dict[str, str] = {}
    direct_calls: dict[str, str] = {}
    direct_errors: set[str] = set()
    call_outputs: set[str] = set()
    exec_source_hashes: set[str] = set()
    session_ids: set[str] = set()
    known_tools = set(public_tool_inventory())

    def text_values(value: object) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, dict):
            if isinstance(value.get("text"), str):
                return [value["text"]]
            return [
                text
                for key, child in value.items()
                if key != "type"
                for text in text_values(child)
            ]
        if isinstance(value, list):
            return [text for child in value for text in text_values(child)]
        return []

    def inventory_names(source: str, output: object) -> set[str] | None:
        texts = text_values(output)
        if not any("Script completed" in text for text in texts):
            return None
        result_texts = [
            text.rsplit("Output:\n", 1)[1] if "Output:\n" in text else text
            for text in texts
        ]
        if any("Warning: truncated output" in text for text in result_texts):
            return None
        for result in result_texts:
            value = result.strip()
            if not value:
                continue
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                if ".join(" in source:
                    return {line.strip() for line in value.splitlines() if line.strip()}
                continue
            if not isinstance(parsed, list):
                continue
            names: set[str] = set()
            for item in parsed:
                if isinstance(item, str):
                    # One observed projection appends a short description after each name.
                    name = item.split(maxsplit=1)[0] if item else ""
                elif isinstance(item, dict) and isinstance(item.get("name"), str):
                    name = item["name"]
                else:
                    return None
                if not name:
                    return None
                names.add(name)
            return names
        return None

    active = False
    started = completed = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    last_event: dict[str, object] | None = None
    for line in content.decode("utf-8", "replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        payload = event.get("payload")
        if event.get("type") == "session_meta" and isinstance(payload, dict):
            for field in ("session_id", "id"):
                value = payload.get(field)
                if isinstance(value, str) and value:
                    session_ids.add(value)
        if isinstance(payload, dict) and event.get("type") == "event_msg":
            if payload.get("type") == "task_started" and active:
                return None
            if payload.get("type") == "task_started" and payload.get("turn_id") == turn_id:
                if active or started:
                    return None
                active = True
                started = 1
                try:
                    started_at = _parse_aware_datetime(event.get("timestamp"))
                except ValueError:
                    return None
            elif payload.get("type") == "task_complete" and active and payload.get("turn_id") != turn_id:
                return None
            elif payload.get("type") == "task_complete" and payload.get("turn_id") == turn_id:
                if not active or completed:
                    return None
                active = False
                completed = 1
                try:
                    completed_at = _parse_aware_datetime(event.get("timestamp"))
                except ValueError:
                    return None
        if not active or not isinstance(payload, dict):
            last_event = event
            continue
        if (
            event.get("type") == "response_item"
            and payload.get("type")
            not in {"message", "reasoning", "custom_tool_call", "custom_tool_call_output"}
        ):
            return None
        call_id = payload.get("call_id")
        if payload.get("type") == "custom_tool_call":
            if (
                event.get("type") != "response_item"
                or payload.get("name") != "exec"
                or not isinstance(call_id, str)
                or not call_id
                or call_id in inventory_calls
                or call_id in method_lookups
                or call_id in resource_calls
                or call_id in direct_calls
            ):
                return None
            input_text = payload.get("input")
            digest = (
                hashlib.sha256(input_text.encode("utf-8")).hexdigest()
                if isinstance(input_text, str)
                else None
            )
            cell = allowed_cells.get(digest) if digest is not None else None
            if not isinstance(cell, dict) or cell.get("source") != input_text:
                return None
            exec_source_hashes.add(digest)
            kind = cell.get("kind")
            if kind == "missing_rob2_method":
                tool_name = cell.get("method")
                if not isinstance(tool_name, str) or tool_name not in known_tools:
                    return None
                direct_calls[call_id] = tool_name
            elif kind == "inventory_method_lookup":
                tool_name = cell.get("method")
                if not isinstance(tool_name, str) or tool_name not in known_tools:
                    return None
                method_lookups[call_id] = tool_name
            elif kind == "tool_inventory_probe":
                inventory_calls[call_id] = cell
            elif kind == "read_only_mcp_resource_probe":
                resource_method = {
                    "resources": "list_mcp_resources",
                    "resource_templates": "list_mcp_resource_templates",
                }.get(cell.get("resource_type"))
                if resource_method is None:
                    return None
                resource_calls.add(call_id)
                resource_methods[call_id] = resource_method
            else:
                return None
        elif payload.get("type") == "custom_tool_call_output":
            if (
                event.get("type") != "response_item"
                or not isinstance(call_id, str)
                or call_id in call_outputs
                or (
                    call_id not in inventory_calls
                    and call_id not in method_lookups
                    and call_id not in resource_calls
                    and call_id not in direct_calls
                )
            ):
                return None
            call_outputs.add(call_id)
            output = payload.get("output")
            texts = text_values(output)
            if call_id in inventory_calls:
                if not any("Script completed" in text for text in texts):
                    return None
                inventory_results[call_id] = inventory_names(
                    inventory_calls[call_id].get("source", ""), output
                )
            elif call_id in method_lookups:
                if not any("Script completed" in text for text in texts):
                    return None
                result_text = "\n".join(
                    text.rsplit("Output:\n", 1)[1] if "Output:\n" in text else text
                    for text in texts
                ).strip()
                if result_text == "undefined":
                    method_lookups[call_id] = "undefined:" + method_lookups[call_id]
                else:
                    # A registry entry with a description is not proof that it is missing.
                    method_lookups[call_id] = "present:" + method_lookups[call_id]
            elif call_id in resource_calls:
                if not any("Script completed" in text for text in texts):
                    return None
            elif call_id in direct_calls:
                expected_error = (
                    "TypeError: tools.mcp__rob2__"
                    + direct_calls[call_id]
                    + " is not a function"
                )
                if any(expected_error in text for text in texts):
                    direct_errors.add(call_id)
                else:
                    return None
        elif payload.get("type") in {"function_call", "function_call_output"}:
            return None
        last_event = event
    if active or started != 1 or completed != 1 or not isinstance(last_event, dict):
        return None
    last_payload = last_event.get("payload")
    if not (
        isinstance(last_payload, dict)
        and last_payload.get("type") == "task_complete"
        and last_payload.get("turn_id") == turn_id
    ):
        return None
    if started_at is None or completed_at is None:
        return None
    if not (phase_start <= started_at <= completed_at <= phase_finish):
        return None
    if session_ids != {session}:
        return None
    expected_call_ids = set(inventory_calls) | set(method_lookups) | resource_calls | set(direct_calls)
    if (
        not expected_call_ids
        or call_outputs != expected_call_ids
        or not inventory_calls
        or exec_source_hashes != turn_source_hash_set
    ):
        return None
    rollout_resource_counts: dict[str, int] = {}
    for tool in resource_methods.values():
        rollout_resource_counts[tool] = rollout_resource_counts.get(tool, 0) + 1
    if phase_resource_counts != rollout_resource_counts:
        return None
    required_workflow_methods = {"get_status", "request_proposal_approval"}
    if (
        direct_calls
        and set(direct_calls) == direct_errors
        and required_workflow_methods.intersection(direct_calls.values())
        and set(turn_record.get("failed_methods", [])) == set(direct_calls.values())
        and turn_record.get("evidence_subtype") == "required_exec_binding_typeerror"
    ):
        return "required_exec_binding_typeerror"
    missing_approval_lookup = any(
        value == "undefined:request_proposal_approval" for value in method_lookups.values()
    )
    empty_registry_inventory = any(
        cell.get("proof") == "rob2_tool_names"
        and inventory_results.get(call_id) == set()
        for call_id, cell in inventory_calls.items()
    )
    if (
        not direct_calls
        and missing_approval_lookup
        and empty_registry_inventory
        and set(turn_record.get("missing_registry_methods", []))
        == {"request_proposal_approval"}
        and turn_record.get("evidence_subtype") == "required_method_missing_from_registry"
    ):
        return "required_method_missing_from_registry"
    return None


def _workspace_status_projection(value: object) -> dict[str, object]:
    if (
        not isinstance(value, dict)
        or value.get("outcome") != "success"
        or value.get("phase") != "assessment"
        or isinstance(value.get("state_revision"), bool)
        or not isinstance(value.get("state_revision"), int)
    ):
        raise ValueError("rob2 status did not succeed")
    continuation = value.get("continuation")
    if (
        not isinstance(continuation, dict)
        or continuation.get("authority") != "host"
        or not isinstance(continuation.get("operation"), str)
        or not continuation.get("operation")
        or not isinstance(continuation.get("trial_id"), str)
        or not continuation.get("trial_id")
        or not isinstance(continuation.get("domain_id"), str)
        or not continuation.get("domain_id")
    ):
        raise ValueError("rob2 status lacks a host assessment continuation")
    return {
        "phase": value.get("phase"),
        "state_revision": value.get("state_revision"),
        "continuation": {
            key: continuation.get(key)
            for key in ("authority", "operation", "trial_id", "domain_id")
        },
    }


def trace_has_rob2_runtime_evidence(path: Path) -> bool:
    """Return whether a trace proves that the rob2 MCP surface was callable."""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        item = event.get("item")
        if (
            event.get("type") == "item.completed"
            and isinstance(item, dict)
            and item.get("type") == "mcp_tool_call"
            and item.get("server") == "rob2"
            and item.get("status") == "completed"
            and item.get("error") is None
            and item.get("result") is not None
        ):
            return True
    return False


def artifact_manifest_identity(path: Path) -> str:
    """Read the content-addressed identity recorded inside a verified bundle."""

    try:
        with zipfile.ZipFile(path) as archive:
            manifest = json.loads(archive.read("manifest.json"))
    except (OSError, KeyError, ValueError, json.JSONDecodeError, zipfile.BadZipFile) as error:
        raise ValueError(f"artifact manifest is unreadable: {path}") from error
    identity = manifest.get("identity") if isinstance(manifest, dict) else None
    if not isinstance(identity, str) or not identity:
        raise ValueError(f"artifact manifest has no identity: {path}")
    return identity


def _reconciliation_read_only_tools() -> set[str]:
    contract = _load_public_contract()
    tools = contract.get("tools")
    if not isinstance(tools, list):
        raise ValueError("public MCP contract has no tool inventory")
    names: set[str] = set()
    for tool in tools:
        if not isinstance(tool, dict) or not isinstance(tool.get("name"), str):
            raise ValueError("public MCP contract contains a malformed tool")
        if tool.get("read_only") is True:
            names.add(tool["name"])
    if not names:
        raise ValueError("public MCP contract has no read-only tools")
    return names


def _reconciliation_trace_audit(path: Path) -> dict[str, object]:
    """Bind finalization and outstanding calls to one immutable Rob2 trace."""

    public_tools = set(public_tool_inventory())
    read_only_tools = _reconciliation_read_only_tools()
    active: dict[str, dict[str, object]] = {}
    started_ids: set[str] = set()
    completed: list[dict[str, object]] = []
    failed: list[dict[str, object]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as error:
        raise ValueError(f"completion reconciliation trace is unavailable: {path}") from error
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        item_id = item.get("id")
        if not isinstance(item_id, str) or item.get("type") != "mcp_tool_call":
            continue
        if item.get("server") != "rob2":
            continue
        tool = item.get("tool")
        if not isinstance(tool, str) or tool not in public_tools:
            raise ValueError(f"trace contains an unadvertised Rob2 tool: {tool!r}")
        event_type = event.get("type")
        if event_type == "item.started":
            if item_id in started_ids or item_id in active:
                raise ValueError(f"trace repeats Rob2 call id: {item_id}")
            started_ids.add(item_id)
            active[item_id] = {"id": item_id, "tool": tool}
            continue
        if event_type not in {"item.completed", "item.failed"}:
            continue
        record = active.pop(item_id, None)
        if record is None:
            raise ValueError(f"trace completes an unstarted Rob2 call: {item_id}")
        record["status"] = "completed" if event_type == "item.completed" else "failed"
        record["item"] = item
        (completed if event_type == "item.completed" else failed).append(record)

    outstanding = sorted(active.values(), key=lambda item: str(item["id"]))
    if any(item["tool"] not in read_only_tools for item in outstanding):
        raise ValueError("trace has an outstanding Rob2 call that is not public read-only")
    finalizations = [
        item
        for item in completed
        if item.get("tool") == "finalize_batch"
        and isinstance(item.get("item"), dict)
        and item["item"].get("status") == "completed"
        and item["item"].get("error") is None
    ]
    if len(finalizations) != 1:
        raise ValueError("trace must contain exactly one successful finalize_batch event")
    finalize_item = finalizations[0]["item"]
    result = finalize_item.get("result")
    structured = result.get("structured_content") if isinstance(result, dict) else None
    head = structured.get("head") if isinstance(structured, dict) else None
    data = structured.get("data") if isinstance(structured, dict) else None
    artifact = data.get("artifact") if isinstance(data, dict) else None
    if (
        not isinstance(structured, dict)
        or structured.get("outcome") != "success"
        or not isinstance(head, dict)
        or head.get("phase") != "finalized"
        or not isinstance(head.get("state_revision"), int)
        or not isinstance(data, dict)
        or not isinstance(artifact, dict)
    ):
        raise ValueError("finalize_batch did not return a finalized artifact")
    workflow_methods = sorted(
        {str(item["tool"]) for item in completed if item["tool"] not in read_only_tools}
    )
    read_only_methods = sorted(
        {str(item["tool"]) for item in completed if item["tool"] in read_only_tools}
    )
    return {
        "workflow_methods_called": workflow_methods,
        "read_only_methods_called": read_only_methods,
        "failed_methods": sorted({str(item["tool"]) for item in failed}),
        "outstanding_calls": [
            {"id": str(item["id"]), "tool": str(item["tool"])} for item in outstanding
        ],
        "finalize_call_id": str(finalize_item["id"]),
        "finalize_artifact": {
            "path": artifact.get("path"),
            "identity": artifact.get("identity"),
            "sha256": artifact.get("sha256"),
        },
        "finalized_state_revision": head.get("state_revision"),
    }


def _reconciliation_hash(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("reconciliation hash is missing")
    return value.removeprefix("sha256:")


def _reconciliation_artifact_path(run_dir: Path, value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("reconciliation artifact path is missing")
    raw = Path(value)
    candidates = [raw] if raw.is_absolute() else [run_dir / raw, run_dir / "workspace" / raw]
    existing = {candidate.resolve() for candidate in candidates if candidate.is_file()}
    if len(existing) != 1:
        raise ValueError(f"reconciliation artifact path is not uniquely resolved: {value}")
    path = next(iter(existing))
    if not path.is_relative_to(run_dir.resolve()) or path.suffix.casefold() != ".zip":
        raise ValueError("reconciliation artifact must be a ZIP inside the run directory")
    return path


def _reconciliation_status_projection(value: object, trial: str) -> dict[str, object]:
    if not isinstance(value, dict) or value.get("outcome") != "success":
        raise ValueError("rob2 status did not succeed")
    phase = value.get("phase")
    revision = value.get("state_revision")
    dispositions = value.get("trial_dispositions")
    counts = value.get("terminal_counts")
    if (
        phase != "finalized"
        or isinstance(revision, bool)
        or not isinstance(revision, int)
        or dispositions != {trial.casefold(): "assessed"}
        or counts != {
            "assessed": 1,
            "failed": 0,
            "needs_input": 0,
            "pending": 0,
            "reviewable": 0,
            "unsupported_design": 0,
        }
        or value.get("conditions") != []
    ):
        raise ValueError("rob2 status does not prove finalized assessed work")
    return {
        "phase": phase,
        "state_revision": revision,
        "trial_dispositions": dispositions,
        "terminal_counts": counts,
        "conditions": [],
    }


def _completion_reconciliation_check(run_dir: Path, phase: int) -> tuple[dict[str, object], Path]:
    run_dir = run_dir.resolve(strict=True)
    try:
        execution = json.loads((run_dir / "execution.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("completion reconciliation requires a valid execution.json") from error
    if not isinstance(execution, dict) or execution.get("schema") != "rob2-kit.rsi-execution.v1":
        raise ValueError("completion reconciliation requires a fresh execution record")
    phase_rows = execution.get("phases")
    phase_row = next(
        (
            row
            for row in phase_rows
            if isinstance(row, dict) and row.get("phase") == phase
        ),
        None,
    ) if isinstance(phase_rows, list) else None
    if not isinstance(phase_row, dict) or phase_row.get("state") != "failed_infrastructure":
        raise ValueError("selected reconciliation phase is not a failed infrastructure execution")
    if execution.get("state") != "failed_infrastructure":
        raise ValueError("execution failure must remain failed_infrastructure")
    attempt_id = phase_row.get("attempt_id")
    session = phase_row.get("codex_session_id")
    if (
        not isinstance(attempt_id, str)
        or attempt_id != execution.get("attempt_id")
        or not isinstance(session, str)
        or session != execution.get("codex_session_id")
    ):
        raise ValueError("execution attempt or session binding is inconsistent")
    trace_path = run_dir / f"phase-{phase}.jsonl"
    trace_bytes = trace_path.read_bytes()
    trace_sha256 = hashlib.sha256(trace_bytes).hexdigest()
    if phase_row.get("trace_sha256") != trace_sha256 or trace_session_ids(trace_path) != (session,):
        raise ValueError("phase trace is not hash-bound to its execution session")
    try:
        phase_meta = json.loads((run_dir / f"phase-{phase}.meta.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("completion reconciliation phase metadata is unavailable") from error
    if (
        not isinstance(phase_meta, dict)
        or phase_meta.get("trace_sha256") != trace_sha256
        or phase_meta.get("codex_session_id") != session
        or phase_meta.get("session") != session
        or phase_meta.get("phase") != phase
        or phase_meta.get("execution_state") != "failed_infrastructure"
        or phase_meta.get("run_inputs_sha256") != execution.get("run_input_sha256")
    ):
        raise ValueError("phase metadata is not bound to the failed execution")
    phase_exit_code = phase_row.get("exit_code")
    delivery_diagnosis = phase_meta.get("host_delivery_diagnosis")
    if (
        phase_exit_code not in {0, 75}
        or phase_meta.get("exit_code") != phase_exit_code
        or phase_meta.get("codex_exit_code") != 0
        or (
            phase_exit_code == 75
            and (
                not isinstance(delivery_diagnosis, dict)
                or delivery_diagnosis.get("code") != "host_delivery_call_missing"
            )
        )
    ):
        raise ValueError("failed execution is not the audited host-delivery interruption")
    runtime = execution.get("runtime_inputs")
    if not isinstance(runtime, dict):
        raise ValueError("execution runtime inputs are missing")
    _execution_condition(execution)
    runtime_hash = hashlib.sha256(
        json.dumps(runtime, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    phase_runtime = phase_row.get("runtime_inputs")
    phase_runtime_hash = hashlib.sha256(
        json.dumps(phase_runtime, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest() if isinstance(phase_runtime, dict) else None
    if (
        execution.get("runtime_inputs_sha256") != runtime_hash
        or phase_row.get("runtime_inputs_sha256") != phase_runtime_hash
        or phase_meta.get("runtime_inputs") != phase_runtime
    ):
        raise ValueError("runtime input hashes are not internally consistent")
    run_inputs_path = run_dir / "run-inputs.json"
    run_inputs = json.loads(run_inputs_path.read_text(encoding="utf-8"))
    if not isinstance(run_inputs, dict):
        raise ValueError("frozen run inputs are malformed")
    run_input_hash = hashlib.sha256(
        json.dumps(run_inputs, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if execution.get("run_input_sha256") != run_input_hash:
        raise ValueError("frozen run inputs do not match execution.json")
    expected_result = run_inputs.get("expected_result")
    expected_result_hash = hashlib.sha256(
        json.dumps(expected_result, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest() if isinstance(expected_result, dict) else None
    if (
        not isinstance(expected_result_hash, str)
        or phase_row.get("expected_result_sha256") != expected_result_hash
        or execution.get("expected_result_sha256") != expected_result_hash
    ):
        raise ValueError("frozen Result scope is not hash-bound")
    benchmark_index = runtime.get("benchmark_index")
    if not isinstance(benchmark_index, dict) or not isinstance(benchmark_index.get("path"), str):
        raise ValueError("frozen benchmark manifest binding is missing")
    index_path = Path(benchmark_index["path"]).resolve(strict=True)
    index_bytes = index_path.read_bytes()
    if hashlib.sha256(index_bytes).hexdigest() != benchmark_index.get("sha256"):
        raise ValueError("frozen benchmark manifest changed")
    index = json.loads(index_bytes)
    if not isinstance(index, dict):
        raise ValueError("frozen benchmark manifest is malformed")
    identity = execution.get("identity")
    if not isinstance(identity, dict):
        raise ValueError("execution identity is missing")
    row = _unique_case(
        index,
        _case_key({"outcome": identity.get("outcome"), "trial": identity.get("trial_id")}),
    )
    _validate_execution_binding(index_path, index, row, execution)
    approved_path = run_dir / "approved-scope.json"
    approved_bytes = approved_path.read_bytes()
    approved_scope = json.loads(approved_bytes)
    from prepare_rsi_workspace import approved_scope_record

    canonical_scope = approved_scope_record(run_dir / "workspace", run_inputs.get("approved_scope"))
    if canonical_scope is None or approved_scope != canonical_scope:
        raise ValueError("approved scope is not bound to current workspace state")
    approved_hash = hashlib.sha256(approved_bytes).hexdigest()
    trace_audit = _reconciliation_trace_audit(trace_path)
    execution_artifact = execution.get("artifact")
    final_artifact = trace_audit["finalize_artifact"]
    if not isinstance(final_artifact, dict):
        raise ValueError("finalize_batch has no artifact receipt")
    if execution_artifact is not None and not isinstance(execution_artifact, dict):
        raise ValueError("failed execution artifact record is malformed")
    artifact_binding = execution_artifact if isinstance(execution_artifact, dict) else final_artifact
    artifact_path = _reconciliation_artifact_path(run_dir, artifact_binding.get("path"))
    zip_candidates = sorted(path.resolve() for path in run_dir.rglob("*.zip") if path.is_file())
    if len(zip_candidates) != 1 or zip_candidates[0] != artifact_path:
        raise ValueError("execution artifact does not match exactly one ZIP")
    artifact_hash = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    artifact_identity = artifact_binding.get("identity")
    if (
        _reconciliation_hash(artifact_binding.get("sha256")) != artifact_hash
        or not isinstance(artifact_identity, str)
        or artifact_manifest_identity(artifact_path) != artifact_identity
    ):
        raise ValueError("execution artifact hash or identity is invalid")
    if (
        not isinstance(final_artifact, dict)
        or _reconciliation_hash(final_artifact.get("sha256")) != artifact_hash
        or final_artifact.get("identity") != artifact_identity
        or _reconciliation_artifact_path(run_dir, final_artifact.get("path")) != artifact_path
    ):
        raise ValueError("finalize_batch artifact does not match execution artifact")
    verifier = runpy.run_path(str(Path(__file__).with_name("verify_bundle.py")))
    verified, verification_message = verifier["verify"](artifact_path)
    if verified is not True:
        raise ValueError(f"independent bundle verification failed: {verification_message}")
    binding = runtime.get("codex_registered_mcp")
    command = binding.get("command") if isinstance(binding, dict) else None
    if not isinstance(command, str) or not command:
        raise ValueError("frozen rob2 status command is missing")
    status_process = subprocess.run(
        [command, "status", "--workspace", str(run_dir / "workspace")],
        capture_output=True,
        check=False,
        timeout=30,
    )
    if status_process.returncode != 0:
        raise ValueError("current rob2 status failed")
    status_projection = _reconciliation_status_projection(
        json.loads(status_process.stdout), str(run_inputs.get("trial", ""))
    )
    record = {
        "schema": COMPLETION_RECONCILIATION_SCHEMA,
        "phase": phase,
        "attempt_id": attempt_id,
        "codex_session_id": session,
        "execution_state": "failed_infrastructure",
        "trace_sha256": trace_sha256,
        "runtime_inputs_sha256": runtime_hash,
        "phase_runtime_inputs_sha256": phase_runtime_hash,
        "run_input_sha256": run_input_hash,
        "expected_result_sha256": expected_result_hash,
        "manifest_sha256": execution.get("manifest_sha256"),
        "approved_scope_sha256": approved_hash,
        "benchmark_index": {
            "path": str(index_path),
            "sha256": benchmark_index.get("sha256"),
            "case_sha256": benchmark_index.get("case_sha256"),
        },
        "identity": identity,
        "artifact": {
            "path": artifact_binding.get("path"),
            "sha256": artifact_hash,
            "identity": artifact_identity,
        },
        "trace_audit": {
            key: trace_audit[key]
            for key in (
                "workflow_methods_called",
                "read_only_methods_called",
                "failed_methods",
                "outstanding_calls",
                "finalize_call_id",
                "finalized_state_revision",
            )
        },
        "status_projection": status_projection,
        "verification": {"verified": True},
        "original_failure": {
            "execution_state": execution.get("state"),
            "child_exit_code": execution.get("child_exit_code"),
            "phase_state": phase_row.get("state"),
            "phase_exit_code": phase_row.get("exit_code"),
            "terminal_reason": phase_meta.get("terminal_reason"),
        },
    }
    return record, artifact_path


def build_completion_reconciliation_sidecar(run_dir: Path, phase: int) -> dict[str, object]:
    """Validate a failed finalized execution and return its separate sidecar payload."""

    record, _ = _completion_reconciliation_check(run_dir, phase)
    return record


def validate_completion_reconciliation(
    run_dir: Path,
) -> tuple[dict[str, object], Path]:
    """Consume only a sidecar that still matches every frozen execution binding."""

    sidecar_path = Path(run_dir) / COMPLETION_RECONCILIATION_FILENAME
    try:
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("completion reconciliation sidecar is missing or invalid") from error
    if not isinstance(sidecar, dict):
        raise ValueError("completion reconciliation sidecar is malformed")
    phase = sidecar.get("phase")
    if isinstance(phase, bool) or not isinstance(phase, int):
        raise ValueError("completion reconciliation sidecar phase is malformed")
    expected, artifact_path = _completion_reconciliation_check(Path(run_dir), phase)
    if sidecar != expected:
        raise ValueError("completion reconciliation sidecar no longer matches its evidence")
    return sidecar, artifact_path

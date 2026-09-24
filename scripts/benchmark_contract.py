"""Shared benchmark metadata derived from the maintained public contract."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import zipfile
from pathlib import Path

PUBLIC_CONTRACT = Path(__file__).resolve().parents[1] / "docs" / "release" / "public-contract.json"
TOOL_INVENTORY_VERSION = "rob2-kit.mcp-tools.v1"
PUBLIC_CONTRACT_SOURCE = "docs/release/public-contract.json"
ATTEMPT_POLICY = {
    "schema": "rob2-kit.benchmark-attempt-policy.v1",
    "max_attempts": 2,
    "rule": "infrastructure_only",
    "selection": "latest_eligible_replacement",
}


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
    if original_execution is not None and isinstance(execution, dict) and _execution_condition(
        original_execution
    ) != _execution_condition(execution):
        raise ValueError("replacement execution condition differs from predecessor")
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
    requests = (
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "rob2-rsi-preflight", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    )
    environment = os.environ.copy()
    environment["ROB2_WORKSPACE"] = str(workspace)
    try:
        completed = subprocess.run(
            [str(command), "mcp"],
            input="\n".join(json.dumps(item) for item in requests) + "\n",
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError(f"rob2 MCP tools/list preflight failed: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip()[-1000:]
        raise ValueError(
            "rob2 MCP tools/list preflight failed"
            + (f": {detail}" if detail else f" (exit {completed.returncode})")
        )

    initialize_result: dict[str, object] | None = None
    response: dict[str, object] | None = None
    for line in completed.stdout.splitlines():
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(message, dict) and message.get("id") == 1:
            result = message.get("result")
            initialize_result = result if isinstance(result, dict) else None
        elif isinstance(message, dict) and message.get("id") == 2:
            response = message
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
        "server_binding": binding,
        "server_binding_sha256": binding_sha256,
    }


def host_delivery_observed(path: Path, expected_session: str | None = None) -> dict[str, object]:
    """Summarize completed rob2 calls from one Codex CLI trace, without inferring inventory."""

    sessions = set(trace_session_ids(path))
    tools: set[str] = set()
    status_call = False
    typed_call = False
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
        tools.add(tool)
        if tool == "get_status":
            status_call = True
        elif isinstance(item.get("arguments"), dict) and isinstance(item.get("result"), dict):
            typed_call = True
    session_matches = (
        len(sessions) == 1
        and (expected_session is None or next(iter(sessions)) == expected_session)
    )
    return {
        "status": "observed" if session_matches and tools else "unavailable",
        "same_session": session_matches,
        "get_status_call": status_call and session_matches,
        "typed_call": typed_call and session_matches,
        "tools": sorted(tools) if session_matches else [],
        "session_id_sha256": (
            hashlib.sha256(next(iter(sessions)).encode("utf-8")).hexdigest()
            if session_matches
            else None
        ),
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
    """Require a hash-bound same-session status and typed rob2 call before resume."""

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
    if observed.get("get_status_call") is not True or observed.get("typed_call") is not True:
        return blocked(
            "host_delivery_call_missing",
            "The prior trace lacks a completed get_status call and a completed typed rob2 tool "
            "call.",
        )
    return None


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

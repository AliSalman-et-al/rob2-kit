#!/usr/bin/env python3
"""Launch every frozen arm/case/draw once, retaining isolated JSONL runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from rob2_kit.evaluation import validate_comparison_config
from rob2_kit.evaluation.harness import DEVELOPMENT_COMPARISON_SCHEMA

INPUTS_SCHEMA = "rob2-kit.development-comparison-inputs.v1"
LAUNCH_SCHEMA = "rob2-kit.development-comparison-launch.v1"
SUPPORTED_FACTOR = "evidence_exposure"
SUPPORTED_FACTORS = {SUPPORTED_FACTOR, "fact_binding"}
CONTINUATION_PROMPT = b"Continue.\n"
_INPUTS_FIELDS = {"schema", "runs"}
_INPUT_FIELDS = {"intervention_id", "case_id", "case_file", "prompt_file"}
_CASE_FIELDS = {
    "schema",
    "trial",
    "requested_outcome",
    "sources",
    "registry_capture",
    "approved_scope",
    "expected_result",
    "scope_unresolved",
    "campaign_id",
}
_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SOURCE_ROLES = {"main_article", "registry", "supplement", "sap", "protocol", "other"}
_SOURCE_SUFFIXES = {".pdf", ".docx", ".txt", ".md", ".csv", ".json"}
_FACTS_SCHEMA = "rob2-kit.scope-matched-facts.v1"
_FACTS_FIELDS = {
    "schema",
    "trial_id",
    "outcome_id",
    "result_identity",
    "facts",
    "counterevidence",
    "unknowns",
}
_FACT_FIELDS = {"domain_id", "question_id", "statement", "source_name", "locator"}


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"could not read JSON from {path}: {error}") from error


def _hash_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _hash_json(value: Any) -> str:
    return _hash_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def _input_file(value: Any, root: Path, name: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"comparison input {name} must be a relative path")
    path = Path(value)
    if path.is_absolute():
        raise ValueError(f"comparison input {name} must be relative to the inputs file")
    resolved = (root / path).resolve(strict=True)
    if not resolved.is_file() or not resolved.is_relative_to(root):
        raise ValueError(f"comparison input {name} must remain under the inputs directory")
    return resolved


def _case_source_file(case_file: Path, value: Any, trial: str) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError("case Source paths must be non-empty and relative")
    base = case_file.parent
    resolved = (base / value).resolve(strict=True)
    evaluation_root = next(
        (
            parent / "eval"
            for parent in (base, *base.parents)
            if (parent / "eval").is_dir() and resolved.is_relative_to(parent / "eval")
        ),
        base,
    )
    allowed_root = (
        (evaluation_root / "reference" / "sources" / trial).resolve()
        if evaluation_root != base
        else base
    )
    if not resolved.is_file() or not resolved.is_relative_to(allowed_root):
        raise ValueError("case Source path is outside the allowed trial source directory")
    return resolved


def _campaign_fact_file(case_file: Path, value: Any) -> Path:
    """Resolve the facts Source only beside its case manifest."""
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError("fact Source paths must be non-empty and relative")
    resolved = (case_file.parent / value).resolve(strict=True)
    root = case_file.parent.resolve(strict=True)
    if not resolved.is_file() or not resolved.is_relative_to(root):
        raise ValueError(
            "scope-matched-facts.json must be beside its case manifest under comparison inputs"
        )
    return resolved


def _registry_capture_file(case_file: Path, case_data: dict[str, Any]) -> Path | None:
    registry = case_data.get("registry_capture")
    if registry is None:
        return None
    required = {"path", "captured_at", "sha256", "provenance"}
    if (
        not isinstance(registry, dict)
        or set(registry) - (required | {"registry_id"})
        or not required <= set(registry)
        or not isinstance(registry["sha256"], str)
    ):
        raise ValueError("registry_capture has an invalid field set")
    path = _case_source_file(case_file, registry["path"], case_data["trial"])
    actual = _hash_bytes(path.read_bytes()).removeprefix("sha256:")
    if actual != registry["sha256"].lower():
        raise ValueError("registry_capture digest does not match supplied bytes")
    return path


def prepare_campaign(
    config: Any,
    interventions: Any,
    inputs: Any,
    *,
    inputs_root: Path,
    campaign_dir: Path,
    runner: Path,
    factor: str,
) -> dict[str, Any]:
    """Validate the complete blind run matrix before any model invocation."""

    if not isinstance(config, dict) or config.get("schema") != DEVELOPMENT_COMPARISON_SCHEMA:
        raise ValueError(f"campaign requires schema {DEVELOPMENT_COMPARISON_SCHEMA}")
    validate_comparison_config(config, interventions)
    if config["plan"]["model"] != {"family": "gpt-6-luna", "version": "6", "effort": "medium"}:
        raise ValueError("development comparison launcher is pinned to GPT-6 Luna Medium")
    if config["plan"]["host"]["provider"] != "codex-cli":
        raise ValueError("development comparison launcher requires Codex CLI")
    if config["plan"]["host"]["interface"] != "jsonl":
        raise ValueError("development comparison launcher requires JSONL host output")
    if factor not in SUPPORTED_FACTORS:
        raise ValueError(
            "launcher supports evidence_exposure and fact_binding; context and review "
            "need different runner controls"
        )
    selected_pairs = [pair for pair in config["pairs"] if pair["factor"] == factor]
    if len(selected_pairs) != 1:
        raise ValueError(f"launcher requires exactly one declared {factor} pair")
    selected_pair = selected_pairs[0]
    arms_by_id = {arm["id"]: arm for arm in config["arms"]}
    selected_arms = [arms_by_id[selected_pair[key]] for key in ("left", "right")]
    fact_intervention_id = arms_by_id[selected_pair["right"]]["intervention_id"]
    if not isinstance(inputs, dict) or set(inputs) != _INPUTS_FIELDS:
        raise ValueError("comparison inputs have an unclosed field set")
    if inputs["schema"] != INPUTS_SCHEMA or not isinstance(inputs["runs"], list):
        raise ValueError(f"comparison inputs must use schema {INPUTS_SCHEMA}")

    input_root = inputs_root.resolve(strict=True)
    expected = {
        (arm["intervention_id"], case["case_id"]): case
        for arm in selected_arms
        for case in config["plan"]["cases"]
    }
    resolved_inputs: dict[tuple[str, str], dict[str, Any]] = {}
    case_sources: dict[tuple[str, str], set[tuple[str, str, str]]] = {}
    source_identities: dict[tuple[str, str], dict[tuple[str, str, str], str]] = {}
    for index, row in enumerate(inputs["runs"]):
        if not isinstance(row, dict) or set(row) != _INPUT_FIELDS:
            raise ValueError(f"comparison inputs runs[{index}] has an unclosed field set")
        if not all(
            isinstance(row[key], str) and row[key] for key in ("intervention_id", "case_id")
        ):
            raise ValueError(f"comparison inputs runs[{index}] has invalid identities")
        key = (row["intervention_id"], row["case_id"])
        if key not in expected or key in resolved_inputs:
            raise ValueError(f"comparison inputs runs[{index}] has an unknown or duplicate pair")
        case_file = _input_file(row["case_file"], input_root, "case_file")
        prompt_file = _input_file(row["prompt_file"], input_root, "prompt_file")
        try:
            case_data = json.loads(case_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"case input is not readable JSON: {case_file}") from error
        planned_case = expected[key]
        if (
            not isinstance(case_data, dict)
            or set(case_data) - _CASE_FIELDS
            or case_data.get("schema") != "rob2-kit.rsi-case.v1"
            or not isinstance(case_data.get("sources"), list)
            or not case_data["sources"]
            or case_data.get("trial") != planned_case["trial_id"]
            or case_data.get("requested_outcome") != planned_case["outcome_id"]
            or not isinstance(case_data.get("expected_result"), dict)
            or _hash_json(case_data["expected_result"]) != planned_case["result_identity"]
            or "scope_unresolved" in case_data
        ):
            raise ValueError(f"case input does not match planned Trial/Result: {key}")
        source_rows = case_data["sources"]
        if any(
            not isinstance(source, dict)
            or set(source) != {"path", "name", "role"}
            or not isinstance(source["path"], str)
            or not source["path"]
            or not isinstance(source["name"], str)
            or Path(source["name"]).name != source["name"]
            or source["name"] in {".", "..", "sources.toml", "registry.json"}
            or Path(source["name"]).suffix.lower() not in _SOURCE_SUFFIXES
            or not isinstance(source["role"], str)
            or source["role"] not in _SOURCE_ROLES
            for source in source_rows
        ):
            raise ValueError(f"case input has an invalid Source allowlist: {key}")
        source_set = {(source["path"], source["name"], source["role"]) for source in source_rows}
        if len(source_set) != len(source_rows) or len(
            {source["name"] for source in source_rows}
        ) != len(source_rows):
            raise ValueError(f"case input Source allowlist has duplicates: {key}")
        case_sources[key] = source_set
        source_files = {}
        for source_key in source_set:
            if (
                factor == "fact_binding"
                and row["intervention_id"] == fact_intervention_id
                and source_key[1] == "scope-matched-facts.json"
            ):
                source_files[source_key] = _campaign_fact_file(case_file, source_key[0])
            else:
                source_files[source_key] = _case_source_file(
                    case_file, source_key[0], case_data["trial"]
                )
        source_identities[key] = {
            source_key: _hash_bytes(source_file.read_bytes())
            for source_key, source_file in source_files.items()
        }
        registry_file = _registry_capture_file(case_file, case_data)
        if registry_file is not None:
            source_identities[key][("<registry_capture>", "registry.json", "registry")] = (
                _hash_bytes(registry_file.read_bytes())
            )
        if factor == "fact_binding" and row["intervention_id"] == fact_intervention_id:
            _validate_scope_matched_facts(
                source_files,
                source_rows,
                planned_case,
                {
                    source["name"]
                    for source in source_rows
                    if source["name"] != "scope-matched-facts.json"
                },
            )
        prompt_identity = _hash_bytes(prompt_file.read_bytes())
        if prompt_identity != config["plan"]["host"]["prompt_identity"]:
            raise ValueError(f"prompt input does not match the frozen prompt identity: {key}")
        resolved_inputs[key] = {
            "case_file": case_file,
            "case_identity": _hash_bytes(case_file.read_bytes()),
            "prompt_file": prompt_file,
            "prompt_identity": prompt_identity,
            "case_data": case_data,
            "source_files": source_files,
            "registry_file": registry_file,
        }
    if set(resolved_inputs) != set(expected):
        raise ValueError("comparison inputs must cover every intervention/case pair")
    left_intervention = arms_by_id[selected_pair["left"]]["intervention_id"]
    right_intervention = arms_by_id[selected_pair["right"]]["intervention_id"]
    for case in config["plan"]["cases"]:
        case_id = case["case_id"]
        left_key = (left_intervention, case_id)
        right_key = (right_intervention, case_id)
        left_sources = case_sources[left_key]
        right_sources = case_sources[right_key]
        if not left_sources < right_sources:
            raise ValueError(f"{factor} inputs must add Source allowlist entries over the baseline")
        added_sources = right_sources - left_sources
        if factor == "fact_binding" and (
            len(added_sources) != 1 or next(iter(added_sources))[1] != "scope-matched-facts.json"
        ):
            raise ValueError("fact_binding must add exactly one scope-matched-facts.json Source")
        if any(
            source_identities[left_key][source] != source_identities[right_key][source]
            for source in left_sources
        ):
            raise ValueError("evidence_exposure must retain identical bytes for baseline Sources")
        left_case = resolved_inputs[left_key]["case_data"]
        right_case = resolved_inputs[right_key]["case_data"]
        for field in (
            "trial",
            "requested_outcome",
            "expected_result",
            "approved_scope",
            "registry_capture",
            "campaign_id",
        ):
            if left_case.get(field) != right_case.get(field):
                raise ValueError(f"paired inputs must share the same {field}")
        baseline_rows = [
            {"name": name, "role": role, "sha256": identity.removeprefix("sha256:")}
            for (_path, name, role), identity in sorted(
                source_identities[left_key].items(), key=lambda item: item[0][1]
            )
        ]
        if _hash_json(baseline_rows) != case["source_identity"]:
            raise ValueError(
                "plan source_identity does not match baseline Source descriptors and bytes"
            )

    for arm in selected_arms:
        if not _SAFE_COMPONENT.fullmatch(arm["id"]):
            raise ValueError(f"unsafe arm id for run directory: {arm['id']}")
    for case in config["plan"]["cases"]:
        if not _SAFE_COMPONENT.fullmatch(case["case_id"]):
            raise ValueError(f"unsafe case id for run directory: {case['case_id']}")
    for draw_id in config["plan"]["draw_policy"]["draw_ids"]:
        if not _SAFE_COMPONENT.fullmatch(draw_id):
            raise ValueError(f"unsafe draw id for run directory: {draw_id}")

    if campaign_dir.exists() and any(campaign_dir.iterdir()):
        raise ValueError(
            "campaign directory must be new or empty; existing traces are never reused"
        )
    if not runner.is_file():
        raise ValueError(f"Codex CLI runner script does not exist: {runner}")

    attempts = []
    attempt_number = 0
    for arm in selected_arms:
        intervention_id = arm["intervention_id"]
        for case in config["plan"]["cases"]:
            case_id = case["case_id"]
            run_input = resolved_inputs[(intervention_id, case_id)]
            for draw_id in config["plan"]["draw_policy"]["draw_ids"]:
                attempt_number += 1
                run_relative = Path("runs") / arm["id"] / case_id / draw_id
                attempt_id = f"attempt-{attempt_number:04d}"
                command = [
                    sys.executable,
                    str(runner.resolve()),
                    "--case",
                    str(run_input["case_file"]),
                    "--prompt",
                    str(run_input["prompt_file"]),
                    "--run-dir",
                    str(campaign_dir / run_relative),
                    "--phase",
                    "1",
                    "--model",
                    config["plan"]["model"]["family"],
                    "--effort",
                    config["plan"]["model"]["effort"],
                    "--require-isolated-host",
                ]
                attempts.append(
                    {
                        "attempt_id": attempt_id,
                        "arm_id": arm["id"],
                        "intervention_id": intervention_id,
                        "cell_id": case_id,
                        "trial_id": case["trial_id"],
                        "outcome_id": case["outcome_id"],
                        "result_identity": case["result_identity"],
                        "expected_result": run_input["case_data"]["expected_result"],
                        "draw_id": draw_id,
                        "case_file": str(run_input["case_file"].relative_to(input_root)),
                        "case_path": str(run_input["case_file"]),
                        "case_identity": run_input["case_identity"],
                        "frozen_case_metadata": {
                            field: run_input["case_data"].get(field)
                            for field in (
                                "trial",
                                "requested_outcome",
                                "expected_result",
                                "approved_scope",
                                "registry_capture",
                                "campaign_id",
                            )
                        },
                        "source_identities": [
                            {
                                "path": path,
                                "name": name,
                                "role": role,
                                "identity": identity,
                            }
                            for (path, name, role), identity in sorted(
                                source_identities[(intervention_id, case_id)].items()
                            )
                        ],
                        "source_expectations": [
                            {
                                "name": name,
                                "role": role,
                                "sha256": identity.removeprefix("sha256:"),
                            }
                            for (_path, name, role), identity in sorted(
                                source_identities[(intervention_id, case_id)].items()
                            )
                        ],
                        "frozen_inputs": {
                            "case": {
                                "path": str(run_input["case_file"]),
                                "identity": run_input["case_identity"],
                            },
                            "prompt": {
                                "path": str(run_input["prompt_file"]),
                                "identity": run_input["prompt_identity"],
                            },
                            "sources": [
                                {"path": str(path), "identity": _hash_bytes(path.read_bytes())}
                                for path in [
                                    *run_input["source_files"].values(),
                                    *(
                                        [run_input["registry_file"]]
                                        if run_input["registry_file"] is not None
                                        else []
                                    ),
                                ]
                            ],
                        },
                        "runner_file": str(runner.resolve()),
                        "runner_identity": _hash_bytes(runner.read_bytes()),
                        "registry_capture": run_input["case_data"].get("registry_capture"),
                        "prompt_file": str(run_input["prompt_file"].relative_to(input_root)),
                        "prompt_identity": run_input["prompt_identity"],
                        "run_dir": run_relative.as_posix(),
                        "trace": (run_relative / "phase-1.jsonl").as_posix(),
                        "launch_status": "planned",
                        "command": command,
                    }
                )

    return {
        "schema": LAUNCH_SCHEMA,
        "status": "planned",
        "comparison_identity": _hash_json(config),
        "interventions_identity": _hash_json(interventions),
        "inputs_identity": _hash_json(inputs),
        "runner_identity": _hash_bytes(runner.read_bytes()),
        "runner_file": str(runner.resolve()),
        "declared_environment": {
            "host": config["plan"]["host"],
            "model": config["plan"]["model"],
            "artifacts": config["plan"]["artifacts"],
        },
        "model": config["plan"]["model"],
        "selected_factor": factor,
        "selected_pair": selected_pair["id"],
        "selected_arm_ids": [arm["id"] for arm in selected_arms],
        "excluded_pairs": [pair["id"] for pair in config["pairs"] if pair is not selected_pair],
        "declared_draw_count": len(config["arms"])
        * len(config["plan"]["cases"])
        * len(config["plan"]["draw_policy"]["draw_ids"]),
        "planned_draw_count": len(attempts),
        "continuation_prompt_identity": _hash_bytes(CONTINUATION_PROMPT),
        "continuation_prompt_file": "continuation.txt",
        "attempts": attempts,
    }


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _campaign_member(
    campaign_root: Path, value: Any, description: str, *, strict: bool = True
) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"campaign {description} path must be a relative path")
    relative = Path(value)
    if relative.is_absolute():
        raise ValueError(f"campaign {description} path must be relative")
    candidate = campaign_root / relative
    try:
        resolved = candidate.resolve(strict=strict)
    except OSError as error:
        raise ValueError(f"campaign {description} path is missing") from error
    if not resolved.is_relative_to(campaign_root):
        raise ValueError(f"campaign {description} path escapes the campaign directory")
    if resolved != candidate:
        raise ValueError(f"campaign {description} path must not use traversal or symlinks")
    return resolved


def _validate_scope_matched_facts(
    source_files: dict[tuple[str, str, str], Path],
    source_rows: list[dict[str, str]],
    planned_case: dict[str, Any],
    baseline_source_names: set[str],
) -> None:
    facts_rows = [source for source in source_rows if source["name"] == "scope-matched-facts.json"]
    if len(facts_rows) != 1:
        raise ValueError("fact_binding treatment must provide scope-matched-facts.json")
    key = (facts_rows[0]["path"], facts_rows[0]["name"], facts_rows[0]["role"])
    facts = _read_json(source_files[key])
    if not isinstance(facts, dict) or set(facts) != _FACTS_FIELDS:
        raise ValueError("scope-matched facts have an unclosed field set")
    if (
        facts.get("schema") != _FACTS_SCHEMA
        or facts.get("trial_id") != planned_case["trial_id"]
        or facts.get("outcome_id") != planned_case["outcome_id"]
        or facts.get("result_identity") != planned_case["result_identity"]
    ):
        raise ValueError("scope-matched facts do not match the frozen Trial and Result")
    for list_name in ("facts", "counterevidence", "unknowns"):
        rows = facts.get(list_name)
        if not isinstance(rows, list) or (list_name == "facts" and not rows):
            raise ValueError(f"scope-matched facts.{list_name} must be a list")
        for item in rows:
            if (
                not isinstance(item, dict)
                or set(item) != _FACT_FIELDS
                or item.get("domain_id") not in planned_case["domain_ids"]
                or any(
                    not isinstance(item.get(field), str) or not item[field].strip()
                    for field in ("question_id", "statement", "source_name", "locator")
                )
                or item["source_name"] not in baseline_source_names
            ):
                raise ValueError(
                    f"scope-matched facts.{list_name} entries must cite a common Source and "
                    "match a planned Domain"
                )


def launch_campaign(
    manifest: dict[str, Any], campaign_dir: Path, *, runner_call: Any = subprocess.run
) -> int:
    """Run every planned draw once and retain its raw phase trace."""

    campaign_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = campaign_dir / "launch.json"
    continuation_path = campaign_dir / manifest["continuation_prompt_file"]
    continuation_path.write_bytes(CONTINUATION_PROMPT)
    manifest["status"] = "running"
    _write_manifest(manifest_path, manifest)
    failures = 0
    for attempt in manifest["attempts"]:
        logs = campaign_dir / "logs"
        logs.mkdir(exist_ok=True)
        stdout_path = logs / f"{attempt['attempt_id']}.stdout.txt"
        stderr_path = logs / f"{attempt['attempt_id']}.stderr.txt"
        frozen_check = _verify_frozen_inputs(attempt)
        attempt["frozen_input_check"] = frozen_check
        if frozen_check["status"] != "verified":
            attempt["launch_status"] = "frozen_input_changed"
            failures += 1
            _write_manifest(manifest_path, manifest)
            continue
        attempt["launch_status"] = "running"
        _write_manifest(manifest_path, manifest)
        try:
            with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
                result = runner_call(
                    attempt["command"],
                    cwd=Path(__file__).resolve().parents[1],
                    stdout=stdout,
                    stderr=stderr,
                    check=False,
                )
        except OSError as error:
            attempt["launch_status"] = "runner_unavailable"
            attempt["launch_error"] = str(error)
            failures += 1
        else:
            attempt["exit_code"] = result.returncode
            attempt["trace_retained"] = (campaign_dir / attempt["trace"]).is_file()
            if result.returncode != 0:
                attempt["launch_status"] = "runner_failed"
                failures += 1
            elif attempt["trace_retained"]:
                input_check = _verify_execution_inputs(
                    attempt, campaign_dir / attempt["run_dir"], phase=1
                )
                attempt["execution_input_check"] = input_check
                if input_check["status"] != "verified":
                    attempt["launch_status"] = "execution_input_mismatch"
                    failures += 1
                    _write_manifest(manifest_path, manifest)
                    continue
                attempt["source_materialization"] = _verify_source_materialization(
                    campaign_dir / attempt["run_dir"],
                    attempt["trial_id"],
                    attempt["source_expectations"],
                    attempt["frozen_case_metadata"],
                )
                if attempt["source_materialization"]["status"] == "verified":
                    attempt["launch_status"] = "phase_started"
                else:
                    attempt["launch_status"] = "source_materialization_mismatch"
                    failures += 1
            else:
                attempt["launch_status"] = "trace_missing"
                failures += 1
        _write_manifest(manifest_path, manifest)
    manifest["status"] = "launches_finished" if failures == 0 else "launch_failures"
    manifest["failed_launches"] = failures
    _write_manifest(manifest_path, manifest)
    return 1 if failures else 0


def continue_approved_campaign(
    campaign_dir: Path,
    *,
    config: Any,
    interventions: Any,
    inputs: Any,
    runner: Path,
    factor: str,
    runner_call: Any = subprocess.run,
) -> int:
    """Continue only durable executions awaiting the real researcher gate."""
    campaign_root = campaign_dir.resolve(strict=True)
    if not campaign_root.is_dir():
        raise ValueError("campaign directory must be a directory")
    manifest_path = _campaign_member(campaign_root, "launch.json", "manifest")
    manifest = _read_json(manifest_path)
    if not isinstance(manifest, dict) or manifest.get("schema") != LAUNCH_SCHEMA:
        raise ValueError("campaign launch manifest is missing or unsupported")
    if (
        manifest.get("selected_factor") != factor
        or manifest.get("comparison_identity") != _hash_json(config)
        or manifest.get("interventions_identity") != _hash_json(interventions)
        or manifest.get("inputs_identity") != _hash_json(inputs)
        or manifest.get("runner_file") != str(runner.resolve())
        or manifest.get("runner_identity") != _hash_bytes(runner.read_bytes())
    ):
        raise ValueError("continuation inputs differ from the frozen campaign")
    if manifest.get("model") != config["plan"]["model"]:
        raise ValueError("campaign model differs from the frozen plan")
    prompt_name = manifest.get("continuation_prompt_file")
    if prompt_name != "continuation.txt":
        raise ValueError("campaign continuation prompt path must be continuation.txt")
    continuation_path = _campaign_member(campaign_root, prompt_name, "continuation prompt")
    if (
        not continuation_path.is_file()
        or _hash_bytes(continuation_path.read_bytes())
        != manifest.get("continuation_prompt_identity")
        or continuation_path.read_bytes() != CONTINUATION_PROMPT
    ):
        raise ValueError("frozen continuation prompt is missing or changed")
    attempts = manifest.get("attempts")
    if not isinstance(attempts, list):
        raise ValueError("campaign attempts are malformed")

    pairs = [pair for pair in config["pairs"] if pair["factor"] == factor]
    arms_by_id = {arm["id"]: arm for arm in config["arms"]}
    if len(pairs) != 1:
        raise ValueError("frozen comparison must contain exactly one selected factor pair")
    pair = pairs[0]
    selected_arm_ids = [arms_by_id[pair[key]]["id"] for key in ("left", "right")]
    if (
        manifest.get("selected_pair") != pair["id"]
        or manifest.get("selected_arm_ids") != selected_arm_ids
    ):
        raise ValueError("campaign arms differ from the frozen comparison pair")
    cases = {case["case_id"]: case for case in config["plan"]["cases"]}
    draw_ids = config["plan"]["draw_policy"]["draw_ids"]
    planned_cells = {
        (arm_id, case_id, draw_id)
        for arm_id in selected_arm_ids
        for case_id in cases
        for draw_id in draw_ids
    }
    validated_attempts: list[tuple[dict[str, Any], Path]] = []
    seen_cells: set[tuple[str, str, str]] = set()
    seen_attempt_ids: set[str] = set()
    for attempt in attempts:
        if not isinstance(attempt, dict):
            raise ValueError("campaign attempt is malformed")
        attempt_id = attempt.get("attempt_id")
        arm_id = attempt.get("arm_id")
        case_id = attempt.get("cell_id")
        draw_id = attempt.get("draw_id")
        if (
            not isinstance(attempt_id, str)
            or _SAFE_COMPONENT.fullmatch(attempt_id) is None
            or attempt_id in seen_attempt_ids
            or not all(isinstance(value, str) for value in (arm_id, case_id, draw_id))
            or any(
                _SAFE_COMPONENT.fullmatch(value) is None
                for value in (arm_id, case_id, draw_id)
                if isinstance(value, str)
            )
        ):
            raise ValueError("campaign attempt identity is invalid")
        key = (arm_id, case_id, draw_id)
        case = cases.get(case_id)
        expected_run_dir = (Path("runs") / arm_id / case_id / draw_id).as_posix()
        if (
            key not in planned_cells
            or key in seen_cells
            or attempt.get("run_dir") != expected_run_dir
            or case is None
            or attempt.get("trial_id") != case["trial_id"]
            or attempt.get("outcome_id") != case["outcome_id"]
            or attempt.get("result_identity") != case["result_identity"]
        ):
            raise ValueError("campaign attempt differs from its frozen arm/case/draw identity")
        run_dir = _campaign_member(campaign_root, expected_run_dir, "run directory", strict=False)
        validated_attempts.append((attempt, run_dir))
        seen_attempt_ids.add(attempt_id)
        seen_cells.add(key)
    if seen_cells != planned_cells:
        raise ValueError("campaign attempts do not cover the frozen arm/case/draw matrix")

    failures = 0
    model = manifest["model"]
    for attempt, run_dir in validated_attempts:
        execution_relative = (run_dir.relative_to(campaign_root) / "execution.json").as_posix()
        execution_path = _campaign_member(
            campaign_root, execution_relative, "execution record", strict=False
        )
        if not execution_path.is_file():
            attempt["continuation_status"] = "execution_missing"
            continue
        try:
            execution = _read_json(execution_path)
        except ValueError as error:
            attempt["continuation_status"] = "execution_invalid"
            attempt["continuation_error"] = str(error)
            failures += 1
            continue
        if not isinstance(execution, dict):
            attempt["continuation_status"] = "execution_invalid"
            failures += 1
            continue
        if execution.get("state") != "waiting_for_user":
            attempt["continuation_status"] = "not_waiting_for_user"
            attempt["execution_state"] = execution.get("state")
            continue

        session_id = execution.get("codex_session_id")
        phases = execution.get("phases")
        if not isinstance(session_id, str) or not session_id or not isinstance(phases, list):
            attempt["continuation_status"] = "session_unavailable"
            failures += 1
            continue
        phase_numbers = [
            phase["phase"]
            for phase in phases
            if isinstance(phase, dict) and isinstance(phase.get("phase"), int)
        ]
        recorded_sessions = {
            phase.get("codex_session_id")
            for phase in phases
            if isinstance(phase, dict) and isinstance(phase.get("codex_session_id"), str)
        }
        if not phase_numbers or recorded_sessions != {session_id}:
            attempt["continuation_status"] = "session_mismatch"
            failures += 1
            continue
        materialization = _verify_source_materialization(
            run_dir,
            attempt["trial_id"],
            attempt["source_expectations"],
            attempt["frozen_case_metadata"],
        )
        attempt["pre_continuation_source_materialization"] = materialization
        if materialization["status"] != "verified":
            attempt["continuation_status"] = "source_materialization_mismatch"
            failures += 1
            continue
        frozen_check = _verify_frozen_inputs(attempt)
        attempt["continuation_frozen_input_check"] = frozen_check
        if frozen_check["status"] != "verified":
            attempt["continuation_status"] = "frozen_input_changed"
            failures += 1
            continue

        phase_number = max(phase_numbers) + 1
        trace_relative = run_dir.relative_to(campaign_root) / f"phase-{phase_number}.jsonl"
        command = [
            sys.executable,
            str(runner.resolve()),
            "--prompt",
            str(continuation_path.resolve()),
            "--run-dir",
            str(run_dir.resolve()),
            "--phase",
            str(phase_number),
            "--session",
            session_id,
            "--model",
            model["family"],
            "--effort",
            model["effort"],
            "--require-isolated-host",
        ]
        continuation = {
            "phase": phase_number,
            "prompt_identity": manifest["continuation_prompt_identity"],
            "session_id": session_id,
            "trace": trace_relative.as_posix(),
            "command": command,
            "launch_status": "running",
        }
        attempt.setdefault("continuations", []).append(continuation)
        logs = campaign_root / "logs"
        if logs.exists() or logs.is_symlink():
            logs = _campaign_member(campaign_root, "logs", "logs directory")
            if not logs.is_dir():
                raise ValueError("campaign logs path is not a directory")
        else:
            logs.mkdir()
        try:
            with (
                (logs / f"{attempt['attempt_id']}.phase-{phase_number}.stdout.txt").open(
                    "wb"
                ) as stdout,
                (logs / f"{attempt['attempt_id']}.phase-{phase_number}.stderr.txt").open(
                    "wb"
                ) as stderr,
            ):
                result = runner_call(
                    command,
                    cwd=Path(__file__).resolve().parents[1],
                    stdout=stdout,
                    stderr=stderr,
                    check=False,
                )
        except OSError as error:
            continuation["launch_status"] = "runner_unavailable"
            continuation["launch_error"] = str(error)
            failures += 1
        else:
            continuation["exit_code"] = result.returncode
            trace_path = campaign_root / trace_relative
            continuation["trace_retained"] = trace_path.is_file()
            if trace_path.is_file():
                continuation["trace_identity"] = _hash_bytes(trace_path.read_bytes())
            try:
                final_execution = _read_json(execution_path)
            except ValueError:
                final_execution = {}
            attempt["execution_state"] = (
                final_execution.get("state") if isinstance(final_execution, dict) else None
            )
            if result.returncode != 0:
                continuation["launch_status"] = "runner_failed"
                failures += 1
            elif not trace_path.is_file():
                continuation["launch_status"] = "trace_missing"
                failures += 1
            else:
                input_check = _verify_execution_inputs(
                    attempt,
                    run_dir,
                    phase=phase_number,
                    prompt_identity=manifest["continuation_prompt_identity"],
                )
                continuation["execution_input_check"] = input_check
                check = (
                    _verify_source_materialization(
                        run_dir,
                        attempt["trial_id"],
                        attempt["source_expectations"],
                        attempt["frozen_case_metadata"],
                    )
                    if input_check["status"] == "verified"
                    else {"status": "skipped", "reason": input_check["error"]}
                )
                continuation["source_materialization"] = check
                if input_check["status"] != "verified":
                    continuation["launch_status"] = "execution_input_mismatch"
                    failures += 1
                elif check["status"] == "verified":
                    continuation["launch_status"] = "phase_started"
                else:
                    continuation["launch_status"] = "source_materialization_mismatch"
                    failures += 1
        _write_manifest(manifest_path, manifest)
    manifest["status"] = "continuations_finished" if failures == 0 else "continuation_failures"
    manifest["failed_continuations"] = failures
    _write_manifest(manifest_path, manifest)
    return 1 if failures else 0


def _verify_source_materialization(
    run_dir: Path,
    trial_id: str,
    expected: list[dict[str, str]],
    case_metadata: dict[str, Any],
) -> dict[str, Any]:
    try:
        run_inputs = _read_json(run_dir / "run-inputs.json")
        recorded = run_inputs.get("sources")
        if not isinstance(recorded, list):
            raise ValueError("runner input manifest has no Sources")
        if any(
            not isinstance(row, dict)
            or set(row) != {"name", "role", "sha256"}
            or not all(isinstance(row[field], str) for field in ("name", "role", "sha256"))
            for row in recorded
        ):
            raise ValueError("runner input manifest has an invalid Source row")
        recorded_names = [row.get("name") for row in recorded]
        if len(recorded_names) != len(expected) or set(recorded_names) != {
            source["name"] for source in expected
        }:
            raise ValueError("runner materialized a different Source set than planned")
        if (
            run_inputs.get("trial") != case_metadata["trial"]
            or run_inputs.get("requested_outcome") != case_metadata["requested_outcome"]
            or _hash_json(run_inputs.get("expected_result"))
            != _hash_json(case_metadata["expected_result"])
            or run_inputs.get("approved_scope") != case_metadata["approved_scope"]
            or run_inputs.get("campaign_id") != case_metadata["campaign_id"]
        ):
            raise ValueError("runner materialized a different frozen Trial/Result scope")
        _verify_registry_materialization(run_inputs, case_metadata.get("registry_capture"))
        copied = run_dir / "workspace" / "input" / trial_id
        for source in expected:
            name = source["name"]
            path = copied / name
            if (
                not path.is_file()
                or _hash_bytes(path.read_bytes()).removeprefix("sha256:") != source["sha256"]
            ):
                raise ValueError(f"workspace Source bytes are missing or changed: {name}")
            if not any(
                isinstance(row, dict)
                and row.get("name") == name
                and row.get("role") == source["role"]
                and row.get("sha256") == source["sha256"]
                for row in recorded
            ):
                raise ValueError(f"run input manifest does not record Source: {name}")
    except (OSError, ValueError, AttributeError) as error:
        return {"status": "mismatch", "error": str(error)}
    return {"status": "verified", "source_count": len(expected)}


def _verify_registry_materialization(
    run_inputs: dict[str, Any], expected: dict[str, Any] | None
) -> None:
    actual = run_inputs.get("registry_capture")
    if expected is None:
        if actual is not None:
            raise ValueError("unexpected registry capture was materialized")
        return
    if (
        not isinstance(actual, dict)
        or actual.get("captured_at") != expected.get("captured_at")
        or actual.get("sha256") != expected.get("sha256", "").lower()
        or actual.get("capture_provenance") != expected.get("provenance")
        or actual.get("registry_id") != expected.get("registry_id")
    ):
        raise ValueError("runner registry capture provenance does not match frozen input")


def _verify_frozen_inputs(attempt: dict[str, Any]) -> dict[str, Any]:
    frozen = attempt.get("frozen_inputs")
    if not isinstance(frozen, dict):
        return {"status": "mismatch", "error": "frozen input identities are missing"}
    rows = [frozen.get("case"), frozen.get("prompt"), *frozen.get("sources", [])]
    try:
        for row in rows:
            if (
                not isinstance(row, dict)
                or not isinstance(row.get("path"), str)
                or not isinstance(row.get("identity"), str)
            ):
                raise ValueError("frozen input identity row is invalid")
            if _hash_bytes(Path(row["path"]).read_bytes()) != row["identity"]:
                raise ValueError(f"frozen input changed after preflight: {row['path']}")
        runner_file = attempt.get("runner_file")
        runner_identity = attempt.get("runner_identity")
        if (
            not isinstance(runner_file, str)
            or not isinstance(runner_identity, str)
            or _hash_bytes(Path(runner_file).read_bytes()) != runner_identity
        ):
            raise ValueError("frozen runner changed after preflight")
    except (OSError, ValueError) as error:
        return {"status": "mismatch", "error": str(error)}
    return {"status": "verified", "file_count": len(rows)}


def _verify_execution_inputs(
    attempt: dict[str, Any], run_dir: Path, *, phase: int, prompt_identity: str | None = None
) -> dict[str, Any]:
    """Bind each recorded phase to the frozen case and phase prompt digests."""
    try:
        execution = _read_json(run_dir / "execution.json")
        if not isinstance(execution, dict):
            raise ValueError("runner execution record is malformed")
        case_identity = attempt.get("case_identity")
        if not isinstance(case_identity, str) or execution.get("manifest_sha256") != (
            case_identity.removeprefix("sha256:")
        ):
            raise ValueError("runner execution used a different case manifest")
        expected_prompt = prompt_identity or attempt.get("prompt_identity")
        prompts = execution.get("prompt_sha256_by_phase")
        observed_prompt = prompts.get(str(phase)) if isinstance(prompts, dict) else None
        if not isinstance(expected_prompt, str) or observed_prompt != expected_prompt.removeprefix(
            "sha256:"
        ):
            raise ValueError("runner execution used a different phase prompt")
    except (OSError, ValueError) as error:
        return {"status": "mismatch", "error": str(error)}
    return {"status": "verified", "phase": phase}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--interventions", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--campaign-dir", type=Path, required=True)
    parser.add_argument("--factor", choices=sorted(SUPPORTED_FACTORS), required=True)
    parser.add_argument(
        "--runner",
        type=Path,
        default=Path(__file__).with_name("run_rsi_case.py"),
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--continue-approved",
        action="store_true",
        help="Continue existing waiting executions after the researcher approved Proposal Review",
    )
    args = parser.parse_args(argv)

    try:
        config_path = args.config.resolve(strict=True)
        interventions_path = args.interventions.resolve(strict=True)
        inputs_path = args.inputs.resolve(strict=True)
        runner_path = args.runner.resolve(strict=True)
        campaign_dir = args.campaign_dir.resolve()
        if args.continue_approved:
            if args.dry_run:
                raise ValueError("--continue-approved cannot be combined with --dry-run")
            result = continue_approved_campaign(
                campaign_dir.resolve(strict=True),
                config=_read_json(config_path),
                interventions=_read_json(interventions_path),
                inputs=_read_json(inputs_path),
                runner=runner_path,
                factor=args.factor,
            )
            print(
                f"continuation finished: {campaign_dir}; "
                "the runner enforces the accepted researcher review gate"
            )
            return result
        if args.dry_run and campaign_dir.exists() and any(campaign_dir.iterdir()):
            raise ValueError("campaign directory must be new or empty")
        manifest = prepare_campaign(
            _read_json(config_path),
            _read_json(interventions_path),
            _read_json(inputs_path),
            inputs_root=inputs_path.parent,
            campaign_dir=campaign_dir,
            runner=runner_path,
            factor=args.factor,
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))

    if args.dry_run:
        print(json.dumps(manifest, sort_keys=True, indent=2))
        return 0
    result = launch_campaign(manifest, campaign_dir)
    print(
        f"{manifest['status']}: launched {len(manifest['attempts'])} planned draw attempts; "
        f"{manifest.get('failed_launches', 0)} runner failures; raw traces retained under "
        f"{campaign_dir}"
    )
    return result


if __name__ == "__main__":
    raise SystemExit(main())

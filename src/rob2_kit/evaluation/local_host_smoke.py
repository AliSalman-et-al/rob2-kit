"""Local-only, explicitly opted-in smoke orchestration for commercial Harnesses.

The public planning seam is intentionally model-free.  The executable script is
kept outside CI and requires both a command-line flag and a local environment
flag before it will return commands that can start Codex or Claude Code.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

Host = Literal["codex", "claude"]
OPT_IN_ENV = "ROB2_LOCAL_COMMERCIAL_HOST_SMOKE"
WORKSPACE_MARKER = ".rob2-local-host-smoke"


class CommercialHostOptInRequired(ValueError):
    """Raised before constructing commercial-host commands without both opt-ins."""


@dataclass(frozen=True)
class HostSmokeOptions:
    wheel: Path
    workspace: Path
    execute: bool = False
    keep: bool = True
    codex_model: str | None = None
    claude_model: str | None = None


@dataclass(frozen=True)
class SmokeScenario:
    name: str
    project: Path
    first_host: Host
    resume_host: Host
    checkpoint_prompt: str
    resume_prompt: str


@dataclass(frozen=True)
class SmokePlan:
    release_sha256: str
    workspace: Path
    scenarios: tuple[SmokeScenario, ...]
    install_commands: tuple[tuple[str, ...], ...]
    adapter_commands: tuple[tuple[str, ...], ...]
    doctor_commands: tuple[tuple[str, ...], ...]
    mcp_commands: tuple[tuple[str, ...], ...]
    host_commands: tuple[tuple[str, ...], ...]


def build_smoke_plan(
    options: HostSmokeOptions, *, environ: Mapping[str, str] | None = None
) -> SmokePlan:
    """Validate the double opt-in and construct a credential-neutral command plan."""

    env = os.environ if environ is None else environ
    if env.get("CI", "").casefold() in {"1", "true", "yes"}:
        raise CommercialHostOptInRequired("commercial-host smoke is forbidden when CI is set")
    if not options.execute or env.get(OPT_IN_ENV) != "1":
        raise CommercialHostOptInRequired(
            f"real hosts require --execute and {OPT_IN_ENV}=1 in the local shell"
        )
    if not options.codex_model or not options.claude_model:
        raise ValueError("--codex-model and --claude-model are required for review metadata")
    wheel = options.wheel.resolve()
    if not wheel.is_file() or wheel.suffix != ".whl":
        raise ValueError("--wheel must name an existing exact wheel file")
    workspace = options.workspace.resolve()
    scenarios = (
        _scenario(workspace, "codex-to-claude", "codex", "claude"),
        _scenario(workspace, "claude-to-codex", "claude", "codex"),
    )
    installs: list[tuple[str, ...]] = []
    adapters: list[tuple[str, ...]] = []
    doctors: list[tuple[str, ...]] = []
    mcps: list[tuple[str, ...]] = []
    hosts: list[tuple[str, ...]] = []
    for scenario in scenarios:
        python = (
            scenario.project / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        )
        executable = python.parent
        installs.append(
            (
                "uv",
                "pip",
                "install",
                "--python",
                str(python),
                str(wheel),
            )
        )
        adapters.append((str(executable / _exe("rob2")), "bootstrap", str(scenario.project)))
        doctors.append((str(executable / _exe("rob2")), "doctor", str(scenario.project)))
        mcps.append((str(executable / _exe("rob2-mcp")),))
        hosts.extend(
            (
                _host_command(
                    scenario.first_host, scenario.project, scenario.checkpoint_prompt, options
                ),
                _host_command(
                    scenario.resume_host, scenario.project, scenario.resume_prompt, options
                ),
            )
        )
    return SmokePlan(
        release_sha256=hashlib.sha256(wheel.read_bytes()).hexdigest(),
        workspace=workspace,
        scenarios=scenarios,
        install_commands=tuple(installs),
        adapter_commands=tuple(adapters),
        doctor_commands=tuple(doctors),
        mcp_commands=tuple(mcps),
        host_commands=tuple(hosts),
    )


def redact_diagnostic(text: str, *, limit: int = 16_384) -> str:
    """Redact common credential assignments and return a byte-bounded diagnostic."""

    redacted = re.sub(
        r"(?i)\b([A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD))\s*[=:]\s*[^\s,}\"]+",
        r"\1=<redacted>",
        text,
    )
    redacted = re.sub(r"(?i)\bBearer\s+\S+", "Bearer <redacted>", redacted)
    redacted = re.sub(r"\b(?:sk|sk-ant)-[A-Za-z0-9_-]{8,}\b", "<redacted>", redacted)
    payload = redacted.encode("utf-8")[:limit]
    while True:
        try:
            return payload.decode("utf-8")
        except UnicodeDecodeError:
            payload = payload[:-1]


def compare_semantic_outcomes(
    left: Mapping[str, Any], right: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    """Compare stable state, actions, reports, and repair counts, never prose."""

    fields = ("run_state", "durable_state", "next_actions", "reports", "repair_count")
    return {
        field: {"left": left.get(field), "right": right.get(field)}
        for field in fields
        if left.get(field) != right.get(field)
    }


def inspect_durable_outcome(project: Path) -> dict[str, Any]:
    """Project durable Run state and reports without trusting host-authored prose."""

    ledger = project.resolve() / ".rob2" / "ledger.sqlite3"
    if not ledger.is_file():
        raise ValueError(f"durable Run ledger is missing: {ledger}")
    with sqlite3.connect(ledger) as connection:
        operations = [
            row[0]
            for row in connection.execute(
                "SELECT operation FROM workflow_events ORDER BY sequence"
            ).fetchall()
        ]
        results = [
            json.loads(row[0])
            for row in connection.execute(
                """SELECT o.result_json
                   FROM workflow_events AS e
                   JOIN operations AS o ON o.operation_key = e.operation_key
                   ORDER BY e.sequence"""
            ).fetchall()
        ]
    run_ids = set(_all_named_values(results, "run_id"))
    if len(run_ids) != 1:
        raise ValueError(f"expected exactly one durable Run, found {len(run_ids)}")
    run_state = _last_named_value(results, "run_state")
    next_actions = _last_named_value(results, "next_actions") or []
    reports = sorted(
        path.relative_to(project).as_posix()
        for path in project.rglob("*")
        if path.is_file() and "report" in path.name.casefold()
    )
    if run_state is None:
        raise ValueError("installed workflow produced no durable run_state")
    return {
        "run_state": run_state,
        "durable_state": {"operations": operations},
        "next_actions": next_actions,
        "reports": reports,
        "repair_count": sum("repair" in operation.casefold() for operation in operations),
    }


def _last_named_value(values: list[Any], name: str) -> Any:
    found = None
    for value in values:
        if isinstance(value, Mapping):
            if name in value:
                found = value[name]
            nested = _last_named_value(list(value.values()), name)
            if nested is not None:
                found = nested
        elif isinstance(value, list):
            nested = _last_named_value(value, name)
            if nested is not None:
                found = nested
    return found


def _all_named_values(values: list[Any], name: str) -> list[str]:
    found: list[str] = []
    for value in values:
        if isinstance(value, Mapping):
            item = value.get(name)
            if isinstance(item, str):
                found.append(item)
            found.extend(_all_named_values(list(value.values()), name))
        elif isinstance(value, list):
            found.extend(_all_named_values(value, name))
    return found


def cleanup_smoke_workspace(target: Path, *, workspace: Path) -> None:
    """Delete only a marked child of the exact declared smoke workspace."""

    target = target.resolve()
    workspace = workspace.resolve()
    if target == workspace or workspace not in target.parents:
        raise ValueError("cleanup target is outside the declared smoke workspace")
    marker = target / WORKSPACE_MARKER
    if not marker.is_file() or marker.read_text(encoding="utf-8") != str(target):
        raise ValueError("cleanup target marker is missing or mismatched")
    shutil.rmtree(target)


def _scenario(workspace: Path, name: str, first: Host, resume: Host) -> SmokeScenario:
    project = workspace / name
    return SmokeScenario(
        name=name,
        project=project,
        first_host=first,
        resume_host=resume,
        checkpoint_prompt=(
            "In natural language, use the installed rob2-init and rob2-assess skills to prepare "
            "the bundled small trial, reach a Preparation checkpoint, report the "
            "returned next action, then stop without completing the assessment."
        ),
        resume_prompt=(
            "In natural language, find and resume the existing durable Run in this project; do "
            "not start a new Run. Follow returned next actions to the deterministic report-ready "
            "checkpoint, then summarize the Durable run state and returned next actions without "
            "including credentials, configuration, prompts, or hidden reasoning."
        ),
    )


def _host_command(
    host: Host, project: Path, prompt: str, options: HostSmokeOptions
) -> tuple[str, ...]:
    model = options.codex_model if host == "codex" else options.claude_model
    if host == "codex":
        command = ["codex", "exec", "-C", str(project), "--json"]
        if model:
            command.extend(("--model", model))
        command.append(prompt)
        return tuple(command)
    command = ["claude", "-p", "--output-format", "stream-json"]
    if model:
        command.extend(("--model", model))
    command.append(prompt)
    return tuple(command)


def _exe(name: str) -> str:
    return f"{name}.exe" if os.name == "nt" else name

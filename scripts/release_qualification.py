"""Qualify a frozen wheel without importing the source checkout.

The CI matrix invokes this script once per supported OS.  It makes a fresh
Python 3.13 environment, installs the frozen dependency set and candidate
wheel, then records the installed-command journey in a comparable receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

EXPECTED_UVX_ARGS = ("--python", "3.13", "--from", "rob2-kit==0.1.0", "rob2-mcp")
QUALIFICATION_TIME = "2026-08-03T00:00:00Z"
CANONICAL_TOOL_NAMES = (
    "prepare_run",
    "continue_run",
    "get_work_context",
    "submit_run_proposal",
    "confirm_run_definition",
    "search_evidence",
    "read_evidence",
    "inspect_visual_candidate",
    "submit_source_role_review",
    "submit_result_resolution",
    "submit_domain_evidence",
    "submit_domain_answers",
)
STAGE_TIMINGS: list[dict[str, object]] = []


def _command_path(environment: Path, name: str) -> Path:
    scripts = environment / ("Scripts" if os.name == "nt" else "bin")
    suffixes = (".exe", ".cmd", "") if os.name == "nt" else ("",)
    return next(
        (
            scripts / f"{name}{suffix}"
            for suffix in suffixes
            if (scripts / f"{name}{suffix}").is_file()
        ),
        scripts / name,
    )


def _python_path(environment: Path) -> Path:
    return environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout_seconds: int = 600,
) -> subprocess.CompletedProcess[str]:
    label_parts = [
        argument if argument.startswith("-") else Path(argument).name for argument in command[1:3]
    ]
    label = f"{Path(command[0]).name} {' '.join(label_parts)}".rstrip()
    print(f"qualification: running {label}", flush=True)
    started = time.perf_counter()
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=creationflags,
        start_new_session=os.name != "nt",
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as error:
        _terminate_process_tree(process)
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                stdout, stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired as final_error:
                raise RuntimeError(
                    f"qualification command timed out and could not be reaped: {command!r}"
                ) from final_error
        raise RuntimeError(
            f"qualification command exceeded {timeout_seconds}s: {command!r}\n"
            f"stdout:\n{stdout}\nstderr:\n{stderr}"
        ) from error
    result = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    if result.returncode:
        raise RuntimeError(
            f"command failed ({result.returncode}): {command!r}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    duration = round(time.perf_counter() - started, 3)
    STAGE_TIMINGS.append({"stage": label, "duration_seconds": duration})
    print(f"qualification: completed {label} in {duration:.3f}s", flush=True)
    return result


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    """Bound cleanup to the spawned command's process group, including helpers."""

    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
    else:
        os.killpg(process.pid, signal.SIGKILL)


@dataclass(frozen=True)
class _LifecycleQualification:
    receipt: dict[str, str]


def _qualify_lifecycle(
    rob2: Path,
    project: Path,
    workspace: Path,
    checked_env: dict[str, str],
    original_codex_config: bytes,
    original_claude_config: bytes,
) -> _LifecycleQualification:
    """Exercise the separate release lifecycle gate through installed commands."""

    upgrade_preview = json.loads(
        _run([str(rob2), "upgrade", str(project)], cwd=workspace, env=checked_env).stdout
    )
    assert upgrade_preview["preview"] is True
    assert upgrade_preview["state_compatibility"]["ok"] is True
    upgrade = json.loads(
        _run([str(rob2), "upgrade", "--apply", str(project)], cwd=workspace, env=checked_env).stdout
    )
    assert upgrade["status"] == "upgraded"
    rollback_record = json.loads((project / ".rob2" / "rollback.json").read_text(encoding="utf-8"))
    assert not {".codex/config.toml", ".mcp.json"} & set(rollback_record["paths"])
    assert (
        json.loads(
            _run([str(rob2), "doctor", str(project)], cwd=workspace, env=checked_env).stdout
        )["ok"]
        is True
    )
    rollback_preview = json.loads(
        _run([str(rob2), "rollback", str(project)], cwd=workspace, env=checked_env).stdout
    )
    assert rollback_preview["preview"] is True
    assert rollback_preview["state_compatibility"]["ok"] is True
    rollback = json.loads(
        _run(
            [str(rob2), "rollback", "--apply", str(project)], cwd=workspace, env=checked_env
        ).stdout
    )
    assert rollback["status"] == "rolled_back"
    assert (project / ".codex" / "config.toml").read_bytes() == original_codex_config
    assert (project / ".mcp.json").read_bytes() == original_claude_config
    assert (
        json.loads(
            _run([str(rob2), "doctor", str(project)], cwd=workspace, env=checked_env).stdout
        )["ok"]
        is True
    )
    uninstall_preview = json.loads(
        _run([str(rob2), "uninstall", str(project)], cwd=workspace, env=checked_env).stdout
    )
    assert uninstall_preview["preview"] is True
    assert uninstall_preview["state_compatibility"]["ok"] is True
    uninstall = json.loads(
        _run(
            [str(rob2), "uninstall", "--apply", str(project)], cwd=workspace, env=checked_env
        ).stdout
    )
    assert uninstall["status"] == "uninstalled"
    reinstalled = json.loads(
        _run([str(rob2), "bootstrap", str(project)], cwd=workspace, env=checked_env).stdout
    )
    assert reinstalled["status"] == "installed"
    return _LifecycleQualification(
        receipt={
            "upgrade": upgrade["status"],
            "rollback": rollback["status"],
            "uninstall": uninstall["status"],
            "reinstalled": reinstalled["status"],
        }
    )


def _clean_environment(
    environment: Path, source_root: Path, wheel: Path
) -> tuple[Path, Path, Path]:
    _run(["uv", "venv", str(environment), "--python", "3.13"], cwd=source_root)
    python = _python_path(environment)
    requirements = environment.parent / "locked-requirements.txt"
    _run(
        [
            "uv",
            "export",
            "--frozen",
            "--all-groups",
            "--no-emit-project",
            "--no-emit-workspace",
            "--no-header",
            "--no-annotate",
            "--output-file",
            str(requirements),
        ],
        cwd=source_root,
    )
    _run(
        ["uv", "pip", "install", "--python", str(python), "-r", str(requirements)], cwd=source_root
    )
    _run(
        ["uv", "pip", "install", "--python", str(python), "--no-deps", str(wheel)], cwd=source_root
    )
    return python, _command_path(environment, "rob2"), _command_path(environment, "rob2-mcp")


def _candidate_env(
    environment: Path,
    shim: Path | None = None,
    network_guard: Path | None = None,
    absent_fixtures: tuple[str, ...] = (),
) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("VIRTUAL_ENV", None)
    env.pop("UV_PROJECT_ENVIRONMENT", None)
    env["ROB2_QUALIFICATION_UTC_NOW"] = QUALIFICATION_TIME
    env["ROB2_QUALIFICATION_RELEASE_FIXTURE"] = "installed-replay-v1"
    if absent_fixtures:
        env["ROB2_QUALIFICATION_ABSENT_FIXTURES"] = ",".join(absent_fixtures)
    if network_guard is not None:
        env["PYTHONPATH"] = str(network_guard)
        env["ROB2_QUALIFICATION_NETWORK_LOG"] = str(network_guard / "outbound.jsonl")
    paths = [str(environment / ("Scripts" if os.name == "nt" else "bin"))]
    if shim is not None:
        paths = [str(shim)]
    env["PATH"] = os.pathsep.join(paths + [env.get("PATH", "")])
    if os.name == "nt" and shim is not None:
        env["PATHEXT"] = ".CMD;.EXE;.BAT;.COM"
    return env


def _write_network_guard(directory: Path) -> Path:
    """Install a subprocess-only guard for non-loopback socket connections."""
    directory.mkdir()
    (directory / "sitecustomize.py").write_text(
        """import errno
import ipaddress
import json
import os
import socket

_LOG = os.environ.get("ROB2_QUALIFICATION_NETWORK_LOG")
_CONNECT = socket.socket.connect
_CONNECT_EX = socket.socket.connect_ex
_CREATE_CONNECTION = socket.create_connection
_SENDTO = socket.socket.sendto


def _host_is_loopback(host):
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if not isinstance(host, str):
        return False
    if host.casefold() in {"localhost", "ip6-localhost", "ip6-loopback"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _allowed(sock, address):
    if sock.family == getattr(socket, "AF_UNIX", None):
        return True
    return isinstance(address, tuple) and bool(address) and _host_is_loopback(address[0])


def _record(address):
    if _LOG:
        with open(_LOG, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"destination": repr(address)}, sort_keys=True) + "\\n")


def _deny(address):
    _record(address)
    raise OSError(errno.EACCES, "qualification blocks non-loopback outbound network", address)


def guarded_connect(sock, address):
    if not _allowed(sock, address):
        _deny(address)
    return _CONNECT(sock, address)


def guarded_connect_ex(sock, address):
    if not _allowed(sock, address):
        _record(address)
        return errno.EACCES
    return _CONNECT_EX(sock, address)


def guarded_create_connection(address, *args, **kwargs):
    if not (isinstance(address, tuple) and bool(address) and _host_is_loopback(address[0])):
        _deny(address)
    return _CREATE_CONNECTION(address, *args, **kwargs)


def guarded_sendto(sock, data, address):
    if not _allowed(sock, address):
        _deny(address)
    return _SENDTO(sock, data, address)


socket.socket.connect = guarded_connect
socket.socket.connect_ex = guarded_connect_ex
socket.create_connection = guarded_create_connection
socket.socket.sendto = guarded_sendto
""",
        encoding="utf-8",
    )
    return directory / "outbound.jsonl"


def _network_guard_receipt(log: Path) -> dict[str, object]:
    attempts = (
        [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        if log.is_file()
        else []
    )
    if attempts:
        raise RuntimeError(f"qualification observed outbound network attempts: {attempts!r}")
    serialized = json.dumps(attempts, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "non_loopback_outbound_attempts": attempts,
        "normalized_attempts_hash": _sha256(serialized),
    }


def _write_uvx_shim(directory: Path, server: Path) -> None:
    directory.mkdir()
    driver = Path(__file__).resolve()
    if os.name == "nt":
        (directory / "uvx.cmd").write_text(
            f'@echo off\r\n"{sys.executable}" "{driver}" --uvx-shim "{server}" %*\r\n',
            encoding="utf-8",
        )
        return
    shim = directory / "uvx"
    program = (
        f"#!{sys.executable}\nimport os\nos.execv(\n"
        f"    {sys.executable!r},\n"
        "    [\n"
        f'        {sys.executable!r}, {str(driver)!r}, "--uvx-shim",\n'
        f"        {str(server)!r}, *os.sys.argv[1:],\n"
        "    ],\n"
        f")\n"
    )
    shim.write_text(program, encoding="utf-8")
    shim.chmod(0o755)


def _uvx_shim(server: str, args: list[str]) -> int:
    if tuple(args) != EXPECTED_UVX_ARGS:
        raise SystemExit(f"unexpected locked uvx arguments: {args!r}")
    os.execv(server, [server])
    return 1


def _adapter_launch_receipts(project: Path, environment: dict[str, str]) -> dict[str, object]:
    """Launch each installed Harness configuration through its own external command seam."""
    import anyio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    codex = tomllib.loads((project / ".codex" / "config.toml").read_text(encoding="utf-8"))
    claude = json.loads((project / ".mcp.json").read_text(encoding="utf-8"))
    configurations = {
        "codex": codex["mcp_servers"]["rob2-kit"],
        "claude": claude["mcpServers"]["rob2-kit"],
    }

    async def inspect(host: str, configuration: dict[str, object]) -> tuple[str, dict[str, object]]:
        configured_command = configuration["command"]
        args = configuration["args"]
        assert isinstance(configured_command, str) and isinstance(args, list)
        command_args = cast(list[str], args)
        parameters = StdioServerParameters(
            command=configured_command, args=command_args, cwd=project, env=environment
        )
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
        return host, {
            "configured_command": configured_command,
            "executed_command": configured_command,
            "args": command_args,
            "tools": sorted(tool.name for tool in tools.tools),
        }

    async def inspect_all() -> dict[str, object]:
        results = await asyncio.gather(
            *(inspect(host, config) for host, config in configurations.items())
        )
        return dict(results)

    import asyncio

    # The MCP SDK resolves Windows command names before applying
    # ``StdioServerParameters.env``.  Scope its resolver PATH to this
    # candidate invocation so the configured `uvx` name resolves to the
    # frozen-wheel compatibility launcher rather than any host-global uvx.
    original_path = os.environ.get("PATH")
    os.environ["PATH"] = environment["PATH"]
    try:
        return anyio.run(inspect_all)
    finally:
        if original_path is None:
            del os.environ["PATH"]
        else:
            os.environ["PATH"] = original_path


def _injected_fault_receipts(
    server: Path, project: Path, environment: dict[str, str]
) -> dict[str, dict[str, object]]:
    """Exercise injected dependencies through complete public stdio journeys."""

    original = os.environ.copy()
    faults: dict[str, dict[str, object]] = {}
    try:
        os.environ.update(environment)
        for scenario in ("input-change", "integrity", "writer", "report-failure"):
            root = project.parent / f"qualification-{scenario}"
            if root.exists():
                shutil.rmtree(root)
            if scenario in {"writer", "report-failure"}:
                os.environ["ROB2_QUALIFICATION_INJECTED_FAULT"] = scenario
            else:
                os.environ.pop("ROB2_QUALIFICATION_INJECTED_FAULT", None)
            observed = _journey(
                server,
                root,
                root.with_suffix(".json"),
                restart_after_source=False,
                expected_fault=scenario,
            )
            if observed is None or scenario not in observed:
                raise AssertionError(f"installed {scenario} dependency did not surface its fault")
            faults.update(observed)
    finally:
        os.environ.clear()
        os.environ.update(original)
    return faults


def _blank_pdf() -> bytes:
    stream = (
        b"BT /F1 12 Tf 100 700 Td (Methods) Tj "
        b"0 -70 Td (Participants were enrolled at two centres.) Tj "
        b"0 -70 Td (Allocation was concealed in the randomized trial.) Tj "
        b"0 -70 Td (Outcome assessors recorded vital status at 30 days.) Tj "
        b"0 -70 Td (All randomized participants were analysed.) Tj "
        b"0 -70 Td (Results are reported below.) Tj ET"
    )
    objects = (
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    )
    data = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, content in enumerate(objects, start=1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode() + content + b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    data.extend(b"0000000000 65535 f \n")
    for offset in offsets:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(data)


def _sha256(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _durable_state_digest(project: Path) -> str:
    """Digest durable state before and after a rejected public MCP request."""

    from rob2_kit.storage import ArtifactStore, WorkflowLedger

    state = project / ".rob2"
    ledger = WorkflowLedger(state / "ledger.sqlite3", ArtifactStore(state / "artifacts"))
    logical_state = {
        "events": [event.model_dump(mode="json") for event in ledger.events()],
        "revisions": [revision.model_dump(mode="json") for revision in ledger.current_revisions()],
        "checkpoints": [checkpoint.model_dump(mode="json") for checkpoint in ledger.checkpoints()],
        "artifacts": {
            str(path.relative_to(state / "artifacts")): _sha256(path.read_bytes())
            for path in sorted((state / "artifacts").rglob("*"))
            if path.is_file()
        },
    }
    return _sha256(json.dumps(logical_state, sort_keys=True, separators=(",", ":")).encode())


def _journey_receipt(project: Path) -> dict[str, object]:
    """Collect the complete deterministic artifacts after a terminal journey."""
    from rob2_kit.storage import ArtifactStore, WorkflowLedger

    report_base = project / "output" / "report-bundle"
    # Result bundles are rooted at runs/<run>/trials/<trial>/results/<result>.
    # Discover the manifest rather than assuming the historical flat root.
    manifests = []
    for candidate in report_base.rglob("manifest.json"):
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if isinstance(payload, dict) and isinstance(payload.get("files"), dict):
            manifests.append((candidate.parent, payload))
    if len(manifests) != 1:
        raise AssertionError(f"expected one result manifest, found {len(manifests)}")
    report, manifest = manifests[0]
    report_hashes = {
        name: _sha256((report / name).read_bytes()) for name in sorted(manifest["files"])
    }
    assert report_hashes == manifest["files"]
    ledger = WorkflowLedger(
        project / ".rob2" / "ledger.sqlite3", ArtifactStore(project / ".rob2" / "artifacts")
    )
    ledger_state = {
        "current_revisions": [
            revision.model_dump(mode="json") for revision in ledger.current_revisions()
        ],
        "checkpoints": [checkpoint.model_dump(mode="json") for checkpoint in ledger.checkpoints()],
        "events": [event.model_dump(mode="json") for event in ledger.events()],
    }
    ledger_bytes = json.dumps(ledger_state, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assessment = (report / "assessment.json").read_bytes()
    archive = (report / "verification-archive.rob2.zip").read_bytes()
    return {
        "manifest": manifest,
        "report_hashes": report_hashes,
        "canonical_assessment_hash": _sha256(assessment),
        "normalized_ledger_hash": _sha256(ledger_bytes),
        "semantic_invariants": {
            "overall_judgment": manifest["overall_judgment"],
            "assessment_revision_id": manifest["assessment_revision_id"],
            "domain_judgments": manifest["domains"],
            "result_report": "assessment.html",
        },
        # Keep the semantic objects themselves, not only a hash.  This makes
        # a golden diff identify a changed workflow event, revision, evidence
        # answer, decision trace, machine report, or generated asset.
        "durable_semantics": {
            "workflow": ledger_state,
            "assessment": json.loads(assessment),
            "report_machine_data": {
                "assessment_summary": json.loads(
                    (report / "assessment.summary.json").read_text(encoding="utf-8")
                ),
                "visual_citations": json.loads(
                    (report / "visual-citations.json").read_text(encoding="utf-8")
                ),
            },
            "assets": report_hashes,
            "archive_digest": _sha256(archive),
        },
        "semantic_trace": {
            "workflow_events": [event.operation for event in ledger.events()],
            "checkpoints": [
                checkpoint.model_dump(mode="json") for checkpoint in ledger.checkpoints()
            ],
            "revisions": [
                revision.model_dump(mode="json") for revision in ledger.current_revisions()
            ],
        },
    }


def _installed_replay_receipt(
    source_root: Path, journey: dict[str, object], *, accept: bool = False
) -> dict[str, object]:
    """Freeze the model-free installed-wheel replay contract.

    The default invocation omits the explicit local acceptance flag. CI can
    therefore only compare the committed semantic contract; changing it
    requires the explicit local ``--accept-replay-golden`` action.
    """

    from rob2_kit.evaluation import accept_golden

    matrix = dict(cast(dict[str, dict[str, object]], journey["fault_matrix"]))
    matrix.update(cast(dict[str, dict[str, object]], journey["injected_faults"]))
    matrix["interruption"] = {
        "operation": "installed stdio reconnect",
        "mutation_free": True,
        "response_class": "operational",
        "legal_replacement_action": "reconnect and continue the Current run",
    }
    required_faults = {
        "malformed",
        "unknown",
        "invalid",
        "wrong-state",
        "stale",
        "cross-scope",
        "retry",
        "writer",
        "retrieval-condition",
        "interruption",
        "input-change",
        "report-failure",
        "integrity",
    }
    if set(matrix) != required_faults:
        missing = sorted(required_faults - set(matrix))
        raise AssertionError(f"installed fault matrix is incomplete: {missing}")
    fixture_replays = cast(dict[str, dict[str, object]], journey["fixture_replays"])
    all_absent = cast(dict[str, object], journey["all_optional_absent_sequentially"])
    fixture_degradation = {
        "full": {"core_outcome": "complete", "degradation": "none"},
        **{
            name: {
                "core_outcome": replay["core_outcome"],
                "degradation": replay["degradation"],
                "absent": replay["absent"],
            }
            for name, replay in sorted(fixture_replays.items())
        },
        "all_optional_absent_sequentially": {
            "core_outcome": all_absent["core_outcome"],
            "degradation": all_absent["degradation"],
            "absent": all_absent["absent"],
        },
    }
    receipt = {
        "schema_version": 1,
        "seam": "installed-wheel-real-stdio-mcp",
        "fixture_degradation": fixture_degradation,
        "matrix": matrix,
        "canonical": journey,
    }
    golden = source_root / "tests" / "public_fixtures" / "traces" / "installed-replay.golden.json"
    accept_golden(golden, receipt, accept=accept)
    return receipt


def _journey(
    server: Path,
    project: Path,
    receipt_path: Path,
    *,
    restart_after_source: bool = True,
    expected_fault: str | None = None,
    resume_only: bool = False,
    stop_after_source: bool = False,
) -> dict[str, dict[str, object]] | None:
    """Run the full five-domain journey against the installed stdio entry point."""
    import anyio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    domains = {
        "domain:randomization": (
            "sq:randomization:sequence",
            "sq:randomization:concealment",
            "sq:randomization:baseline-imbalance",
        ),
        "domain:deviations": (
            "sq:deviations:participants-aware",
            "sq:deviations:personnel-aware",
            "sq:deviations:context-deviations",
            "sq:deviations:affected-outcome",
            "sq:deviations:balanced",
            "sq:deviations:appropriate-analysis",
            "sq:deviations:substantial-impact",
        ),
        "domain:missing": (
            "sq:missing:data-available",
            "sq:missing:evidence-unbiased",
            "sq:missing:true-value-dependent",
            "sq:missing:likely-dependent",
        ),
        "domain:measurement": (
            "sq:measurement:method-inappropriate",
            "sq:measurement:differential",
            "sq:measurement:assessor-aware",
            "sq:measurement:influence-possible",
            "sq:measurement:influence-likely",
        ),
        "domain:selection": (
            "sq:selection:prespecified-analysis",
            "sq:selection:multiple-measurements",
            "sq:selection:multiple-analyses",
        ),
    }
    answers = {
        "sq:randomization:sequence": "yes",
        "sq:randomization:concealment": "yes",
        "sq:randomization:baseline-imbalance": "no",
        "sq:deviations:participants-aware": "no",
        "sq:deviations:personnel-aware": "no",
        "sq:deviations:context-deviations": "no",
        "sq:deviations:affected-outcome": "no",
        "sq:deviations:balanced": "no",
        "sq:deviations:appropriate-analysis": "yes",
        "sq:deviations:substantial-impact": "no",
        "sq:missing:data-available": "yes",
        "sq:missing:evidence-unbiased": "no",
        "sq:missing:true-value-dependent": "no",
        "sq:missing:likely-dependent": "no",
        "sq:measurement:method-inappropriate": "no",
        "sq:measurement:differential": "no",
        "sq:measurement:assessor-aware": "no",
        "sq:measurement:influence-possible": "no",
        "sq:measurement:influence-likely": "no",
        "sq:selection:prespecified-analysis": "yes",
        "sq:selection:multiple-measurements": "no",
        "sq:selection:multiple-analyses": "no",
    }
    use_primary_report_for_all_domains = True
    trial = project / "input" / "trial-a"
    if not resume_only:
        trial.mkdir(parents=True)
        (trial / "report.pdf").write_bytes(_blank_pdf())
        (trial / "trial.yaml").write_text("nct: NCT00000001\n", encoding="utf-8")
        (project / "rob2.yaml").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "results": [
                        {
                            "result": {
                                "result_id": "result:trial-a-mortality",
                                "trial_id": "trial:trial-a",
                                "randomization_id": "randomization:trial-a",
                                "comparison": {
                                    "experimental_arm_id": "arm:treatment",
                                    "comparator_arm_id": "arm:control",
                                },
                                "effect_of_interest": "assignment",
                                "outcome_construct": "Mortality",
                                "measurement_instrument": "Vital status",
                                "time_point": "30 days",
                                "analysis_population": "Intention to treat",
                                "analysis_model": "Risk ratio",
                                "effect_measure": "RR",
                                "source_locator": "source:trial-a-1#result",
                            },
                            "estimate": {"value": "0.8"},
                            "provenance_note": "Synthetic qualification Result.",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    trace_calls: list[dict[str, object]] = []
    fault_matrix: dict[str, dict[str, object]] = {}

    async def call(client, name: str, arguments: dict[str, object]):
        result = await client.call_tool(name, arguments)
        response = result.structured_content
        trace_calls.append(
            {
                "name": name,
                "arguments": arguments,
                "response": (
                    response if isinstance(response, dict) else {"is_error": result.is_error}
                ),
            }
        )
        return result

    async def rejected_probe(
        client, scenario: str, name: str, arguments: dict[str, object]
    ) -> None:
        """Exercise a real rejected MCP request and prove it did not mutate state."""

        before = _durable_state_digest(project)
        result = await call(client, name, arguments)
        after = _durable_state_digest(project)
        if before != after:
            raise AssertionError(f"{scenario} rejected MCP request mutated durable state")
        response = trace_calls[-1]["response"]
        assert isinstance(response, dict)
        if response.get("committed") is True:
            raise AssertionError(f"{scenario} unexpectedly committed")
        error = response.get("error")
        next_action = response.get("next_action") or response.get("next_actions")
        if not next_action and not result.is_error:
            raise AssertionError(f"{scenario} rejection omitted a legal replacement action")
        fault_matrix[scenario] = {
            "operation": name,
            "mutation_free": True,
            "response_class": (
                error.get("error_class", "retrieval") if isinstance(error, dict) else "protocol"
            ),
            "legal_replacement_action": next_action,
        }

    async def session():
        return stdio_client(
            StdioServerParameters(
                command=str(server),
                args=[],
                cwd=project,
                env=dict(os.environ),
            )
        )

    async def finish_domains(client, run_id: str) -> bool:
        for index, (domain, questions) in enumerate(domains.items()):
            evidence = (await call(client, "continue_run", {"run_id": run_id})).structured_content
            assert evidence is not None
            context = (
                await call(
                    client,
                    "get_work_context",
                    {
                        "run_id": run_id,
                        "work_token": evidence["work_item"]["work_token"],
                    },
                )
            ).structured_content
            assert context is not None and context["context"]["domain_context"] is not None
            active_questions = tuple(context["context"]["domain_context"]["active_question_ids"])
            if index == 0:
                issued_token = evidence["work_item"]["work_token"]
                await rejected_probe(
                    client,
                    "invalid",
                    "search_evidence",
                    {
                        "run_id": run_id,
                        "work_token": issued_token,
                        "query": {"terms": ["allocation"]},
                        "sq_id": "sq:qualification-invalid",
                    },
                )
                await rejected_probe(
                    client,
                    "wrong-state",
                    "submit_domain_answers",
                    {
                        "run_id": run_id,
                        "work_token": issued_token,
                        "result_id": "result:trial-a-mortality",
                        "domain_id": domain,
                        "answers": [
                            {
                                "question_id": questions[0],
                                "answer": answers[questions[0]],
                                "rationale": "Qualification wrong-state probe.",
                            }
                        ],
                        "contract_version": "1.2.0",
                    },
                )
                await rejected_probe(
                    client,
                    "cross-scope",
                    "submit_domain_evidence",
                    {
                        "run_id": run_id,
                        "work_token": issued_token,
                        "result_id": "result:other",
                        "domain_id": "domain:other",
                        "contract_version": "1.2.0",
                    },
                )
                await rejected_probe(
                    client,
                    "retrieval-condition",
                    "read_evidence",
                    {
                        "run_id": run_id,
                        "location_handle": "loc:qualification-unknown",
                        "work_token": issued_token,
                        "sq_id": questions[0],
                        "result_id": "result:trial-a-mortality",
                    },
                )
            passages: list[dict[str, object]] = []
            coverage_receipts: list[dict[str, object]] = []
            # The fixed primary report is reviewed separately for every SQ,
            # including when the registry fixture is deliberately unavailable.
            # This preserves complete five-domain terminal exercise without
            # misrepresenting unavailable registry coverage as no-information.
            if use_primary_report_for_all_domains:
                from rob2_kit.domain.canonical import canonical_hash
                from rob2_kit.domain.results import ResultSpecRevision
                from rob2_kit.domain.revisions import RecordReference
                from rob2_kit.domain.sources import TrialSourceInventory
                from rob2_kit.evidence import (
                    SearchCoverageReceipt,
                    SearchResultDisposition,
                    SearchResultDispositionKind,
                    SourceSearchCoverage,
                    SourceSearchState,
                )
                from rob2_kit.storage import ArtifactStore, WorkflowLedger

                state = project / ".rob2"
                store = ArtifactStore(state / "artifacts")
                ledger = WorkflowLedger(state / "ledger.sqlite3", store)
                prepared_revision = next(
                    revision
                    for revision in ledger.current_revisions()
                    if revision.checkpoint == "checkpoint:run-prepared"
                )
                prepared_artifact = json.loads(
                    store.read(prepared_revision.artifact_hash).decode("utf-8")
                )
                inventory = TrialSourceInventory.model_validate(
                    prepared_artifact["proposal"]["initialization"]["trials"][0]["inventory"]
                )
                result_revision = next(
                    revision
                    for revision in ledger.current_revisions()
                    if revision.checkpoint and revision.checkpoint.startswith("checkpoint:result-")
                )
                result_artifact = json.loads(
                    store.read(result_revision.artifact_hash).decode("utf-8")
                )
                result_spec = ResultSpecRevision.model_validate(result_artifact["result_spec"])
                result_ref = RecordReference(
                    entity_id=result_spec.entity_id,
                    revision_id=result_spec.revision_id,
                    content_hash=canonical_hash(result_spec),
                )
                inventory_suffix = hashlib.sha256(
                    (
                        f"{run_id}|result:trial-a-mortality|{result_ref.content_hash}|"
                        "source-inventory"
                    ).encode()
                ).hexdigest()[:24]
                inventory_ref = RecordReference(
                    entity_id="source-inventory:trial-a-mortality",
                    revision_id=f"revision:source-inventory-{inventory_suffix}",
                    content_hash=canonical_hash(inventory),
                )
                parse_hashes = tuple(
                    sorted(
                        parse.output_hash
                        for source in inventory.sources
                        for parse in source.parse_records
                    )
                )
                hit = None
                for question_index, question in enumerate(questions):
                    seed_family = "seed:" + question.removeprefix("sq:").replace(":", "-")
                    pass_specs = (
                        ("guidance_seed", seed_family, ("Allocation",)),
                        ("trial_follow_up", None, ("participants",)),
                        ("contradiction", None, ("open",)),
                    )
                    responses: list[dict[str, object]] = []
                    for pass_kind, seed, terms in pass_specs:
                        arguments: dict[str, object] = {
                            "run_id": run_id,
                            "work_token": evidence["work_item"]["work_token"],
                            "sq_id": question,
                            "result_id": "result:trial-a-mortality",
                            "query": {"terms": list(terms)},
                            "pass_kind": pass_kind,
                        }
                        if seed is not None:
                            arguments["seed_family"] = seed
                        searched = await call(client, "search_evidence", arguments)
                        response = searched.structured_content
                        if response is None or response.get("executed_query") is None:
                            raise AssertionError(
                                "release search did not produce an executed query: "
                                f"response={response!r}, result={searched!r}"
                            )
                        responses.append(response)
                    returned_ids = tuple(
                        dict.fromkeys(
                            unit_id
                            for response in responses
                            for unit_id in response["executed_query"]["returned_unit_ids"]
                        )
                    )
                    dispositions = tuple(
                        SearchResultDisposition(
                            unit_id=unit_id,
                            kind=(
                                SearchResultDispositionKind.RETAINED_CANDIDATE
                                if question_index == 0 and hit and unit_id == hit["unit"]["unit_id"]
                                else SearchResultDispositionKind.IRRELEVANT
                            ),
                            candidate_id=(
                                unit_id
                                if question_index == 0 and hit and unit_id == hit["unit"]["unit_id"]
                                else None
                            ),
                        )
                        for unit_id in returned_ids
                    )
                    receipt = SearchCoverageReceipt(
                        receipt_id=f"coverage:qualification-{question_index}",
                        sq_id=question,
                        snapshot_hash=responses[0]["page"]["snapshot_hash"],
                        policy_id=responses[0]["page"]["policy_id"],
                        policy_hash=responses[0]["page"]["policy_hash"],
                        result_spec=result_ref,
                        source_inventory=inventory_ref,
                        parse_record_hashes=parse_hashes,
                        guidance_release_id="guidance:rob2-2019.1",
                        required_seed_families=(seed_family,),
                        completed_seed_families=(seed_family,),
                        completed_passes=tuple(item[0] for item in pass_specs),
                        executed_queries=tuple(
                            response["executed_query"] for response in responses
                        ),
                        returned_unit_ids=returned_ids,
                        result_dispositions=dispositions,
                        sources=tuple(
                            SourceSearchCoverage(
                                source_id=source.source_id,
                                state=(
                                    SourceSearchState.SEARCHED
                                    if source.artifact_hash is not None
                                    else SourceSearchState.UNOBTAINED
                                ),
                                sufficiently_readable=source.artifact_hash is not None,
                                artifact_hash=source.artifact_hash,
                                parse_record_hashes=tuple(
                                    parse.output_hash for parse in source.parse_records
                                ),
                                limitations=(
                                    ()
                                    if source.artifact_hash is not None
                                    else ("declared registry source was unavailable",)
                                ),
                            )
                            for source in inventory.sources
                        ),
                        inventory_source_ids=tuple(
                            source.source_id for source in inventory.sources
                        ),
                        coverage_limits=inventory.coverage_limitations,
                        traversal_complete=True,
                        interrupted=False,
                    )
                    proof = receipt.model_dump(mode="json")
                    proof["recorder_proof"] = None
                    completed_receipt = receipt.model_copy(
                        update={"recorder_proof": canonical_hash(proof)}
                    )
                    coverage_receipts.append(completed_receipt.model_dump(mode="json"))
                # Retrieval intentionally remains broad: source-authored
                # candidates are visible before attributable review, so the
                # first lexical hit is not necessarily for this Domain.  Walk
                # the public continuation until the fixture's separately
                # scoped canonical unit is encountered rather than borrowing
                # a same-text unit from another Domain.
                cursor: str | None = None
                read_receipts: dict[str, str] = {}
                while hit is None:
                    searched = await call(
                        client,
                        "search_evidence",
                        {
                            "run_id": run_id,
                            "work_token": evidence["work_item"]["work_token"],
                            "sq_id": questions[0],
                            "result_id": "result:trial-a-mortality",
                            "query": {"terms": ["Allocation"]},
                            **({"cursor": cursor} if cursor is not None else {}),
                        },
                    )
                    response = searched.structured_content
                    assert response is not None
                    for candidate in response["page"]["hits"]:
                        read = await call(
                            client,
                            "read_evidence",
                            {
                                "run_id": run_id,
                                "location_handle": candidate["location_handle"],
                                "work_token": evidence["work_item"]["work_token"],
                                "sq_id": questions[0],
                                "result_id": "result:trial-a-mortality",
                            },
                        )
                        read_content = read.structured_content
                        if read_content is None:
                            continue
                        hit = candidate
                        read_receipts[questions[0]] = read_content["read_view_receipt"]
                        break
                    cursor = response["page"].get("next_cursor")
                    if cursor is None and hit is None:
                        raise AssertionError(
                            "release fixture omitted its Domain-scoped canonical unit"
                        )
                assert hit is not None
                unit_id = hit["unit"]["unit_id"]
                for question in questions:
                    if question in read_receipts:
                        continue
                    read = await call(
                        client,
                        "read_evidence",
                        {
                            "run_id": run_id,
                            "location_handle": hit["location_handle"],
                            "work_token": evidence["work_item"]["work_token"],
                            "sq_id": question,
                            "result_id": "result:trial-a-mortality",
                        },
                    )
                    if read.structured_content is None:
                        raise AssertionError("canonical Trial unit could not be read")
                    read_receipts[question] = read.structured_content["read_view_receipt"]
                passages = [
                    {
                        "unit_id": unit_id,
                        "candidate_id": unit_id,
                        "span_start": hit["projection"]["start"],
                        "span_end": hit["projection"]["end"],
                        "claim_type": "claim-type:trial-report",
                        "question_ids": list(questions),
                    }
                ]
            else:
                # Coverage is recorder-owned in the 1.1 contract.  Domains
                # without a retained passage still need their own completed
                # Search passes before they can establish no-information.
                for question in questions:
                    seed_family = "seed:" + question.removeprefix("sq:").replace(":", "-")
                    for pass_kind, seed, terms in (
                        ("guidance_seed", seed_family, ("Allocation",)),
                        ("trial_follow_up", None, ("participants",)),
                        ("contradiction", None, ("open",)),
                    ):
                        cursor: str | None = None
                        while True:
                            arguments: dict[str, object] = {
                                "run_id": run_id,
                                "work_token": evidence["work_item"]["work_token"],
                                "sq_id": question,
                                "result_id": "result:trial-a-mortality",
                                "query": {"terms": list(terms)},
                                "pass_kind": pass_kind,
                            }
                            if seed is not None:
                                arguments["seed_family"] = seed
                            if cursor is not None:
                                arguments["cursor"] = cursor
                            searched = await call(client, "search_evidence", arguments)
                            response = searched.structured_content
                            assert response is not None and response["executed_query"] is not None
                            cursor = response["page"].get("next_cursor")
                            if cursor is None:
                                break
                        if pass_kind == "contradiction":
                            assert response["coverage_progress"]["coverage_complete"], response[
                                "coverage_progress"
                            ]
            committed = await call(
                client,
                "submit_domain_evidence",
                {
                    "run_id": run_id,
                    "work_token": evidence["work_item"]["work_token"],
                    "idempotency_key": f"qualification:evidence:{index}",
                    "contract_version": "1.2.0",
                    "result_id": "result:trial-a-mortality",
                    "domain_id": domain,
                    "passages": passages,
                    "no_information_basis": not passages,
                    "review_revisions": (
                        [
                            {
                                "entity_id": f"evidence-review:qualification:{index}:{question}",
                                "revision_id": (
                                    f"revision:evidence-review:qualification:{index}:{question}:1"
                                ),
                                "actor": {
                                    "kind": "agent",
                                    "actor_id": "actor:qualification",
                                    "display_name": "Release qualification",
                                },
                                "observed_at": "2026-01-01T00:00:00Z",
                                "candidate_id": unit_id,
                                "result_id": "result:trial-a-mortality",
                                "domain_id": domain,
                                "sq_id": question,
                                "spans": [
                                    {
                                        "read_view_receipt": read_receipts[question],
                                        "span_start": hit["projection"]["start"],
                                        "span_end": hit["projection"]["end"],
                                        "trial_attribution": "active",
                                        "disposition": "supporting",
                                        "rationale": "Qualification source span.",
                                        "attribution_rationale": "Issued bounded context identifies the active Trial.",
                                    }
                                ],
                            }
                            for question in questions
                        ]
                        if passages
                        else []
                    ),
                },
            )
            assert committed.structured_content and committed.structured_content["committed"], (
                committed.structured_content or committed.content
            )
            answer = (await call(client, "continue_run", {"run_id": run_id})).structured_content
            assert answer is not None
            # get_work_context reports activation against empty answers.  The
            # fixed low-risk measurement responses then activate the assessor
            # question, which must be supplied in the same atomic answer
            # request (the public submit boundary reevaluates conditions).
            answer_question_ids = tuple(
                dict.fromkeys(
                    active_questions
                    + (
                        ("sq:measurement:assessor-aware",)
                        if domain == "domain:measurement"
                        else ()
                    )
                )
            )
            committed = await call(
                client,
                "submit_domain_answers",
                {
                    "run_id": run_id,
                    "work_token": answer["work_item"]["work_token"],
                    "idempotency_key": f"qualification:answers:{index}",
                    "contract_version": "1.0.0",
                    "result_id": "result:trial-a-mortality",
                    "domain_id": domain,
                    "answers": [
                        {
                            "question_id": question,
                            "answer": answers[question] if passages else "no_information",
                            "rationale": "Frozen synthetic qualification evidence.",
                        }
                        for question in answer_question_ids
                    ],
                },
            )
            if expected_fault == "report-failure" and not (
                committed.structured_content and committed.structured_content.get("committed")
            ):
                fault_matrix["report-failure"] = {
                    "operation": "submit_domain_answers",
                    "mutation_free": True,
                    "response_class": "operational",
                    "legal_replacement_action": "continue_run",
                }
                return False
            assert committed.structured_content and committed.structured_content["committed"], (
                committed.structured_content or committed.content
            )
        complete = (await call(client, "continue_run", {"run_id": run_id})).structured_content
        if complete and complete["run_state"] == "complete":
            return True
        if expected_fault == "report-failure":
            error = complete.get("error") if isinstance(complete, dict) else None
            fault_matrix["report-failure"] = {
                "operation": "continue_run",
                "mutation_free": True,
                "response_class": "operational",
                "legal_replacement_action": (
                    error.get("recovery") if isinstance(error, dict) else "continue_run"
                ),
            }
            return False
        raise AssertionError("the normal installed replay did not complete")

    async def run() -> None:
        if expected_fault == "integrity":
            ledger_path = project / ".rob2" / "ledger.sqlite3"
            ledger_path.parent.mkdir(parents=True, exist_ok=True)
            ledger_path.write_bytes(b"not a sqlite ledger")
        async with await session() as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                inventory = await client.list_tools()
                assert tuple(tool.name for tool in inventory.tools) == CANONICAL_TOOL_NAMES
                prepared = (
                    await call(
                        client,
                        "prepare_run",
                        {
                            "project_root": str(project),
                            "authorized": not resume_only,
                        },
                    )
                ).structured_content
                assert prepared is not None
                if resume_only:
                    run_id = prepared["run_id"]
                    if prepared.get("run_state") == "complete":
                        return
                    if prepared.get("condition") == "confirmation_required":
                        proposal = prepared.get("proposal")
                        if not isinstance(proposal, dict):
                            raise AssertionError(
                                "resumed confirmation-required Run omitted its proposal"
                            )
                        proposed = (
                            await call(
                                client,
                                "submit_run_proposal",
                                {
                                    "run_id": run_id,
                                    "proposal_token": proposal["proposal_token"],
                                    "idempotency_key": "qualification:proposal",
                                    "contract_version": "1.0.0",
                                },
                            )
                        ).structured_content
                        assert proposed is not None
                        await call(
                            client,
                            "confirm_run_definition",
                            {
                                "run_id": run_id,
                                "proposal_token": proposed["proposal"]["proposal_token"],
                                "idempotency_key": "qualification:confirm",
                                "confirmed_by": {
                                    "kind": "human",
                                    "actor_id": "actor:qualification",
                                    "display_name": "Qualification",
                                },
                                "contract_version": "1.0.0",
                            },
                        )
                    completed = await finish_domains(client, run_id)
                    if not completed:
                        raise AssertionError("resumed installed Run did not complete")
                    return
                if expected_fault == "integrity":
                    if prepared.get("run_state") != "integrity_failed":
                        raise AssertionError("corrupt installed ledger was not rejected")
                    fault_matrix["integrity"] = {
                        "operation": "prepare_run",
                        "mutation_free": True,
                        "response_class": "operational",
                        "legal_replacement_action": prepared["integrity"]["recovery"],
                    }
                    return
                if expected_fault == "input-change":
                    before = _durable_state_digest(project)
                    (trial / "report.pdf").write_bytes(_blank_pdf() + b"changed")
                    changed = (
                        await call(client, "prepare_run", {"project_root": str(project)})
                    ).structured_content
                    if _durable_state_digest(project) != before:
                        raise AssertionError("unapproved input change mutated the ledger")
                    if not changed or (
                        changed.get("error", {}).get("code") != "authorization_required"
                    ):
                        raise AssertionError("input change did not require explicit reconciliation")
                    fault_matrix["input-change"] = {
                        "operation": "prepare_run",
                        "mutation_free": True,
                        "response_class": changed["error"]["error_class"],
                        "legal_replacement_action": changed["error"]["recovery"],
                    }
                    return
                invalid_token = {
                    "token": "work-token:qualification-invalid",
                    "run_id": prepared["run_id"],
                    "work_item_id": "work-item:qualification-invalid",
                    "operation": "submit_domain_evidence",
                    "dependency_fingerprint": "sha256:" + "0" * 64,
                    "result_id": "result:trial-a-mortality",
                    "domain_id": "domain:randomization",
                }
                await rejected_probe(
                    client,
                    "malformed",
                    "search_evidence",
                    {
                        "run_id": prepared["run_id"],
                        "work_token": invalid_token,
                        "query": {"terms": []},
                        "sq_id": "sq:randomization:sequence",
                    },
                )
                await rejected_probe(
                    client,
                    "unknown",
                    "continue_run",
                    {"run_id": "run:" + "0" * 24},
                )
                # Source-role review (#119) now resolves before submit_run_proposal,
                # issued as a work item while the Run still awaits confirmation.
                work = (
                    await call(client, "continue_run", {"run_id": prepared["run_id"]})
                ).structured_content
                assert work is not None
                result = await call(
                    client,
                    "submit_source_role_review",
                    {
                        "run_id": prepared["run_id"],
                        "work_token": work["work_item"]["work_token"],
                        "idempotency_key": "qualification:source",
                        "contract_version": "1.0.0",
                        "selections": [
                            {
                                "trial_id": "trial:trial-a",
                                "source_id": "source:trial-a-1",
                                "accepted": True,
                            }
                        ],
                    },
                )
                if expected_fault == "writer" and not (
                    result.structured_content and result.structured_content.get("committed")
                ):
                    response = result.structured_content or {}
                    error = response.get("error", {})
                    fault_matrix["writer"] = {
                        "operation": "submit_source_role_review",
                        "mutation_free": True,
                        "response_class": error.get("error_class"),
                        "legal_replacement_action": error.get("recovery"),
                    }
                    return
                assert result.structured_content and result.structured_content["committed"]
                before_retry = _durable_state_digest(project)
                retried = await call(
                    client,
                    "submit_source_role_review",
                    {
                        "run_id": prepared["run_id"],
                        "work_token": work["work_item"]["work_token"],
                        "contract_version": "1.0.0",
                        "selections": [
                            {
                                "trial_id": "trial:trial-a",
                                "source_id": "source:trial-a-1",
                                "accepted": True,
                            }
                        ],
                    },
                )
                if _durable_state_digest(project) != before_retry:
                    raise AssertionError("idempotent retry duplicated durable work")
                retry_response = trace_calls[-1]["response"]
                assert isinstance(retry_response, dict)
                fault_matrix["retry"] = {
                    "operation": "submit_source_role_review",
                    "mutation_free": True,
                    "response_class": "accepted" if not retried.is_error else "protocol",
                    "legal_replacement_action": "continue from the committed checkpoint",
                }
                stale_token = dict(work["work_item"]["work_token"])
                stale_token["token"] = "work-token:qualification-stale"
                await rejected_probe(
                    client,
                    "stale",
                    "submit_source_role_review",
                    {
                        "run_id": prepared["run_id"],
                        "work_token": stale_token,
                        "contract_version": "1.0.0",
                        "selections": [
                            {
                                "trial_id": "trial:trial-a",
                                "source_id": "source:trial-a-1",
                                "accepted": True,
                            }
                        ],
                    },
                )
                run_id = prepared["run_id"]
                if stop_after_source:
                    return
                proposed = (
                    await call(
                        client,
                        "submit_run_proposal",
                        {
                            "run_id": prepared["run_id"],
                            "proposal_token": prepared["proposal"]["proposal_token"],
                            "idempotency_key": "qualification:proposal",
                            "contract_version": "1.0.0",
                        },
                    )
                ).structured_content
                assert proposed is not None
                await call(
                    client,
                    "confirm_run_definition",
                    {
                        "run_id": prepared["run_id"],
                        "proposal_token": proposed["proposal"]["proposal_token"],
                        "idempotency_key": "qualification:confirm",
                        "confirmed_by": {
                            "kind": "human",
                            "actor_id": "actor:qualification",
                            "display_name": "Qualification",
                        },
                        "contract_version": "1.0.0",
                    },
                )
                if not restart_after_source:
                    completed = await finish_domains(client, run_id)
                    if not completed:
                        return
                    return
        async with await session() as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                rebound = (
                    await call(client, "prepare_run", {"project_root": str(project)})
                ).structured_content
                assert rebound and rebound["run_id"] == run_id
                completed = await finish_domains(client, run_id)
                if not completed:
                    return

    anyio.run(run)

    if expected_fault is not None:
        return fault_matrix

    from rob2_kit.evaluation.installed_replay import normalize_replay_trace

    if stop_after_source:
        from rob2_kit.storage import ArtifactStore, WorkflowLedger

        state = project / ".rob2"
        ledger = WorkflowLedger(state / "ledger.sqlite3", ArtifactStore(state / "artifacts"))
        prepared_response = trace_calls[0]["response"]
        assert isinstance(prepared_response, dict)
        active_work_token = next(
            (
                response["work_item"]["work_token"]
                for call_receipt in reversed(trace_calls)
                if isinstance((response := call_receipt["response"]), dict)
                and isinstance(response.get("work_item"), dict)
            ),
            None,
        )
        journey = {
            "run_id": prepared_response["run_id"],
            "run_state": "assessing",
            "events": [event.model_dump(mode="json") for event in ledger.events()],
            "revisions": [
                revision.model_dump(mode="json") for revision in ledger.current_revisions()
            ],
            "checkpoints": [
                checkpoint.model_dump(mode="json") for checkpoint in ledger.checkpoints()
            ],
            "active_work_token": active_work_token,
        }
    else:
        journey = _journey_receipt(project)

    final_state = "assessing" if stop_after_source else "complete"
    journey["normalized_trace"] = normalize_replay_trace(
        trace_calls,
        final={"run_state": final_state, "project_root": str(project)},
    )
    if stop_after_source or resume_only:
        journey["raw_trace_calls"] = trace_calls
    journey["fault_matrix"] = fault_matrix
    receipt_path.write_text(
        json.dumps(journey, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return None


def _qualify(
    wheel: Path,
    receipt_path: Path,
    source_root: Path,
    *,
    skip_full_suite: bool = False,
    accept_replay_golden: bool = False,
    replay_only: bool = False,
) -> None:
    STAGE_TIMINGS.clear()
    qualification_started = time.perf_counter()
    wheel = wheel.resolve()
    source_root = source_root.resolve()
    if wheel.is_dir():
        candidates = tuple(sorted(wheel.glob("rob2_kit-*.whl")))
        if len(candidates) != 1:
            raise ValueError(f"expected exactly one candidate wheel in {wheel}")
        wheel = candidates[0]
    if not wheel.is_file():
        raise ValueError(f"candidate wheel is missing: {wheel}")
    with tempfile.TemporaryDirectory(prefix="rob2-wheel-qualification-") as temporary:
        workspace = Path(temporary)
        environment = workspace / "candidate"
        python, rob2, mcp = _clean_environment(environment, source_root, wheel)
        network_log = _write_network_guard(workspace / "network-guard")
        candidate_env = _candidate_env(environment, network_guard=network_log.parent)
        if not skip_full_suite:
            _run(
                [str(python), "-m", "pytest", str(source_root / "tests")],
                cwd=source_root,
                env=candidate_env,
            )
        project = workspace / "project"
        first = json.loads(
            _run([str(rob2), "bootstrap", str(project)], cwd=workspace, env=candidate_env).stdout
        )
        second = json.loads(
            _run([str(rob2), "bootstrap", str(project)], cwd=workspace, env=candidate_env).stdout
        )
        assert first["status"] == "installed" and second["status"] == "already_installed"
        assert first["hosts"] == ["claude", "codex"]
        assert (project / ".codex" / "skills" / "rob2-init" / "SKILL.md").is_file()
        assert (project / ".claude" / "skills" / "rob2-assess" / "SKILL.md").is_file()
        shim = workspace / "shim"
        _write_uvx_shim(shim, mcp)
        checked_env = _candidate_env(environment, shim, network_log.parent)
        initial_doctor = json.loads(
            _run([str(rob2), "doctor", str(project)], cwd=workspace, env=checked_env).stdout
        )
        assert initial_doctor["ok"] is True
        original_codex_config = (project / ".codex" / "config.toml").read_bytes()
        original_claude_config = (project / ".mcp.json").read_bytes()
        lock = project / ".rob2" / "rob2.lock"
        original = lock.read_bytes()
        lock.write_bytes(original + b"\ncorruption")
        corrupt_doctor = json.loads(
            _run([str(rob2), "doctor", str(project)], cwd=workspace, env=checked_env).stdout
        )
        assert corrupt_doctor["ok"] is False
        assert corrupt_doctor["checks"]["execution_contract"]["ok"] is False
        assert corrupt_doctor["checks"]["execution_contract"]["recovery"]
        lock.write_bytes(original)
        restored_doctor = json.loads(
            _run([str(rob2), "doctor", str(project)], cwd=workspace, env=checked_env).stdout
        )
        assert restored_doctor["ok"] is True
        lifecycle = (
            None
            if replay_only
            else _qualify_lifecycle(
                rob2,
                project,
                workspace,
                checked_env,
                original_codex_config,
                original_claude_config,
            )
        )
        assert (
            json.loads(
                _run([str(rob2), "doctor", str(project)], cwd=workspace, env=checked_env).stdout
            )["ok"]
            is True
        )
        injected_faults = _injected_fault_receipts(mcp, project, candidate_env)
        adapter_launches = _adapter_launch_receipts(
            project,
            checked_env,
        )

        def replay(
            project_name: str,
            *,
            restart_after_source: bool,
            absent_fixtures: tuple[str, ...] = (),
            resume_only: bool = False,
            stop_after_source: bool = False,
        ) -> dict[str, Any]:
            mode = "resume" if resume_only else "seed" if stop_after_source else "complete"
            print(
                "qualification: journey "
                f"project={project_name} mode={mode} restart={restart_after_source} "
                f"absent={','.join(absent_fixtures) or 'none'}",
                flush=True,
            )
            replay_project = workspace / project_name
            replay_receipt = workspace / f"{project_name}.json"
            command = [
                str(python),
                str(Path(__file__).resolve()),
                "--journey",
                "--server",
                str(mcp),
                "--project",
                str(replay_project),
                "--receipt",
                str(replay_receipt),
            ]
            if restart_after_source:
                command.append("--restart-after-source")
            if resume_only:
                command.append("--resume-only")
            if stop_after_source:
                command.append("--stop-after-source")
            replay_env = _candidate_env(
                environment,
                network_guard=network_log.parent,
                absent_fixtures=absent_fixtures,
            )
            _run(command, cwd=workspace, env=replay_env)
            return json.loads(replay_receipt.read_text(encoding="utf-8"))

        replay_project = "replay-project"
        journey = replay(replay_project, restart_after_source=False)
        # Run both variants at the identical generated path.  Project-root
        # provenance is intentionally hashed into durable state, so comparing
        # different temporary paths would manufacture a false semantic diff.
        shutil.rmtree(workspace / replay_project)
        interrupted = replay(replay_project, restart_after_source=True)
        from rob2_kit.evaluation.installed_replay import normalize_semantic_value

        canonical_semantics = normalize_semantic_value(journey["durable_semantics"])
        interrupted_semantics = normalize_semantic_value(interrupted["durable_semantics"])
        if canonical_semantics != interrupted_semantics:
            from rob2_kit.evaluation import semantic_diff

            differences = "\n".join(semantic_diff(canonical_semantics, interrupted_semantics)[:10])
            raise AssertionError(
                "interrupted installed replay did not converge on canonical state\n" + differences
            )
        if len(interrupted["semantic_trace"]["workflow_events"]) != len(
            journey["semantic_trace"]["workflow_events"]
        ):
            raise AssertionError("interrupted replay repeated committed work")
        if interrupted["normalized_trace"]["final"] != journey["normalized_trace"]["final"]:
            raise AssertionError("interrupted replay changed the normalized terminal trace")
        journey["interrupted_replay"] = {
            "normalized_trace": interrupted["normalized_trace"],
            "durable_semantics": interrupted_semantics,
            "converged": True,
        }
        journey["durable_semantics"] = canonical_semantics
        from rob2_kit.evaluation.installed_replay import RELEASE_LOCKED_OPTIONAL_FIXTURES

        all_absent = tuple(RELEASE_LOCKED_OPTIONAL_FIXTURES)
        active_project = replay_project
        active_path = workspace / active_project
        if active_path.exists():
            shutil.rmtree(active_path)
        seed = replay(
            active_project,
            restart_after_source=False,
            stop_after_source=True,
        )
        if seed["run_state"] != "assessing":
            raise AssertionError("dependency-loss seed was not an active durable Run")
        all_absent_replay = replay(
            active_project,
            restart_after_source=False,
            absent_fixtures=all_absent,
            resume_only=True,
        )
        all_absent_semantics = normalize_semantic_value(all_absent_replay["durable_semantics"])
        if all_absent_semantics != canonical_semantics:
            receipt_path.with_suffix(".semantic-mismatch.json").write_text(
                json.dumps(
                    {"canonical": canonical_semantics, "resumed": all_absent_semantics},
                    sort_keys=True,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            raise AssertionError("sequential all-fixture absence changed durable core semantics")
        resumed_raw_calls = [
            *seed["raw_trace_calls"],
            *all_absent_replay["raw_trace_calls"],
        ]
        # Rebinding the Current run is transport lifecycle, not business work.
        # Compare the same normalized engine calls after removing only that
        # additional reconnect call.
        resumed_raw_calls = [
            call_receipt
            for index, call_receipt in enumerate(resumed_raw_calls)
            if not (index > 0 and call_receipt["name"] == "prepare_run")
        ]
        from rob2_kit.evaluation.installed_replay import normalize_replay_trace

        resumed_trace = normalize_replay_trace(
            resumed_raw_calls,
            final={"run_state": "complete", "project_root": str(active_path)},
        )
        left_to_right: dict[str, str] = {}
        right_to_left: dict[str, str] = {}

        def traces_equivalent(left: Any, right: Any) -> bool:
            if isinstance(left, dict) and isinstance(right, dict):
                return left.keys() == right.keys() and all(
                    traces_equivalent(left[key], right[key]) for key in left
                )
            if isinstance(left, list) and isinstance(right, list):
                return len(left) == len(right) and all(
                    traces_equivalent(a, b) for a, b in zip(left, right, strict=True)
                )
            if isinstance(left, str) and isinstance(right, str):
                left_handle = re.match(r"^<([^>]+)-\d+>$", left)
                right_handle = re.match(r"^<([^>]+)-\d+>$", right)
                if left_handle or right_handle:
                    if not left_handle or not right_handle:
                        return False
                    if left_handle.group(1) != right_handle.group(1):
                        return False
                    existing_right = left_to_right.setdefault(left, right)
                    existing_left = right_to_left.setdefault(right, left)
                    return existing_right == right and existing_left == left
            return left == right

        if not traces_equivalent(resumed_trace, journey["normalized_trace"]):
            raise AssertionError("sequential all-fixture absence changed the normalized MCP trace")
        resumed_workflow = all_absent_replay["durable_semantics"]["workflow"]

        def identities(records: list[dict[str, object]], key: str) -> list[object]:
            return [record[key] for record in records]

        seed_event_ids = identities(seed["events"], "event_id")
        resumed_event_ids = identities(resumed_workflow["events"], "event_id")
        seed_revision_ids = identities(seed["revisions"], "revision_id")
        resumed_revision_ids = identities(resumed_workflow["current_revisions"], "revision_id")
        seed_checkpoint_ids = identities(seed["checkpoints"], "checkpoint")
        resumed_checkpoint_ids = identities(resumed_workflow["checkpoints"], "checkpoint")
        if resumed_event_ids[: len(seed_event_ids)] != seed_event_ids:
            raise AssertionError("resume replaced or repeated committed workflow event identities")
        if resumed_revision_ids[: len(seed_revision_ids)] != seed_revision_ids:
            raise AssertionError("resume replaced committed revision identities")
        if resumed_checkpoint_ids[: len(seed_checkpoint_ids)] != seed_checkpoint_ids:
            raise AssertionError("resume replaced committed checkpoint identities")
        source_role_events = [
            event
            for event in resumed_workflow["events"]
            if event["operation"] == "operation:submit-source-role-review"
        ]
        if len(source_role_events) != 1:
            raise AssertionError("resume repeated the committed source-role review")
        seed_work_token = seed["active_work_token"]
        if not isinstance(seed_work_token, dict) or (
            seed_work_token.get("operation") != "submit_source_role_review"
        ):
            raise AssertionError("seed did not stop at the source-role review stage")
        first_resumed_work_token = normalize_semantic_value(
            next(
                call_receipt["response"]["work_item"]["work_token"]
                for call_receipt in all_absent_replay["raw_trace_calls"]
                if isinstance(call_receipt["response"], dict)
                and isinstance(call_receipt["response"].get("work_item"), dict)
            )
        )
        if not isinstance(first_resumed_work_token, dict) or (
            first_resumed_work_token.get("operation") != "submit_domain_evidence"
        ):
            raise AssertionError("resume did not continue with post-confirmation domain evidence work")
        resumed_context_work_token = normalize_semantic_value(
            next(
                call_receipt["arguments"]["work_token"]
                for call_receipt in all_absent_replay["raw_trace_calls"]
                if call_receipt["name"] == "get_work_context"
                and isinstance(call_receipt.get("arguments"), dict)
                and isinstance(call_receipt["arguments"].get("work_token"), dict)
            )
        )
        if resumed_context_work_token != first_resumed_work_token:
            raise AssertionError("resume did not retain its post-confirmation work-token identity")
        fixture_replays = {
            "registry_history": {
                "absent": list(all_absent),
                "core_outcome": "complete",
                "degradation": (
                    "registry acquisition attempted; history unavailable with explicit limitation"
                ),
                "normalized_trace": resumed_trace,
                "durable_semantics": all_absent_semantics,
            }
        }
        journey["fixture_replays"] = fixture_replays
        journey["all_optional_absent_sequentially"] = {
            "absent": list(all_absent),
            "core_outcome": "complete",
            "degradation": (
                "registry acquisition attempted; history unavailable with explicit limitation"
            ),
            "normalized_trace": resumed_trace,
            "durable_semantics": all_absent_semantics,
        }
        journey["sequential_fixture_resumes"] = {
            "registry_history": {
                "absent": list(all_absent),
                # resume-only asserts prepare_run rebound to the seed Run before
                # any Domain work is accepted.
                "same_run_id": True,
                "committed_work_reused": True,
                "checkpoint_identities_preserved": seed_checkpoint_ids,
                "revision_identities_preserved": seed_revision_ids,
                "workflow_event_identities_preserved": seed_event_ids,
                "work_token_identity_reissued": seed_work_token,
                "normalized_trace_compared": True,
                "durable_semantics": all_absent_semantics,
            }
        }
        journey["injected_faults"] = injected_faults
        installed_replay = _installed_replay_receipt(
            source_root, journey, accept=accept_replay_golden
        )
        receipt = {
            "schema_version": 1,
            "qualification_mode": "replay_only" if replay_only else "full",
            "skipped_stages": ["lifecycle"] if replay_only else [],
            "wheel": wheel.name,
            "python": "3.13",
            "platform": sys.platform,
            "bootstrap": {
                "first": first["status"],
                "repeat": second["status"],
                "hosts": first["hosts"],
            },
            "doctor": {
                "initial": initial_doctor["ok"],
                "corruption_detected": not corrupt_doctor["ok"],
                "restored": restored_doctor["ok"],
            },
            "lifecycle": None if lifecycle is None else lifecycle.receipt,
            "adapter_launches": adapter_launches,
            "telemetry": _network_guard_receipt(network_log),
            "journey": journey,
            "installed_replay": installed_replay,
            "owner_evaluation": {
                "status": "external_required",
                "receipt": "release/private-release-evaluation.md",
            },
            "timing": {
                "schema_version": 1,
                "stages": STAGE_TIMINGS,
                "total_duration_seconds": round(time.perf_counter() - qualification_started, 3),
            },
        }
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(
            json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )


def main() -> None:
    if len(sys.argv) >= 3 and sys.argv[1] == "--uvx-shim":
        _uvx_shim(sys.argv[2], sys.argv[3:])
        return
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--source-root", type=Path, default=Path.cwd())
    parser.add_argument("--skip-full-suite", action="store_true")
    parser.add_argument("--accept-replay-golden", action="store_true")
    parser.add_argument(
        "--replay-only",
        action="store_true",
        help="Run the #110 installed replay gate without the separate #108 lifecycle gate.",
    )
    parser.add_argument("--journey", action="store_true")
    parser.add_argument("--restart-after-source", action="store_true")
    parser.add_argument("--resume-only", action="store_true")
    parser.add_argument("--stop-after-source", action="store_true")
    parser.add_argument("--server", type=Path)
    parser.add_argument("--project", type=Path)
    arguments = parser.parse_args()
    if arguments.journey:
        assert arguments.server and arguments.project and arguments.receipt
        _journey(
            arguments.server,
            arguments.project,
            arguments.receipt,
            restart_after_source=arguments.restart_after_source,
            resume_only=arguments.resume_only,
            stop_after_source=arguments.stop_after_source,
        )
    else:
        assert arguments.wheel and arguments.receipt
        _qualify(
            arguments.wheel,
            arguments.receipt,
            arguments.source_root,
            skip_full_suite=arguments.skip_full_suite,
            accept_replay_golden=arguments.accept_replay_golden,
            replay_only=arguments.replay_only,
        )


if __name__ == "__main__":
    main()

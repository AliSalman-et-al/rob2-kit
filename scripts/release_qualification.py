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
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import cast

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
    "submit_source_classification",
    "submit_result_resolution",
    "submit_domain_evidence",
    "submit_domain_answers",
)


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
    command: list[str], *, cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(
            f"command failed ({result.returncode}): {command!r}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


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
    environment: Path, shim: Path | None = None, network_guard: Path | None = None
) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("VIRTUAL_ENV", None)
    env.pop("UV_PROJECT_ENVIRONMENT", None)
    env["ROB2_QUALIFICATION_UTC_NOW"] = QUALIFICATION_TIME
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


def _blank_pdf() -> bytes:
    stream = b"BT /F1 12 Tf 10 36 Td (Trial report) Tj ET"
    objects = (
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 72 72] "
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
    }


def _journey(server: Path, project: Path, receipt_path: Path) -> None:
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
            "sq:deviations:appropriate-analysis",
        ),
        "domain:missing": ("sq:missing:data-available",),
        "domain:measurement": (
            "sq:measurement:method-inappropriate",
            "sq:measurement:differential",
            "sq:measurement:assessor-aware",
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
        "sq:deviations:appropriate-analysis": "yes",
        "sq:missing:data-available": "yes",
        "sq:measurement:method-inappropriate": "no",
        "sq:measurement:differential": "no",
        "sq:measurement:assessor-aware": "no",
        "sq:selection:prespecified-analysis": "yes",
        "sq:selection:multiple-measurements": "no",
        "sq:selection:multiple-analyses": "no",
    }
    trial = project / "input" / "trial-a"
    trial.mkdir(parents=True)
    (trial / "report.pdf").write_bytes(_blank_pdf())
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

    async def session():
        return stdio_client(
            StdioServerParameters(
                command=str(server),
                args=[],
                cwd=project,
                env=dict(os.environ),
            )
        )

    async def run() -> None:
        async with await session() as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                inventory = await client.list_tools()
                assert tuple(tool.name for tool in inventory.tools) == CANONICAL_TOOL_NAMES
                prepared = (
                    await client.call_tool(
                        "prepare_run", {"project_root": str(project), "authorized": True}
                    )
                ).structured_content
                assert prepared is not None
                proposed = (
                    await client.call_tool(
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
                await client.call_tool(
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
                work = (
                    await client.call_tool("continue_run", {"run_id": prepared["run_id"]})
                ).structured_content
                assert work is not None
                result = await client.call_tool(
                    "submit_source_classification",
                    {
                        "run_id": prepared["run_id"],
                        "work_token": work["work_item"]["work_token"],
                        "idempotency_key": "qualification:source",
                        "contract_version": "1.0.0",
                        "classifications": [
                            {"source_id": "source:trial-a-1", "roles": ["primary_report"]}
                        ],
                    },
                )
                assert result.structured_content and result.structured_content["committed"]
                run_id = prepared["run_id"]
        async with await session() as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                rebound = (
                    await client.call_tool("prepare_run", {"project_root": str(project)})
                ).structured_content
                assert rebound and rebound["run_id"] == run_id
                for index, (domain, questions) in enumerate(domains.items()):
                    evidence = (
                        await client.call_tool("continue_run", {"run_id": run_id})
                    ).structured_content
                    assert evidence is not None
                    committed = await client.call_tool(
                        "submit_domain_evidence",
                        {
                            "run_id": run_id,
                            "work_token": evidence["work_item"]["work_token"],
                            "idempotency_key": f"qualification:evidence:{index}",
                            "contract_version": "1.0.0",
                            "result_id": "result:trial-a-mortality",
                            "domain_id": domain,
                        },
                    )
                    assert (
                        committed.structured_content and committed.structured_content["committed"]
                    )
                    answer = (
                        await client.call_tool("continue_run", {"run_id": run_id})
                    ).structured_content
                    assert answer is not None
                    committed = await client.call_tool(
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
                                    "answer": answers[question],
                                    "rationale": "Frozen synthetic qualification evidence.",
                                }
                                for question in questions
                            ],
                        },
                    )
                    assert (
                        committed.structured_content and committed.structured_content["committed"]
                    )
                complete = (
                    await client.call_tool("continue_run", {"run_id": run_id})
                ).structured_content
                assert complete and complete["run_state"] == "complete"

    anyio.run(run)

    receipt_path.write_text(
        json.dumps(_journey_receipt(project), sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _qualify(
    wheel: Path, receipt_path: Path, source_root: Path, *, skip_full_suite: bool = False
) -> None:
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
        candidate_env = _candidate_env(
            environment, network_guard=network_log.parent
        )
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
        upgrade_preview = json.loads(
            _run([str(rob2), "upgrade", str(project)], cwd=workspace, env=checked_env).stdout
        )
        assert upgrade_preview["preview"] is True
        assert upgrade_preview["state_compatibility"]["ok"] is True
        upgrade = json.loads(
            _run(
                [str(rob2), "upgrade", "--apply", str(project)],
                cwd=workspace,
                env=checked_env,
            ).stdout
        )
        assert upgrade["status"] == "upgraded"
        upgraded_doctor = json.loads(
            _run([str(rob2), "doctor", str(project)], cwd=workspace, env=checked_env).stdout
        )
        assert upgraded_doctor["ok"] is True, upgraded_doctor
        rollback_preview = json.loads(
            _run([str(rob2), "rollback", str(project)], cwd=workspace, env=checked_env).stdout
        )
        assert rollback_preview["preview"] is True
        assert rollback_preview["state_compatibility"]["ok"] is True
        rollback = json.loads(
            _run(
                [str(rob2), "rollback", "--apply", str(project)],
                cwd=workspace,
                env=checked_env,
            ).stdout
        )
        assert rollback["status"] == "rolled_back"
        assert json.loads(
            _run([str(rob2), "doctor", str(project)], cwd=workspace, env=checked_env).stdout
        )["ok"] is True
        uninstall_preview = json.loads(
            _run([str(rob2), "uninstall", str(project)], cwd=workspace, env=checked_env).stdout
        )
        assert uninstall_preview["preview"] is True
        assert uninstall_preview["state_compatibility"]["ok"] is True
        uninstall = json.loads(
            _run(
                [str(rob2), "uninstall", "--apply", str(project)],
                cwd=workspace,
                env=checked_env,
            ).stdout
        )
        assert uninstall["status"] == "uninstalled"
        reinstalled = json.loads(
            _run([str(rob2), "bootstrap", str(project)], cwd=workspace, env=candidate_env).stdout
        )
        assert reinstalled["status"] == "installed"
        assert json.loads(
            _run([str(rob2), "doctor", str(project)], cwd=workspace, env=checked_env).stdout
        )["ok"] is True
        adapter_launches = _adapter_launch_receipts(
            project,
            checked_env,
        )
        journey_receipt = workspace / "journey.json"
        _run(
            [
                str(python),
                str(Path(__file__).resolve()),
                "--journey",
                "--server",
                str(mcp),
                "--project",
                str(project),
                "--receipt",
                str(journey_receipt),
            ],
            cwd=workspace,
            env=candidate_env,
        )
        journey = json.loads(journey_receipt.read_text(encoding="utf-8"))
        receipt = {
            "schema_version": 1,
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
            "lifecycle": {
                "upgrade": upgrade["status"],
                "rollback": rollback["status"],
                "uninstall": uninstall["status"],
                "reinstalled": reinstalled["status"],
            },
            "adapter_launches": adapter_launches,
            "telemetry": _network_guard_receipt(network_log),
            "journey": journey,
            "owner_evaluation": {
                "status": "external_required",
                "receipt": "release/private-release-evaluation.md",
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
    parser.add_argument("--journey", action="store_true")
    parser.add_argument("--server", type=Path)
    parser.add_argument("--project", type=Path)
    arguments = parser.parse_args()
    if arguments.journey:
        assert arguments.server and arguments.project and arguments.receipt
        _journey(arguments.server, arguments.project, arguments.receipt)
    else:
        assert arguments.wheel and arguments.receipt
        _qualify(
            arguments.wheel,
            arguments.receipt,
            arguments.source_root,
            skip_full_suite=arguments.skip_full_suite,
        )


if __name__ == "__main__":
    main()

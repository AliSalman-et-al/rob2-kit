"""Run one isolated Codex/rob2 diagnostic phase and retain its full JSONL trace."""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import runpy
import shutil
import signal
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from benchmark_contract import (
    TOOL_INVENTORY_VERSION,
    artifact_manifest_identity,
    execution_index_binding,
    host_delivery_diagnosis,
    host_delivery_observed,
    host_tools_infrastructure_recovery_diagnosis,
    probe_server_advertised_inventory,
    public_contract_version,
    public_tool_inventory,
    rob2_call_diagnostics,
    tool_inventory_provenance,
    trace_session_ids,
)
from prepare_rsi_workspace import approved_scope_record, prepare_workspace

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows uses msvcrt below.
    fcntl = None

if os.name == "nt":
    import msvcrt
else:  # pragma: no cover - exercised only on Windows.
    msvcrt = None

# Keep the expected surface at the launcher boundary: a resumed session with
# a different public contract is not the same experimental condition.
EXPECTED_TOOL_INVENTORY = public_tool_inventory()
# The prior 300-second MCP client limit expired while a benchmark search later
# returned after roughly 447 seconds.
ROB2_MCP_TOOL_TIMEOUT_SECONDS = 600


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _first_text(*values: object, default: str) -> str:
    for value in values:
        text = _optional_text(value)
        if text is not None:
            return text
    return default


def _normalise_tool_inventory(value: object) -> tuple[str, ...] | None:
    """Return a canonical tool-name tuple from a host inventory payload."""

    if not isinstance(value, (list, tuple, set)):
        return None
    names: set[str] = set()
    for item in value:
        if isinstance(item, str) and item.strip():
            names.add(item.strip())
        elif isinstance(item, dict):
            name = item.get("name") or item.get("tool")
            if isinstance(name, str) and name.strip():
                names.add(name.strip())
    return tuple(sorted(names)) if names else None


def _trace_metadata(path: Path) -> dict[str, object]:
    """Recover only explicit session/inventory events from a JSONL trace.

    MCP search receipts also contain a ``session_id``.  They are not host
    session bindings, so this parser intentionally accepts session identifiers
    only from session/thread events (or their supported legacy envelopes).
    """

    return {"sessions": trace_session_ids(path)}


def _resolve_executable(
    repository: Path,
    environment_name: str,
    relative_candidates: tuple[Path, ...],
    path_candidates: tuple[str, ...],
) -> Path:
    override = os.environ.get(environment_name)
    candidates = ([Path(override)] if override else []) + [
        repository / candidate for candidate in relative_candidates
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    for name in ((override,) if override else ()) + path_candidates:
        if not name:
            continue
        located = shutil.which(name)
        if located:
            return Path(located).resolve()
    description = override or ", ".join(str(candidate) for candidate in relative_candidates)
    raise RuntimeError(f"{environment_name} executable is unavailable ({description})")


def _preflight_executable(executable: Path, label: str) -> str:
    """Run a harmless version/help probe without invoking the paid host."""

    for argument in ("--version", "--help"):
        try:
            output = subprocess.check_output(
                [str(executable), argument],
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            if argument == "--help":
                raise RuntimeError(f"{label} preflight failed: {error}") from error
            continue
        line = next((line.strip() for line in output.splitlines() if line.strip()), "unknown")
        return line[:256]
    raise RuntimeError(f"{label} preflight failed")


def _is_windows() -> bool:
    return os.name == "nt"


def _codex_environment(
    codex_home: Path, workspace: Path, *, strict: bool, base: dict[str, str] | None = None
) -> dict[str, str]:
    source = os.environ if base is None else base
    if strict:
        allowed = {
            "HOME",
            "PATH",
            "USER",
            "LOGNAME",
            "SHELL",
            "TMPDIR",
            "TMP",
            "TEMP",
            "LANG",
            "LC_ALL",
            "LC_CTYPE",
            "LC_MESSAGES",
            "SSL_CERT_FILE",
            "SSL_CERT_DIR",
            "REQUESTS_CA_BUNDLE",
            "CURL_CA_BUNDLE",
            "NO_COLOR",
            "TERM",
            "XDG_RUNTIME_DIR",
        }
        environment = {key: value for key, value in source.items() if key in allowed}
        private_tmp = workspace / ".tmp"
        environment.update({key: str(private_tmp) for key in ("TMPDIR", "TMP", "TEMP")})
    else:
        environment = dict(source)
    environment["CODEX_HOME"] = str(codex_home)
    environment["ROB2_WORKSPACE"] = str(workspace)
    return environment


def _strict_filesystem_profile(
    workspace: Path,
    repository: Path,
    denied_directories: tuple[Path, ...],
    denied_files: tuple[Path, ...],
) -> list[str]:
    profile = [
        'approval_policy = "never"',
        'default_permissions = "rob2-rsi"',
        "",
        "[permissions.rob2-rsi.filesystem]",
        '":root" = "deny"',
        '":minimal" = "read"',
    ]
    profile.extend(f'{json.dumps(path.as_posix())} = "deny"' for path in denied_directories)
    profile.append(f'{json.dumps(workspace.as_posix())} = "write"')
    profile.append(f'{json.dumps((repository / ".venv").as_posix())} = "read"')
    profile.append(f'{json.dumps(str(Path(sys.executable).resolve().parent.parent))} = "read"')
    profile.extend(f'{json.dumps(path.as_posix())} = "deny"' for path in denied_files)
    profile.extend(["", "[permissions.rob2-rsi.network]", "enabled = false"])
    return profile


def _preflight_isolation(codex_command: Path, required: bool) -> dict[str, object]:
    if not required:
        return {"requested": False, "supported": True, "sentinel": "not_requested"}
    if _is_windows():
        raise RuntimeError(
            "requested strict host isolation is unsupported on Windows without UAC; "
            "use a POSIX host or run the documented non-strict Windows profile"
        )
    with tempfile.TemporaryDirectory(prefix="rob2-rsi-preflight-", dir=Path.home()) as directory:
        root = Path(directory)
        campaign_root = root / "campaign"
        attempt = campaign_root / "runs" / "outcome" / "attempt"
        attempt.mkdir(parents=True)
        allowed = attempt / "workspace"
        allowed.mkdir()
        (allowed / ".tmp").mkdir()
        sentinel = root / "forbidden sentinel.txt"
        sentinel.write_text("ROB2_RSI_FORBIDDEN_READ", encoding="utf-8")
        codex_home_parent = root / "rob2-kit-codex-home"
        codex_home_parent.mkdir()
        codex_home = codex_home_parent / "current"
        codex_home.mkdir()
        sibling_codex_home = codex_home_parent / "sibling"
        sibling_codex_home.mkdir()
        sibling_attempt = campaign_root / "runs" / "outcome" / "sibling"
        sibling_attempt.mkdir(parents=True)
        source_home = root / "source-home"
        source_auth_dir = source_home / ".codex"
        source_auth_dir.mkdir(parents=True)
        allowed_probe = allowed / "allowed-probe.txt"
        allowed_probe.write_text("ROB2_RSI_ALLOWED_WORKSPACE", encoding="utf-8")
        protected_files = {
            "sentinel": sentinel,
            "run_inputs": attempt / "run-inputs.json",
            "approved_scope": attempt / "approved-scope.json",
            "codex_auth": codex_home / "auth.json",
            "execution": attempt / "execution.json",
            "source_auth": source_auth_dir / "auth.json",
            "sibling_codex_auth": sibling_codex_home / "auth.json",
            "sibling_run_inputs": sibling_attempt / "run-inputs.json",
            "outside_temp": root / "outside-temp.txt",
        }
        protected_files["run_inputs"].write_text(
            '{"expected_result":"ROB2_RSI_EXPECTED_RESULT_SECRET"}', encoding="utf-8"
        )
        protected_files["approved_scope"].write_text(
            '{"expected_result":"ROB2_RSI_APPROVED_SCOPE_SECRET"}', encoding="utf-8"
        )
        protected_files["codex_auth"].write_text(
            '{"access_token":"ROB2_RSI_AUTH_SECRET"}', encoding="utf-8"
        )
        protected_files["execution"].write_text(
            '{"state":"running","attempt_id":"ROB2_RSI_EXECUTION_SECRET"}',
            encoding="utf-8",
        )
        protected_files["source_auth"].write_text(
            '{"access_token":"ROB2_RSI_SOURCE_AUTH_SECRET"}', encoding="utf-8"
        )
        protected_files["sibling_codex_auth"].write_text(
            '{"access_token":"ROB2_RSI_SIBLING_AUTH_SECRET"}', encoding="utf-8"
        )
        protected_files["sibling_run_inputs"].write_text(
            '{"expected_result":"ROB2_RSI_SIBLING_RESULT_SECRET"}', encoding="utf-8"
        )
        protected_files["outside_temp"].write_text("ROB2_RSI_OUTSIDE_TEMP_SECRET", encoding="utf-8")
        profile = _strict_filesystem_profile(
            allowed,
            Path(__file__).resolve().parents[1],
            (),
            tuple(protected_files.values()),
        )
        (codex_home / "config.toml").write_text("\n".join(profile) + "\n", encoding="utf-8")
        sandbox_command = codex_command.resolve()
        if sandbox_command.is_file():
            if sandbox_command.read_bytes()[:4] != b"\x7fELF":
                native = tuple(
                    sandbox_command.parent.parent.glob(
                        "node_modules/@openai/codex-linux-*/vendor/*/bin/codex"
                    )
                )
                if len(native) == 1:
                    sandbox_command = native[0]
            sandbox_copy = allowed / "codex-sandbox-preflight"
            shutil.copy2(sandbox_command, sandbox_copy)
        else:
            sandbox_copy = sandbox_command
        probes = [(name, str(path)) for name, path in protected_files.items()]
        script = (
            "from pathlib import Path\n"
            "import os\n"
            "print('ENV:secret_present' if 'ROB2_RSI_PREFLIGHT_SECRET' in os.environ "
            "else 'ENV:clean')\n"
            f"allowed = Path({str(allowed_probe)!r})\n"
            "try:\n"
            "    assert allowed.read_text(encoding='utf-8') == 'ROB2_RSI_ALLOWED_WORKSPACE'\n"
            "    allowed.with_name('allowed-write.txt').write_text('ok', encoding='utf-8')\n"
            "    private_tmp = Path(os.environ['TMPDIR'])\n"
            "    assert private_tmp == allowed.parent / '.tmp'\n"
            "    private_tmp.mkdir(exist_ok=True)\n"
            "    (private_tmp / 'probe.tmp').write_text('ok', encoding='utf-8')\n"
            "except OSError:\n"
            "    print('ALLOWED:denied')\n"
            "else:\n"
            "    print('ALLOWED:read_write')\n"
            f"for name, path in {probes!r}:\n"
            "    try:\n"
            "        Path(path).read_text(encoding='utf-8')\n"
            "    except OSError:\n"
            "        print('DENIED:' + name)\n"
            "    else:\n"
            "        print('READ:' + name)\n"
            "    try:\n"
            "        Path(path).write_text('probe', encoding='utf-8')\n"
            "    except OSError:\n"
            "        print('DENIED_WRITE:' + name)\n"
            "    else:\n"
            "        print('WRITE:' + name)\n"
        )
        command = [
            str(sandbox_copy),
            "sandbox",
            "-C",
            str(allowed),
            "-P",
            "rob2-rsi",
            "--",
            str(Path(sys.executable).resolve()),
            "-c",
            script,
        ]
        preflight_environment = dict(os.environ)
        preflight_environment["HOME"] = str(source_home)
        environment = _codex_environment(
            codex_home, allowed, strict=True, base=preflight_environment
        )
        try:
            output = subprocess.check_output(
                command,
                cwd=allowed,
                env=environment,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
            )
        except subprocess.CalledProcessError as error:
            detail = error.output if isinstance(error.output, str) else ""
            raise RuntimeError(
                "strict host isolation preflight failed before all probes completed: "
                + (detail.strip() or "the sandbox command returned a non-zero status")
            ) from error
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RuntimeError(
                "requested strict host isolation is unavailable; forbidden-file sentinel "
                f"was not verified: {error}"
            ) from error
        lines = {line.strip() for line in output.splitlines()}
        exposed = [
            name for name in protected_files if f"READ:{name}" in lines or f"WRITE:{name}" in lines
        ]
        if exposed:
            raise RuntimeError(
                "requested strict host isolation failed: a protected file was readable: "
                + ", ".join(exposed)
            )
        missing_denials = [
            name
            for name in protected_files
            if f"DENIED:{name}" not in lines or f"DENIED_WRITE:{name}" not in lines
        ]
        if missing_denials:
            raise RuntimeError(
                "requested strict host isolation did not deny protected files: "
                + ", ".join(missing_denials)
            )
        if "ALLOWED:read_write" not in lines:
            raise RuntimeError(
                "requested strict host isolation did not verify workspace read/write access"
            )
        if "ENV:clean" not in lines or "ENV:secret_present" in lines:
            raise RuntimeError(
                "requested strict host isolation exposed a non-allowlisted environment secret"
            )
        return {
            "requested": True,
            "supported": True,
            "sentinel": "denied",
            "sentinel_command": command,
        }


def _add_digest_member(digest: hashlib._Hash, path: Path, repository: Path) -> None:
    """Fingerprint an input by content and a stable label, including external tools."""

    resolved = path.resolve()
    try:
        label = resolved.relative_to(repository).as_posix()
    except ValueError:
        label = "external/" + hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()
    digest.update(label.encode("utf-8"))
    digest.update(resolved.read_bytes())


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _trace_session_id(path: Path) -> str | None:
    """Recover a Codex session identifier from a complete or partial JSONL trace."""

    sessions = _trace_metadata(path)["sessions"]
    if not isinstance(sessions, tuple):
        return None
    if len(sessions) > 1:
        raise ValueError(f"ambiguous Codex session identifiers in {path}")
    return sessions[0] if sessions else None


def _phase_completion_metadata(trace: Path, expected_session: str | None) -> dict[str, object]:
    calls = rob2_call_diagnostics(trace)
    return {
        "trace_sha256": _sha256_file(trace) if trace.is_file() else None,
        "trace_complete": trace.is_file(),
        "codex_session_id": _trace_session_id(trace) if trace.is_file() else None,
        "host_delivery_observed": host_delivery_observed(trace, expected_session),
        "timed_out_rob2_calls": list(calls["timed_out"]),
    }


def _host_delivery_postcondition(
    exit_code: int, trace: Path, expected_session: str | None
) -> tuple[int, str | None, str | None, dict[str, str] | None]:
    if exit_code != 0:
        return exit_code, None, None, None
    session = expected_session or _trace_session_id(trace)
    diagnosis = host_delivery_diagnosis(
        trace,
        expected_sha256=_sha256_file(trace) if trace.is_file() else None,
        expected_session=session,
    )
    if diagnosis is None:
        return exit_code, None, None, None
    return (
        75,
        "failed_infrastructure",
        "Codex completed without verified rob2 host-tool delivery: " + diagnosis["code"],
        diagnosis,
    )


def _codex_mcp_config(command: str, workspace: Path) -> list[str]:
    return [
        "[mcp_servers.rob2]",
        "command = " + json.dumps(command),
        'args = ["mcp"]',
        "env = { ROB2_WORKSPACE = " + json.dumps(str(workspace.resolve())) + " }",
        "required = true",
        'default_tools_approval_mode = "approve"',
        "startup_timeout_sec = 120",
        f"tool_timeout_sec = {ROB2_MCP_TOOL_TIMEOUT_SECONDS}",
    ]


def _validate_tool_inventory(
    run_dir: Path,
    phase: int,
    *,
    expected: tuple[str, ...] = EXPECTED_TOOL_INVENTORY,
    server_inventory: dict[str, object] | None = None,
) -> tuple[str, ...]:
    """Compare a live stdio tools/list probe with the frozen release inventory."""

    execution_path = run_dir / "execution.json"
    execution: dict[str, object] | None = None
    frozen: tuple[str, ...] | None = None
    frozen_version: str | None = None
    frozen_provenance: dict[str, object] | None = None
    frozen_server_inventory: dict[str, object] | None = None
    if execution_path.is_file():
        try:
            execution = json.loads(execution_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("frozen launch runtime record is unreadable") from error
        runtime = execution.get("runtime_inputs") if isinstance(execution, dict) else None
        if isinstance(runtime, dict) and execution.get("runtime_inputs_sha256") != _json_sha256(
            runtime
        ):
            raise ValueError("frozen launch runtime inputs failed their integrity check")
        if isinstance(runtime, dict):
            frozen = _normalise_tool_inventory(runtime.get("expected_tool_inventory"))
            frozen_version = _optional_text(runtime.get("tool_inventory_version"))
            provenance = runtime.get("tool_inventory")
            if isinstance(provenance, dict):
                frozen_provenance = provenance
                frozen = _normalise_tool_inventory(provenance.get("names")) or frozen
                frozen_version = _optional_text(provenance.get("version")) or frozen_version
            advertised = runtime.get("server_advertised_inventory")
            if isinstance(advertised, dict):
                frozen_server_inventory = advertised
        if frozen is None:
            frozen = _normalise_tool_inventory(execution.get("expected_tool_inventory"))
            frozen_version = _optional_text(execution.get("tool_inventory_version"))
    if frozen is None:
        raise ValueError(
            "frozen launch tool inventory is unavailable; recovery: start a fresh "
            "benchmark attempt and retain this run as resumable"
        )
    if frozen_version is None:
        raise ValueError(
            "frozen launch tool inventory provenance is unavailable; recovery: start a fresh "
            "benchmark attempt and retain this run as resumable"
        )
    if frozen_version != TOOL_INVENTORY_VERSION:
        raise ValueError(
            "frozen launch tool inventory version is incompatible ("
            f"{frozen_version} != {TOOL_INVENTORY_VERSION}); recovery: start a fresh "
            "benchmark attempt"
        )
    if frozen_provenance is not None:
        current_provenance = tool_inventory_provenance()
        for field in ("source", "contract_version", "contract_sha256"):
            frozen_value = frozen_provenance.get(field)
            current_value = current_provenance.get(field)
            if frozen_value is not None and frozen_value != current_value:
                raise ValueError(
                    "current tool inventory provenance is incompatible with the frozen "
                    f"launch record ({field}); recovery: start a fresh benchmark attempt"
                )
    if (
        not isinstance(frozen_server_inventory, dict)
        or frozen_server_inventory.get("status") != "verified"
        or frozen_server_inventory.get("source") != "stdio tools/list"
        or frozen_server_inventory.get("server") != "rob2"
        or frozen_server_inventory.get("names")
        != sorted(name for name in frozen if isinstance(name, str))
        or frozen_server_inventory.get("tool_count") != len(frozen)
    ):
        raise ValueError(
            "server-advertised MCP inventory is missing; recovery: start a fresh benchmark "
            "attempt and retain this run as resumable"
        )
    frozen_binding = frozen_server_inventory.get("server_binding")
    registered_binding = (
        execution.get("runtime_inputs", {}).get("codex_registered_mcp")
        if isinstance(execution, dict) and isinstance(execution.get("runtime_inputs"), dict)
        else None
    )
    if not isinstance(frozen_binding, dict) or registered_binding != frozen_binding:
        raise ValueError(
            "frozen Codex rob2 command/args do not match the server-advertised binding; "
            "recovery: start a fresh benchmark attempt"
        )
    if not isinstance(server_inventory, dict) or server_inventory.get("status") != "verified":
        raise ValueError(
            "current rob2 MCP tools/list preflight is unavailable; do not resume this session"
        )
    for field in (
        "inventory_sha256",
        "contract_version",
        "contract_sha256",
        "server_binding_sha256",
    ):
        if server_inventory.get(field) != frozen_server_inventory.get(field):
            raise ValueError(
                "current rob2 MCP tools/list inventory or server binding differs from the "
                f"frozen attempt ({field}); recovery: start a fresh benchmark attempt"
            )
    current = _normalise_tool_inventory(expected)
    if current is None or frozen != current:
        frozen_set = set(frozen)
        expected_set = set(current or ())
        missing = sorted(frozen_set - expected_set)
        unexpected = sorted(expected_set - frozen_set)
        detail = []
        if missing:
            detail.append("missing=" + ",".join(missing))
        if unexpected:
            detail.append("unexpected=" + ",".join(unexpected))
        raise ValueError(
            "current tool inventory is incompatible with the frozen launch inventory ("
            + "; ".join(detail)
            + "); recovery: start a fresh benchmark attempt"
        )
    phases = execution.get("phases") if isinstance(execution, dict) else None
    prior = (
        next(
            (
                row
                for row in reversed(phases)
                if isinstance(row, dict) and row.get("phase") == phase
            ),
            None,
        )
        if isinstance(phases, list)
        else None
    )
    delivery = host_delivery_diagnosis(
        run_dir / f"phase-{phase}.jsonl",
        expected_sha256=(prior.get("trace_sha256") if isinstance(prior, dict) else None),
        expected_session=(prior.get("codex_session_id") if isinstance(prior, dict) else None),
    )
    if delivery is not None:
        if delivery.get("code") != "host_delivery_call_missing":
            raise ValueError(json.dumps(delivery, sort_keys=True))
        if phase not in (2, 3, 4):
            raise ValueError(json.dumps(delivery, sort_keys=True))
        recovery = host_tools_infrastructure_recovery_diagnosis(run_dir, phase)
        if recovery is not None:
            raise ValueError(json.dumps(recovery, sort_keys=True))
    return frozen


def _trace_artifact(run_dir: Path, phase: int) -> dict[str, object] | None:
    """Recover a finalized artifact receipt from one or more Codex traces."""

    def find(value: object) -> dict[str, object] | None:
        if isinstance(value, dict):
            candidate = value.get("artifact")
            if (
                isinstance(candidate, dict)
                and isinstance(candidate.get("path"), str)
                and isinstance(candidate.get("sha256"), str)
            ):
                return candidate
            for child in value.values():
                found = find(child)
                if found is not None:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = find(child)
                if found is not None:
                    return found
        return None

    for trace_phase in range(phase, 0, -1):
        path = run_dir / f"phase-{trace_phase}.jsonl"
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            artifact = find(value)
            if artifact is not None:
                return artifact
    return None


def _atomic_json(path: Path, value: object) -> None:
    """Replace a JSON record atomically, including on Windows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


_EXECUTION_LOCKS: dict[Path, int] = {}


def _lock_descriptor(descriptor: int) -> None:
    """Acquire a kernel-held, non-blocking lock on the first lock-file byte."""

    if os.name == "nt":
        assert msvcrt is not None
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"\0")
        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        except OSError as error:
            if error.errno in {errno.EACCES, errno.EDEADLK, errno.EAGAIN}:
                raise ValueError(
                    "execution is already running; duplicate launch refused"
                ) from error
            raise
        return
    if fcntl is None:  # pragma: no cover - every supported POSIX host has fcntl.
        raise RuntimeError("execution locking is unavailable on this host")
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        if error.errno in {errno.EACCES, errno.EAGAIN}:
            raise ValueError("execution is already running; duplicate launch refused") from error
        raise


def _acquire_execution_lock(run_dir: Path) -> None:
    """Own one case directory for the whole host invocation.

    The descriptor remains open for the whole host invocation.  The operating
    system releases the lock after a crash, so recovery never depends on a
    racy PID probe or unlinking a file another process may just have opened.
    """

    lock_path = run_dir / "execution.lock"
    run_dir.mkdir(parents=True, exist_ok=True)
    if run_dir in _EXECUTION_LOCKS:
        raise ValueError("execution is already running; duplicate launch refused")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        _lock_descriptor(descriptor)
        os.ftruncate(descriptor, 0)
        os.lseek(descriptor, 0, os.SEEK_SET)
        os.write(
            descriptor,
            (
                json.dumps(
                    {
                        "pid": os.getpid(),
                        "started_at": datetime.now(UTC).isoformat(),
                    },
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8"),
        )
        os.fsync(descriptor)
        _EXECUTION_LOCKS[run_dir] = descriptor
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def _release_execution_lock(run_dir: Path) -> None:
    descriptor = _EXECUTION_LOCKS.pop(run_dir, None)
    if descriptor is not None:
        try:
            if os.name == "nt":
                assert msvcrt is not None
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            elif fcntl is not None:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            os.close(descriptor)
        except OSError:
            pass


def _phase1_run_dir_is_retryable(run_dir: Path) -> bool:
    """Allow a fresh launch after the phase launcher recorded a failed preparation."""
    if not run_dir.exists():
        return True
    launcher_logs = {
        "launcher-phase-1.stdout.txt",
        "launcher-phase-1.stderr.txt",
    }
    entries = list(run_dir.iterdir())
    return all(entry.is_file() and entry.name in launcher_logs for entry in entries)


def _set_parent_death_signal() -> None:
    """Make a POSIX Codex child exit when its launcher disappears."""

    if not sys.platform.startswith("linux"):
        return
    try:
        import ctypes
        import signal

        ctypes.CDLL(None).prctl(1, signal.SIGKILL)
    except (AttributeError, OSError):
        # The Windows path uses a Job Object; non-Linux POSIX hosts retain the
        # process group boundary and normal wait/cleanup below.
        return


def _windows_job_guard(process: subprocess.Popen[bytes]) -> int | None:
    """Attach a child to a kill-on-close Job Object on Windows."""

    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimitInformation),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        wintypes.INT,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    information = ExtendedLimitInformation()
    information.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel32.SetInformationJobObject(
        job,
        9,  # JobObjectExtendedLimitInformation
        ctypes.byref(information),
        ctypes.sizeof(information),
    ):
        error = ctypes.WinError(ctypes.get_last_error())
        kernel32.CloseHandle(job)
        raise error
    child_handle = kernel32.OpenProcess(0x1F0FFF, False, process.pid)
    if not child_handle:
        error = ctypes.WinError(ctypes.get_last_error())
        kernel32.CloseHandle(job)
        raise error
    assigned = kernel32.AssignProcessToJobObject(job, child_handle)
    kernel32.CloseHandle(child_handle)
    if not assigned:
        error = ctypes.WinError(ctypes.get_last_error())
        kernel32.CloseHandle(job)
        raise error
    return int(job.value if hasattr(job, "value") else job)


def _close_windows_job_guard(job: int | None) -> None:
    if job is None or os.name != "nt":
        return
    import ctypes

    ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(job)


def _run_owned_codex(
    command: list[str],
    *,
    cwd: Path,
    prompt: bytes,
    trace: Path,
    stderr: Path,
    environment: dict[str, str],
    timeout_seconds: float | None = None,
) -> int:
    """Run Codex with launcher-death cleanup tied to the child lifetime."""

    creation_flags = 0
    if os.name == "nt":
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP
    process: subprocess.Popen[bytes] | None = None
    job: int | None = None
    with trace.open("wb") as output, stderr.open("wb") as errors:
        try:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                stdin=subprocess.PIPE,
                stdout=output,
                stderr=errors,
                env=environment,
                creationflags=creation_flags,
                start_new_session=os.name != "nt",
                preexec_fn=_set_parent_death_signal if os.name != "nt" else None,
            )
            job = _windows_job_guard(process)
            process.communicate(input=prompt, timeout=timeout_seconds)
            return int(process.returncode)
        except subprocess.TimeoutExpired:
            if process is not None and (os.name != "nt" or process.poll() is None):
                _terminate_owned_process(process, process_group=os.name != "nt")
            raise
        except BaseException:
            if process is not None and (os.name != "nt" or process.poll() is None):
                _terminate_owned_process(process, process_group=os.name != "nt")
            raise
        finally:
            _close_windows_job_guard(job)


def _terminate_owned_process(process: subprocess.Popen[bytes], *, process_group: bool) -> None:
    """Stop the Codex child and any descendants it started for this phase."""

    if not process_group:
        process.kill()
        process.wait()
        return
    killpg = getattr(os, "killpg")
    try:
        killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    try:
        killpg(process.pid, getattr(signal, "SIGKILL", 9))
    except ProcessLookupError:
        pass
    process.wait()


def _recover_codex_session(run_dir: Path, record: dict[str, object]) -> str | None:
    """Recover the authoritative session from a prior phase trace after a crash."""

    recorded = record.get("codex_session_id")
    if recorded is not None:
        if not isinstance(recorded, str) or not recorded.strip():
            raise ValueError("execution codex session binding is malformed")
        return recorded
    phases = record.get("phases")
    if not isinstance(phases, list):
        return None
    for item in reversed(phases):
        if not isinstance(item, dict) or not isinstance(item.get("phase"), int):
            continue
        session = _trace_session_id(run_dir / f"phase-{item['phase']}.jsonl")
        if session is None:
            continue
        record["codex_session_id"] = session
        item["codex_session_id"] = session
        return session
    return None


def _execution_identity(run_dir: Path, run_inputs: dict[str, object]) -> dict[str, str]:
    trial = str(run_inputs["trial"])
    outcome = str(run_inputs.get("requested_outcome", ""))
    campaign_value = run_inputs.get("campaign_id")
    campaign = (
        campaign_value
        if isinstance(campaign_value, str) and campaign_value.strip()
        else run_dir.parents[1].name
        if len(run_dir.parents) > 1
        else run_dir.parent.name
    )
    outcome_slug = "".join(c for c in outcome.casefold() if c.isalnum())
    trial_slug = "".join(c for c in trial.casefold() if c.isalnum())
    case = f"{campaign}-{outcome_slug}-{trial_slug}"
    return {
        "campaign_id": campaign,
        "case_id": case,
        "trial_id": trial,
        "outcome": outcome,
    }


def _json_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _changed_runtime_input_keys(prior: dict[str, object], current: dict[str, object]) -> list[str]:
    """Return top-level runtime fields whose frozen values changed."""

    missing = object()
    return sorted(
        key
        for key in set(prior) | set(current)
        if prior.get(key, missing) != current.get(key, missing)
    )


def _codex_home_path(run_dir: Path) -> Path:
    """Keep resumable Codex state outside retained benchmark artifacts."""

    digest = hashlib.sha256(str(run_dir.resolve()).encode("utf-8")).hexdigest()[:24]
    return Path(tempfile.gettempdir()) / "rob2-kit-codex-home" / digest


def _prepare_codex_home(path: Path) -> None:
    """Create a private external session directory and reject symlinked paths."""

    parent = path.parent
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if parent.is_symlink():
        raise ValueError("Codex session directory parent must not be a symlink")
    path.mkdir(mode=0o700, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise ValueError("Codex session directory must be a real directory")
    if os.name != "nt":
        parent_stat = parent.stat()
        path_stat = path.stat()
        current_uid = os.getuid()
        if parent_stat.st_uid != current_uid or path_stat.st_uid != current_uid:
            raise ValueError("Codex session directories must be owned by the current user")
        parent.chmod(0o700)
        path.chmod(0o700)
        if parent.stat().st_mode & 0o077 or path.stat().st_mode & 0o077:
            raise ValueError("Codex session directories must be private to the current user")


def _attempt_identity(
    identity: dict[str, str],
    *,
    run_input_sha256: str,
    prompt_sha256: str,
    manifest_sha256: str | None,
    model: str,
    effort: str,
    selection_policy: str,
    retry: int,
    runtime_inputs: dict[str, object] | None = None,
) -> str:
    """Create a stable attempt identity from immutable launch inputs."""

    payload = {
        "identity": identity,
        "run_input_sha256": run_input_sha256,
        "prompt_sha256": prompt_sha256,
        "manifest_sha256": manifest_sha256,
        "model": model,
        "reasoning_effort": effort,
        "selection_policy": selection_policy,
        "retry": retry,
        "runtime_inputs": runtime_inputs or {},
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return "attempt_" + digest[:32]


def _load_or_create_execution_record(
    run_dir: Path,
    identity: dict[str, str],
    *,
    run_inputs: dict[str, object],
    case_file: Path | None,
    prompt_file: Path,
    phase: int,
    session: str | None,
    allow_stale_running: bool = False,
    expected_tool_inventory: tuple[str, ...] | None = None,
    model: str | None = None,
    effort: str | None = None,
    selection_policy: str | None = None,
    overrides: dict[str, str] | None = None,
    runtime_inputs: dict[str, object] | None = None,
    prompt_bytes: bytes | None = None,
    attempt_number: int = 1,
    allow_build_only_transition: bool = False,
    build_transition_reason: str | None = None,
) -> dict[str, object]:
    path = run_dir / "execution.json"
    now = datetime.now(UTC).isoformat()
    model = model or "gpt-6-luna"
    effort = effort or "medium"
    selection_policy = selection_policy or (
        "select the declared attempt before execution; retain every attempt; "
        "never select a best-scoring retry"
    )
    overrides = dict(overrides or {})
    runtime_inputs = dict(runtime_inputs or {})
    if phase == 1 and (allow_build_only_transition or build_transition_reason is not None):
        raise ValueError("build-only runtime transitions are valid only for continuation phases")
    has_build_transition_reason = bool(
        isinstance(build_transition_reason, str) and build_transition_reason.strip()
    )
    if build_transition_reason is not None and not has_build_transition_reason:
        raise ValueError("--build-transition-reason must be nonempty")
    if allow_build_only_transition != has_build_transition_reason:
        raise ValueError(
            "--allow-build-only-transition and --build-transition-reason must be supplied together"
        )
    if build_transition_reason is not None:
        build_transition_reason = build_transition_reason.strip()
    if (
        isinstance(attempt_number, bool)
        or not isinstance(attempt_number, int)
        or attempt_number < 1
    ):
        raise ValueError("attempt number must be a positive integer")
    runtime_inputs_sha256 = _json_sha256(runtime_inputs) if runtime_inputs else None
    runtime_transition: dict[str, object] | None = None
    if phase > 1 and not path.exists():
        raise ValueError("continuation requires an existing execution.json")
    if path.exists():
        record = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(record, dict) or record.get("identity") != identity:
            raise ValueError("execution identity mismatch; refusing duplicate or moved launch")
        if record.get("state") == "succeeded":
            raise ValueError("execution already succeeded; refusing a duplicate launch")
        if record.get("state") in {"scientific_failed", "cancelled"}:
            raise ValueError(
                f"execution is terminal ({record['state']}); start a new benchmark attempt"
            )
        phases = record.get("phases")
        if not isinstance(phases, list):
            raise ValueError("execution phases are malformed")
        recorded_phases = {
            item.get("phase")
            for item in phases
            if isinstance(item, dict) and isinstance(item.get("phase"), int)
        }
        if phase in recorded_phases:
            raise ValueError(f"phase {phase} is already recorded; use a new phase number")
        if phase > 1 and phase - 1 not in recorded_phases:
            raise ValueError(
                f"phase {phase} has no durable predecessor phase {phase - 1}; "
                "resume from the last recorded checkpoint"
            )
        prior_session = _recover_codex_session(run_dir, record)
        if phase > 1:
            if expected_tool_inventory is not None:
                _validate_tool_inventory(
                    run_dir,
                    phase - 1,
                    expected=expected_tool_inventory,
                    server_inventory=cast(
                        dict[str, object] | None,
                        runtime_inputs.get("server_advertised_inventory")
                        if isinstance(runtime_inputs.get("server_advertised_inventory"), dict)
                        else None,
                    ),
                )
            if not isinstance(prior_session, str):
                raise ValueError(
                    "continuation session binding is unavailable; recover the original "
                    "Codex thread or start a new case"
                )
            if prior_session != session:
                raise ValueError(
                    "continuation session does not match the authoritative phase-1 session"
                )
    else:
        record = {
            "schema": "rob2-kit.rsi-execution.v1",
            "identity": identity,
            "state": "queued",
            "attempt": attempt_number,
            "retry": attempt_number - 1,
            "selected_attempt_rule": selection_policy,
            "attempts": [],
            "phases": [],
            "created_at": now,
            **(
                {
                    "expected_tool_inventory": list(expected_tool_inventory),
                    "tool_inventory_version": TOOL_INVENTORY_VERSION,
                }
                if expected_tool_inventory is not None
                else {}
            ),
            **(
                {
                    "runtime_inputs": runtime_inputs,
                    "runtime_inputs_sha256": runtime_inputs_sha256,
                }
                if runtime_inputs_sha256 is not None
                else {}
            ),
        }
    if record.get("state") == "running" and not allow_stale_running:
        raise ValueError("execution is already running; duplicate launch refused")
    if record.get("state") == "running":
        record["recovered_from_running"] = True
        record["recovered_at"] = now
    prior_state = record.get("state")
    retry_value = record.get("retry", 0)
    retrying_infrastructure = prior_state in {"failed_infrastructure", "expired"}
    retry = (retry_value if isinstance(retry_value, int) else 0) + int(retrying_infrastructure)
    continuation = record.get("continuation")
    prior_lineage = (
        continuation.get("lineage", [])
        if isinstance(continuation, dict) and isinstance(continuation.get("lineage", []), list)
        else []
    )
    run_input_sha256 = hashlib.sha256(
        json.dumps(run_inputs, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    expected_result = run_inputs.get("expected_result")
    expected_result_sha256 = (
        _json_sha256(expected_result) if isinstance(expected_result, dict) else None
    )
    scope_unresolved = run_inputs.get("scope_unresolved")
    scope_unresolved = (
        scope_unresolved.strip()
        if isinstance(scope_unresolved, str) and scope_unresolved.strip()
        else None
    )
    scope_status = "frozen" if expected_result_sha256 is not None else "scope_unresolved"
    prompt_sha256 = hashlib.sha256(
        prompt_bytes if prompt_bytes is not None else prompt_file.read_bytes()
    ).hexdigest()
    manifest_sha256 = _sha256_file(case_file) if case_file else None
    if path.exists():
        for field, current in (
            ("run_input_sha256", run_input_sha256),
            ("manifest_sha256", manifest_sha256),
        ):
            prior = record.get(field)
            if prior is not None and current is not None and prior != current:
                raise ValueError(f"continuation input mismatch for {field}")
        if phase == 1 and record.get("prompt_sha256") not in {None, prompt_sha256}:
            raise ValueError("initial prompt mismatch")
        for field, current in (
            ("model", model),
            ("reasoning_effort", effort),
            ("selected_attempt_rule", selection_policy),
        ):
            prior = record.get(field)
            if prior is not None and prior != current:
                raise ValueError(f"continuation input mismatch for {field}")
        prior_runtime_inputs_sha256 = record.get("runtime_inputs_sha256")
        if runtime_inputs_sha256 is not None or prior_runtime_inputs_sha256 is not None:
            if runtime_inputs_sha256 is None:
                raise ValueError("continuation runtime inputs are required")
            prior_runtime_inputs = record.get("runtime_inputs")
            if not isinstance(prior_runtime_inputs, dict) or not isinstance(
                prior_runtime_inputs_sha256, str
            ):
                raise ValueError("continuation prior top-level runtime provenance is incomplete")
            if _json_sha256(prior_runtime_inputs) != prior_runtime_inputs_sha256:
                raise ValueError(
                    "continuation prior top-level runtime inputs failed their integrity check"
                )
            prior_phase = next(
                (
                    row
                    for row in reversed(phases)
                    if isinstance(row, dict) and row.get("phase") == phase - 1
                ),
                None,
            )
            if not isinstance(prior_phase, dict):
                raise ValueError(f"continuation phase {phase - 1} runtime provenance is missing")
            prior_phase_runtime = prior_phase.get("runtime_inputs")
            prior_phase_runtime_sha256 = prior_phase.get("runtime_inputs_sha256")
            if not isinstance(prior_phase_runtime, dict) or not isinstance(
                prior_phase_runtime_sha256, str
            ):
                raise ValueError(f"continuation phase {phase - 1} runtime provenance is incomplete")
            if _json_sha256(prior_phase_runtime) != prior_phase_runtime_sha256:
                raise ValueError(
                    f"continuation phase {phase - 1} runtime inputs failed their integrity check"
                )
            if prior_phase_runtime_sha256 != prior_runtime_inputs_sha256:
                raise ValueError(
                    "continuation prior phase and top-level runtime hashes do not match"
                )
            changed_keys = _changed_runtime_input_keys(prior_runtime_inputs, runtime_inputs)
            if changed_keys:
                if changed_keys != ["build_sha256"]:
                    raise ValueError(
                        "continuation runtime input mismatch (changed keys: "
                        + ", ".join(changed_keys)
                        + "); only build_sha256 may change with an explicit build-only transition"
                    )
                old_build = prior_runtime_inputs.get("build_sha256")
                new_build = runtime_inputs.get("build_sha256")
                if not isinstance(old_build, str) or not isinstance(new_build, str):
                    raise ValueError(
                        "build-only runtime transition requires nonempty prior and current "
                        "build_sha256"
                    )
                if not allow_build_only_transition:
                    raise ValueError(
                        "continuation runtime input mismatch (changed keys: build_sha256); "
                        "use --allow-build-only-transition with a nonempty "
                        "--build-transition-reason"
                    )
                runtime_transition = {
                    "kind": "build_sha256_only",
                    "old_build_sha256": old_build,
                    "new_build_sha256": new_build,
                    "reason": build_transition_reason,
                    "prior_runtime_inputs_sha256": prior_runtime_inputs_sha256,
                    "prior_phase_runtime_inputs_sha256": prior_phase_runtime_sha256,
                    "new_runtime_inputs_sha256": runtime_inputs_sha256,
                }
            elif allow_build_only_transition:
                raise ValueError(
                    "build-only runtime transition was requested but build_sha256 did not change"
                )
    initial_prompt_sha256 = record.get("prompt_sha256", prompt_sha256)
    if not isinstance(initial_prompt_sha256, str):
        initial_prompt_sha256 = prompt_sha256
    phase_prompt_hashes = record.get("prompt_sha256_by_phase", {})
    if not isinstance(phase_prompt_hashes, dict):
        raise ValueError("execution prompt provenance is malformed")
    phase_prompt_hashes = {str(key): value for key, value in phase_prompt_hashes.items()}
    phase_prompt_hashes[str(phase)] = prompt_sha256
    record_update = {
        "state": "queued",
        "retry": retry,
        "updated_at": now,
        "run_input_sha256": run_input_sha256,
        "expected_result_sha256": expected_result_sha256,
        "scope_status": scope_status,
        **({"scope_unresolved": scope_unresolved} if scope_unresolved is not None else {}),
        "prompt_sha256": initial_prompt_sha256,
        "prompt_sha256_by_phase": phase_prompt_hashes,
        "manifest_sha256": (
            manifest_sha256 if manifest_sha256 is not None else record.get("manifest_sha256")
        ),
        "model": model,
        "reasoning_effort": effort,
        "selected_attempt_rule": selection_policy,
        "selection_policy": {
            "declared_before_execution": True,
            "rule": selection_policy,
        },
        "overrides": overrides,
        "continuation": {
            "session": session,
            "parent_phase": phase - 1 if phase > 1 else None,
            "lineage": [
                *prior_lineage,
                {"phase": phase, "session": session},
            ],
        },
    }
    if runtime_inputs_sha256 is not None:
        record_update["runtime_inputs"] = runtime_inputs
        record_update["runtime_inputs_sha256"] = runtime_inputs_sha256
    record.update(record_update)
    attempt_id = None if retrying_infrastructure else record.get("attempt_id")
    if not isinstance(attempt_id, str) or not attempt_id:
        attempt_id = _attempt_identity(
            identity,
            run_input_sha256=run_input_sha256,
            prompt_sha256=prompt_sha256,
            manifest_sha256=(
                manifest_sha256
                if manifest_sha256 is not None
                else _optional_text(record.get("manifest_sha256"))
            ),
            model=model,
            effort=effort,
            selection_policy=selection_policy,
            retry=retry,
            runtime_inputs=runtime_inputs,
        )
        record["attempt_id"] = attempt_id
    if retrying_infrastructure:
        record["attempt"] = retry + 1
    selection_policy_record = record.get("selection_policy")
    if isinstance(selection_policy_record, dict):
        selection_policy_record["selected_attempt_id"] = attempt_id
    phases = record.setdefault("phases", [])
    if not isinstance(phases, list):
        raise ValueError("execution phases are malformed")
    phase_record: dict[str, object] = {
        "phase": phase,
        "state": "queued",
        "attempt_id": attempt_id,
        "session": session,
        "retry": retry,
        "prompt_sha256": prompt_sha256,
        "started_at": now,
        "expected_result_sha256": expected_result_sha256,
        "scope_status": scope_status,
    }
    if scope_unresolved is not None:
        phase_record["scope_unresolved"] = scope_unresolved
    if runtime_inputs_sha256 is not None:
        phase_record["runtime_inputs"] = runtime_inputs
        phase_record["runtime_inputs_sha256"] = runtime_inputs_sha256
    if runtime_transition is not None:
        phase_record["runtime_transition"] = runtime_transition
    phases.append(phase_record)
    attempts = record.setdefault("attempts", [])
    if not isinstance(attempts, list):
        raise ValueError("execution attempts are malformed")
    attempt_record: dict[str, object] = {
        "attempt_id": attempt_id,
        "attempt": (record.get("attempt", 1) if isinstance(record.get("attempt", 1), int) else 1),
        "phase": phase,
        "state": "queued",
        "retry": retry,
        "kind": "initial"
        if phase == 1 and not retrying_infrastructure and retry == 0
        else ("infrastructure_retry" if retrying_infrastructure or retry > 0 else "resumption"),
        "overrides": overrides,
        "expected_result_sha256": expected_result_sha256,
        "scope_status": scope_status,
    }
    if scope_unresolved is not None:
        attempt_record["scope_unresolved"] = scope_unresolved
    if runtime_inputs_sha256 is not None:
        attempt_record["runtime_inputs_sha256"] = runtime_inputs_sha256
    attempts.append(attempt_record)
    _atomic_json(path, record)
    return record


def _mark_execution_running(run_dir: Path, record: dict[str, object], phase: int) -> None:
    """Persist the transition immediately before starting the Codex child."""
    now = datetime.now(UTC).isoformat()
    record["state"] = "running"
    record["updated_at"] = now
    phases = record.get("phases")
    phase_record = (
        next(
            (
                item
                for item in reversed(phases)
                if isinstance(item, dict) and item.get("phase") == phase
            ),
            None,
        )
        if isinstance(phases, list)
        else None
    )
    if isinstance(phase_record, dict):
        phase_record["state"] = "running"
        phase_record["running_at"] = now
    attempts = record.get("attempts")
    attempt_id = phase_record.get("attempt_id") if isinstance(phase_record, dict) else None
    if isinstance(attempts, list):
        attempt_record = next(
            (
                item
                for item in reversed(attempts)
                if isinstance(item, dict)
                and item.get("attempt_id") == attempt_id
                and item.get("phase") == phase
            ),
            None,
        )
        if isinstance(attempt_record, dict):
            attempt_record["state"] = "running"
            attempt_record["running_at"] = now
    _atomic_json(run_dir / "execution.json", record)


def _load_or_create_execution(
    run_dir: Path,
    identity: dict[str, str],
    *,
    run_inputs: dict[str, object],
    case_file: Path | None,
    prompt_file: Path,
    phase: int,
    session: str | None,
    expected_tool_inventory: tuple[str, ...] | None = None,
    model: str | None = None,
    effort: str | None = None,
    selection_policy: str | None = None,
    overrides: dict[str, str] | None = None,
    runtime_inputs: dict[str, object] | None = None,
    prompt_bytes: bytes | None = None,
    attempt_number: int = 1,
    allow_build_only_transition: bool = False,
    build_transition_reason: str | None = None,
) -> dict[str, object]:
    _acquire_execution_lock(run_dir)
    try:
        allow_stale_running = False
        execution_path = run_dir / "execution.json"
        if execution_path.is_file():
            try:
                prior = json.loads(execution_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                prior = None
            allow_stale_running = isinstance(prior, dict) and prior.get("state") == "running"
        return _load_or_create_execution_record(
            run_dir,
            identity,
            run_inputs=run_inputs,
            case_file=case_file,
            prompt_file=prompt_file,
            phase=phase,
            session=session,
            allow_stale_running=allow_stale_running,
            expected_tool_inventory=expected_tool_inventory,
            model=model,
            effort=effort,
            selection_policy=selection_policy,
            overrides=overrides,
            runtime_inputs=runtime_inputs,
            prompt_bytes=prompt_bytes,
            attempt_number=attempt_number,
            allow_build_only_transition=allow_build_only_transition,
            build_transition_reason=build_transition_reason,
        )
    except BaseException:
        _release_execution_lock(run_dir)
        raise


def _finish_execution(
    run_dir: Path,
    record: dict[str, object],
    phase: int,
    exit_code: int,
    *,
    artifact: dict[str, object] | None = None,
    waiting_for_user: bool = False,
    terminal_state: str | None = None,
    terminal_reason: str | None = None,
    expected_session: str | None = None,
) -> str | None:
    path = run_dir / "execution.json"
    trace = run_dir / f"phase-{phase}.jsonl"
    rob2_calls = rob2_call_diagnostics(trace)
    pending_calls = rob2_calls["incomplete"]
    if terminal_state is None and pending_calls:
        terminal_state = "failed_infrastructure"
        terminal_reason = (
            "Codex exited without a successful rob2 MCP response for call(s): "
            + ", ".join(pending_calls)
        )
    phases = record.get("phases")
    phase_record = (
        next(
            (
                item
                for item in reversed(phases)
                if isinstance(item, dict) and item.get("phase") == phase
            ),
            None,
        )
        if isinstance(phases, list)
        else None
    )
    if isinstance(phase_record, dict):
        delivery = host_delivery_observed(trace, expected_session)
        phase_record.update(
            {
                "finished_at": datetime.now(UTC).isoformat(),
                "exit_code": exit_code,
                "trace_sha256": _sha256_file(trace) if trace.is_file() else None,
                "codex_session_id": _trace_session_id(trace),
                "host_delivery_observed": delivery,
                "timed_out_rob2_calls": list(rob2_calls["timed_out"]),
            }
        )
    session_id = _trace_session_id(trace)
    if session_id is not None:
        record["codex_session_id"] = session_id
    if artifact and isinstance(artifact.get("path"), str):
        artifact_path = run_dir / "workspace" / str(artifact["path"])
        if artifact_path.is_file():
            verified = False
            verification_message = "bundle verification was not attempted"
            try:
                verifier = runpy.run_path(str(Path(__file__).with_name("verify_bundle.py")))
                verified, verification_message = verifier["verify"](artifact_path)
            except (OSError, KeyError, TypeError, ValueError) as error:
                verification_message = f"bundle verification failed to run: {error}"
            record["artifact"] = {
                "path": str(artifact_path.relative_to(run_dir)),
                "sha256": _sha256_file(artifact_path),
                "identity": artifact.get("identity"),
                "attempt_id": record.get("attempt_id"),
                "verified": bool(verified),
                "verification": verification_message,
            }
    saved_artifact = record.get("artifact")
    artifact_error: str | None = None
    if artifact and isinstance(artifact.get("path"), str):
        artifact_path = run_dir / "workspace" / str(artifact["path"])
        if artifact_path.is_file():
            try:
                internal_identity = artifact_manifest_identity(artifact_path)
            except ValueError as error:
                artifact_error = str(error)
            else:
                reported_identity = artifact.get("identity")
                if not isinstance(reported_identity, str) or reported_identity != internal_identity:
                    artifact_error = (
                        "artifact identity mismatch: execution receipt does not match "
                        "the identity recorded in manifest.json"
                    )
        else:
            artifact_error = "artifact path is missing while binding its internal identity"
    if artifact_error is not None:
        record.pop("artifact", None)
        record["artifact_error"] = artifact_error
    effective_terminal_state = terminal_state if terminal_state is not None else None
    if effective_terminal_state is not None and effective_terminal_state not in {
        "queued",
        "running",
        "waiting_for_user",
        "resumable",
        "succeeded",
        "failed_infrastructure",
        "scientific_failed",
        "cancelled",
        "expired",
    }:
        raise ValueError(f"unsupported execution terminal state: {terminal_state}")
    if terminal_state in {"failed_infrastructure", "scientific_failed", "cancelled", "expired"}:
        if not isinstance(terminal_reason, str) or not terminal_reason.strip():
            raise ValueError(f"{terminal_state} requires an explicit terminal reason")
        record["terminal_reason"] = terminal_reason.strip()
    record["state"] = (
        effective_terminal_state
        if effective_terminal_state is not None
        else (
            "waiting_for_user"
            if waiting_for_user and exit_code == 0
            else (
                "succeeded"
                if exit_code == 0
                and artifact_error is None
                and isinstance(saved_artifact, dict)
                and saved_artifact.get("verified") is True
                else "resumable"
            )
        )
    )
    phase_reason = terminal_reason.strip() if isinstance(terminal_reason, str) else ""
    if not phase_reason and artifact_error is not None:
        phase_reason = artifact_error
    if not phase_reason and exit_code != 0:
        phase_reason = (
            f"Codex CLI exited with status {exit_code}; no scientific outcome was inferred."
        )
    record["child_exit_code"] = exit_code
    record["updated_at"] = datetime.now(UTC).isoformat()
    if isinstance(phases, list):
        phase_record = next(
            (
                item
                for item in reversed(phases)
                if isinstance(item, dict) and item.get("phase") == phase
            ),
            None,
        )
        if isinstance(phase_record, dict):
            phase_record["state"] = record["state"]
            if phase_reason:
                phase_record["terminal_reason"] = phase_reason
            phase_record["artifact_sha256"] = (
                saved_artifact.get("sha256") if isinstance(saved_artifact, dict) else None
            )
    attempts = record.get("attempts")
    if isinstance(attempts, list) and isinstance(phase_record, dict):
        attempt_id = phase_record.get("attempt_id")
        attempt_record = next(
            (
                item
                for item in reversed(attempts)
                if isinstance(item, dict)
                and item.get("attempt_id") == attempt_id
                and item.get("phase") == phase
            ),
            None,
        )
        if isinstance(attempt_record, dict):
            attempt_record["state"] = record["state"]
            if phase_reason:
                attempt_record["terminal_reason"] = phase_reason
    try:
        _atomic_json(path, record)
    finally:
        _release_execution_lock(run_dir)
    if artifact_error is not None:
        raise ValueError(artifact_error)
    return terminal_reason.strip() if isinstance(terminal_reason, str) else None


def _mark_scientific_terminal(run_dir: Path, reason: str) -> dict[str, object]:
    """Record an explicit operator classification without deriving it from exit status."""

    _acquire_execution_lock(run_dir)
    path = run_dir / "execution.json"
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(record, dict):
            raise ValueError("execution record is malformed")
        prior_state = record.get("state")
        if prior_state not in {"resumable", "waiting_for_user"}:
            raise ValueError(
                "only a resumable or waiting execution can be classified scientifically terminal"
            )
        record["state"] = "scientific_failed"
        record["terminal_reason"] = reason.strip()
        record["terminal_classification_source"] = "explicit operator command"
        record["updated_at"] = datetime.now(UTC).isoformat()
        phases = record.get("phases")
        if isinstance(phases, list) and phases and isinstance(phases[-1], dict):
            phases[-1]["state_before_classification"] = prior_state
            phases[-1]["state"] = "scientific_failed"
            phases[-1]["terminal_reason"] = reason.strip()
            attempts = record.get("attempts")
            if isinstance(attempts, list):
                last_phase = phases[-1].get("phase")
                last_attempt = next(
                    (
                        item
                        for item in reversed(attempts)
                        if isinstance(item, dict)
                        and item.get("phase") == last_phase
                        and item.get("attempt_id") == phases[-1].get("attempt_id")
                    ),
                    None,
                )
                if isinstance(last_attempt, dict):
                    last_attempt["state_before_classification"] = prior_state
                    last_attempt["state"] = "scientific_failed"
                    last_attempt["terminal_reason"] = reason.strip()
        history = record.setdefault("terminal_classification_history", [])
        if isinstance(history, list):
            history.append(
                {
                    "prior_state": prior_state,
                    "state": "scientific_failed",
                    "reason": reason.strip(),
                    "classified_at": record["updated_at"],
                }
            )
        _atomic_json(path, record)
        return record
    finally:
        _release_execution_lock(run_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, help="Frozen JSON source/scope manifest (phase 1)")
    parser.add_argument("--prompt", type=Path)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--phase", type=int)
    parser.add_argument("--session", help="Codex session ID for a continuation phase")
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        help="Stop and record an expired infrastructure attempt after this many seconds",
    )
    parser.add_argument("--benchmark-index", type=Path)
    parser.add_argument("--benchmark-index-sha256")
    parser.add_argument("--attempt-number", type=int, default=1)
    parser.add_argument(
        "--mark-scientific-terminal",
        action="store_true",
        help="Explicitly mark an existing non-successful execution scientifically terminal",
    )
    parser.add_argument("--terminal-reason")
    parser.add_argument("--model")
    parser.add_argument("--effort")
    parser.add_argument(
        "--manifest-model",
        help="model declared by the benchmark manifest (used to identify overrides)",
    )
    parser.add_argument(
        "--manifest-effort",
        help="reasoning effort declared by the benchmark manifest",
    )
    parser.add_argument(
        "--selection-policy",
        default=(
            "select the declared attempt before execution; retain every attempt; "
            "never select a best-scoring retry"
        ),
    )
    parser.add_argument(
        "--require-isolated-host",
        action="store_true",
        help="Use a deny-by-default filesystem profile for qualification runs",
    )
    parser.add_argument(
        "--proposal-correction",
        action="store_true",
        help="Resume a pending Proposal Review to request a replacement Result",
    )
    parser.add_argument(
        "--allow-build-only-transition",
        action="store_true",
        help="Permit a continuation whose only runtime change is build_sha256",
    )
    parser.add_argument(
        "--build-transition-reason",
        help="Required nonempty reason when allowing a build-only continuation transition",
    )
    args = parser.parse_args()
    if args.mark_scientific_terminal:
        if not args.terminal_reason or not args.terminal_reason.strip():
            parser.error("--mark-scientific-terminal requires --terminal-reason")
        if any((args.prompt, args.phase is not None, args.session, args.case)):
            parser.error("scientific terminal marking is a separate command, without phase inputs")
        try:
            record = _mark_scientific_terminal(args.run_dir.resolve(), args.terminal_reason)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            parser.error(str(error))
        print(json.dumps({"state": record["state"], "terminal_reason": record["terminal_reason"]}))
        return
    if args.prompt is None or args.phase is None:
        parser.error("launching a phase requires --prompt and --phase")
    if args.timeout_seconds is not None and args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    if args.attempt_number < 1:
        parser.error("--attempt-number must be positive")
    if args.phase == 1 and (
        args.allow_build_only_transition or args.build_transition_reason is not None
    ):
        parser.error("build-only runtime transitions are valid only for continuation phases")
    if args.allow_build_only_transition != bool(
        isinstance(args.build_transition_reason, str) and args.build_transition_reason.strip()
    ):
        parser.error(
            "--allow-build-only-transition and --build-transition-reason must be supplied together"
        )
    if args.build_transition_reason is not None and not args.build_transition_reason.strip():
        parser.error("--build-transition-reason must be nonempty")
    if bool(args.benchmark_index) != bool(args.benchmark_index_sha256):
        parser.error("--benchmark-index and --benchmark-index-sha256 must be supplied together")
    if args.phase < 1 or (args.phase > 1) != bool(args.session):
        parser.error("phase 1 starts a session; later phases require --session")
    if args.proposal_correction and (args.phase == 1 or not args.session):
        parser.error("Proposal corrections require a continuation phase and session")
    if args.require_isolated_host and _is_windows():
        parser.error(
            "requested strict host isolation is unsupported on Windows without UAC; "
            "use a POSIX host or run the documented non-strict Windows profile"
        )
    repository = Path(__file__).resolve().parents[1]
    run_dir = args.run_dir.resolve()
    prompt_file = args.prompt.resolve(strict=True)
    prompt_bytes = prompt_file.read_bytes()
    prompt_sha256 = hashlib.sha256(prompt_bytes).hexdigest()
    codex_home = _codex_home_path(run_dir)
    case_file = args.case.resolve(strict=True) if args.case is not None else None
    case_settings: dict[str, object] = {}
    if case_file is not None:
        try:
            loaded_case = json.loads(case_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            parser.error(f"case manifest is unreadable: {error}")
        if isinstance(loaded_case, dict):
            case_settings = loaded_case
    manifest_model = _optional_text(args.manifest_model) or (
        case_settings.get("model") if isinstance(case_settings.get("model"), str) else None
    )
    manifest_effort = _optional_text(args.manifest_effort) or (
        case_settings.get("reasoning_effort")
        if isinstance(case_settings.get("reasoning_effort"), str)
        else case_settings.get("effort")
        if isinstance(case_settings.get("effort"), str)
        else None
    )
    cli_model = _optional_text(args.model)
    cli_effort = _optional_text(args.effort)
    model = _first_text(cli_model, manifest_model, default="gpt-6-luna")
    effort = _first_text(cli_effort, manifest_effort, default="medium")
    overrides = {
        key: value
        for key, value, manifest_value in (
            ("model", cli_model, manifest_model),
            ("reasoning_effort", cli_effort, manifest_effort),
        )
        if isinstance(value, str) and value != manifest_value
    }
    phase_artifacts = tuple(
        run_dir / f"phase-{args.phase}{suffix}"
        for suffix in (
            ".jsonl",
            ".stderr.txt",
            ".last-message.txt",
            ".meta.json",
        )
    )
    if any(path.exists() for path in phase_artifacts):
        parser.error(
            f"phase {args.phase} artifacts already exist; choose a new phase or run directory"
        )
    if args.phase == 1 and not _phase1_run_dir_is_retryable(run_dir):
        parser.error("run directory already contains phase-1 state; choose a fresh run directory")
    isolation_record = run_dir / "host-isolation.json"
    if args.phase > 1:
        if not isolation_record.is_file():
            parser.error("phase 1 host-isolation.json is missing; start a fresh run")
        try:
            previous_isolation = json.loads(isolation_record.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            parser.error(f"phase 1 host-isolation.json is unreadable: {error}")
        if not isinstance(previous_isolation, dict):
            parser.error("phase 1 host-isolation.json is malformed")
        if bool(previous_isolation.get("required")) != args.require_isolated_host:
            parser.error(
                "host isolation must match phase 1; repeat --require-isolated-host "
                "for every continuation"
            )

    auth_source = Path.home() / ".codex" / "auth.json"
    if not auth_source.is_file():
        raise RuntimeError(f"Codex authentication file is unavailable: {auth_source}")

    rob2_command = _resolve_executable(
        repository,
        "ROB2_EXECUTABLE",
        (Path(".venv") / "Scripts" / "rob2.exe", Path(".venv") / "bin" / "rob2"),
        ("rob2",),
    )
    codex_command = _resolve_executable(
        repository,
        "CODEX_EXECUTABLE",
        (),
        ("codex.cmd", "codex.exe", "codex"),
    )
    preflight = {
        "rob2": {"path": str(rob2_command)},
        "codex": {
            "path": str(codex_command),
            "version": _preflight_executable(codex_command, "Codex"),
        },
        "host": {"platform": sys.platform, "os_name": os.name},
        "isolation": _preflight_isolation(codex_command, args.require_isolated_host),
    }
    workspace = run_dir / "workspace"
    skill = workspace / ".agents" / "skills" / "rob2-assess"
    approved_scope_for_record: dict[str, object] | None = None
    if args.phase == 1:
        if case_file is None:
            parser.error("phase 1 requires --case")
        run_inputs = prepare_workspace(case_file, workspace)
        (workspace / ".tmp").mkdir(parents=True, exist_ok=True)
        isolation_record.write_text(
            json.dumps(
                {
                    "required": args.require_isolated_host,
                    "preflight": preflight["isolation"],
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        (run_dir / "run-inputs.json").write_text(
            json.dumps(run_inputs, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        subprocess.run(
            [
                str(rob2_command),
                "export-skill",
                "--output",
                str(skill),
            ],
            check=True,
        )
    elif not (workspace / "input").is_dir():
        parser.error("prepared workspace is missing")
    else:
        (workspace / ".tmp").mkdir(parents=True, exist_ok=True)

    run_inputs = json.loads((run_dir / "run-inputs.json").read_text(encoding="utf-8"))
    expected_result = run_inputs.get("expected_result") if isinstance(run_inputs, dict) else None
    unresolved_scope = run_inputs.get("scope_unresolved") if isinstance(run_inputs, dict) else None
    unresolved_scope = (
        unresolved_scope.strip()
        if isinstance(unresolved_scope, str) and unresolved_scope.strip()
        else None
    )
    if not isinstance(expected_result, dict):
        parser.error(
            "scope_unresolved cases cannot launch; freeze a complete expected_result "
            "before execution"
        )
    if unresolved_scope is not None:
        parser.error("launch inputs cannot contain both expected_result and scope_unresolved")
    benchmark_binding: dict[str, str] | None = None
    if args.benchmark_index is not None and isinstance(run_inputs, dict):
        index_row = {
            "trial": run_inputs.get("trial"),
            "outcome": run_inputs.get("requested_outcome"),
            "expected_result": run_inputs.get("expected_result"),
            "scope_unresolved": run_inputs.get("scope_unresolved"),
            "campaign_id": run_inputs.get("campaign_id"),
        }
        try:
            benchmark_binding = execution_index_binding(
                args.benchmark_index,
                args.benchmark_index_sha256,
                index_row,
                run_dir,
                args.attempt_number,
            )
        except (OSError, ValueError) as error:
            parser.error(str(error))
    try:
        server_inventory = probe_server_advertised_inventory(rob2_command, workspace)
        # Process cleanup is per-probe telemetry, not part of frozen server identity.
        preflight["rob2"]["probe_cleanup"] = server_inventory.pop("probe_cleanup", "unknown")
        server_info = server_inventory.get("server_info")
        server_version = server_info.get("version") if isinstance(server_info, dict) else None
        preflight["rob2"]["version"] = (
            server_version.strip()
            if isinstance(server_version, str) and server_version.strip()
            else "unknown"
        )
        if args.phase > 1:
            _validate_tool_inventory(
                run_dir,
                args.phase - 1,
                server_inventory=server_inventory,
            )
    except (OSError, ValueError, RuntimeError) as error:
        parser.error(str(error))
    if args.phase > 1:
        status = subprocess.run(
            [str(rob2_command), "status", "--workspace", str(workspace)],
            capture_output=True,
            text=True,
            check=True,
        )
        status_data = json.loads(status.stdout)
        continuation = status_data.get("continuation") or {}
        proposal_review_pending = (
            status_data.get("phase") == "proposal"
            and continuation.get("authority") == "researcher"
            and continuation.get("operation") == "researcher_review"
        )
        if proposal_review_pending and not args.proposal_correction:
            parser.error(
                "Proposal Review is still pending; acknowledge it with rob2 review "
                "before resuming the Codex session"
            )
        if args.proposal_correction and not proposal_review_pending:
            parser.error("Proposal correction requires a pending researcher Proposal Review")
        approved_scope = approved_scope_record(workspace, run_inputs.get("approved_scope"))
        if approved_scope is not None:
            approved_scope_for_record = approved_scope

    skill_digest = hashlib.sha256()
    for member in sorted(path for path in skill.rglob("*") if path.is_file()):
        skill_digest.update(member.relative_to(skill).as_posix().encode("utf-8"))
        skill_digest.update(member.read_bytes())
    build_digest = hashlib.sha256()
    package_root = repository / "src" / "rob2_kit"
    for member in sorted(
        path
        for path in package_root.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    ):
        build_digest.update(member.relative_to(repository).as_posix().encode("utf-8"))
        build_digest.update(member.read_bytes())
    for member in (
        Path(__file__).resolve(),
        Path(__file__).resolve().with_name("prepare_rsi_workspace.py"),
        Path(__file__).resolve().with_name("benchmark_contract.py"),
        Path(__file__).resolve().with_name("benchmark_recovery_exec_allowlist.json"),
        repository / "pyproject.toml",
        repository / "uv.lock",
        rob2_command,
        codex_command,
    ):
        _add_digest_member(build_digest, member, repository)
    runtime_inputs: dict[str, object] = {
        "build_sha256": build_digest.hexdigest(),
        "skill_sha256": skill_digest.hexdigest(),
        # Case manifests predate explicit pack/contract fields; retain the
        # installed benchmark defaults in the immutable launch inputs.
        "pack": (run_inputs.get("pack_version") or run_inputs.get("pack") or "2019.1"),
        "contract": (
            run_inputs.get("contract_version")
            or run_inputs.get("contract")
            or public_contract_version()
        ),
        "host": preflight["host"],
        "expected_tool_inventory": list(EXPECTED_TOOL_INVENTORY),
        "tool_inventory_version": TOOL_INVENTORY_VERSION,
        "tool_inventory": tool_inventory_provenance(),
        "server_advertised_inventory": server_inventory,
        # This is the exact runner-generated Codex MCP configuration. It is
        # separate from the server's tools/list claim and does not claim that
        # Codex exposed every advertised tool to the model.
        "codex_registered_mcp": server_inventory.get("server_binding"),
        "scope_status": "frozen" if isinstance(expected_result, dict) else "scope_unresolved",
        "timeout_seconds": args.timeout_seconds,
        "host_isolation_required": args.require_isolated_host,
        "campaign_attempt_number": args.attempt_number,
        "codex_home_path": str(codex_home),
        **({"benchmark_index": benchmark_binding} if benchmark_binding is not None else {}),
        **({"scope_unresolved": unresolved_scope} if unresolved_scope is not None else {}),
    }
    previous_runtime: object = None
    previous_execution_path = run_dir / "execution.json"
    if args.phase > 1 and previous_execution_path.is_file():
        try:
            previous_execution = json.loads(previous_execution_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous_execution = None
        if isinstance(previous_execution, dict):
            previous_runtime = previous_execution.get("runtime_inputs")
    if args.phase == 1 or (
        isinstance(previous_runtime, dict) and "codex_mcp_tool_timeout_sec" in previous_runtime
    ):
        runtime_inputs["codex_mcp_tool_timeout_sec"] = ROB2_MCP_TOOL_TIMEOUT_SECONDS

    try:
        execution = _load_or_create_execution(
            run_dir,
            _execution_identity(run_dir, run_inputs),
            run_inputs=run_inputs,
            case_file=case_file,
            prompt_file=prompt_file,
            phase=args.phase,
            session=args.session,
            expected_tool_inventory=EXPECTED_TOOL_INVENTORY,
            model=model,
            effort=effort,
            selection_policy=args.selection_policy,
            overrides=overrides,
            runtime_inputs=runtime_inputs,
            prompt_bytes=prompt_bytes,
            attempt_number=args.attempt_number,
            allow_build_only_transition=args.allow_build_only_transition,
            build_transition_reason=args.build_transition_reason,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))

    if approved_scope_for_record is not None:
        (run_dir / "approved-scope.json").write_text(
            json.dumps(approved_scope_for_record, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    _prepare_codex_home(codex_home)
    auth_copy = codex_home / "auth.json"
    profile: list[str] = []
    if args.require_isolated_host:
        auth_source = Path.home() / ".codex" / "auth.json"
        campaign_root = (
            args.benchmark_index.resolve().parent if args.benchmark_index is not None else run_dir
        )
        denied_directories = tuple(
            dict.fromkeys(
                (
                    Path(tempfile.gettempdir()),
                    campaign_root,
                    run_dir,
                    auth_source.parent,
                    repository / "eval" / "reference",
                    repository / "eval" / "cohorts",
                    repository / "eval" / "runs",
                )
            )
        )
        profile = _strict_filesystem_profile(
            workspace,
            repository,
            denied_directories,
            (),
        )
        profile.insert(
            profile.index("[permissions.rob2-rsi.network]"),
            f'{json.dumps(str(codex_command.resolve().parent.parent))} = "read"',
        )
    scorer_path = repository / "scripts" / "analyze_rsi_runs.py"
    scorer_metadata: dict[str, object] = {
        "schema": "rob2-kit.rsi-run-analysis.v1",
        "path": str(scorer_path),
    }
    if scorer_path.is_file():
        scorer_metadata["sha256"] = hashlib.sha256(scorer_path.read_bytes()).hexdigest()
    else:
        scorer_metadata["available"] = False
    codex_mcp_binding = runtime_inputs.get("codex_registered_mcp")
    if not isinstance(codex_mcp_binding, dict):
        parser.error("Codex rob2 command/args binding is missing from the server preflight")
    codex_mcp_command = codex_mcp_binding.get("command")
    codex_mcp_args = codex_mcp_binding.get("args")
    if (
        not isinstance(codex_mcp_command, str)
        or codex_mcp_args != ["mcp"]
        or codex_mcp_binding.get("server") != "rob2"
        or codex_mcp_binding.get("workspace_sha256")
        != hashlib.sha256(str(workspace.resolve()).encode("utf-8")).hexdigest()
    ):
        parser.error("Codex rob2 command/args do not match the exact tools/list preflight")
    profile.extend(_codex_mcp_config(codex_mcp_command, workspace))
    codex_config_path = codex_home / "config.toml"
    codex_config_bytes = ("\n".join(profile) + "\n").encode("utf-8")
    codex_config_path.write_bytes(codex_config_bytes)
    config_snapshot_path = run_dir / f"phase-{args.phase}.codex-config.toml"
    if config_snapshot_path.is_file():
        if config_snapshot_path.read_bytes() != codex_config_bytes:
            parser.error(
                f"Phase {args.phase} Codex config snapshot already exists with different content"
            )
    else:
        config_snapshot_path.write_bytes(codex_config_bytes)
    config: list[str] = [
        "-c",
        "model_reasoning_effort=" + json.dumps(effort),
    ]
    if not args.require_isolated_host:
        config += [
            "-c",
            'approval_policy="on-request"',
            "-c",
            'approvals_reviewer="auto_review"',
            "-c",
            'sandbox_mode="workspace-write"',
        ]
        if _is_windows():
            config += ["-c", 'windows.sandbox="unelevated"']
    command: list[str] = [str(codex_command), "exec"]
    if args.session:
        command += ["resume", args.session]
    command += [
        *(
            ["--strict-config", "-c", 'default_permissions="rob2-rsi"']
            if args.require_isolated_host
            else []
        ),
        "--skip-git-repo-check",
        "--json",
        "--model",
        model,
        *config,
        "--disable",
        "plugins",
        "--disable",
        "apps",
        "--disable",
        "remote_plugin",
        "--output-last-message",
        str(run_dir / f"phase-{args.phase}.last-message.txt"),
        "-",
    ]
    if not args.session:
        command[command.index("-") : command.index("-")] = ["-C", str(workspace)]
    trace = run_dir / f"phase-{args.phase}.jsonl"
    stderr = run_dir / f"phase-{args.phase}.stderr.txt"
    metadata = {
        "model": model,
        "effort": effort,
        "manifest_model": manifest_model,
        "manifest_effort": manifest_effort,
        "overrides": overrides,
        "kit_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repository, text=True
        ).strip(),
        "build_sha256": build_digest.hexdigest(),
        "skill_sha256": skill_digest.hexdigest(),
        "trial": run_inputs["trial"],
        "phase": args.phase,
        "phase_kind": (
            "proposal_correction"
            if args.proposal_correction
            else ("initial" if args.phase == 1 else "continuation")
        ),
        "session": args.session,
        "prompt_file": str(prompt_file),
        "prompt_sha256": prompt_sha256,
        "run_inputs_sha256": hashlib.sha256(
            json.dumps(run_inputs, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "command": command,
        "host_isolation": {
            "required": args.require_isolated_host,
            "policy": "deny-by-default" if args.require_isolated_host else "legacy-workspace-write",
        },
        "preflight": preflight,
        "selection_convention": (
            "one uncoached run per eligible Trial/outcome; retain every attempt; use the "
            "declared selected attempt for scoring; never select a best retry"
        ),
        "retry_rule": (
            "retry only a documented infrastructure interruption; retain the failed attempt; "
            "do not retry a scientific disagreement"
        ),
        "budget": {
            "reasoning_effort": effort,
            "phase": "single host invocation",
            "declared": "Codex CLI budget for the selected reasoning effort",
            "timeout_seconds": args.timeout_seconds,
        },
        "scorer": scorer_metadata,
        "runtime_inputs": runtime_inputs,
        "runtime_inputs_sha256": _json_sha256(runtime_inputs),
        "codex_mcp_config": {
            "path": str(codex_config_path),
            "sha256": _sha256_file(codex_config_path),
            "snapshot_path": config_snapshot_path.name,
            "snapshot_sha256": _sha256_file(config_snapshot_path),
            "required": True,
            "tool_timeout_sec": ROB2_MCP_TOOL_TIMEOUT_SECONDS,
            "timeout_reason": (
                "Increased after a benchmark source search exceeded the former 300-second "
                "client limit and returned later."
            ),
        },
        "server_advertised_inventory": server_inventory,
    }
    phase_transition = None
    recorded_phases = execution.get("phases")
    if isinstance(recorded_phases, list):
        recorded_phase = next(
            (
                row
                for row in reversed(recorded_phases)
                if isinstance(row, dict) and row.get("phase") == args.phase
            ),
            None,
        )
        if isinstance(recorded_phase, dict):
            candidate_transition = recorded_phase.get("runtime_transition")
            if isinstance(candidate_transition, dict):
                phase_transition = candidate_transition
    if phase_transition is not None:
        metadata["runtime_transition"] = phase_transition
    execution_identity = execution.get("identity")
    execution_identity = execution_identity if isinstance(execution_identity, dict) else {}
    execution["provenance"] = {
        "case": {
            "campaign_id": execution_identity.get("campaign_id"),
            "case_id": execution_identity.get("case_id"),
            "trial": run_inputs.get("trial"),
            "outcome": run_inputs.get("requested_outcome"),
            "run_inputs_sha256": metadata["run_inputs_sha256"],
            "sources": run_inputs.get("sources", []),
        },
        "prompt": {
            "path": str(prompt_file),
            "sha256": metadata["prompt_sha256"],
        },
        "build": {
            "kit_commit": metadata["kit_commit"],
            "sha256": metadata["build_sha256"],
        },
        "skill": {"sha256": metadata["skill_sha256"]},
        "contract": runtime_inputs["contract"],
        "pack": runtime_inputs["pack"],
        "host": preflight["host"],
        "model": model,
        "reasoning_effort": effort,
        "overrides": overrides,
        "tool_inventory": {
            "expected": list(EXPECTED_TOOL_INVENTORY),
            "version": TOOL_INVENTORY_VERSION,
        },
    }
    execution["selection_policy"] = {
        "declared_before_execution": True,
        "rule": args.selection_policy,
        "selected_attempt_id": execution.get("attempt_id"),
    }
    _atomic_json(run_dir / "execution.json", execution)
    metadata_path = run_dir / f"phase-{args.phase}.meta.json"
    _atomic_json(metadata_path, metadata)
    environment = _codex_environment(
        codex_home,
        workspace,
        strict=args.require_isolated_host,
    )
    completed: subprocess.CompletedProcess[bytes] | None = None
    terminal_state: str | None = None
    terminal_reason: str | None = None
    try:
        auth_copy.unlink(missing_ok=True)
        shutil.copyfile(auth_source, auth_copy)
        _mark_execution_running(run_dir, execution, args.phase)
        completed = subprocess.CompletedProcess(
            command,
            _run_owned_codex(
                command,
                cwd=workspace,
                prompt=prompt_bytes,
                trace=trace,
                stderr=stderr,
                environment=environment,
                timeout_seconds=args.timeout_seconds,
            ),
        )
    except subprocess.TimeoutExpired:
        terminal_state = "expired"
        terminal_reason = f"Codex phase exceeded {args.timeout_seconds} seconds."
        completed = subprocess.CompletedProcess(command, 124)
    except KeyboardInterrupt:
        terminal_state = "cancelled"
        terminal_reason = "Codex phase was interrupted by the operator."
        completed = subprocess.CompletedProcess(command, 130)
    except BaseException:
        _finish_execution(run_dir, execution, args.phase, 125, expected_session=args.session)
        raise
    finally:
        auth_copy.unlink(missing_ok=True)
    if completed is None:
        raise RuntimeError("Codex phase did not start")
    codex_exit_code = completed.returncode
    postcondition_exit, postcondition_state, postcondition_reason, delivery_diagnosis = (
        _host_delivery_postcondition(codex_exit_code, trace, args.session)
    )
    if postcondition_state is not None:
        terminal_state = postcondition_state
        terminal_reason = postcondition_reason
        completed = subprocess.CompletedProcess(command, postcondition_exit)
    artifact = None
    waiting_for_user = False
    if completed.returncode == 0:
        try:
            status = subprocess.run(
                [str(rob2_command), "status", "--workspace", str(workspace)],
                capture_output=True,
                text=True,
                check=True,
            )
            status_data = json.loads(status.stdout)
            status_payload = status_data.get("data") if isinstance(status_data, dict) else None
            artifact = status_data.get("artifact") if isinstance(status_data, dict) else None
            if artifact is None and isinstance(status_payload, dict):
                artifact = status_payload.get("artifact")
            if artifact is None:
                artifact = _trace_artifact(run_dir, args.phase)
            continuation = (
                status_data.get("continuation") if isinstance(status_data, dict) else None
            )
            waiting_for_user = bool(
                isinstance(status_data, dict)
                and status_data.get("phase") == "proposal"
                and isinstance(continuation, dict)
                and continuation.get("authority") == "researcher"
            )
        except (OSError, subprocess.CalledProcessError, json.JSONDecodeError):
            artifact = None
    terminal_reason = _finish_execution(
        run_dir,
        execution,
        args.phase,
        completed.returncode,
        artifact=artifact,
        waiting_for_user=waiting_for_user,
        terminal_state=terminal_state,
        terminal_reason=terminal_reason,
        expected_session=args.session,
    )
    metadata.update(
        {
            "finished_at": datetime.now(UTC).isoformat(),
            "exit_code": completed.returncode,
            "codex_exit_code": codex_exit_code,
            **(
                {"host_delivery_diagnosis": delivery_diagnosis}
                if delivery_diagnosis is not None
                else {}
            ),
            **_phase_completion_metadata(trace, args.session),
            "execution_state": execution.get("state"),
            "terminal_reason": terminal_reason,
        }
    )
    _atomic_json(metadata_path, metadata)
    print(json.dumps({"exit_code": completed.returncode, "trace": str(trace)}))
    if completed.returncode:
        raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()

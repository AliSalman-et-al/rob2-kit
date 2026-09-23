"""Run one isolated Codex/rob2 diagnostic phase and retain its full JSONL trace."""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import runpy
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from benchmark_contract import (
    TOOL_INVENTORY_VERSION,
    artifact_manifest_identity,
    public_contract_version,
    public_tool_inventory,
    tool_inventory_provenance,
    trace_has_rob2_runtime_evidence,
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

_SESSION_EVENT_TYPES = {
    "session.started",
    "session.created",
    "session_id",
    "thread.started",
}
_TOOL_INVENTORY_EVENT_TYPES = {
    "mcp_list_tools",
    "mcp.tools.list",
    "session.ready",
    "thread.ready",
}


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

    sessions: set[str] = set()
    inventories: set[tuple[str, ...]] = set()
    if not path.is_file():
        return {"sessions": (), "inventories": ()}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {"sessions": (), "inventories": ()}
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        event_type = event.get("type")
        if event_type in _SESSION_EVENT_TYPES or (
            event_type is None and any(key in event for key in ("thread_id", "session_id"))
        ):
            for key in ("thread_id", "session_id"):
                value = event.get(key)
                if isinstance(value, str) and value.strip():
                    sessions.add(value.strip())
            thread = event.get("thread")
            if isinstance(thread, dict):
                value = thread.get("id")
                if isinstance(value, str) and value.strip():
                    sessions.add(value.strip())
        item = event.get("item")
        if isinstance(item, dict):
            item_type = item.get("type")
            if item_type in _SESSION_EVENT_TYPES:
                for key in ("thread_id", "session_id"):
                    value = item.get(key)
                    if isinstance(value, str) and value.strip():
                        sessions.add(value.strip())
        inventory_payload = None
        if event_type in _TOOL_INVENTORY_EVENT_TYPES:
            inventory_payload = (
                event.get("tools")
                or event.get("tool_inventory")
                or event.get("available_tools")
                or event.get("mcp_tools")
            )
        elif event_type == "item.completed" and isinstance(item, dict):
            if item.get("type") in _TOOL_INVENTORY_EVENT_TYPES:
                inventory_payload = (
                    item.get("tools")
                    or item.get("tool_inventory")
                    or item.get("available_tools")
                    or item.get("mcp_tools")
                )
        inventory = _normalise_tool_inventory(inventory_payload)
        if inventory is not None:
            inventories.add(inventory)
    return {
        "sessions": tuple(sorted(sessions)),
        "inventories": tuple(sorted(inventories)),
    }


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
                timeout=15,
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


def _preflight_isolation(codex_command: Path, required: bool) -> dict[str, object]:
    if not required:
        return {"requested": False, "supported": True, "sentinel": "not_requested"}
    if _is_windows():
        raise RuntimeError(
            "requested strict host isolation is unsupported on Windows without UAC; "
            "use a POSIX host or run the documented non-strict Windows profile"
        )
    with tempfile.TemporaryDirectory(prefix="rob2-rsi-preflight-") as directory:
        root = Path(directory)
        allowed = root / "allowed workspace with spaces"
        allowed.mkdir()
        sentinel = root / "forbidden sentinel.txt"
        sentinel.write_text("ROB2_RSI_FORBIDDEN_READ", encoding="utf-8")
        codex_home = root / "codex-home"
        codex_home.mkdir()
        profile = [
            'approval_policy = "never"',
            'default_permissions = "rob2-rsi"',
            "",
            "[permissions.rob2-rsi.filesystem]",
            '":root" = "deny"',
            '":minimal" = "read"',
            '":tmpdir" = "write"',
            '":slash_tmp" = "write"',
            f'{json.dumps(allowed.as_posix())} = "write"',
            f'{json.dumps(sentinel.as_posix())} = "deny"',
            "",
            "[permissions.rob2-rsi.network]",
            "enabled = false",
        ]
        (codex_home / "config.toml").write_text("\n".join(profile) + "\n", encoding="utf-8")
        script = (
            "from pathlib import Path; "
            f"print(Path({json.dumps(str(sentinel))}).read_text(encoding='utf-8'))"
        )
        command = [
            str(codex_command),
            "sandbox",
            "-C",
            str(allowed),
            "-P",
            "rob2-rsi",
            "--",
            sys.executable,
            "-c",
            script,
        ]
        environment = os.environ.copy()
        environment["CODEX_HOME"] = str(codex_home)
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
            lowered = detail.casefold()
            if "not supported" in lowered or "unsupported" in lowered:
                raise RuntimeError(
                    "requested strict host isolation is unsupported; forbidden-file sentinel "
                    "was not run"
                ) from error
            if not any(
                marker in lowered
                for marker in (
                    "permission denied",
                    "access denied",
                    "operation not permitted",
                    "not allowed",
                    "outside the allowed",
                )
            ):
                raise RuntimeError(
                    "strict host isolation preflight failed without a verified denial: "
                    + (detail.strip() or "the sandbox command returned a non-zero status")
                ) from error
            return {
                "requested": True,
                "supported": True,
                "sentinel": "denied",
                "sentinel_command": command,
            }
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RuntimeError(
                "requested strict host isolation is unavailable; forbidden-file sentinel "
                f"was not verified: {error}"
            ) from error
        if "ROB2_RSI_FORBIDDEN_READ" in output:
            raise RuntimeError(
                "requested strict host isolation failed: forbidden-file sentinel was readable"
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


def _trace_tool_inventory(path: Path) -> tuple[str, ...] | None:
    inventories = _trace_metadata(path)["inventories"]
    if not isinstance(inventories, tuple):
        return None
    if len(inventories) > 1:
        raise ValueError(f"ambiguous tool inventories in {path}")
    return inventories[0] if inventories else None


def _validate_tool_inventory(
    run_dir: Path,
    phase: int,
    *,
    expected: tuple[str, ...] = EXPECTED_TOOL_INVENTORY,
) -> tuple[str, ...]:
    """Validate the current launch against the frozen runtime inventory.

    Codex does not emit an MCP inventory event in every JSONL trace.  The
    launch record is authoritative for the expected surface; when a trace does
    expose an inventory it is an additional consistency check, not a required
    continuation prerequisite.
    """

    trace = run_dir / f"phase-{phase}.jsonl"
    execution_path = run_dir / "execution.json"
    frozen: tuple[str, ...] | None = None
    frozen_version: str | None = None
    frozen_provenance: dict[str, object] | None = None
    if execution_path.is_file():
        try:
            execution = json.loads(execution_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("frozen launch runtime record is unreadable") from error
        runtime = execution.get("runtime_inputs") if isinstance(execution, dict) else None
        if isinstance(runtime, dict):
            frozen = _normalise_tool_inventory(runtime.get("expected_tool_inventory"))
            frozen_version = _optional_text(runtime.get("tool_inventory_version"))
            provenance = runtime.get("tool_inventory")
            if isinstance(provenance, dict):
                frozen_provenance = provenance
                frozen = _normalise_tool_inventory(provenance.get("names")) or frozen
                frozen_version = _optional_text(provenance.get("version")) or frozen_version
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
    observed = _trace_tool_inventory(trace)
    if observed is None and not trace_has_rob2_runtime_evidence(trace):
        raise ValueError(
            "continuation runtime availability is unverified; no rob2 MCP call was observed; "
            "recovery: start a fresh benchmark attempt and retain this run"
        )
    if observed is not None and set(observed) != set(frozen):
        observed_set = set(observed)
        frozen_set = set(frozen)
        missing = sorted(frozen_set - observed_set)
        unexpected = sorted(observed_set - frozen_set)
        detail = []
        if missing:
            detail.append("missing=" + ",".join(missing))
        if unexpected:
            detail.append("unexpected=" + ",".join(unexpected))
        raise ValueError(
            "continuation tool inventory is incompatible ("
            + "; ".join(detail)
            + "); recovery: start a fresh benchmark attempt"
        )
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
            process.communicate(input=prompt)
            return int(process.returncode)
        except BaseException:
            if process is not None and process.poll() is None:
                process.kill()
                process.wait()
            raise
        finally:
            _close_windows_job_guard(job)


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
    campaign = run_dir.parents[1].name if len(run_dir.parents) > 1 else run_dir.parent.name
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
) -> dict[str, object]:
    path = run_dir / "execution.json"
    now = datetime.now(UTC).isoformat()
    model = model or "gpt-5.6-luna"
    effort = effort or "medium"
    selection_policy = selection_policy or (
        "select the declared attempt before execution; retain every attempt; "
        "never select a best-scoring retry"
    )
    overrides = dict(overrides or {})
    runtime_inputs = dict(runtime_inputs or {})
    runtime_inputs_sha256 = _json_sha256(runtime_inputs) if runtime_inputs else None
    if phase > 1 and not path.exists():
        raise ValueError("continuation requires an existing execution.json")
    if path.exists():
        record = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(record, dict) or record.get("identity") != identity:
            raise ValueError("execution identity mismatch; refusing duplicate or moved launch")
        if record.get("state") == "succeeded":
            raise ValueError("execution already succeeded; refusing a duplicate launch")
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
            "attempt": 1,
            "retry": 0,
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
    retry = (retry_value if isinstance(retry_value, int) else 0) + (
        1 if prior_state == "failed_infrastructure" else 0
    )
    continuation = record.get("continuation")
    prior_lineage = (
        continuation.get("lineage", [])
        if isinstance(continuation, dict) and isinstance(continuation.get("lineage", []), list)
        else []
    )
    run_input_sha256 = hashlib.sha256(
        json.dumps(run_inputs, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    prompt_sha256 = _sha256_file(prompt_file)
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
            if (
                not isinstance(prior_runtime_inputs, dict)
                or not isinstance(prior_runtime_inputs_sha256, str)
                or prior_runtime_inputs != runtime_inputs
                or _json_sha256(prior_runtime_inputs) != prior_runtime_inputs_sha256
                or prior_runtime_inputs_sha256 != runtime_inputs_sha256
            ):
                raise ValueError("continuation runtime input mismatch")
    initial_prompt_sha256 = record.get("prompt_sha256", prompt_sha256)
    if not isinstance(initial_prompt_sha256, str):
        initial_prompt_sha256 = prompt_sha256
    phase_prompt_hashes = record.get("prompt_sha256_by_phase", {})
    if not isinstance(phase_prompt_hashes, dict):
        raise ValueError("execution prompt provenance is malformed")
    phase_prompt_hashes = {str(key): value for key, value in phase_prompt_hashes.items()}
    phase_prompt_hashes[str(phase)] = prompt_sha256
    record_update = {
        "state": "running",
        "retry": retry,
        "updated_at": now,
        "run_input_sha256": run_input_sha256,
        "prompt_sha256": initial_prompt_sha256,
        "prompt_sha256_by_phase": phase_prompt_hashes,
        "manifest_sha256": (
            manifest_sha256 if manifest_sha256 is not None else record.get("manifest_sha256")
        ),
        "model": model,
        "reasoning_effort": effort,
        "selected_attempt_rule": selection_policy,
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
    attempt_id = record.get("attempt_id")
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
    phases = record.setdefault("phases", [])
    if not isinstance(phases, list):
        raise ValueError("execution phases are malformed")
    phase_record: dict[str, object] = {
        "phase": phase,
        "session": session,
        "retry": retry,
        "prompt_sha256": prompt_sha256,
        "started_at": now,
    }
    if runtime_inputs_sha256 is not None:
        phase_record["runtime_inputs"] = runtime_inputs
        phase_record["runtime_inputs_sha256"] = runtime_inputs_sha256
    phases.append(phase_record)
    attempts = record.setdefault("attempts", [])
    if not isinstance(attempts, list):
        raise ValueError("execution attempts are malformed")
    attempt_record: dict[str, object] = {
        "attempt_id": attempt_id,
        "attempt": (record.get("attempt", 1) if isinstance(record.get("attempt", 1), int) else 1),
        "phase": phase,
        "retry": retry,
        "selected": phase == 1,
        "kind": "initial" if phase == 1 else "resumption",
        "overrides": overrides,
    }
    if runtime_inputs_sha256 is not None:
        attempt_record["runtime_inputs_sha256"] = runtime_inputs_sha256
    attempts.append(attempt_record)
    _atomic_json(path, record)
    return record


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
) -> None:
    path = run_dir / "execution.json"
    trace = run_dir / f"phase-{phase}.jsonl"
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
        phase_record.update(
            {
                "finished_at": datetime.now(UTC).isoformat(),
                "exit_code": exit_code,
                "trace_sha256": _sha256_file(trace) if trace.is_file() else None,
                "codex_session_id": _trace_session_id(trace),
                "tool_inventory": (
                    (
                        list(inventory)
                        if (inventory := _trace_tool_inventory(trace)) is not None
                        else None
                    )
                    if trace.is_file()
                    else None
                ),
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
    effective_terminal_state = (
        terminal_state
        if terminal_state is not None
        else "failed_infrastructure"
        if artifact_error is not None
        else None
    )
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
                else ("failed_infrastructure" if exit_code else "resumable")
            )
        )
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
            phase_record["artifact_sha256"] = (
                saved_artifact.get("sha256") if isinstance(saved_artifact, dict) else None
            )
    try:
        _atomic_json(path, record)
    finally:
        _release_execution_lock(run_dir)
    if artifact_error is not None:
        raise ValueError(artifact_error)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, help="Frozen JSON source/scope manifest (phase 1)")
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--phase", type=int, required=True)
    parser.add_argument("--session", help="Codex session ID for a continuation phase")
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
    args = parser.parse_args()
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
    model = _first_text(cli_model, manifest_model, default="gpt-5.6-luna")
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
    if args.phase == 1 and run_dir.exists():
        parser.error("run directory already exists")
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
        try:
            _validate_tool_inventory(run_dir, args.phase - 1)
        except (OSError, ValueError) as error:
            parser.error(str(error))

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
        "rob2": {"path": str(rob2_command), "version": _preflight_executable(rob2_command, "rob2")},
        "codex": {
            "path": str(codex_command),
            "version": _preflight_executable(codex_command, "Codex"),
        },
        "host": {"platform": sys.platform, "os_name": os.name},
        "isolation": _preflight_isolation(codex_command, args.require_isolated_host),
    }
    workspace = run_dir / "workspace"
    skill = workspace / ".agents" / "skills" / "rob2-assess"
    if args.phase == 1:
        if case_file is None:
            parser.error("phase 1 requires --case")
        run_inputs = prepare_workspace(case_file, workspace)
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

    run_inputs = json.loads((run_dir / "run-inputs.json").read_text(encoding="utf-8"))
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
            (run_dir / "approved-scope.json").write_text(
                json.dumps(approved_scope, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )

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
    }

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
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))

    codex_home = run_dir / "codex-home"
    codex_home.mkdir(exist_ok=True)
    if args.require_isolated_host:
        profile = [
            'approval_policy = "never"',
            'default_permissions = "rob2-rsi"',
            "",
            "[permissions.rob2-rsi.filesystem]",
            '":root" = "deny"',
            '":minimal" = "read"',
            '":tmpdir" = "write"',
            '":slash_tmp" = "write"',
        ]
        for path, access in (
            (workspace, "write"),
            (run_dir, "write"),
            (codex_home, "write"),
            (repository / ".venv", "read"),
        ):
            profile.append(f"{json.dumps(path.as_posix())} = {json.dumps(access)}")
        profile.extend(["", "[permissions.rob2-rsi.network]", "enabled = false"])
        (codex_home / "config.toml").write_text("\n".join(profile) + "\n", encoding="utf-8")
    scorer_path = repository / "scripts" / "analyze_rsi_runs.py"
    scorer_metadata: dict[str, object] = {
        "schema": "rob2-kit.rsi-run-analysis.v1",
        "path": str(scorer_path),
    }
    if scorer_path.is_file():
        scorer_metadata["sha256"] = hashlib.sha256(scorer_path.read_bytes()).hexdigest()
    else:
        scorer_metadata["available"] = False
    auth_copy = codex_home / "auth.json"
    config: list[str] = [
        "-c",
        "model_reasoning_effort=" + json.dumps(effort),
        "-c",
        "mcp_servers.rob2.command=" + json.dumps(str(rob2_command)),
        "-c",
        'mcp_servers.rob2.args=["mcp"]',
        "-c",
        "mcp_servers.rob2.env={ROB2_WORKSPACE=" + json.dumps(str(workspace)) + "}",
        "-c",
        "mcp_servers.rob2.startup_timeout_sec=120",
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
        *([] if args.require_isolated_host else ["--ignore-user-config"]),
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
        "prompt_sha256": hashlib.sha256(prompt_file.read_bytes()).hexdigest(),
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
        },
        "scorer": scorer_metadata,
        "runtime_inputs": runtime_inputs,
    }
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
    environment = os.environ.copy()
    environment["CODEX_HOME"] = str(codex_home)
    environment["ROB2_WORKSPACE"] = str(workspace)
    completed: subprocess.CompletedProcess[bytes] | None = None
    try:
        shutil.copyfile(auth_source, auth_copy)
        completed = subprocess.CompletedProcess(
            command,
            _run_owned_codex(
                command,
                cwd=workspace,
                prompt=prompt_file.read_bytes(),
                trace=trace,
                stderr=stderr,
                environment=environment,
            ),
        )
    except BaseException:
        _finish_execution(run_dir, execution, args.phase, 125)
        raise
    finally:
        auth_copy.unlink(missing_ok=True)
    if completed is None:
        raise RuntimeError("Codex phase did not start")
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
    _finish_execution(
        run_dir,
        execution,
        args.phase,
        completed.returncode,
        artifact=artifact,
        waiting_for_user=waiting_for_user,
    )
    metadata.update(
        {
            "finished_at": datetime.now(UTC).isoformat(),
            "exit_code": completed.returncode,
            "trace_sha256": _sha256_file(trace) if trace.is_file() else None,
            "trace_complete": trace.is_file(),
            "execution_state": execution.get("state"),
        }
    )
    _atomic_json(metadata_path, metadata)
    print(json.dumps({"exit_code": completed.returncode, "trace": str(trace)}))
    if completed.returncode:
        raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()

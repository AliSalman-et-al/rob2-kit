"""Project-local Codex and Claude Harness installation and diagnostics."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
import uuid
import zipfile
from pathlib import Path
from typing import Any

from rob2_kit.release import (
    CANONICAL_SKILL_NAMES,
    SKILL_ALLOWED_TOOL_NAMES,
    SKILL_REFERENCE_FILENAMES,
    SUPPORTED_HOSTS,
    ReleaseLock,
    load_release_lock,
    verify_host_adapters,
    verify_mcp_launchability,
)
from rob2_kit.storage import ArtifactStore, WorkflowLedger
from rob2_kit.storage.ledger import IntegrityError, LedgerError, LedgerSchemaRefusal

_MCP_SERVER_NAME = "rob2-kit"
_BOOTSTRAP_LOCK = "rob2.lock"
_OWNERSHIP_SCHEMA = 1
_OWNERSHIP_KIND = "rob2-kit-project"
_INSTALL_MUTEX = "install.lock"
_RUNTIME_RELATIVE = ".rob2/runtime"
_WHEEL_PIN = "release/wheel-pin.json"
_RUNTIME_WHEEL_PIN = "release/runtime-wheel-pin.json"
_REFERENCE_FILENAMES = SKILL_REFERENCE_FILENAMES
_HOST_SKILL_ROOTS = (("codex", ".codex/skills"), ("claude", ".claude/skills"))
_ROLLBACK_ROOT = ".rob2/release-rollbacks"
_PENDING_TRANSACTION = ".rob2/pending-release-transaction.json"
_OWNED_METADATA_PATHS = (
    "rob2.lock",
    ".rob2/rob2.lock",
    ".rob2/rollback.json",
    ".rob2/install-journal.json",
    ".rob2/runtime",
)


def preview_upgrade_project(project_root: Path) -> dict[str, Any]:
    """Describe a candidate release change without touching a project."""

    root = project_root.resolve()
    current = _load_ownership_manifest(root)
    release_root = _release_root()
    candidate = load_release_lock(release_root)
    candidate_paths = _candidate_owned_source_paths(release_root)
    owned = current["owned_paths"]
    current_paths = set(owned) | set(_owned_metadata_paths(current))
    additions = sorted(path for path in candidate_paths if path not in current_paths)
    removals = sorted(path for path in current_paths if path not in candidate_paths)
    replacements = sorted(
        path
        for path, source in candidate_paths.items()
        if path in owned and _content_hash(source) != owned[path]
    )
    state = _check_project_state(root)
    current_release = current["release"]
    return {
        "operation": "upgrade",
        "preview": True,
        "user_action": "Review this receipt, then run rob2 upgrade --apply PROJECT_ROOT.",
        "from": {
            "version": current_release.get("version"),
            "lock_hash": current_release.get("lock_hash"),
        },
        "to": {
            "version": candidate.package_version,
            "lock_hash": _content_hash(release_root / _BOOTSTRAP_LOCK),
        },
        "owned_additions": additions,
        "owned_replacements": replacements,
        "owned_removals": removals,
        "state_compatibility": state,
    }


def upgrade_project(project_root: Path, *, apply: bool = False) -> dict[str, Any]:
    """Install a verified candidate only after an explicit preview/apply action."""

    root = project_root.resolve()
    _recover_interrupted_upgrade(root)
    preview = preview_upgrade_project(root)
    if not apply:
        return preview
    if not preview["state_compatibility"]["ok"]:
        raise HarnessBootstrapError(
            "durable project state is incompatible with the candidate release. "
            "Follow state_compatibility.recovery before upgrading."
        )
    release_root = _release_root()
    lock = load_release_lock(release_root)
    current = _load_ownership_manifest(root)
    _validate_manifest_owned_files(root, current)
    mutex = _acquire_install_mutex(root)
    snapshot = _snapshot_managed_state(root)
    journal = root / ".rob2" / "install-journal.json"
    _write_journal(journal, "upgrade_started", (), ())
    backup: Path | None = None
    staged_runtime: Path | None = None
    try:
        backup = _write_rollback_backup(root, current)
        candidate_paths = _candidate_owned_source_paths(release_root)
        _write_pending_upgrade(root, current, backup, tuple(candidate_paths))
        staged_runtime = _stage_candidate_runtime(root, release_root)
        _verify_staged_candidate(root, release_root, staged_runtime)
        # The rollback receipt is durable before any live release bytes move.
        # A hard interruption can therefore always recover the prior generation.
        _write_rollback_record(root, current, backup)
        target_paths = set(candidate_paths) | set(_owned_metadata_paths(current))
        current_paths = set(current["owned_paths"]) | set(_owned_metadata_paths(current))
        _remove_owned_files(
            root,
            sorted(current_paths - target_paths),
        )
        _refresh_release_assets(root, release_root)
        if staged_runtime is not None:
            _commit_staged_runtime(root, staged_runtime, backup)
            staged_runtime = None
        _install_ownership_manifest(root, release_root, lock)
        _verify_candidate_install(root, release_root)
        _write_journal(journal, "upgrade_complete", _changed_paths(root, snapshot), ())
        _pending_transaction_path(root).unlink()
    except Exception as error:
        _restore_managed_state(root, snapshot)
        _clear_pending_upgrade(root, backup)
        if staged_runtime is not None and staged_runtime.exists():
            shutil.rmtree(staged_runtime)
        _write_journal(journal, "upgrade_rollback_succeeded", _changed_paths(root, snapshot), ())
        raise HarnessBootstrapError(
            f"upgrade failed before cutover: {error}. Prior project state was restored."
        ) from error
    finally:
        _release_install_mutex(mutex)
    return {
        **preview,
        "preview": False,
        "status": "upgraded",
        "rollback": str(backup.relative_to(root)),
    }


def rollback_project(project_root: Path, *, apply: bool = False) -> dict[str, Any]:
    """Restore the exact owned files recorded by the most recent upgrade."""

    root = project_root.resolve()
    _recover_interrupted_upgrade(root)
    record = _load_rollback_record(root)
    current = _load_ownership_manifest(root)
    current_paths = set(current["owned_paths"]) | set(_owned_metadata_paths(current))
    restore_paths = set(record["paths"])
    preview = {
        "operation": "rollback",
        "preview": True,
        "user_action": "Review this receipt, then run rob2 rollback --apply PROJECT_ROOT.",
        "from": current["release"],
        "to": record["release"],
        "owned_additions": sorted(restore_paths - current_paths),
        "owned_replacements": sorted(restore_paths & current_paths),
        "owned_removals": sorted(current_paths - restore_paths),
        "state_compatibility": _check_project_state(root),
    }
    if not apply:
        return preview
    if not preview["state_compatibility"]["ok"]:
        raise HarnessBootstrapError(
            "durable project state is incompatible with the rollback release. "
            "Follow state_compatibility.recovery before rolling back."
        )
    mutex = _acquire_install_mutex(root)
    recovery_backup = _begin_recoverable_lifecycle(root, current)
    try:
        _remove_owned_files(root, current["owned_paths"])
        rollback_backup = _project_relative_path(root, record["backup"])
        prior_runtime = rollback_backup / "runtime-tree"
        if prior_runtime.is_dir():
            runtime = root / _RUNTIME_RELATIVE
            if runtime.exists():
                shutil.move(str(runtime), str(rollback_backup / "failed-runtime"))
            shutil.move(str(prior_runtime), str(runtime))
        for relative in record["paths"]:
            source = rollback_backup / relative
            if source.is_file():
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
        _write_journal(root / ".rob2" / "install-journal.json", "rollback_complete", (), ())
        _clear_pending_upgrade(root, recovery_backup)
        _clear_rollback_record(root, rollback_backup)
    except Exception:
        _recover_interrupted_upgrade(root)
        _clear_pending_upgrade(root, recovery_backup)
        raise
    finally:
        _release_install_mutex(mutex)
    return {**preview, "preview": False, "status": "rolled_back"}


def preview_uninstall_project(project_root: Path) -> dict[str, Any]:
    """List exactly the manifest-owned files eligible for safe removal."""

    root = project_root.resolve()
    manifest = _load_ownership_manifest(root)
    return {
        "operation": "uninstall",
        "preview": True,
        "user_action": "Review this receipt, then run rob2 uninstall --apply PROJECT_ROOT.",
        "release": manifest["release"],
        "owned_removals": sorted((*manifest["owned_paths"], *_owned_metadata_paths(manifest))),
        "preserved": ["unlisted project files", "unrelated host configuration"],
        "state_compatibility": _check_project_state(root),
    }


def uninstall_project(project_root: Path, *, apply: bool = False) -> dict[str, Any]:
    """Remove only files proven by the ownership manifest to be generated."""

    preview = preview_uninstall_project(project_root)
    if not apply:
        return preview
    root = project_root.resolve()
    _recover_interrupted_upgrade(root)
    manifest = _load_ownership_manifest(root)
    _validate_manifest_owned_files(root, manifest)
    mutex = _acquire_install_mutex(root)
    backup = _begin_recoverable_lifecycle(root, manifest)
    try:
        _remove_owned_host_configuration(root, manifest)
        _remove_owned_files(root, [*manifest["owned_paths"], *_owned_metadata_paths(manifest)])
        _remove_owned_runtime(root)
        _clear_pending_upgrade(root, backup)
    except Exception:
        _recover_interrupted_upgrade(root)
        _clear_pending_upgrade(root, backup)
        raise
    finally:
        _release_install_mutex(mutex)
    return {**preview, "preview": False, "status": "uninstalled"}


class HarnessBootstrapError(ValueError):
    """A project-local Harness file would need unsafe replacement."""

    def __init__(self, detail: str) -> None:
        super().__init__(
            f"{detail} Recovery: preserve the existing configuration, remove or "
            f"reconcile its {_MCP_SERVER_NAME!r} entry, then rerun rob2 bootstrap."
        )


def bootstrap_project(project_root: Path) -> dict[str, Any]:
    """Install the locked adapters without changing unrelated host settings."""

    root = project_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    _recover_interrupted_upgrade(root)
    release_root = _release_root()
    lock = load_release_lock(release_root)
    verify_host_adapters(release_root)

    codex_path = root / ".codex" / "config.toml"
    claude_path = root / ".mcp.json"
    codex_config = _read_toml(codex_path)
    claude_config = _read_json_object(claude_path)
    expected_codex_server = _server_config(lock, release_root, "codex")
    expected_claude_server = _server_config(lock, release_root, "claude")
    codex_servers = codex_config.get("mcp_servers", {})
    if not isinstance(codex_servers, dict):
        raise HarnessBootstrapError(f"{codex_path} has a non-table mcp_servers value.")
    _validate_server_entry(codex_servers.get(_MCP_SERVER_NAME), expected_codex_server, codex_path)
    claude_servers = claude_config.get("mcpServers", {})
    if not isinstance(claude_servers, dict):
        raise HarnessBootstrapError(f"{claude_path} has a non-object mcpServers value.")
    _validate_server_entry(
        claude_servers.get(_MCP_SERVER_NAME), expected_claude_server, claude_path
    )
    _validate_adapter_targets(root, release_root)
    _validate_ownership_target(root, release_root, lock)

    mutex = _acquire_install_mutex(root)
    snapshot = _snapshot_managed_state(root)
    journal = root / ".rob2" / "install-journal.json"
    _write_journal(journal, "started", (), ())
    changed = False
    try:
        changed |= _install_runtime(root, release_root)
        changed |= _install_adapter_trees(root, release_root)
        changed |= _install_skills(root, release_root)
        changed |= _install_references(root, release_root)
        changed |= _install_bootstrap_lock(root, release_root)
        changed |= _install_codex_server(codex_path, codex_config, expected_codex_server)
        changed |= _install_claude_server(claude_path, claude_config, expected_claude_server)
        changed |= _install_ownership_manifest(root, release_root, lock)
        _write_journal(journal, "complete", _changed_paths(root, snapshot), ())
    except Exception as error:
        changed_paths = _changed_paths(root, snapshot)
        _restore_managed_state(root, snapshot)
        restored_paths = tuple(sorted(path.relative_to(root).as_posix() for path in snapshot))
        _write_journal(journal, "rollback_succeeded", changed_paths, restored_paths)
        if isinstance(error, HarnessBootstrapError):
            raise HarnessBootstrapError(
                f"{error} Prior project state was restored; no committed files changed."
            ) from error
        if isinstance(error, ValueError):
            raise HarnessBootstrapError(
                f"bootstrap failed: {error}. Prior project state was restored; "
                "no committed files changed."
            ) from error
        raise HarnessBootstrapError(
            f"bootstrap failed before commit: {error}. "
            "The prior project state was restored; rerun rob2 doctor before retrying."
        ) from error
    finally:
        _release_install_mutex(mutex)

    return {
        "status": "installed" if changed else "already_installed",
        "hosts": list(sorted(SUPPORTED_HOSTS)),
        "project_root": str(root),
        "launcher": _launcher_text(expected_codex_server),
        "runtime": _RUNTIME_RELATIVE if _runtime_assets(release_root) else None,
        "ownership_manifest": "rob2.lock",
        "recovery": "Run rob2 doctor to verify this locked project-local Harness install.",
    }


def doctor_project(project_root: Path) -> dict[str, Any]:
    """Return actionable, deterministic checks for the lean-v1 Harness journey."""

    root = project_root.resolve()
    release_root = _release_root()
    checks = {
        "execution_contract": _check_execution_contract(root, release_root),
        "canonical_skills": _check_canonical_skills(root, release_root),
        "host_adapters": _check_host_adapters(root, release_root),
        "mcp_launchability": _check_mcp_launchability(root),
        "project_state_schema": _check_project_state(root),
    }
    if _runtime_assets(release_root):
        checks["locked_runtime"] = _check_locked_runtime(root, release_root)
        checks["ownership"] = _check_ownership(root, release_root)
        checks["install_journal"] = _check_install_journal(root)
    return {"ok": all(check["ok"] for check in checks.values()), "checks": checks}


def _release_root() -> Path:
    package_root = Path(__file__).resolve().parents[1]
    if (package_root / _BOOTSTRAP_LOCK).is_file():
        return package_root
    return package_root.parents[1]


def _server_config(lock: ReleaseLock, release_root: Path, host: str = "codex") -> dict[str, Any]:
    runtime = _runtime_assets(release_root)
    if runtime is not None:
        project = _RUNTIME_RELATIVE
        if host == "claude":
            project = "${CLAUDE_PROJECT_DIR}/" + _RUNTIME_RELATIVE
        return {
            "command": "uv",
            "args": ["run", "--locked", "--project", project, "rob2-mcp"],
        }
    if _is_bundled_install(release_root):
        return {
            "command": sys.executable,
            "args": ["-m", "rob2_kit.interfaces.mcp.server"],
        }
    parts = lock.launcher.split()
    if not parts or parts[0] != "uvx":
        raise HarnessBootstrapError("The locked MCP launcher is not an isolated uvx command.")
    return {"command": parts[0], "args": parts[1:]}


def _is_bundled_install(release_root: Path) -> bool:
    return (release_root / "__init__.py").is_file()


def _runtime_assets(release_root: Path) -> Path | None:
    """Return packaged runtime assets, when running from a release wheel."""

    # The source checkout has a top-level ``release`` folder for build input,
    # but it is intentionally not treated as an installed runtime. A wheel's
    # package root always contains ``__init__.py`` alongside the bundled assets.
    if not (release_root / "__init__.py").is_file():
        return None
    runtime = release_root / "release" / "runtime"
    if not (release_root / "release").is_dir():
        return None
    if not (runtime / "pyproject.toml").is_file() or not (runtime / "uv.lock").is_file():
        raise HarnessBootstrapError("installed release runtime files are missing or malformed")
    return runtime


def _launcher_text(server: dict[str, Any]) -> str:
    return " ".join((str(server["command"]), *(str(arg) for arg in server["args"])))


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise HarnessBootstrapError(f"Cannot read {path}: {error}") from error
    if not isinstance(value, dict):
        raise HarnessBootstrapError(f"{path} must contain a TOML object.")
    return value


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise HarnessBootstrapError(f"Cannot read {path}: {error}") from error
    if not isinstance(value, dict):
        raise HarnessBootstrapError(f"{path} must contain a JSON object.")
    return value


def _validate_server_entry(entry: object, expected: dict[str, Any], path: Path) -> None:
    if entry is None:
        return
    if entry != expected:
        raise HarnessBootstrapError(
            f"{path} already defines a different {_MCP_SERVER_NAME!r} MCP server."
        )


def _validate_adapter_targets(root: Path, release_root: Path) -> None:
    for host in SUPPORTED_HOSTS:
        source = release_root / "adapters" / host
        destination = root / ".rob2" / "adapters" / host
        if destination.exists() and not _same_tree(source, destination):
            raise HarnessBootstrapError(f"{destination} differs from the locked {host} adapter.")
    for host, skill_root in _HOST_SKILL_ROOTS:
        for skill_name in CANONICAL_SKILL_NAMES:
            source = release_root / "skills" / skill_name
            destination = root / skill_root / skill_name
            if destination.exists() and not _same_tree(source, destination):
                raise HarnessBootstrapError(
                    f"{destination} differs from the canonical {host} skill adapter."
                )
    project_lock = root / ".rob2" / _BOOTSTRAP_LOCK
    release_lock = release_root / _BOOTSTRAP_LOCK
    if project_lock.exists() and project_lock.read_bytes() != release_lock.read_bytes():
        raise HarnessBootstrapError(
            f"{project_lock} differs from the installed execution contract."
        )
    for name in _REFERENCE_FILENAMES:
        source = release_root / "docs" / name
        destination = root / ".rob2" / "references" / name
        if destination.exists() and destination.read_bytes() != source.read_bytes():
            raise HarnessBootstrapError(
                f"{destination} differs from the bundled shared Harness reference."
            )
    for _host, skill_root in _HOST_SKILL_ROOTS:
        for name in _REFERENCE_FILENAMES:
            source = release_root / "docs" / name
            destination = root / skill_root / "references" / name
            if destination.exists() and destination.read_bytes() != source.read_bytes():
                raise HarnessBootstrapError(
                    f"{destination} differs from the bundled shared Harness reference."
                )
    runtime = _runtime_assets(release_root)
    if runtime is not None:
        destination = root / _RUNTIME_RELATIVE
        if destination.exists() and not _runtime_matches(runtime, destination):
            raise HarnessBootstrapError(
                f"{destination} differs from the locked project runtime."
            )


def _install_adapter_trees(root: Path, release_root: Path) -> bool:
    changed = False
    for host in SUPPORTED_HOSTS:
        source = release_root / "adapters" / host
        destination = root / ".rob2" / "adapters" / host
        if not destination.exists():
            shutil.copytree(source, destination)
            changed = True
    return changed


def _install_runtime(root: Path, release_root: Path) -> bool:
    """Materialize the release's runtime project and install its locked deps."""

    source = _runtime_assets(release_root)
    if source is None:
        # Source checkouts predate the embedded runtime. They retain the
        # interpreter-local launcher used by the compatibility tests.
        return False
    destination = root / _RUNTIME_RELATIVE
    if destination.exists():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)
    wheel = _wheel_artifact(release_root)
    if wheel is None:
        raise HarnessBootstrapError(
            "the exact rob2-kit wheel artifact is unavailable. "
            "Install this release from a wheel (not an editable checkout), then rerun bootstrap."
        )
    pin = _wheel_pin(release_root)
    release = load_release_lock(release_root)
    if pin["version"] != release.package_version:
        raise HarnessBootstrapError("wheel provenance version differs from rob2.lock")
    _validate_wheel(wheel, pin)
    shutil.copyfile(wheel, destination / wheel.name)
    uv = shutil.which("uv")
    if uv is None:
        raise HarnessBootstrapError(
            "uv is required to create the locked project runtime. "
            "Install uv using its official installer, then rerun rob2 bootstrap."
        )
    try:
        subprocess.run(
            [uv, "venv", str(destination / ".venv")],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        (destination / "runtime-install.json").write_text(
            json.dumps(
                {
                    "package": release.package,
                    "version": release.package_version,
                    "wheel_hash": _content_hash(wheel),
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        subprocess.run(
            [uv, "sync", "--locked", "--project", str(destination)],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise HarnessBootstrapError(
            f"the locked runtime could not be created: {error}. "
            "Verify network access and the exact wheel release, then rerun rob2 bootstrap."
        ) from error
    return True


def _wheel_artifact(release_root: Path) -> Path | None:
    """Resolve the exact wheel that supplied this installed distribution."""

    override = os.environ.get("ROB2_KIT_WHEEL")
    if override:
        candidate = Path(override).expanduser().resolve()
        return candidate if candidate.is_file() else None
    packaged = next(iter((release_root / "release" / "runtime").glob("*.whl")), None)
    if packaged is not None:
        return packaged
    packaged = next(
        iter((*release_root.glob("rob2-kit-*.whl"), *release_root.glob("rob2_kit-*.whl"))),
        None,
    )
    if packaged is not None:
        return packaged
    try:
        distribution = importlib.metadata.distribution("rob2-kit")
        direct_url = distribution.read_text("direct_url.json")
        if direct_url:
            payload = json.loads(direct_url)
            url = payload.get("url")
            if isinstance(url, str) and url.lower().endswith(".whl"):
                candidate = Path(url.removeprefix("file://")).resolve()
                if candidate.is_file():
                    return candidate
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return None


def _wheel_pin(release_root: Path) -> dict[str, str]:
    candidates = (
        release_root / _RUNTIME_WHEEL_PIN,
        release_root / _WHEEL_PIN,
        release_root.parent / "wheel-pin.json",
    )
    path = next((candidate for candidate in candidates if candidate.is_file()), candidates[0])
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise HarnessBootstrapError(
            "authoritative wheel provenance is missing or malformed"
        ) from error
    if not all(
        isinstance(raw.get(key), str) and raw[key]
        for key in ("filename", "version", "sha256")
    ):
        raise HarnessBootstrapError("authoritative wheel provenance is incomplete")
    return raw


def _validate_wheel(wheel: Path, pin: dict[str, str]) -> None:
    if wheel.name != pin["filename"]:
        raise HarnessBootstrapError("installed wheel filename does not match the release pin")
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    if digest != pin["sha256"]:
        raise HarnessBootstrapError("installed wheel hash does not match the release pin")
    try:
        with zipfile.ZipFile(wheel) as archive:
            metadata = next(
                archive.read(name).decode("utf-8")
                for name in archive.namelist()
                if name.endswith(".dist-info/METADATA")
            )
    except (OSError, KeyError, StopIteration, zipfile.BadZipFile) as error:
        raise HarnessBootstrapError("supplied wheel is not a valid distribution archive") from error
    fields = dict(
        line.split(": ", 1) for line in metadata.splitlines() if ": " in line
    )
    if fields.get("Name", "").casefold() != "rob2-kit" or fields.get("Version") != pin["version"]:
        raise HarnessBootstrapError(
            "wheel metadata does not match authoritative release provenance"
        )


def _write_journal(
    path: Path, status: str, changed: tuple[str, ...], restored: tuple[str, ...]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "status": status,
        "changed_paths": changed,
        "restored_paths": restored,
    }
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _changed_paths(root: Path, snapshot: dict[Path, bytes]) -> tuple[str, ...]:
    current = _snapshot_managed_state(root)
    paths = set(current) | set(snapshot)
    return tuple(
        sorted(
            path.relative_to(root).as_posix()
            for path in paths
            if current.get(path) != snapshot.get(path)
        )
    )


def _runtime_matches(source: Path, destination: Path) -> bool:
    return destination.is_dir() and all(
        (destination / name).is_file() for name in ("pyproject.toml", "uv.lock")
    ) and any(destination.glob("*.whl")) and not (destination / "src").exists()


def _acquire_install_mutex(root: Path) -> Path:
    mutex = root / ".rob2" / _INSTALL_MUTEX
    mutex.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(mutex, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write("rob2 bootstrap\n")
    except FileExistsError as error:
        raise HarnessBootstrapError(
            f"another rob2 installation is active ({mutex}). "
            "Wait for it to finish or remove the stale mutex after confirming "
            "no process is running."
        ) from error
    except OSError as error:
        raise HarnessBootstrapError(f"cannot create installation mutex {mutex}: {error}") from error
    return mutex


def _release_install_mutex(mutex: Path) -> None:
    try:
        mutex.unlink()
    except FileNotFoundError:
        pass


def _managed_roots(root: Path) -> tuple[Path, ...]:
    return (
        root / ".rob2" / "adapters",
        root / ".rob2" / "references",
        *(root / skill_root / "references" for _host, skill_root in _HOST_SKILL_ROOTS),
        root / ".rob2" / "runtime" / "src" / "rob2_kit",
        root / ".rob2" / "runtime",
        root / ".rob2" / "rob2.lock",
        root / ".rob2" / "install-journal.json",
        root / ".rob2" / "rollback.json",
        root / "rob2.lock",
        root / ".codex" / "config.toml",
        root / ".mcp.json",
        *(
            root / skill_root / skill_name
            for _host, skill_root in _HOST_SKILL_ROOTS
            for skill_name in CANONICAL_SKILL_NAMES
        ),
    )


def _snapshot_managed_state(root: Path) -> dict[Path, bytes]:
    snapshot: dict[Path, bytes] = {}
    for target in _managed_roots(root):
        if target.is_file():
            snapshot[target] = target.read_bytes()
        elif target.is_dir():
            for path in target.rglob("*"):
                if path.is_file():
                    snapshot[path] = path.read_bytes()
    return snapshot


def _restore_managed_state(root: Path, snapshot: dict[Path, bytes]) -> None:
    managed_files = {
        path
        for target in _managed_roots(root)
        if target.is_file()
        for path in (target,)
    }
    for target in _managed_roots(root):
        if target.is_dir():
            managed_files.update(path for path in target.rglob("*") if path.is_file())
    for path in managed_files - snapshot.keys():
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    for path, content in snapshot.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    # Remove empty directories created by a failed transaction, without ever
    # deleting a project or host directory that contains user data.
    directories = {
        directory
        for target in _managed_roots(root)
        if target.is_dir()
        for directory in (target, *target.rglob("*"))
        if directory.is_dir()
    }
    for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            pass


def _validate_ownership_target(root: Path, release_root: Path, lock: ReleaseLock) -> None:
    target = root / _BOOTSTRAP_LOCK
    if not target.exists():
        return
    try:
        manifest = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise HarnessBootstrapError(
            f"{target} is not a readable rob2 ownership manifest. "
            "Preserve it and move the project to a clean root before retrying."
        ) from error
    if not isinstance(manifest, dict) or manifest.get("kind") != _OWNERSHIP_KIND:
        raise HarnessBootstrapError(
            f"{target} is not owned by rob2-kit; refusing to overwrite user content. "
            "Choose another project root or reconcile the file manually."
        )
    if manifest.get("schema_version") != _OWNERSHIP_SCHEMA:
        raise HarnessBootstrapError(
            f"{target} uses unsupported ownership schema {manifest.get('schema_version')!r}. "
            "Back up project state and use a compatible rob2-kit release."
        )
    if manifest.get("package") != lock.package:
        raise HarnessBootstrapError(f"{target} belongs to a different package release.")
    release = manifest.get("release")
    if not isinstance(release, dict) or release.get("lock_hash") != _content_hash(
        release_root / _BOOTSTRAP_LOCK
    ):
        raise HarnessBootstrapError(
            f"{target} belongs to a different locked release. "
            "Preserve the project and use its matching rob2-kit release."
        )
    owned_paths = manifest.get("owned_paths")
    if not isinstance(owned_paths, dict):
        raise HarnessBootstrapError(f"{target} has no valid owned-path manifest.")
    for relative, expected_hash in owned_paths.items():
        if not isinstance(relative, str) or not isinstance(expected_hash, str):
            raise HarnessBootstrapError(f"{target} has an invalid owned-path manifest.")
        owned_path = root / relative
        if not owned_path.is_file() or _content_hash(owned_path) != expected_hash:
            raise HarnessBootstrapError(
                f"owned generated file differs: {relative}. "
                "Preserve the project state and reconcile it before rerunning bootstrap."
            )
    # A project lock is portable; it must not smuggle host paths or secrets.
    serialized = target.read_text(encoding="utf-8")
    if str(root) in serialized:
        raise HarnessBootstrapError(f"{target} contains an absolute project path and is unsafe.")


def _install_ownership_manifest(root: Path, release_root: Path, lock: ReleaseLock) -> bool:
    target = root / _BOOTSTRAP_LOCK
    existing = target.read_bytes() if target.exists() else None
    manifest = _ownership_manifest(root, release_root, lock)
    encoded = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if existing == encoded:
        return False
    target.write_bytes(encoded)
    return True


def _ownership_manifest(root: Path, release_root: Path, lock: ReleaseLock) -> dict[str, Any]:
    runtime = _runtime_assets(release_root)
    schema_hashes = {
        path.name: _content_hash(path)
        for path in sorted((release_root / "schemas").glob("*.json"))
        if path.is_file()
    }
    generated_paths: dict[str, str] = {}
    for target in (
        root / ".rob2" / "adapters",
        root / ".rob2" / "references",
        root / ".rob2" / "runtime" / "pyproject.toml",
        root / ".rob2" / "runtime" / "uv.lock",
        root / ".rob2" / "runtime" / "runtime-install.json",
        *root.glob(".rob2/runtime/*.whl"),
        root / ".rob2" / "runtime" / "src" / "rob2_kit",
        *(
            root / skill_root / skill_name
            for _host, skill_root in _HOST_SKILL_ROOTS
            for skill_name in CANONICAL_SKILL_NAMES
        ),
    ):
        if target.is_file():
            generated_paths[target.relative_to(root).as_posix()] = _content_hash(target)
        elif target.is_dir():
            for path in sorted(item for item in target.rglob("*") if item.is_file()):
                generated_paths[path.relative_to(root).as_posix()] = _content_hash(path)
    config_ownership = {
        "codex": {
            "path": ".codex/config.toml",
            "key": "mcp_servers.rob2-kit",
            "value_hash": _value_hash(
                _read_toml(root / ".codex" / "config.toml")
                .get("mcp_servers", {})
                .get(_MCP_SERVER_NAME)
            ),
            "section_hash": _codex_server_section_hash(root / ".codex" / "config.toml"),
        },
        "claude": {
            "path": ".mcp.json",
            "key": "mcpServers.rob2-kit",
            "value_hash": _value_hash(
                _read_json_object(root / ".mcp.json")
                .get("mcpServers", {})
                .get(_MCP_SERVER_NAME)
            ),
        },
    }
    return {
        "kind": _OWNERSHIP_KIND,
        "schema_version": _OWNERSHIP_SCHEMA,
        "package": lock.package,
        "release": {
            "version": lock.package_version,
            "status": lock.release_status,
            "lock_hash": _content_hash(release_root / _BOOTSTRAP_LOCK),
            "application_contract": lock.application_contract,
        },
        "identities": {
            "engine": {"package": lock.package, "version": lock.package_version},
            "schema": {"version": "1", "hashes": schema_hashes},
            "parser": {"name": "liteparse", "version": _distribution_version("liteparse")},
            "packs": {
                "logic": {"id": lock.logic_pack, "hash": lock.logic_pack_hash},
                "guidance": {"id": lock.guidance_pack, "hash": lock.guidance_pack_hash},
            },
            "skills": {
                name: {
                    "hash": pin.content_hash,
                    "activation_fixtures_hash": pin.activation_fixtures_hash,
                }
                for name, pin in lock.skills.items()
            },
            "adapters": {
                host: {"version": pin.version, "hash": pin.content_hash}
                for host, pin in lock.adapters.items()
            },
            "policies": {"release_status": lock.release_status},
        },
        "hosts": list(sorted(SUPPORTED_HOSTS)),
        "runtime": {
            "path": _RUNTIME_RELATIVE,
            "pyproject_hash": _content_hash(runtime / "pyproject.toml") if runtime else None,
            "lock_hash": _content_hash(runtime / "uv.lock") if runtime else None,
            "wheel_hash": next(
                (_content_hash(path) for path in (root / _RUNTIME_RELATIVE).glob("*.whl")),
                None,
            ),
        },
        "owned_paths": generated_paths,
        "owned_metadata_paths": list(_OWNED_METADATA_PATHS),
        "config_ownership": config_ownership,
        "transaction": {"operation": "bootstrap", "status": "complete"},
    }


def _load_ownership_manifest(root: Path) -> dict[str, Any]:
    """Load a portable ownership manifest before any lifecycle mutation."""

    target = root / _BOOTSTRAP_LOCK
    try:
        manifest = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise HarnessBootstrapError(f"cannot read ownership manifest {target}: {error}") from error
    if (
        not isinstance(manifest, dict)
        or manifest.get("kind") != _OWNERSHIP_KIND
        or manifest.get("schema_version") != _OWNERSHIP_SCHEMA
        or not isinstance(manifest.get("owned_paths"), dict)
        or not isinstance(manifest.get("owned_metadata_paths", list), list)
        or not isinstance(manifest.get("release"), dict)
    ):
        raise HarnessBootstrapError("ownership manifest is malformed or not owned by rob2-kit")
    return manifest


def _owned_metadata_paths(manifest: dict[str, Any]) -> tuple[str, ...]:
    """Return fixed generated receipts that cannot hash themselves."""

    paths = manifest.get("owned_metadata_paths", _OWNED_METADATA_PATHS)
    if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
        raise HarnessBootstrapError("ownership manifest has invalid metadata paths")
    if not set(paths) <= set(_OWNED_METADATA_PATHS):
        raise HarnessBootstrapError("ownership manifest has unexpected metadata paths")
    return tuple(dict.fromkeys((*paths, *_OWNED_METADATA_PATHS)))


def _validate_manifest_owned_files(root: Path, manifest: dict[str, Any]) -> None:
    """Refuse lifecycle changes when an allegedly owned file is ambiguous."""

    owned = manifest.get("owned_paths")
    if not isinstance(owned, dict):
        raise HarnessBootstrapError("ownership manifest has no owned_paths mapping")
    for relative, expected_hash in owned.items():
        if not isinstance(relative, str) or not isinstance(expected_hash, str):
            raise HarnessBootstrapError("ownership manifest contains an invalid owned path")
        path = _project_relative_path(root, relative)
        if not path.is_file() or _content_hash(path) != expected_hash:
            raise HarnessBootstrapError(
                f"owned generated file differs: {relative}; refusing to replace or remove it"
            )


def _candidate_owned_source_paths(release_root: Path) -> dict[str, Path]:
    """Map each installed generated file to its candidate source bytes."""

    paths: dict[str, Path] = {}
    for host in SUPPORTED_HOSTS:
        for path in (release_root / "adapters" / host).rglob("*"):
            if path.is_file():
                relative = path.relative_to(release_root / "adapters" / host)
                paths[(Path(".rob2") / "adapters" / host / relative).as_posix()] = path
    for name in _REFERENCE_FILENAMES:
        source = release_root / "docs" / name
        paths[(Path(".rob2") / "references" / name).as_posix()] = source
        for _host, skill_root in _HOST_SKILL_ROOTS:
            paths[(Path(skill_root) / "references" / name).as_posix()] = source
    for _host, skill_root in _HOST_SKILL_ROOTS:
        for skill_name in CANONICAL_SKILL_NAMES:
            source_root = release_root / "skills" / skill_name
            for path in source_root.rglob("*"):
                if path.is_file():
                    relative = path.relative_to(source_root)
                    paths[(Path(skill_root) / skill_name / relative).as_posix()] = path
    paths[(Path(".rob2") / _BOOTSTRAP_LOCK).as_posix()] = release_root / _BOOTSTRAP_LOCK
    return paths


def _refresh_release_assets(root: Path, release_root: Path) -> None:
    """Replace only generated assets; user configuration stays outside this step."""

    for relative, source in _candidate_owned_source_paths(release_root).items():
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)


def _verify_candidate_install(root: Path, release_root: Path) -> None:
    """Run deterministic candidate checks before a transaction is committed."""

    verify_host_adapters(release_root)
    if _runtime_assets(release_root) is not None:
        ownership = _check_ownership(root, release_root)
        if not ownership["ok"]:
            raise HarnessBootstrapError(f"candidate ownership check failed: {ownership['detail']}")
    state = _check_project_state(root)
    if not state["ok"]:
        raise HarnessBootstrapError(f"candidate durable-state check failed: {state['detail']}")


def _verify_staged_candidate(root: Path, release_root: Path, staged_runtime: Path | None) -> None:
    """Doctor every candidate component before the live generation is touched."""

    verify_host_adapters(release_root)
    for relative, source in _candidate_owned_source_paths(release_root).items():
        if not source.is_file() or not _content_hash(source):
            raise HarnessBootstrapError(f"candidate release asset is unavailable: {relative}")
    if staged_runtime is not None and not (staged_runtime / "runtime-install.json").is_file():
        raise HarnessBootstrapError("candidate runtime stage did not complete its doctor receipt")
    state = _check_project_state(root)
    if not state["ok"]:
        raise HarnessBootstrapError(f"candidate durable-state check failed: {state['detail']}")


def _stage_candidate_runtime(root: Path, release_root: Path) -> Path | None:
    """Build and doctor a candidate runtime without touching the live runtime."""

    source = _runtime_assets(release_root)
    if source is None:
        return None
    stage = root / ".rob2" / f"runtime-stage-{uuid.uuid4()}"
    try:
        shutil.copytree(source, stage)
        wheel = _wheel_artifact(release_root)
        if wheel is None:
            raise HarnessBootstrapError("candidate wheel artifact is unavailable")
        pin = _wheel_pin(release_root)
        _validate_wheel(wheel, pin)
        shutil.copyfile(wheel, stage / wheel.name)
        uv = shutil.which("uv")
        if uv is None:
            raise HarnessBootstrapError("uv is required to stage the candidate runtime")
        subprocess.run(
            [uv, "venv", str(stage / ".venv")],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        subprocess.run(
            [uv, "sync", "--locked", "--project", str(stage)],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        tools = verify_mcp_launchability(
            stage,
            uv,
            ("run", "--locked", "--project", str(stage), "rob2-mcp"),
        )
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        if stage.exists():
            shutil.rmtree(stage)
        raise HarnessBootstrapError(f"candidate runtime doctor failed: {error}") from error
    if tools != SKILL_ALLOWED_TOOL_NAMES:
        raise HarnessBootstrapError("candidate runtime doctor found a non-canonical tool catalog")
    (stage / "runtime-install.json").write_text(
        json.dumps(
            {
                "package": load_release_lock(release_root).package,
                "version": pin["version"],
                "wheel_hash": _content_hash(wheel),
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return stage


def _commit_staged_runtime(root: Path, stage: Path, backup: Path) -> None:
    """Switch a doctor-verified staged runtime while retaining the prior tree."""

    target = root / _RUNTIME_RELATIVE
    prior = backup / "runtime-tree"
    if prior.exists():
        shutil.rmtree(prior)
    if target.exists():
        shutil.move(str(target), str(prior))
    shutil.move(str(stage), str(target))


def _write_rollback_backup(root: Path, manifest: dict[str, Any]) -> Path:
    """Persist an exact owned-file rollback set, excluding unowned user data."""

    transaction_id = f"transaction:{uuid.uuid4()}"
    relative_backup = Path(_ROLLBACK_ROOT) / transaction_id.removeprefix("transaction:")
    backup = root / relative_backup
    for relative in _lifecycle_snapshot_paths(root, manifest):
        source = _project_relative_path(root, relative)
        destination = backup / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    runtime = root / _RUNTIME_RELATIVE
    if runtime.is_dir():
        shutil.copytree(runtime, backup / "runtime-tree")
    return backup


def _write_rollback_record(root: Path, manifest: dict[str, Any], backup: Path) -> None:
    paths = _rollback_record_paths(root, manifest)
    record = {
        "schema_version": 1,
        "backup": backup.relative_to(root).as_posix(),
        "release": manifest["release"],
        "paths": list(dict.fromkeys(paths)),
    }
    record_path = root / ".rob2" / "rollback.json"
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _pending_transaction_path(root: Path) -> Path:
    return root / _PENDING_TRANSACTION


def _write_pending_upgrade(
    root: Path,
    manifest: dict[str, Any],
    backup: Path,
    candidate_paths: tuple[str, ...],
) -> None:
    """Durably describe how to restore before changing release-owned bytes."""

    pending = {
        "schema_version": 1,
        "backup": backup.relative_to(root).as_posix(),
        "previous_paths": _lifecycle_snapshot_paths(root, manifest),
        "candidate_paths": sorted((*candidate_paths, *_owned_metadata_paths(manifest))),
    }
    path = _pending_transaction_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(pending, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _begin_recoverable_lifecycle(root: Path, manifest: dict[str, Any]) -> Path:
    """Create the same durable restore point used by every release mutation."""

    backup = _write_rollback_backup(root, manifest)
    _write_pending_upgrade(root, manifest, backup, tuple(manifest["owned_paths"]))
    return backup


def _recover_interrupted_upgrade(root: Path) -> None:
    """Deterministically restore a pre-cutover generation after interruption."""

    path = _pending_transaction_path(root)
    if not path.exists():
        return
    try:
        pending = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(pending, dict)
            or pending.get("schema_version") != 1
            or not isinstance(pending.get("backup"), str)
            or not isinstance(pending.get("previous_paths"), list)
            or not isinstance(pending.get("candidate_paths"), list)
        ):
            raise ValueError("pending transaction shape is invalid")
        backup = _project_relative_path(root, pending["backup"])
        rollback_root = _project_relative_path(root, _ROLLBACK_ROOT)
        if rollback_root not in backup.parents or not backup.is_dir():
            raise ValueError("pending transaction backup is not contained")
        paths = (*pending["previous_paths"], *pending["candidate_paths"])
        if not all(isinstance(relative, str) for relative in paths):
            raise ValueError("pending transaction paths are invalid")
        for relative in paths:
            _project_relative_path(root, relative)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise HarnessBootstrapError(
            "release transaction recovery data is corrupt; preserve .rob2 and restore "
            "from a verified backup before continuing"
        ) from error
    _remove_owned_files(root, list(pending["candidate_paths"]))
    prior_runtime = backup / "runtime-tree"
    if prior_runtime.is_dir():
        runtime = root / _RUNTIME_RELATIVE
        if runtime.exists():
            shutil.move(str(runtime), str(backup / "interrupted-runtime"))
        shutil.move(str(prior_runtime), str(runtime))
    for relative in pending["previous_paths"]:
        source = backup / relative
        if source.is_file():
            destination = _project_relative_path(root, relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
    path.unlink()
    _cleanup_runtime_stages(root)
    _write_journal(root / ".rob2" / "install-journal.json", "upgrade_rollback_succeeded", (), ())


def _clear_pending_upgrade(root: Path, backup: Path | None) -> None:
    pending = _pending_transaction_path(root)
    try:
        pending.unlink()
    except FileNotFoundError:
        pass
    if backup is not None and backup.is_dir():
        # The transaction has not become a rollback point, so its private
        # backup contains no user-owned target and can be discarded safely.
        shutil.rmtree(backup)


def _clear_rollback_record(root: Path, backup: Path | None = None) -> None:
    """Discard a consumed rollback point without leaving a dangling receipt."""

    record = root / ".rob2" / "rollback.json"
    try:
        record.unlink()
    except FileNotFoundError:
        pass
    if backup is not None and backup.is_dir():
        shutil.rmtree(backup)


def _lifecycle_snapshot_paths(root: Path, manifest: dict[str, Any]) -> list[str]:
    """Return byte-for-byte restore inputs for an interrupted mutation."""

    candidates = [*manifest["owned_paths"], *_owned_metadata_paths(manifest)]
    candidates.extend((".codex/config.toml", ".mcp.json"))
    return sorted(
        relative
        for relative in dict.fromkeys(candidates)
        if _project_relative_path(root, relative).is_file()
    )


def _rollback_record_paths(root: Path, manifest: dict[str, Any]) -> list[str]:
    """Record only the previous release artifacts, not mutable host settings."""

    candidates = [*manifest["owned_paths"], *_owned_metadata_paths(manifest)]
    return sorted(
        relative
        for relative in dict.fromkeys(candidates)
        if _project_relative_path(root, relative).is_file()
    )


def _cleanup_runtime_stages(root: Path) -> None:
    """Remove only abandoned transaction staging directories."""

    runtime_parent = root / ".rob2"
    if not runtime_parent.is_dir():
        return
    for stage in runtime_parent.glob("runtime-stage-*"):
        if stage.is_dir():
            shutil.rmtree(stage)


def _load_rollback_record(root: Path) -> dict[str, Any]:
    try:
        record = json.loads((root / ".rob2" / "rollback.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise HarnessBootstrapError(
            "no complete release rollback transaction is recorded"
        ) from error
    if (
        not isinstance(record, dict)
        or record.get("schema_version") != 1
        or not isinstance(record.get("backup"), str)
        or not isinstance(record.get("paths"), list)
        or not isinstance(record.get("release"), dict)
    ):
        raise HarnessBootstrapError("release rollback transaction is malformed")
    backup = _project_relative_path(root, record["backup"])
    rollback_root = _project_relative_path(root, _ROLLBACK_ROOT)
    if rollback_root not in backup.parents or not backup.is_dir():
        raise HarnessBootstrapError(
            "release rollback transaction is outside the owned rollback root"
        )
    for relative in record["paths"]:
        if not isinstance(relative, str):
            raise HarnessBootstrapError("release rollback transaction has an invalid owned path")
        _project_relative_path(root, relative)
    return record


def _remove_owned_files(root: Path, owned: dict[str, Any] | list[str]) -> None:
    paths = owned.keys() if isinstance(owned, dict) else owned
    for relative in sorted(paths, reverse=True):
        if not isinstance(relative, str):
            raise HarnessBootstrapError("ownership manifest contains an invalid owned path")
        path = _project_relative_path(root, relative)
        if path.is_file():
            path.unlink()
    directories: set[Path] = set()
    for relative in paths:
        if not isinstance(relative, str):
            continue
        directory = _project_relative_path(root, relative).parent
        while directory != root:
            directories.add(directory)
            directory = directory.parent
    for directory in sorted(directories, key=lambda path: len(path.parts), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            pass


def _remove_owned_runtime(root: Path) -> None:
    """Remove the explicitly owned runtime tree, including its mutable virtualenv."""

    runtime = root / _RUNTIME_RELATIVE
    if runtime.is_dir():
        shutil.rmtree(runtime)


def _remove_owned_host_configuration(root: Path, manifest: dict[str, Any]) -> None:
    """Remove only host entries whose exact values remain manifest-owned."""

    ownership = manifest.get("config_ownership")
    if not isinstance(ownership, dict):
        raise HarnessBootstrapError("ownership manifest has no host configuration receipts")
    codex_path = root / ".codex" / "config.toml"
    codex = _read_toml(codex_path)
    codex_value = codex.get("mcp_servers", {}).get(_MCP_SERVER_NAME)
    expected_codex_hash = ownership.get("codex", {}).get("value_hash")
    if _value_hash(codex_value) != expected_codex_hash:
        raise HarnessBootstrapError("Codex MCP entry differs from its ownership receipt")
    if codex_value is not None:
        text = _read_utf8_bytes(codex_path)
        if ownership.get("codex", {}).get("section_hash") != _codex_server_section_hash(
            codex_path
        ):
            raise HarnessBootstrapError("Codex MCP section differs from its ownership receipt")
        section = (
            rf"(?ms)^[ \t]*\[mcp_servers\.{re.escape(_MCP_SERVER_NAME)}\][ \t]*\r?$"
            rf".*?(?=^[ \t]*\[|\Z)"
        )
        rendered, removed = re.subn(section, "", text)
        if removed != 1:
            raise HarnessBootstrapError(
                "Codex MCP entry cannot be removed without touching user content"
            )
        codex_path.write_bytes(rendered.encode("utf-8"))

    claude_path = root / ".mcp.json"
    claude = _read_json_object(claude_path)
    claude_value = claude.get("mcpServers", {}).get(_MCP_SERVER_NAME)
    expected_claude_hash = ownership.get("claude", {}).get("value_hash")
    if _value_hash(claude_value) != expected_claude_hash:
        raise HarnessBootstrapError("Claude MCP entry differs from its ownership receipt")
    if claude_value is not None:
        servers = claude.get("mcpServers")
        if not isinstance(servers, dict):
            raise HarnessBootstrapError("Claude MCP configuration is malformed")
        del servers[_MCP_SERVER_NAME]
        claude_path.write_text(
            json.dumps(claude, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )


def _project_relative_path(root: Path, relative: str) -> Path:
    """Resolve a manifest path while refusing absolute or escaping input."""

    candidate = Path(relative)
    if candidate.is_absolute():
        raise HarnessBootstrapError("ownership manifest contains an absolute path")
    resolved_root = root.resolve()
    resolved = (root / candidate).resolve()
    if resolved == resolved_root or resolved_root not in resolved.parents:
        raise HarnessBootstrapError("ownership manifest attempts to escape the project root")
    return resolved


def _codex_server_section_hash(path: Path) -> str | None:
    """Hash the exact generated TOML section so comments remain user-owned."""

    if not path.exists():
        return None
    text = _read_utf8_bytes(path)
    section = re.search(
        (
            rf"(?ms)^[ \t]*\[mcp_servers\.{re.escape(_MCP_SERVER_NAME)}\][ \t]*\r?$"
            rf".*?(?=^[ \t]*\[|\Z)"
        ),
        text,
    )
    if section is None:
        return None
    return "sha256:" + hashlib.sha256(section.group(0).encode("utf-8")).hexdigest()


def _read_utf8_bytes(path: Path) -> str:
    """Decode configuration text without normalizing user-owned line endings."""

    return path.read_bytes().decode("utf-8")


def _content_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _distribution_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "unavailable"


def _value_hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _install_skills(root: Path, release_root: Path) -> bool:
    changed = False
    for _host, skill_root in _HOST_SKILL_ROOTS:
        for skill_name in CANONICAL_SKILL_NAMES:
            source = release_root / "skills" / skill_name
            destination = root / skill_root / skill_name
            if not destination.exists():
                shutil.copytree(source, destination)
                changed = True
    return changed


def _install_bootstrap_lock(root: Path, release_root: Path) -> bool:
    destination = root / ".rob2" / _BOOTSTRAP_LOCK
    if destination.exists():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(release_root / _BOOTSTRAP_LOCK, destination)
    return True


def _install_references(root: Path, release_root: Path) -> bool:
    changed = False
    reference_root = root / ".rob2" / "references"
    reference_root.mkdir(parents=True, exist_ok=True)
    for name in _REFERENCE_FILENAMES:
        destination = reference_root / name
        if not destination.exists():
            shutil.copyfile(release_root / "docs" / name, destination)
            changed = True
    for _host, skill_root in _HOST_SKILL_ROOTS:
        host_references = root / skill_root / "references"
        host_references.mkdir(parents=True, exist_ok=True)
        for name in _REFERENCE_FILENAMES:
            destination = host_references / name
            if not destination.exists():
                shutil.copyfile(release_root / "docs" / name, destination)
                changed = True
    return changed


def _install_codex_server(path: Path, config: dict[str, Any], expected: dict[str, Any]) -> bool:
    servers = config.get("mcp_servers")
    if servers is not None and not isinstance(servers, dict):
        raise HarnessBootstrapError(f"{path} has a non-table mcp_servers value.")
    if isinstance(servers, dict) and _MCP_SERVER_NAME in servers:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    prefix = _read_utf8_bytes(path) if path.exists() else ""
    if re.search(r"(?m)^\s*mcp_servers\s*=", prefix):
        raise HarnessBootstrapError(
            f"{path} defines mcp_servers as an inline value that cannot be extended safely."
        )
    separator = "" if not prefix or prefix.endswith(("\n", "\r")) else "\n"
    args = ", ".join(json.dumps(value) for value in expected["args"])
    path.write_bytes(
        (
            f"{prefix}{separator}[mcp_servers.{_MCP_SERVER_NAME}]\n"
            f"command = {json.dumps(expected['command'])}\nargs = [{args}]\n"
        ).encode()
    )
    return True


def _install_claude_server(path: Path, config: dict[str, Any], expected: dict[str, Any]) -> bool:
    servers = config.get("mcpServers")
    if servers is None:
        servers = {}
        config["mcpServers"] = servers
    if not isinstance(servers, dict):
        raise HarnessBootstrapError(f"{path} has a non-object mcpServers value.")
    if _MCP_SERVER_NAME in servers:
        return False
    servers[_MCP_SERVER_NAME] = expected
    path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return True


def _check_execution_contract(root: Path, release_root: Path) -> dict[str, Any]:
    try:
        verify_host_adapters(release_root)
        lock = load_release_lock(release_root)
        project_lock = root / ".rob2" / _BOOTSTRAP_LOCK
        if project_lock.read_bytes() != (release_root / _BOOTSTRAP_LOCK).read_bytes():
            raise ValueError(
                "project-local execution contract differs from the installed rob2.lock"
            )
    except (OSError, ValueError) as error:
        return _failed(
            str(error),
            "Run rob2 bootstrap to install the exact locked execution contract.",
        )
    return {
        "ok": True,
        "lock": lock.model_dump(mode="json"),
        "effective_launcher": _server_config(lock, release_root),
        "launcher_note": (
            "lock.launcher declares the published registry release; "
            "effective_launcher is the installed adapter that doctor probes"
        ),
        "recovery": (),
    }


def _check_canonical_skills(root: Path, release_root: Path) -> dict[str, Any]:
    try:
        for host, skill_root in _HOST_SKILL_ROOTS:
            for skill_name in CANONICAL_SKILL_NAMES:
                if not _same_tree(
                    release_root / "skills" / skill_name,
                    root / skill_root / skill_name,
                ):
                    raise ValueError(f"{host} {skill_name} differs from the canonical skill")
    except (LedgerError, ValueError) as error:
        return _failed(
            str(error),
            "Run rob2 bootstrap after preserving any intentional local edits.",
        )
    return {"ok": True, "skills": list(CANONICAL_SKILL_NAMES), "recovery": ()}


def _check_host_adapters(root: Path, release_root: Path) -> dict[str, Any]:
    try:
        for host in SUPPORTED_HOSTS:
            if not _same_tree(
                release_root / "adapters" / host,
                root / ".rob2" / "adapters" / host,
            ):
                raise ValueError(f"project-local {host} adapter differs from the locked adapter")
        expected_server = _server_config(load_release_lock(release_root), release_root)
        expected_claude_server = _server_config(
            load_release_lock(release_root), release_root, "claude"
        )
        codex_config = _read_toml(root / ".codex" / "config.toml")
        codex_servers = codex_config.get("mcp_servers")
        if not isinstance(codex_servers, dict):
            raise ValueError("Codex config does not define an MCP server table")
        _require_server_entry(codex_servers.get(_MCP_SERVER_NAME), expected_server, "Codex config")
        claude_config = _read_json_object(root / ".mcp.json")
        claude_servers = claude_config.get("mcpServers")
        if not isinstance(claude_servers, dict):
            raise ValueError("Claude config does not define an MCP server object")
        _require_server_entry(
            claude_servers.get(_MCP_SERVER_NAME), expected_claude_server, "Claude config"
        )
    except ValueError as error:
        return _failed(str(error), "Run rob2 bootstrap to restore the generated adapter tree.")
    return {"ok": True, "hosts": list(sorted(SUPPORTED_HOSTS)), "recovery": ()}


def _require_server_entry(entry: object, expected: dict[str, Any], description: str) -> None:
    if entry != expected:
        raise ValueError(f"{description} does not match the locked {_MCP_SERVER_NAME} launcher")


def _check_mcp_launchability(project_root: Path) -> dict[str, Any]:
    launcher: dict[str, Any] | None = None
    try:
        release_root = _release_root()
        lock = load_release_lock(release_root)
        launcher = _server_config(lock, release_root, "codex")
        if launcher["command"] == "uvx" and shutil.which("uvx") is None:
            raise ValueError("uvx is not available on PATH")
        tools = verify_mcp_launchability(
            project_root,
            launcher["command"],
            tuple(launcher["args"]),
        )
    except (ImportError, OSError, TimeoutError, ValueError) as error:
        if launcher is not None and launcher["command"] != "uvx":
            recovery = (
                "Reinstall rob2-kit in the Python environment used for bootstrap, "
                "then rerun rob2 doctor."
            )
        else:
            recovery = "Install the exact locked release with uvx, then rerun rob2 doctor."
        return _failed(
            str(error),
            recovery,
        )
    return {"ok": True, "tools": list(tools), "recovery": ()}


def _check_locked_runtime(root: Path, release_root: Path) -> dict[str, Any]:
    source = _runtime_assets(release_root)
    destination = root / _RUNTIME_RELATIVE
    if source is None:
        return {"ok": True, "state": "compatibility_launcher", "recovery": ()}
    if not destination.is_dir():
        return _failed(
            f"locked runtime is missing: {destination}",
            "Run rob2 bootstrap to recreate the project-local runtime.",
        )
    try:
        for name in ("pyproject.toml", "uv.lock"):
            if _content_hash(destination / name) != _content_hash(source / name):
                raise ValueError(f"runtime {name} differs from the installed release")
        venv = destination / ".venv"
        if not venv.is_dir():
            raise ValueError("locked runtime environment is unavailable")
        wheels = tuple(destination.glob("*.whl"))
        if len(wheels) != 1:
            raise ValueError("exact released rob2-kit wheel is missing from the locked runtime")
        pin = _wheel_pin(release_root)
        _validate_wheel(wheels[0], pin)
        marker = json.loads((destination / "runtime-install.json").read_text(encoding="utf-8"))
        if marker != {
            "package": load_release_lock(release_root).package,
            "version": pin["version"],
            "wheel_hash": _content_hash(wheels[0]),
        }:
            raise ValueError("runtime installation marker differs from the exact released wheel")
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return _failed(
            str(error),
            "Run rob2 bootstrap from the exact wheel release, then rerun rob2 doctor.",
        )
    return {
        "ok": True,
        "state": "locked",
        "path": _RUNTIME_RELATIVE,
        "environment": "available",
        "wheel_hash": _content_hash(wheels[0]),
        "recoverability": "recreate from bundled runtime project and lock",
        "recovery": (),
    }


def _check_ownership(root: Path, release_root: Path) -> dict[str, Any]:
    target = root / _BOOTSTRAP_LOCK
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("ownership manifest is not an object")
        if raw.get("kind") != _OWNERSHIP_KIND or raw.get("schema_version") != _OWNERSHIP_SCHEMA:
            raise ValueError("ownership manifest schema is unsupported")
        lock = load_release_lock(release_root)
        if raw.get("release", {}).get("lock_hash") != _content_hash(
            release_root / _BOOTSTRAP_LOCK
        ):
            raise ValueError("ownership manifest release hash differs from the installed release")
        for relative, expected in raw.get("owned_paths", {}).items():
            path = root / relative
            if not path.is_file() or _content_hash(path) != expected:
                raise ValueError(f"owned generated file differs: {relative}")
        runtime_manifest = raw.get("runtime", {})
        if not isinstance(runtime_manifest, dict):
            raise ValueError("ownership runtime identity is malformed")
        runtime = _runtime_assets(release_root)
        if runtime is None or runtime_manifest.get("pyproject_hash") != _content_hash(
            runtime / "pyproject.toml"
        ) or runtime_manifest.get("lock_hash") != _content_hash(runtime / "uv.lock"):
            raise ValueError("ownership runtime lock identity differs from the installed release")
        wheel_paths = tuple((root / _RUNTIME_RELATIVE).glob("*.whl"))
        if len(wheel_paths) != 1 or runtime_manifest.get("wheel_hash") != _content_hash(
            wheel_paths[0]
        ):
            raise ValueError("runtime wheel hash is missing or differs from ownership manifest")
        marker = json.loads(
            (root / _RUNTIME_RELATIVE / "runtime-install.json").read_text(encoding="utf-8")
        )
        if marker.get("wheel_hash") != runtime_manifest.get("wheel_hash"):
            raise ValueError("runtime installation marker differs from the pinned wheel")
        if raw.get("package") != lock.package:
            raise ValueError("ownership manifest package differs from the installed release")
        identities = raw.get("identities", {})
        if not isinstance(identities, dict):
            raise ValueError("ownership identities are malformed")
        if identities.get("engine", {}).get("version") != lock.package_version:
            raise ValueError("ownership engine identity differs from the installed release")
        expected_schema_hashes = {
            path.name: _content_hash(path)
            for path in sorted((release_root / "schemas").glob("*.json"))
            if path.is_file()
        }
        schema = identities.get("schema", {})
        if schema.get("version") != "1" or schema.get("hashes") != expected_schema_hashes:
            raise ValueError("ownership schema identity differs from the installed release")
        parser = identities.get("parser", {})
        if parser.get("name") != "liteparse" or parser.get("version") != _distribution_version(
            "liteparse"
        ):
            raise ValueError("ownership parser identity differs from the installed release")
        packs = identities.get("packs", {})
        if packs.get("logic", {}).get("hash") != lock.logic_pack_hash or packs.get(
            "guidance", {}
        ).get("hash") != lock.guidance_pack_hash:
            raise ValueError("ownership pack identity differs from the installed release")
        for name, pin in lock.skills.items():
            if identities.get("skills", {}).get(name, {}).get("hash") != pin.content_hash:
                raise ValueError(f"ownership skill identity differs for {name}")
        for host, pin in lock.adapters.items():
            if identities.get("adapters", {}).get(host, {}).get("hash") != pin.content_hash:
                raise ValueError(f"ownership adapter identity differs for {host}")
        if identities.get("policies", {}).get("release_status") != lock.release_status:
            raise ValueError("ownership policy identity differs from the installed release")
        config_ownership = raw.get("config_ownership", {})
        codex_value = _read_toml(root / ".codex" / "config.toml").get("mcp_servers", {}).get(
            _MCP_SERVER_NAME
        )
        claude_value = _read_json_object(root / ".mcp.json").get("mcpServers", {}).get(
            _MCP_SERVER_NAME
        )
        if config_ownership.get("codex", {}).get("value_hash") != _value_hash(codex_value):
            raise ValueError("Codex configuration ownership hash differs")
        if config_ownership.get("claude", {}).get("value_hash") != _value_hash(claude_value):
            raise ValueError("Claude configuration ownership hash differs")
    except (AttributeError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        return _failed(
            str(error),
            "Preserve user files, then run rob2 bootstrap to regenerate owned assets.",
        )
    return {
        "ok": True,
        "schema_version": _OWNERSHIP_SCHEMA,
        "manifest": "rob2.lock",
        "owned_paths": len(raw.get("owned_paths", {})),
        "hosts": raw.get("hosts", []),
        "recovery": (),
    }


def _check_install_journal(root: Path) -> dict[str, Any]:
    path = root / ".rob2" / "install-journal.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("schema_version") != 1 or raw.get("status") not in {
            "complete",
            "rollback_succeeded",
            "upgrade_complete",
            "upgrade_rollback_succeeded",
            "rollback_complete",
            "uninstall_complete",
        }:
            raise ValueError("install journal is incomplete")
    except (AttributeError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        return _failed(str(error), "Run rob2 bootstrap to complete or recover the installation.")
    return {"ok": True, "status": raw["status"], "recovery": ()}


def _check_project_state(root: Path) -> dict[str, Any]:
    ledger_path = root / ".rob2" / "ledger.sqlite3"
    if not ledger_path.exists():
        return {
            "ok": True,
            "state": "not_initialized",
            "recovery": ("Use rob2-init to prepare and confirm a Run when ready.",),
        }
    try:
        receipt = WorkflowLedger(
            ledger_path,
            ArtifactStore(root / ".rob2" / "artifacts"),
        ).preflight()
    except LedgerSchemaRefusal as error:
        return {
            "ok": False,
            "state": "incompatible",
            "expected_schema_version": error.expected_version,
            "found_schema_version": error.found_version,
            "recovery": (
                "Preserve .rob2 before changing it.",
                "Use a release that explicitly migrates this schema or archive the state "
                "and start a new Run.",
            ),
        }
    except IntegrityError as error:
        return _failed(
            str(error),
            "Preserve .rob2 and repair the reported integrity failure before any "
            "release lifecycle action.",
        )
    except ValueError as error:
        return _failed(str(error), "Preserve .rob2, archive it, and start a new compatible Run.")
    return {
        "ok": receipt.ok,
        "state": "compatible",
        "schema_version": receipt.schema_version,
        "recovery": (),
    }


def _same_tree(left: Path, right: Path) -> bool:
    if not left.is_dir() or not right.is_dir():
        return False
    left_files = {path.relative_to(left): path for path in left.rglob("*") if path.is_file()}
    right_files = {path.relative_to(right): path for path in right.rglob("*") if path.is_file()}
    return left_files.keys() == right_files.keys() and all(
        path.read_bytes() == right_files[relative].read_bytes()
        for relative, path in left_files.items()
    )


def _failed(detail: str, recovery: str) -> dict[str, Any]:
    return {"ok": False, "detail": detail, "recovery": (recovery,)}

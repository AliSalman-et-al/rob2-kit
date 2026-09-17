"""Run one isolated Codex/rob2 diagnostic phase and retain its full JSONL trace."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from prepare_rsi_workspace import approved_scope_record, prepare_workspace


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


def _preflight_isolation(codex_command: Path, required: bool) -> dict[str, object]:
    if not required:
        return {"requested": False, "supported": True, "sentinel": "not_requested"}
    if os.name == "nt":
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
                    "forbidden",
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, help="Frozen JSON source/scope manifest (phase 1)")
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--phase", type=int, required=True)
    parser.add_argument("--session", help="Codex session ID for a continuation phase")
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--effort", default="medium")
    parser.add_argument(
        "--require-isolated-host",
        action="store_true",
        help="Use a deny-by-default filesystem profile for qualification runs",
    )
    args = parser.parse_args()
    if args.phase < 1 or (args.phase > 1) != bool(args.session):
        parser.error("phase 1 starts a session; later phases require --session")
    if args.require_isolated_host and os.name == "nt":
        parser.error(
            "requested strict host isolation is unsupported on Windows without UAC; "
            "use a POSIX host or run the documented non-strict Windows profile"
        )
    repository = Path(__file__).resolve().parents[1]
    run_dir = args.run_dir.resolve()
    prompt_file = args.prompt.resolve(strict=True)
    case_file = args.case.resolve(strict=True) if args.case is not None else None
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
        if (
            status_data.get("phase") == "proposal"
            and continuation.get("authority") == "researcher"
            and continuation.get("operation") == "researcher_review"
        ):
            parser.error(
                "Proposal Review is still pending; acknowledge it with rob2 review "
                "before resuming the Codex session"
            )
        approved_scope = approved_scope_record(workspace, run_inputs.get("approved_scope"))
        if approved_scope is not None:
            (run_dir / "approved-scope.json").write_text(
                json.dumps(approved_scope, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )

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
    config = [
        "-c",
        "model_reasoning_effort=" + json.dumps(args.effort),
        "-c",
        "mcp_servers.rob2.command=" + json.dumps(str(rob2_command)),
        "-c",
        'mcp_servers.rob2.args=["mcp"]',
        "-c",
        "mcp_servers.rob2.env={ROB2_WORKSPACE=" + json.dumps(str(workspace)) + "}",
    ]
    if args.session and not args.require_isolated_host:
        config += ["-c", 'approval_policy="never"', "-c", 'sandbox_mode="workspace-write"']
    command = [str(codex_command), "exec"]
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
        args.model,
        *config,
        "--disable",
        "remote_plugin",
        "--output-last-message",
        str(run_dir / f"phase-{args.phase}.last-message.txt"),
        "-",
    ]
    if not args.session:
        command[command.index("-") : command.index("-")] = (
            ["-C", str(workspace)]
            if args.require_isolated_host
            else ["--approve-for-me", "-C", str(workspace)]
        )
    trace = run_dir / f"phase-{args.phase}.jsonl"
    stderr = run_dir / f"phase-{args.phase}.stderr.txt"
    metadata = {
        "model": args.model,
        "effort": args.effort,
        "kit_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repository, text=True
        ).strip(),
        "build_sha256": build_digest.hexdigest(),
        "skill_sha256": skill_digest.hexdigest(),
        "trial": run_inputs["trial"],
        "phase": args.phase,
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
            "reasoning_effort": args.effort,
            "phase": "single host invocation",
            "declared": "Codex CLI budget for the selected reasoning effort",
        },
        "scorer": scorer_metadata,
    }
    (run_dir / f"phase-{args.phase}.meta.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    environment = os.environ.copy()
    environment["CODEX_HOME"] = str(codex_home)
    environment["ROB2_WORKSPACE"] = str(workspace)
    completed: subprocess.CompletedProcess[bytes] | None = None
    try:
        shutil.copyfile(auth_source, auth_copy)
        with trace.open("wb") as output, stderr.open("wb") as errors:
            completed = subprocess.run(
                command,
                cwd=workspace,
                input=prompt_file.read_bytes(),
                stdout=output,
                stderr=errors,
                env=environment,
                check=False,
            )
    finally:
        auth_copy.unlink(missing_ok=True)
    if completed is None:
        raise RuntimeError("Codex phase did not start")
    print(json.dumps({"exit_code": completed.returncode, "trace": str(trace)}))
    if completed.returncode:
        raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()

"""Run one Codex/rob2 diagnostic phase and retain its full JSONL trace."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

from prepare_rsi_workspace import approved_scope_record, prepare_workspace

IS_WINDOWS = os.name == "nt"


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
        help=(
            "Use a deny-by-default filesystem profile for qualification runs; "
            "rejected on Windows to avoid an elevated UAC sandbox"
        ),
    )
    args = parser.parse_args()
    if args.phase < 1 or (args.phase > 1) != bool(args.session):
        parser.error("phase 1 starts a session; later phases require --session")
    if args.require_isolated_host and IS_WINDOWS:
        parser.error(
            "--require-isolated-host is unavailable on Windows; refusing to start "
            "the elevated sandbox so evals never trigger UAC"
        )
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
    isolation_record = run_dir / "host-isolation.json"
    if args.phase > 1 and isolation_record.is_file():
        previous_isolation = json.loads(isolation_record.read_text(encoding="utf-8"))
        if bool(previous_isolation.get("required")) != args.require_isolated_host:
            parser.error(
                "host isolation must match phase 1; repeat --require-isolated-host "
                "for every continuation"
            )

    repository = Path(__file__).resolve().parents[1]
    workspace = run_dir / "workspace"
    skill = workspace / ".agents" / "skills" / "rob2-assess"
    if args.phase == 1:
        if case_file is None:
            parser.error("phase 1 requires --case")
        if run_dir.exists():
            parser.error("run directory already exists")
        run_inputs = prepare_workspace(case_file, workspace)
        isolation_record.write_text(
            json.dumps({"required": args.require_isolated_host}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (run_dir / "run-inputs.json").write_text(
            json.dumps(run_inputs, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        subprocess.run(
            [
                str(repository / ".venv" / "Scripts" / "rob2.exe"),
                "export-skill",
                "--output",
                str(skill),
            ],
            check=True,
        )
    elif not (workspace / "input").is_dir():
        parser.error("prepared workspace is missing")

    run_inputs = json.loads((run_dir / "run-inputs.json").read_text(encoding="utf-8"))

    rob2_command = repository / ".venv" / "Scripts" / "rob2.exe"
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
    ):
        build_digest.update(member.relative_to(repository).as_posix().encode("utf-8"))
        build_digest.update(member.read_bytes())
    auth_source = Path.home() / ".codex" / "auth.json"
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
    if not args.require_isolated_host:
        config += [
            "-c",
            'approval_policy="on-request"',
            "-c",
            'approvals_reviewer="auto_review"',
            "-c",
            'sandbox_mode="workspace-write"',
        ]
        if IS_WINDOWS:
            config += ["-c", 'windows.sandbox="unelevated"']
    command = ["codex.cmd", "exec"]
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
        command[command.index("-") : command.index("-")] = ["-C", str(workspace)]
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
            "policy": (
                "deny-by-default" if args.require_isolated_host else "workspace-write-unelevated"
            ),
        },
    }
    (run_dir / f"phase-{args.phase}.meta.json").write_text(json.dumps(metadata, indent=2))
    environment = os.environ.copy()
    environment["CODEX_HOME"] = str(codex_home)
    environment["ROB2_WORKSPACE"] = str(workspace)
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
    print(json.dumps({"exit_code": completed.returncode, "trace": str(trace)}))
    if completed.returncode:
        raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()

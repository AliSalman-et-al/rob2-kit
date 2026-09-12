"""Run one isolated Codex/rob2 diagnostic phase and retain its full JSONL trace."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="One trial dossier directory")
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--phase", type=int, required=True)
    parser.add_argument("--session", help="Codex session ID for a continuation phase")
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--effort", default="medium")
    args = parser.parse_args()
    if args.phase < 1 or (args.phase > 1) != bool(args.session):
        parser.error("phase 1 starts a session; later phases require --session")

    repository = Path(__file__).resolve().parents[1]
    workspace = args.run_dir / "workspace"
    trial_input = workspace / "input" / args.input.name
    skill = workspace / ".agents" / "skills" / "rob2-assess"
    if args.phase == 1:
        if args.run_dir.exists():
            parser.error("run directory already exists")
        trial_input.parent.mkdir(parents=True)
        shutil.copytree(args.input, trial_input)
        subprocess.run(
            [
                str(repository / ".venv" / "Scripts" / "rob2.exe"),
                "export-skill",
                "--output",
                str(skill),
            ],
            check=True,
        )
    elif not trial_input.exists():
        parser.error("prepared workspace is missing")

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

    codex_home = args.run_dir / "codex-home"
    codex_home.mkdir(exist_ok=True)
    skill_digest = hashlib.sha256()
    for member in sorted(path for path in skill.rglob("*") if path.is_file()):
        skill_digest.update(member.relative_to(skill).as_posix().encode("utf-8"))
        skill_digest.update(member.read_bytes())
    auth_source = Path.home() / ".codex" / "auth.json"
    auth_copy = codex_home / "auth.json"
    shutil.copyfile(auth_source, auth_copy)
    config = [
        "-c",
        "model_reasoning_effort=" + json.dumps(args.effort),
        "-c",
        "mcp_servers.rob2.command=" + json.dumps(str(rob2_command)),
        "-c",
        "mcp_servers.rob2.args=[\"mcp\"]",
        "-c",
        "mcp_servers.rob2.env={ROB2_WORKSPACE=" + json.dumps(str(workspace)) + "}",
    ]
    if args.session:
        config += ["-c", 'approval_policy="never"', "-c", 'sandbox_mode="workspace-write"']
    command = ["codex.cmd", "exec"]
    if args.session:
        command += ["resume", args.session]
    command += [
        "--ignore-user-config",
        "--skip-git-repo-check",
        "--json",
        "--model",
        args.model,
        *config,
        "--disable",
        "remote_plugin",
        "--output-last-message",
        str(args.run_dir / f"phase-{args.phase}.last-message.txt"),
        "-",
    ]
    if not args.session:
        command[command.index("-"):command.index("-")] = [
            "--approve-for-me",
            "-C",
            str(workspace),
        ]
    trace = args.run_dir / f"phase-{args.phase}.jsonl"
    stderr = args.run_dir / f"phase-{args.phase}.stderr.txt"
    metadata = {
        "model": args.model,
        "effort": args.effort,
        "kit_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repository, text=True
        ).strip(),
        "skill_sha256": skill_digest.hexdigest(),
        "trial": args.input.name,
        "phase": args.phase,
        "session": args.session,
        "prompt_file": str(args.prompt.resolve()),
        "command": command,
    }
    (args.run_dir / f"phase-{args.phase}.meta.json").write_text(json.dumps(metadata, indent=2))
    environment = os.environ.copy()
    environment["CODEX_HOME"] = str(codex_home)
    environment["ROB2_WORKSPACE"] = str(workspace)
    try:
        with trace.open("wb") as output, stderr.open("wb") as errors:
            completed = subprocess.run(
                command,
                cwd=workspace,
                input=args.prompt.read_bytes(),
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

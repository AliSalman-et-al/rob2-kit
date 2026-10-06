"""Offline profile preflight; never invokes Codex or paid inference."""

from __future__ import annotations

import argparse
import json
import tomllib
from pathlib import Path


def check(directory: Path, session: Path | None = None) -> dict[str, object]:
    proposal = json.loads((directory / "proposed-case.json").read_text())
    launcher = json.loads((directory / "launcher.json").read_text())
    config = tomllib.loads((directory / "config.toml").read_text())
    expected = ("gpt-6.1-sol", "low")
    for item in (proposal, launcher):
        if (item["model"], item["effort"]) != expected:
            raise ValueError("model/effort mismatch")
    if (config["model"], config["model_reasoning_effort"]) != expected:
        raise ValueError("config model/effort mismatch")
    argv = launcher["argv"]
    if argv[argv.index("-m") + 1] != expected[0]:
        raise ValueError("launcher model mismatch")
    if argv[argv.index("-c") + 1] != 'model_reasoning_effort="low"':
        raise ValueError("launcher effort mismatch")
    if launcher["launch_enabled"] is not False or proposal["paid_launch"] is not False:
        raise ValueError("proposal must remain disabled")
    profiles = []
    if session is not None:
        for line in session.read_text().splitlines():
            row = json.loads(line)
            if row.get("type") == "turn_context":
                payload = row["payload"]
                profile = (payload.get("model"), payload.get("effort"))
                if profile != expected:
                    raise ValueError("durable profile mismatch")
                profiles.append(profile)
        if not profiles:
            raise ValueError("no durable profile record")
    return {
        "model": expected[0],
        "effort": expected[1],
        "offline_preflight": "passed",
        "launch_enabled": False,
        "durable_profiles_checked": len(profiles),
        "scope": "Model pins only; no inference and no complete live MCP readiness claim.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--session", type=Path)
    args = parser.parse_args()
    print(json.dumps(check(args.directory, args.session), indent=2))

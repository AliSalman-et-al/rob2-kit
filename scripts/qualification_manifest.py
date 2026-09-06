#!/usr/bin/env python3
"""Close and validate privacy-safe external qualification evidence."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

SCHEMA = "rob2-kit.retained-evidence.v0.4"
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
FORBIDDEN = {
    "path",
    "paths",
    "source",
    "sources",
    "content",
    "prompt",
    "prompts",
    "credential",
    "credentials",
    "trace",
    "traces",
}
RUN = {
    "id",
    "role",
    "host",
    "model",
    "effort",
    "input_sha256",
    "bundle_identity",
    "bundle_sha256",
    "verifier",
    "dispositions",
    "outcome",
}
RESTART_PROOF = {
    "run_id",
    "before_proposal_review_identity",
    "after_proposal_review_identity",
    "before_batch_identity",
    "after_batch_identity",
    "before_source_set_identity",
    "after_source_set_identity",
    "passed",
}


def _private(value: Any, at: str = "$") -> list[str]:
    if isinstance(value, dict):
        return [f"{at}: private field {key!r}" for key in value if key.casefold() in FORBIDDEN] + [
            err for key, child in value.items() for err in _private(child, f"{at}.{key}")
        ]
    if isinstance(value, list):
        return [
            err for index, child in enumerate(value) for err in _private(child, f"{at}[{index}]")
        ]
    return (
        [f"{at}: paths are forbidden"]
        if isinstance(value, str) and ("/" in value or "\\" in value)
        else []
    )


def validate(manifest: object) -> list[str]:
    if not isinstance(manifest, dict):
        return ["manifest must be an object"]
    errors = _private(manifest)
    if set(manifest) != {
        "schema",
        "commit",
        "wheel_sha256",
        "inputs",
        "outcomes",
        "runs",
        "restart_proof",
        "ci",
        "verdict",
    }:
        return errors + ["manifest has an unclosed field set"]
    if (
        manifest["schema"] != SCHEMA
        or not isinstance(manifest["commit"], str)
        or not re.fullmatch(r"[0-9a-f]{40}", manifest["commit"])
    ):
        errors.append("schema or commit is invalid")
    if not isinstance(manifest["wheel_sha256"], str) or not SHA256.fullmatch(
        manifest["wheel_sha256"]
    ):
        errors.append("wheel hash is invalid")
    inputs = manifest["inputs"]
    if (
        not isinstance(inputs, list)
        or not inputs
        or any(
            not isinstance(item, dict)
            or set(item) != {"identity", "sha256"}
            or not isinstance(item["identity"], str)
            or not SHA256.fullmatch(item["sha256"])
            for item in inputs
        )
    ):
        errors.append("input identities are malformed")
        hashes = set()
    else:
        hashes = {item["sha256"] for item in inputs}
    outcomes = manifest["outcomes"]
    if (
        not isinstance(outcomes, list)
        or len(outcomes) != 3
        or len(set(outcomes)) != 3
        or not all(isinstance(item, str) and item for item in outcomes)
    ):
        errors.append("exactly three required outcome identities are required")
        outcomes = []
    runs = manifest["runs"]
    if not isinstance(runs, list):
        return errors + ["runs are required"]
    ids = []
    runs_by_id: dict[str, dict[str, Any]] = {}
    bundles = []
    haiku = canary = 0
    haiku_outcomes: set[str] = set()
    for run in runs:
        if not isinstance(run, dict) or set(run) != RUN:
            errors.append("run has an unclosed field set")
            continue
        ids.append(run.get("id"))
        bundles.append(run.get("bundle_identity"))
        if not isinstance(run["id"], str) or not run["id"]:
            errors.append("run id is invalid")
        elif run["id"] in runs_by_id:
            errors.append("run ids must be unique")
        else:
            runs_by_id[run["id"]] = run
        if any(
            not isinstance(run[key], str) or not SHA256.fullmatch(run[key])
            for key in ("input_sha256", "bundle_identity", "bundle_sha256")
        ):
            errors.append("run hashes are invalid")
        if run["input_sha256"] not in hashes:
            errors.append("run input is undeclared")
        if (
            run["verifier"] != "passed"
            or not isinstance(run["dispositions"], dict)
            or not run["dispositions"]
        ):
            errors.append("run verifier or output is invalid")
        if run["role"] == "claude_haiku":
            haiku += 1
            if run["host"] != "claude-code" or run["model"] != "haiku":
                errors.append("Claude run must be Claude Code Haiku")
            if not isinstance(run["outcome"], str):
                errors.append("Claude outcome is invalid")
            else:
                haiku_outcomes.add(run["outcome"])
        elif run["role"] == "restart_proof":
            errors.append("restart proof belongs in the top-level restart_proof object")
        elif run["role"] == "codex_canary":
            canary += 1
            if run["host"] != "codex":
                errors.append("Codex canary host is invalid")
        else:
            errors.append("run role is invalid")
    if len(ids) != len(set(ids)) or len(bundles) != len(set(bundles)):
        errors.append("run and bundle identities must be unique")
    if len(runs) != 4 or haiku != 3 or haiku_outcomes != set(outcomes) or canary != 1:
        errors.append("runs must contain exactly three Haiku finals and one Codex canary")
    restart_proof = manifest["restart_proof"]
    if not isinstance(restart_proof, dict) or set(restart_proof) != RESTART_PROOF:
        errors.append("restart_proof has an unclosed field set")
    else:
        identity_fields = (
            "before_proposal_review_identity",
            "after_proposal_review_identity",
            "before_batch_identity",
            "after_batch_identity",
            "before_source_set_identity",
            "after_source_set_identity",
        )
        if any(
            not isinstance(restart_proof[field], str) or not SHA256.fullmatch(restart_proof[field])
            for field in identity_fields
        ):
            errors.append("restart identities are malformed")
        if restart_proof["passed"] is not True:
            errors.append("restart proof must be passed")
        if not isinstance(restart_proof["run_id"], str) or not restart_proof["run_id"]:
            errors.append("restart run id is invalid")
        else:
            restart_run = runs_by_id.get(restart_proof["run_id"])
            if (
                restart_run is None
                or restart_run.get("role") != "claude_haiku"
                or restart_run.get("outcome") not in outcomes
            ):
                errors.append("restart proof must reference a declared final Haiku run")
        if any(
            restart_proof[before] != restart_proof[after]
            for before, after in (
                ("before_proposal_review_identity", "after_proposal_review_identity"),
                ("before_batch_identity", "after_batch_identity"),
                ("before_source_set_identity", "after_source_set_identity"),
            )
        ):
            errors.append("restart Proposal, Batch, and Source identities must be equal")
    ci = manifest["ci"]
    expected = {
        (os_name, python)
        for os_name in ("ubuntu-latest", "windows-latest", "macos-latest")
        for python in ("3.11", "3.12", "3.13")
    }
    if (
        not isinstance(ci, list)
        or {(x.get("os"), x.get("python")) for x in ci if isinstance(x, dict)} != expected
        or any(
            not isinstance(x, dict)
            or set(x) != {"os", "python", "passed"}
            or x["passed"] is not True
            for x in ci
        )
    ):
        errors.append("complete supported OS/Python CI evidence is required")
    if manifest["verdict"] not in {"all_green", "incomplete"}:
        errors.append("verdict is invalid")
    if manifest["verdict"] == "all_green" and errors:
        errors.append("all_green requires complete valid external evidence")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("generate")
    generate.add_argument("input", type=Path)
    generate.add_argument("output", type=Path)
    check = commands.add_parser("validate")
    check.add_argument("manifest", type=Path)
    args = parser.parse_args(argv)
    source = args.input if args.command == "generate" else args.manifest
    try:
        manifest = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(error, file=sys.stderr)
        return 2
    errors = validate(manifest)
    if errors:
        print("qualification rejected: " + "; ".join(errors), file=sys.stderr)
        return 1
    if args.command == "generate":
        args.output.write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8"
        )
        print("qualification manifest generated")
    else:
        print("qualification evidence validated; " + manifest["verdict"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

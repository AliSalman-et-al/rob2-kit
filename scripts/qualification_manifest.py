#!/usr/bin/env python3
"""Close and validate privacy-safe external qualification evidence."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from rob2_kit.evaluation.harness import (
    MANIFEST_SCHEMA,
)
from rob2_kit.evaluation.harness import (
    validate_manifest as _validate_evaluation_manifest,
)

SCHEMA = "rob2-kit.retained-evidence.v0.5"
LEGACY_SCHEMA = "rob2-kit.retained-evidence.v0.4"
EVALUATION_SCHEMA = MANIFEST_SCHEMA
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
QUALIFICATION = {
    "executable",
    "pack",
    "skill",
    "tools",
    "schemas",
    "protocol",
    "runtime",
    "host_checks",
}
HOST_CHECK = {"host", "attempt_id", "success", "repairable_error", "observable"}


def validate_evaluation_manifest(manifest: object) -> list[str]:
    """Validate the privacy-safe development/holdout join manifest.

    This is intentionally independent of retained release evidence: expert
    annotations and source text stay in restricted stores, while this manifest
    contains only immutable fingerprints and versioned run dimensions.
    """
    if not isinstance(manifest, dict):
        return ["evaluation manifest must be an object"]
    try:
        _validate_evaluation_manifest(manifest)
    except ValueError as error:
        return [str(error)]
    return []


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
    base_fields = {
        "schema",
        "commit",
        "wheel_sha256",
        "inputs",
        "outcomes",
        "runs",
        "restart_proof",
        "ci",
        "verdict",
    }
    if set(manifest) not in (base_fields, base_fields | {"qualification"}):
        return errors + ["manifest has an unclosed field set"]
    if (
        manifest["schema"] not in {LEGACY_SCHEMA, SCHEMA}
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
    qualification = manifest.get("qualification")
    if manifest["schema"] == SCHEMA and not isinstance(qualification, dict):
        errors.append("v0.5 qualification identity and host checks are required")
    if qualification is not None:
        if not isinstance(qualification, dict) or set(qualification) != QUALIFICATION:
            errors.append("qualification has an unclosed field set")
        else:
            if any(
                not isinstance(qualification[key], str) or not SHA256.fullmatch(qualification[key])
                for key in QUALIFICATION - {"host_checks"}
            ):
                errors.append("qualification identities are malformed")
            host_checks = qualification["host_checks"]
            if not isinstance(host_checks, list) or not host_checks:
                errors.append("qualification host checks are required")
            else:
                check_rows: dict[tuple[str, str], list[dict[str, Any]]] = {}
                for check in host_checks:
                    if not isinstance(check, dict) or set(check) != HOST_CHECK:
                        errors.append("qualification host check has an unclosed field set")
                        continue
                    key = (check.get("host"), check.get("attempt_id"))
                    check_rows.setdefault(key, []).append(check)
                    if (
                        not isinstance(check["host"], str)
                        or not check["host"]
                        or not isinstance(check["attempt_id"], str)
                        or not check["attempt_id"]
                        or type(check["success"]) is not bool
                        or type(check["repairable_error"]) is not bool
                        or type(check["observable"]) is not bool
                    ):
                        errors.append("qualification host check is malformed")
                declared_pairs = {
                    (run.get("host"), run.get("id")) for run in runs if isinstance(run, dict)
                }
                for pair in declared_pairs:
                    checks = check_rows.get(pair, [])
                    if not any(
                        row.get("success") is True and row.get("observable") is True
                        for row in checks
                    ):
                        errors.append("successful installed-host check is missing")
                    if not any(
                        row.get("repairable_error") is True and row.get("observable") is True
                        for row in checks
                    ):
                        errors.append("repairable installed-host check is missing")
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
    errors = (
        validate_evaluation_manifest(manifest)
        if isinstance(manifest, dict) and manifest.get("schema") == EVALUATION_SCHEMA
        else validate(manifest)
    )
    if errors:
        print("qualification rejected: " + "; ".join(errors), file=sys.stderr)
        return 1
    if args.command == "generate":
        args.output.write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8"
        )
        print("qualification manifest generated")
    else:
        print(
            "evaluation manifest validated"
            if manifest.get("schema") == EVALUATION_SCHEMA
            else "qualification evidence validated; " + manifest["verdict"]
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

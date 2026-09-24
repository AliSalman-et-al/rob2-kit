"""Prepare fresh, one-case-per-trial/outcome RSI inputs and minimal prompts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import uuid
from pathlib import Path
from typing import Any

from benchmark_contract import (
    ATTEMPT_POLICY,
    contradictory_result_scope_dimensions,
    missing_result_scope_dimensions,
)


def _relative_source(case_parent: Path, source_root: Path, relative_name: str) -> str:
    return Path(os.path.relpath(source_root / relative_name, case_parent)).as_posix()


def _load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    required = {
        "outcome",
        "trial",
        "primary_status",
        "role",
        "definition",
        "effect_size",
        "source_locator",
        "reference_label_available",
    }
    if not rows or set(rows[0]) not in (required, required | {"expected_result"}):
        raise ValueError(
            f"metadata must contain exactly {sorted(required)} or those fields plus expected_result"
        )
    invalid_label_flags = {
        row["reference_label_available"].lower()
        for row in rows
        if row["reference_label_available"].lower() not in {"yes", "no"}
    }
    if invalid_label_flags:
        raise ValueError(
            "reference_label_available must be 'yes' or 'no' for every case"
        )
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (
            "".join(character for character in row["outcome"].casefold() if character.isalnum()),
            "".join(character for character in row["trial"].casefold() if character.isalnum()),
        )
        if key in seen:
            raise ValueError(f"duplicate fresh benchmark case: {row['outcome']}/{row['trial']}")
        seen.add(key)
        raw_expected = row.get("expected_result", "")
        if raw_expected.strip():
            expected = json.loads(raw_expected)
            if not isinstance(expected, dict):
                raise ValueError(f"expected_result must be a JSON object for {row['trial']}")
            if expected.get("trial", expected.get("trial_id")) != row["trial"]:
                raise ValueError(f"expected_result trial must match metadata trial {row['trial']}")
            missing = missing_result_scope_dimensions(expected)
            if missing:
                raise ValueError(
                    f"expected_result for {row['trial']} does not freeze complete scope; missing "
                    + ", ".join(missing)
                )
            contradictory = contradictory_result_scope_dimensions(expected)
            if contradictory:
                raise ValueError(
                    f"expected_result for {row['trial']} has conflicting scope fields: "
                    + ", ".join(contradictory)
                )
    return rows


def _case_manifest(
    source_dir: Path,
    source_case: dict[str, Any],
    outcome: str,
    manifest_path: Path,
    campaign_id: str,
    expected_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    case_parent = manifest_path.parent
    sources = []
    for source in source_case["sources"]:
        sources.append(
            {
                "name": source["name"],
                "path": _relative_source(case_parent, source_dir, source["path"]),
                "role": source["role"],
            }
        )
    registry = source_case.get("registry_capture")
    if registry is not None:
        registry = dict(registry)
        registry["path"] = _relative_source(case_parent, source_dir, registry["path"])
        registry["sha256"] = hashlib.sha256(
            (source_dir / source_case["registry_capture"]["path"]).read_bytes()
        ).hexdigest()
    case = {
        "registry_capture": registry,
        "requested_outcome": outcome,
        "schema": source_case["schema"],
        "sources": sources,
        "trial": source_case["trial"],
        "campaign_id": campaign_id,
    }
    if expected_result is not None:
        case["expected_result"] = expected_result
    else:
        case["scope_unresolved"] = (
            "The supplied benchmark metadata did not freeze a complete trial-specific "
            "Result before model execution."
        )
    return case


def _load_source_case(path: Path, trial: str) -> dict[str, Any]:
    source_case = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(source_case, dict) or source_case.get("trial") != trial:
        raise ValueError(f"source qualification case trial must match metadata trial {trial}")
    return source_case


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float)
    args = parser.parse_args()
    if args.timeout_seconds is not None and (
        not math.isfinite(args.timeout_seconds) or args.timeout_seconds <= 0
    ):
        parser.error("--timeout-seconds must be a positive finite number")

    repo = Path(__file__).resolve().parents[1]
    metadata_path = args.metadata.resolve(strict=True)
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing fresh benchmark root: {output}")
    rows = _load_rows(metadata_path)
    campaign_id = uuid.uuid4().hex
    output.mkdir(parents=True)
    (output / "cases").mkdir()
    (output / "prompts").mkdir()
    (output / "runs").mkdir()
    (output / "continuation.txt").write_text("Continue.\n", encoding="utf-8")

    index: list[dict[str, Any]] = []
    for row in rows:
        outcome_slug = row["outcome"].lower().replace(" ", "-")
        source_dir = repo / "eval" / "reference" / "sources" / row["trial"]
        source_case_path = source_dir / "qualification-case.json"
        source_case = _load_source_case(source_case_path, row["trial"])
        case_path = output / "cases" / outcome_slug / f"{row['trial']}.json"
        prompt_path = output / "prompts" / outcome_slug / f"{row['trial']}.txt"
        run_dir = output / "runs" / outcome_slug / row["trial"]
        case_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        expected_result = None
        if "expected_result" in row and row["expected_result"].strip():
            expected_result = json.loads(row["expected_result"])
            if not isinstance(expected_result, dict):
                raise ValueError(f"expected_result must be a JSON object for {row['trial']}")
        case_path.write_text(
            json.dumps(
                _case_manifest(
                    source_dir,
                    source_case,
                    row["outcome"],
                    case_path,
                    campaign_id,
                    expected_result,
                ),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        definition = row["definition"].rstrip(". ")
        effect_size = row["effect_size"].rstrip(". ")
        prompt = (
            f"/rob2-assess Assess risk of bias for {row['outcome']} defined as "
            f"{definition}, {effect_size} in {row['trial']}."
        )
        prompt_path.write_text(prompt + "\n", encoding="utf-8")
        index_row: dict[str, Any] = {
            **row,
            "campaign_id": campaign_id,
            **(
                {
                    "scope_unresolved": (
                        "The supplied benchmark metadata did not freeze a complete "
                        "trial-specific Result before model execution."
                    )
                }
                if expected_result is None
                else {}
            ),
            "case": str(case_path),
            "prompt": str(prompt_path),
            "run_dir": str(run_dir),
        }
        index_row.pop("expected_result", None)
        if expected_result is not None:
            index_row["expected_result"] = expected_result
        index.append(index_row)

    index_payload: dict[str, Any] = {
        "schema": "rob2-kit.fresh-benchmark-index.v1",
        "campaign_id": campaign_id,
        "model": "gpt-6-luna",
        "reasoning_effort": "medium",
        "attempt_policy": ATTEMPT_POLICY,
        "metadata": str(metadata_path),
        "cases": index,
    }
    if args.timeout_seconds is not None:
        index_payload["timeout_seconds"] = args.timeout_seconds
    (output / "index.json").write_text(
        json.dumps(
            index_payload,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"output": str(output), "cases": len(index)}))


if __name__ == "__main__":
    main()

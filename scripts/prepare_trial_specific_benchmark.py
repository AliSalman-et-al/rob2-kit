"""Prepare fresh, one-case-per-trial/outcome RSI inputs and minimal prompts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
from typing import Any


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
    if not rows or set(rows[0]) != required:
        raise ValueError(f"metadata must contain exactly {sorted(required)}")
    if any(row["reference_label_available"].lower() != "yes" for row in rows):
        raise ValueError("fresh benchmark metadata must contain labelled cases only")
    return rows


def _case_manifest(
    source_dir: Path,
    source_case: dict[str, Any],
    outcome: str,
    manifest_path: Path,
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
    return {
        "registry_capture": registry,
        "requested_outcome": outcome,
        "schema": source_case["schema"],
        "sources": sources,
        "trial": source_case["trial"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    metadata_path = args.metadata.resolve(strict=True)
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing fresh benchmark root: {output}")
    rows = _load_rows(metadata_path)
    output.mkdir(parents=True)
    (output / "cases").mkdir()
    (output / "prompts").mkdir()
    (output / "runs").mkdir()
    (output / "continuation.txt").write_text("Continue.\n", encoding="utf-8")

    index: list[dict[str, str]] = []
    for row in rows:
        outcome_slug = row["outcome"].lower().replace(" ", "-")
        source_dir = repo / "eval" / "reference" / "sources" / row["trial"]
        source_case_path = source_dir / "qualification-case.json"
        source_case = json.loads(source_case_path.read_text(encoding="utf-8"))
        case_path = output / "cases" / outcome_slug / f"{row['trial']}.json"
        prompt_path = output / "prompts" / outcome_slug / f"{row['trial']}.txt"
        run_dir = output / "runs" / outcome_slug / row["trial"]
        case_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        case_path.write_text(
            json.dumps(
                _case_manifest(source_dir, source_case, row["outcome"], case_path),
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
        index.append(
            {
                **row,
                "case": str(case_path),
                "prompt": str(prompt_path),
                "run_dir": str(run_dir),
            }
        )

    (output / "index.json").write_text(
        json.dumps(
            {
                "schema": "rob2-kit.fresh-benchmark-index.v1",
                "model": "gpt-5.6-luna",
                "effort": "medium",
                "metadata": str(metadata_path),
                "cases": index,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"output": str(output), "cases": len(index)}))


if __name__ == "__main__":
    main()

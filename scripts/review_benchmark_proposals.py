"""Inspect or acknowledge fresh benchmark Proposal Reviews in bounded waves."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from score_trial_benchmark import _norm_identity, _result_dimensions, _result_mismatches


def _json_objects(data: bytes) -> list[dict[str, Any]]:
    text = data.decode("utf-8", errors="replace")
    decoder = json.JSONDecoder()
    values: list[dict[str, Any]] = []
    offset = 0
    while offset < len(text):
        index = text.find("{", offset)
        if index < 0:
            break
        try:
            value, consumed = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            offset = index + 1
            continue
        if isinstance(value, dict):
            values.append(value)
            offset = index + consumed
        else:
            offset = index + 1
    return values


def _first_json(data: bytes) -> dict[str, Any]:
    values = _json_objects(data)
    if values:
        return values[0]
    raise ValueError("rob2 review output did not contain a JSON object")


def _last_json(data: bytes) -> dict[str, Any]:
    values = _json_objects(data)
    if not values:
        raise ValueError("rob2 review output did not contain a JSON object")
    return values[-1]


def _rob2_executable(repo: Path) -> str:
    for relative in (Path(".venv/Scripts/rob2.exe"), Path(".venv/bin/rob2")):
        candidate = repo / relative
        if candidate.is_file():
            return str(candidate)
    executable = shutil.which("rob2")
    if executable:
        return executable
    raise FileNotFoundError("rob2 executable is unavailable in the repository environment or PATH")


def _scope_mismatches(review: dict[str, Any], item: dict[str, Any]) -> list[dict[str, Any]]:
    expected = item.get("expected_result")
    if not isinstance(expected, dict):
        return [{"field": "expected_result", "expected": "required", "observed": None}]
    results = review.get("candidate", {}).get("proposal", {}).get("results", [])
    if not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], dict):
        return [
            {
                "field": "results",
                "expected": "exactly one Result",
                "observed": len(results) if isinstance(results, list) else None,
            }
        ]
    trial = str(expected.get("trial", expected.get("trial_id", item["trial"])))
    result = results[0]
    observed = _result_dimensions(result, trial)
    mismatches = _result_mismatches(expected, observed, trial)
    if _norm_identity(str(result.get("trial_id", ""))) != _norm_identity(str(item["trial"])):
        mismatches.append(
            {
                "field": "trial_id",
                "expected": item["trial"],
                "observed": result.get("trial_id"),
            }
        )
    if _norm_identity(str(result.get("requested_outcome", ""))) != _norm_identity(
        str(item["outcome"])
    ):
        mismatches.append(
            {
                "field": "requested_outcome",
                "expected": item["outcome"],
                "observed": result.get("requested_outcome"),
            }
        )
    return mismatches


def _one(repo: Path, item: dict[str, Any], answer: str, output: Path) -> dict[str, Any]:
    workspace = Path(item["run_dir"]) / "workspace"
    command = [
        _rob2_executable(repo),
        "review",
        "--workspace",
        str(workspace),
    ]

    # A batch approval must be tied to the frozen Result scope. First fetch the
    # exact current Review without acknowledging it, then compare its sole Result.
    inspected = subprocess.run(
        command,
        cwd=repo,
        input=b"no\n",
        capture_output=True,
        check=False,
    )
    review = _first_json(inspected.stdout)
    mismatches = _scope_mismatches(review, item) if answer == "yes" else []
    completed = inspected
    approval_reference_matches = False
    if answer == "yes" and not mismatches:
        review_reference = review.get("identity")
        if not isinstance(review_reference, str) or not review_reference:
            mismatches = [
                {
                    "field": "review.identity",
                    "expected": "non-empty identity",
                    "observed": review_reference,
                }
            ]
        else:
            approval_command = [*command, "--review-reference", review_reference]
            completed = subprocess.run(
                approval_command,
                cwd=repo,
                input=b"yes\n",
                capture_output=True,
                check=False,
            )
            try:
                approval = _last_json(completed.stdout)
            except ValueError:
                approval = {}
            acknowledgment = approval.get("acknowledgment_record")
            approval_reference_matches = (
                isinstance(acknowledgment, dict)
                and acknowledgment.get("review_identity") == review_reference
            )
            if completed.returncode == 0 and not approval_reference_matches:
                completed = subprocess.CompletedProcess(
                    completed.args,
                    2,
                    completed.stdout,
                    b"approval receipt did not acknowledge the inspected Review identity",
                )
    review_path = output / item["outcome"].lower().replace(" ", "-") / f"{item['trial']}.json"
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text(
        json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    results = review.get("candidate", {}).get("proposal", {}).get("results", [])
    result = results[0] if isinstance(results, list) and results else {}
    reported = result.get("reported", {}) if isinstance(result, dict) else {}
    return {
        "outcome": item["outcome"],
        "trial": item["trial"],
        "answer": answer,
        "exit_code": completed.returncode,
        "scope_mismatches": mismatches,
        "approved": (
            answer == "yes"
            and not mismatches
            and completed.returncode == 0
            and approval_reference_matches
        ),
        "approval_reference_matches": approval_reference_matches,
        "review": str(review_path),
        "review_identity": review.get("identity"),
        "requested_outcome": result.get("requested_outcome"),
        "trial_id": result.get("trial_id"),
        "kind": result.get("kind"),
        "relation": result.get("relation"),
        "endpoint": (
            reported.get("endpoint", {}).get("name") if isinstance(reported, dict) else None
        ),
        "estimate": reported.get("estimate") if isinstance(reported, dict) else None,
        "precision": reported.get("precision") if isinstance(reported, dict) else None,
    }


def main() -> None:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--answer", choices=("no", "yes"), default="no")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    index_path = args.index.resolve(strict=True)
    index = json.loads(index_path.read_text(encoding="utf-8"))
    output = index_path.parent / "proposal-reviews"
    output.mkdir(exist_ok=True)
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(_one, repo, item, args.answer, output) for item in index["cases"]]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    results.sort(key=lambda row: (row["outcome"], row["trial"]))
    summary = output / f"summary-{args.answer}.json"
    summary.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    expected_codes = {0, 1} if args.answer == "no" else {0}
    failures = [row for row in results if row["exit_code"] not in expected_codes]
    if failures:
        raise SystemExit(f"{len(failures)} proposal review commands failed")


if __name__ == "__main__":
    main()

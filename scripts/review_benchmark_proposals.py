"""Inspect or acknowledge fresh benchmark Proposal Reviews in bounded waves."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


def _first_json(data: bytes) -> dict[str, Any]:
    text = data.decode("utf-8", errors="replace")
    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("rob2 review output did not contain a JSON object")


def _one(repo: Path, item: dict[str, Any], answer: str, output: Path) -> dict[str, Any]:
    workspace = Path(item["run_dir"]) / "workspace"
    command = [str(repo / ".venv" / "Scripts" / "rob2.exe"), "review", "--workspace", str(workspace)]
    completed = subprocess.run(
        command,
        cwd=repo,
        input=(answer + "\n").encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    review = _first_json(completed.stdout)
    review_path = output / item["outcome"].lower().replace(" ", "-") / f"{item['trial']}.json"
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    results = review.get("candidate", {}).get("proposal", {}).get("results", [])
    result = results[0] if isinstance(results, list) and results else {}
    reported = result.get("reported", {}) if isinstance(result, dict) else {}
    return {
        "outcome": item["outcome"],
        "trial": item["trial"],
        "answer": answer,
        "exit_code": completed.returncode,
        "review": str(review_path),
        "review_identity": review.get("identity"),
        "requested_outcome": result.get("requested_outcome"),
        "trial_id": result.get("trial_id"),
        "kind": result.get("kind"),
        "relation": result.get("relation"),
        "endpoint": reported.get("endpoint", {}).get("name") if isinstance(reported, dict) else None,
        "estimate": reported.get("estimate") if isinstance(reported, dict) else None,
        "precision": reported.get("precision") if isinstance(reported, dict) else None,
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
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

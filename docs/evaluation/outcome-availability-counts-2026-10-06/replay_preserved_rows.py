"""Compare preserved source rows against the pre-change reconciler without exposing state data."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from rob2_kit.application.missing_data import reconcile_missing_data
from rob2_kit.workflow_models import MissingDataRow

BASELINE = "77926d48047e6a632a36d5960c0240039069f2c8"
MODULE = "src/rob2_kit/application/missing_data.py"


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def replay(state_root: Path, expected_inventory: Path) -> dict:
    code = subprocess.check_output(["git", "show", f"{BASELINE}:{MODULE}"], text=True)
    namespace = {
        "__name__": "rob2_kit.application._baseline_missing_data",
        "__package__": "rob2_kit.application",
    }
    exec(compile(code, "baseline_missing_data.py", "exec"), namespace)
    paths = sorted(
        (state_root / "final-medium-verifier-cutover-20261006/cases").glob(
            "*/assessment-terminal-state.json"
        )
    )
    paths += sorted(
        (state_root / "evidence-weighting-paired-low-20261006").glob(
            "*/cases/*/attempt-02/assessment-terminal-state.json"
        )
    )
    expected = json.loads(expected_inventory.read_text())
    expected_paths = {item["path"]: item["state_sha256"] for item in expected["states"]}
    actual_paths = {
        str(path.relative_to(state_root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
    }
    if not expected_paths or actual_paths != expected_paths:
        raise ValueError("Preserved state inventory or bytes differ from the frozen receipt")
    states, count = [], 0
    for path in paths:
        state = json.loads(path.read_text())
        comparisons = []
        for record in state["domain_records"].values():
            for answer in record["answers"]:
                rows = (answer.get("missing_data") or {}).get("rows", [])
                if not rows:
                    continue
                inputs = [
                    dict(
                        row["scope"],
                        **{
                            k: v
                            for k, v in row.items()
                            if k in MissingDataRow.model_fields and v is not None
                        },
                    )
                    for row in rows
                ]
                baseline = namespace["reconcile_missing_data"](inputs)
                current = reconcile_missing_data(inputs)
                if baseline != current:
                    raise ValueError(f"Changed preserved rows: {path}")
                count += len(rows)
                comparisons.append(
                    {
                        "question_id": answer["question_id"],
                        "row_count": len(rows),
                        "baseline_output_sha256": digest(baseline),
                        "current_output_sha256": digest(current),
                    }
                )
        states.append(
            {
                "path": str(path.relative_to(state_root)),
                "state_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "comparisons": comparisons,
            }
        )
    if len(states) != expected["state_count"] or count != expected["row_count"]:
        raise ValueError("Preserved state or row counts differ from the frozen receipt")
    return {
        "expected_inventory_sha256": hashlib.sha256(expected_inventory.read_bytes()).hexdigest(),
        "baseline_commit": BASELINE,
        "baseline_module_sha256": hashlib.sha256(code.encode()).hexdigest(),
        "current_module_sha256": hashlib.sha256(Path(MODULE).read_bytes()).hexdigest(),
        "replay_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "comparison": (
            "Exact equality of whole reconciliation outputs: normalized source quantities, "
            "scope, semantics, evidence identities, missingness, fractions, bounds and conflicts."
        ),
        "state_count": len(states),
        "row_count": count,
        "states": states,
        "result": "PASS",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--expected-inventory",
        type=Path,
        default=Path(__file__).with_name("preserved-row-replay.json"),
    )
    args = parser.parse_args()
    receipt = replay(args.state_root, args.expected_inventory)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n")
    print(
        f"PASS: {receipt['row_count']} rows across {receipt['state_count']} preserved states; "
        "exact outputs equal"
    )

"""Merge only replacements authorized by the campaign's frozen attempt policy."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from benchmark_contract import (
    _case_key,
    _execution_build_transition_for_rows,
    validate_replacement_case,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--replacement", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    index_path = args.index.resolve(strict=True)
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"refusing to overwrite selected index directory: {output}")
    merged = json.loads(index_path.read_text(encoding="utf-8"))
    if not isinstance(merged, dict) or not isinstance(merged.get("cases"), list):
        raise SystemExit("original benchmark index is malformed")
    replacement_paths = [path.resolve(strict=True) for path in args.replacement]
    replacement_indexes: list[tuple[Path, dict[str, object]]] = []
    for path in replacement_paths:
        replacement = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(replacement, dict) or not isinstance(replacement.get("cases"), list):
            raise SystemExit(f"replacement benchmark index is malformed: {path}")
        replacement_indexes.append((path, replacement))

    replacements: dict[tuple[str, str], tuple[Path, dict[str, object], dict[str, object]]] = {}
    for replacement_path, replacement_index in replacement_indexes:
        replacement_rows = replacement_index["cases"]
        if not isinstance(replacement_rows, list):
            raise SystemExit(f"replacement benchmark index cases are malformed: {replacement_path}")
        for row in replacement_rows:
            key = _case_key(row)
            if key is None:
                raise SystemExit(f"replacement case identity is malformed: {replacement_path}")
            if key in replacements:
                raise SystemExit(f"multiple replacement attempts selected for case: {key}")
            original_row, replacement_row = validate_replacement_case(
                index_path,
                merged,
                replacement_path,
                replacement_index,
                key,
                require_success=False,
            )
            replacements[key] = (replacement_path, original_row, replacement_row)

    merged_rows: list[dict[str, object]] = []
    for row in merged["cases"]:
        key = _case_key(row)
        if key is None or not isinstance(row, dict):
            raise SystemExit("original benchmark case identity is malformed")
        replacement = replacements.get(key)
        if replacement is None:
            merged_rows.append(row)
            continue
        replacement_path, original_row, replacement_row = replacement
        selected_row = dict(replacement_row)
        build_transition = _execution_build_transition_for_rows(original_row, replacement_row)
        if build_transition is not None:
            selected_row["execution_build_transition"] = build_transition
        selected_row["attempt_history"] = [
            {
                "attempt": _index_attempt(merged, original_row),
                "index": str(index_path),
                "index_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
                "run_dir": original_row.get("run_dir"),
                "selected": False,
            },
            {
                "attempt": _index_attempt(
                    next(index for path, index in replacement_indexes if path == replacement_path),
                    replacement_row,
                ),
                "index": str(replacement_path),
                "index_sha256": hashlib.sha256(replacement_path.read_bytes()).hexdigest(),
                "run_dir": replacement_row.get("run_dir"),
                "selected": True,
            },
        ]
        merged_rows.append(selected_row)
    output.mkdir(parents=True)
    (output / "continuation.txt").write_text("Continue.\n", encoding="utf-8")
    result: dict[str, Any] = dict(merged)
    result["cases"] = merged_rows
    result["selected_attempts"] = [str(index_path), *(str(path) for path in replacement_paths)]
    (output / "index.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "cases": len(merged_rows)}))


def _index_attempt(index: dict[str, object], row: dict[str, object]) -> int:
    value = row.get("attempt", index.get("attempt", 1))
    if isinstance(value, str) and value.isdecimal():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("attempt history has a malformed attempt number")
    return value


if __name__ == "__main__":
    main()

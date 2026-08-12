"""Explicit local semantic golden comparison and acceptance."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .traces import NormalizedTrace


class GoldenAcceptanceRequired(RuntimeError):
    """Raised when a caller tries to rewrite a golden without explicit consent."""


def semantic_diff(expected: Any, actual: Any, *, _path: str = "$") -> tuple[str, ...]:
    """Return deterministic, human-readable semantic differences."""

    differences: list[str] = []
    if isinstance(expected, Mapping) and isinstance(actual, Mapping):
        for key in sorted(set(expected) | set(actual), key=str):
            path = f"{_path}.{key}"
            if key not in expected:
                differences.append(f"{path}: missing from expected; actual={_display(actual[key])}")
            elif key not in actual:
                differences.append(
                    f"{path}: expected={_display(expected[key])}; missing from actual"
                )
            else:
                differences.extend(semantic_diff(expected[key], actual[key], _path=path))
        return tuple(differences)
    if isinstance(expected, (list, tuple)) and isinstance(actual, (list, tuple)):
        for index, (left, right) in enumerate(zip(expected, actual)):
            differences.extend(semantic_diff(left, right, _path=f"{_path}[{index}]"))
        if len(expected) != len(actual):
            differences.append(
                f"{_path}: expected {len(expected)} items; actual {len(actual)} items"
            )
        return tuple(differences)
    if expected != actual:
        differences.append(f"{_path}: expected={_display(expected)}; actual={_display(actual)}")
    return tuple(differences)


def accept_golden(
    path: Path,
    actual: Mapping[str, Any] | NormalizedTrace,
    *,
    accept: bool = False,
) -> tuple[str, ...]:
    """Compare a golden and optionally replace it after an explicit accept action.

    CI callers should leave ``accept`` false: they receive a semantic diff and
    cannot mutate repository expectations.  A local maintainer may pass
    ``accept=True`` (the companion script exposes this as ``--accept``).
    """

    actual_data = (
        actual.model_dump(mode="json") if isinstance(actual, NormalizedTrace) else dict(actual)
    )
    try:
        expected_data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        expected_data = None
    differences = semantic_diff(expected_data, actual_data)
    if differences and not accept:
        raise GoldenAcceptanceRequired(
            "golden differs; run the local accept action explicitly "
            "(pass accept=True or --accept)\n" + "\n".join(differences)
        )
    if accept and differences:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(actual_data, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return differences


def _display(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


__all__ = ["GoldenAcceptanceRequired", "accept_golden", "semantic_diff"]

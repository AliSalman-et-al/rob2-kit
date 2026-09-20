"""Typed, scope-bounded handling for Domain 3 missing-outcome quantities."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from ..workflow_models import MissingDataRow

_BASIS = re.compile(r"^(?:eh_[0-9a-f]{16}|sha256:[0-9a-f]{64})$")


def normalize_missing_data_row(row: MissingDataRow | Mapping[str, Any]) -> dict[str, Any]:
    """Return one validated row without deriving outcome availability.

    Legacy dictionaries remain accepted.  Only the explicit ``observed`` field
    participates in missing-count arithmetic; event, analyzed, imputed, safety,
    and exclusion quantities remain separate facts.
    """

    if isinstance(row, MissingDataRow):
        parsed = row
        basis = parsed.basis
    else:
        raw = dict(row)
        basis = raw.pop("basis", ())
        parsed = MissingDataRow.model_validate({**raw, "basis": []})
        if not isinstance(basis, (list, tuple)) or not all(
            isinstance(item, str) and _BASIS.fullmatch(item) for item in basis
        ):
            raise ValueError("basis must contain Evidence handles or canonical identities")
    payload = parsed.model_dump(mode="json", exclude_none=True)
    normalized = {
        key: payload.get(key)
        for key in ("randomized", "observed", "analyzed", "imputed")
    }
    normalized["scope"] = {
        key: payload[key] for key in ("arm", "population", "unit", "time_point")
    }
    normalized["exclusions"] = payload.get("exclusions", [])
    normalized["basis"] = list(basis)
    if "semantics" in payload:
        normalized["semantics"] = payload["semantics"]
    return normalized


def reconcile_missing_data(
    rows: Iterable[MissingDataRow | Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Reconcile only rows with identical participant-flow scope.

    Conflicting reports are retained.  No field other than an explicit
    ``observed`` count is treated as ascertainment, and no scientific judgment
    is made from the resulting arithmetic.
    """

    normalized: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    seen: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        item = normalize_missing_data_row(row)
        scope_data = item["scope"]
        scope = tuple(scope_data[key] for key in ("arm", "population", "unit", "time_point"))
        randomized = item.get("randomized")
        observed = item.get("observed")
        if isinstance(randomized, int) and isinstance(observed, int) and randomized >= observed:
            item["missing"] = randomized - observed
            item["missing_fraction"] = (randomized - observed) / randomized if randomized else 0.0
        else:
            item["missing"] = None
            item["missing_fraction"] = None

        key = scope
        fields = ("randomized", "observed", "analyzed", "imputed", "exclusions", "semantics")
        comparable = tuple(item.get(field) for field in fields)
        prior = seen.get(key)
        if prior is not None and tuple(prior.get(field) for field in fields) != comparable:
            conflicts.append({"scope": item["scope"], "reports": [prior, item]})
        else:
            seen[key] = item
        normalized.append(item)
    return {"rows": normalized, "conflicts": conflicts}


# Short aliases for callers that prefer the contract's noun-first vocabulary.
normalize_missing_data = normalize_missing_data_row

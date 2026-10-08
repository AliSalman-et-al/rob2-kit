"""Typed, scope-bounded handling for Domain 3 missing-outcome quantities."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from ..workflow_models import MissingDataRow

_BASIS = re.compile(r"^(?:eh_[0-9a-f]{16}|sha256:[0-9a-f]{64})$")
_RESULT_SCOPE_FIELDS = ("result_identity", "endpoint", "severity", "window", "event_definition")


def normalize_missing_data_row(row: MissingDataRow | Mapping[str, Any]) -> dict[str, Any]:
    """Return one validated row without deriving outcome availability.

    Legacy dictionaries remain accepted. Only explicit ``observed`` or
    ``unavailable`` quantities participate in missing-count arithmetic; event,
    analyzed, imputed, safety, and exclusion quantities remain separate facts.
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
        for key in (
            "randomized",
            "eligible",
            "treated",
            "observed",
            "analyzed",
            "imputed",
            "excluded",
            "event_count",
        )
    }
    normalized["scope"] = {key: payload[key] for key in ("arm", "population", "unit", "time_point")}
    normalized["exclusions"] = payload.get("exclusions", [])
    normalized["basis"] = list(basis)
    for field in ("completed", "unavailable"):
        if field in payload:
            normalized[field] = payload[field]
    for key in ("result_identity", "endpoint", "severity", "window", "event_definition"):
        if key in payload:
            normalized[key] = payload[key]
    if "semantics" in payload:
        normalized["semantics"] = payload["semantics"]
    return normalized


def reconcile_missing_data(
    rows: Iterable[MissingDataRow | Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Reconcile only rows with identical participant-flow scope.

    Conflicting reports are retained. Only explicit ``observed`` or ``unavailable``
    outcome quantities establish exact missing-count arithmetic. Generic censoring
    does not establish availability; no scientific judgment follows from counts.
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
        unavailable = item.get("unavailable")
        incompatible = isinstance(randomized, int) and (
            isinstance(observed, int)
            and observed > randomized
            or isinstance(unavailable, int)
            and unavailable > randomized
            or isinstance(observed, int)
            and isinstance(unavailable, int)
            and observed + unavailable != randomized
        )
        missing = (
            randomized - observed
            if isinstance(randomized, int) and isinstance(observed, int) and not incompatible
            else unavailable
            if isinstance(randomized, int) and isinstance(unavailable, int) and not incompatible
            else None
        )
        if missing is not None:
            item["missing"] = missing
            item["missing_fraction"] = missing / randomized if randomized else 0.0
            item["missing_bounds"] = {
                "lower": missing,
                "upper": missing,
                "kind": "exact",
            }
        else:
            item["missing"] = None
            item["missing_fraction"] = None
            if incompatible:
                # Preserve the report, but do not expose a consequence from
                # an internally incompatible pair of counts.
                item["missing_bounds"] = None
            elif isinstance(randomized, int) and (
                not isinstance(item.get("imputed"), int) or item["imputed"] <= randomized
            ):
                imputed = item.get("imputed")
                lower = imputed if isinstance(imputed, int) else 0
                item["missing_bounds"] = {
                    "lower": lower,
                    "upper": randomized,
                    "kind": "bound",
                }
            else:
                item["missing_bounds"] = None

        # Reports for different approved Results or endpoint definitions are
        # separate scopes even when their participant-flow labels coincide.
        key = (*scope, *(item.get(field) for field in _RESULT_SCOPE_FIELDS))
        fields = (
            "result_identity",
            "endpoint",
            "severity",
            "window",
            "randomized",
            "eligible",
            "treated",
            "completed",
            "observed",
            "unavailable",
            "analyzed",
            "imputed",
            "excluded",
            "event_count",
            "event_definition",
            "exclusions",
            "semantics",
        )
        comparable = tuple(item.get(field) for field in fields)
        prior = seen.get(key)
        if prior is not None and tuple(prior.get(field) for field in fields) != comparable:
            conflicts.append(
                {
                    "scope": {
                        **item["scope"],
                        **{field: item.get(field) for field in _RESULT_SCOPE_FIELDS},
                    },
                    "reports": [prior, item],
                }
            )
        else:
            seen[key] = item
        normalized.append(item)
    return {"rows": normalized, "conflicts": conflicts}


# Short aliases for callers that prefer the contract's noun-first vocabulary.
normalize_missing_data = normalize_missing_data_row


def missing_data_context(data: dict[str, Any]) -> dict[str, Any]:
    """Withhold context arithmetic contradicted by explicit same-outcome imputation.

    This is a read projection, not a change to canonical/historical reconciliation.
    Ambiguous meanings cannot supply a machine-checked scientific premise.
    """

    def project_row(original: dict[str, Any]) -> dict[str, Any]:
        row = dict(original)
        scope = row.get("scope", {})
        semantics = row.get("semantics") or {}
        imputed = row.get("imputed")
        scoped = (
            row.get("result_identity")
            and row.get("endpoint")
            and row.get("window") == scope.get("time_point")
            and scope.get("unit") == "participants"
            and semantics.get("population_role") == "randomized"
            and semantics.get("outcome_status") == "imputed"
            and (
                not semantics.get("event_definition")
                or semantics.get("event_definition") == row.get("event_definition")
            )
            and row.get("basis")
        )
        if scoped and isinstance(imputed, int) and imputed > 0:
            randomized, observed = row.get("randomized"), row.get("observed")
            limits = [row.get("unavailable")]
            if isinstance(randomized, int):
                limits.append(randomized)
                if isinstance(observed, int):
                    limits.append(randomized - observed)
            if any(isinstance(limit, int) and imputed > limit for limit in limits):
                row["quantity_conflict"] = (
                    f"The same selected-outcome scope reports {imputed} imputed outcomes, "
                    "but its randomized/observed or unavailable counts imply fewer missing "
                    "outcomes. Official Box 8, question 3.1 treats imputed outcomes as missing. "
                    "Reconcile the cited quantities or their declared scope before using "
                    "derived arithmetic; no signalling answer or risk label follows."
                )
                row["missing"] = row["missing_fraction"] = row["missing_bounds"] = None
        return row

    return {
        **data,
        "rows": [project_row(row) for row in data.get("rows", [])],
        "conflicts": [
            {**conflict, "reports": [project_row(row) for row in conflict.get("reports", [])]}
            for conflict in data.get("conflicts", [])
        ],
    }

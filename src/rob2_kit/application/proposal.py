"""Closed Proposal boundary and exact selected-material Evidence validation."""

import math
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..workflow_models import (
    AssessableResult,
    AssessableResultDraft,
    CategoryProfileResult,
    ComparativeEffectResult,
    GroupBoundValuesResult,
    ProposalDraft,
    ProposalReasoningDraft,
    UnavailableIntakeConditionBasisDraft,
)
from ._state import _commit_records, _ensure, _identity, _result, _root, _state
from .contracts import WorkflowConflict
from .evidence import (
    _evidence_catalog,
    _result_value_contains,
    main_report_read_gaps,
)
from .working import working_checkpoint_status


def _leaves(value: Any, path: str) -> dict[str, Any]:
    if isinstance(value, dict):
        return {
            p: leaf
            for key, item in value.items()
            if key not in {"form", "kind"}
            for p, leaf in _leaves(item, f"{path}/{key}").items()
        }
    if isinstance(value, list):
        return {
            p: leaf
            for index, item in enumerate(value)
            for p, leaf in _leaves(item, f"{path}/{index}").items()
        }
    return {path: value}


def _source_bound_leaves(value: Any, path: str) -> dict[str, Any]:
    """Return Result leaves whose values must be supported by Source Evidence.

    The target is a researcher/model interpretation of the captured request;
    its method, timing, population, arm descriptions, and intended measure are
    not duplicated source quotations. The selected passage still proves the
    reported endpoint and reported values. Caller-owned outcome labels,
    effect-of-interest discriminator, randomized-arm identifiers, and target
    arm descriptions are structural or interpretive fields and are validated
    separately.
    """
    leaves = {
        **_leaves(value, path),
    }
    return {
        leaf_path: leaf
        for leaf_path, leaf in leaves.items()
        if not (
            leaf_path
            in {
                "/target/outcome_definition",
                "/target/measurement/metric",
                "/target/measurement/method",
                "/target/effect_of_interest",
                "/target/intended_analysis_population",
                "/target/intended_effect_measure",
                "/reported/group_id",
                "/reported/analysis_population",
            }
            or leaf_path.startswith("/target/time_point_or_window/")
            or (leaf_path == "/reported/precision" and leaf is None)
            or (leaf_path == "/reported/endpoint/definition" and leaf is None)
            or (leaf_path.startswith("/target/comparison_groups/") and leaf_path.endswith("/id"))
            or (
                leaf_path.startswith("/target/comparison_groups/")
                and leaf_path.endswith("/assignment")
            )
            or (leaf_path.startswith("/reported/group_values/") and leaf_path.endswith("/group_id"))
            or (leaf_path.startswith("/reported/values/") and leaf_path.endswith("/group_id"))
            or leaf_path.startswith("/reported/category_axis_names/")
        )
    }


def _decimal(value: str) -> Decimal:
    parsed = Decimal(value)
    if not parsed.is_finite():
        raise InvalidOperation
    return parsed


def _format(value: Decimal) -> str:
    return format(value.normalize(), "f") if value else "0"


def _selected(catalog: dict[str, dict[str, Any]], handle: str) -> dict[str, Any] | None:
    return next((item for item in catalog.values() if item.get("handle") == handle), None)


def _valid_no_supported_sources_basis(batch: object, trial_id: str) -> bool:
    """Require the exact captured intake condition for a source-free Trial."""
    if not isinstance(batch, dict):
        return False
    conditions = batch.get("conditions")
    trials = batch.get("trials")
    expected = {"code": "no_supported_sources", "trial_id": trial_id}
    return (
        isinstance(conditions, list)
        and any(condition == expected for condition in conditions)
        and isinstance(trials, list)
        and any(
            isinstance(trial, dict)
            and trial.get("id") == trial_id
            and isinstance(trial.get("sources"), list)
            and not trial["sources"]
            for trial in trials
        )
    )


def _duplicate_values(values: list[str], path: str, code: str, label: str) -> list[dict[str, str]]:
    seen: dict[str, int] = {}
    repairs: list[dict[str, str]] = []
    for index, value in enumerate(values):
        first = seen.get(value)
        if first is None:
            seen[value] = index
            continue
        repairs.append(
            {
                "path": f"{path}/{index}",
                "code": code,
                "detail": f"{label} '{value}' duplicates item {first}; keep one entry.",
            }
        )
    return repairs


def _proposal_shape_repairs(
    draft: ProposalDraft, requested_outcomes: dict[str, str]
) -> list[dict[str, str]]:
    repairs = _duplicate_values(
        [item.trial_id for item in draft.results],
        "/results",
        "duplicate_trial_result",
        "Trial result",
    )

    def assessable_repairs(result: AssessableResultDraft, path: str) -> list[dict[str, str]]:
        result_repairs: list[dict[str, str]] = []
        result_repairs.extend(
            _duplicate_values(
                [group.id for group in result.target.comparison_groups],
                f"{path}/target/comparison_groups",
                "duplicate_target_group",
                "target comparison group",
            )
        )
        if isinstance(result.reported, ComparativeEffectResult):
            if result.reported.group_values:
                reported_path = f"{path}/reported/group_values"
                reported_ids = [item.group_id for item in result.reported.group_values]
            else:
                reported_path = ""
                reported_ids = []
        elif isinstance(result.reported, GroupBoundValuesResult):
            reported_path = f"{path}/reported/group_values"
            reported_ids = [item.group_id for item in result.reported.group_values]
        else:
            reported_path = ""
            reported_ids = []
        if reported_path:
            result_repairs.extend(
                _duplicate_values(
                    reported_ids,
                    reported_path,
                    "duplicate_reported_group",
                    "reported group value",
                )
            )
            target_ids = {group.id for group in result.target.comparison_groups}
            reported_set = set(reported_ids)
            missing = sorted(target_ids - reported_set)
            unexpected = sorted(reported_set - target_ids)
            if missing or unexpected:
                parts = [
                    "reported group IDs must exactly match target group IDs",
                    "target IDs: " + ", ".join(sorted(target_ids)),
                    "reported IDs: " + ", ".join(reported_ids),
                ]
                if missing:
                    parts.append("missing IDs: " + ", ".join(missing))
                if unexpected:
                    parts.append("unexpected IDs: " + ", ".join(unexpected))
                result_repairs.append(
                    {
                        "path": reported_path,
                        "code": "reported_group_set_mismatch",
                        "detail": "; ".join(parts),
                    }
                )
                if missing and isinstance(result.reported, GroupBoundValuesResult):
                    result_repairs.append(
                        {
                            "path": reported_path,
                            "code": "incomplete_comparative_result",
                            "detail": (
                                "Group-bound values without a value for every randomized group "
                                "cannot enter comparative RoB 2 assessment. Preserve the exact "
                                "report passage as Evidence and submit an unavailable Result "
                                "with the missing group result as a concrete missing fact."
                            ),
                        }
                    )
        elif isinstance(result.reported, CategoryProfileResult):
            result_repairs.append(
                {
                    "path": f"{path}/reported",
                    "code": "single_group_result_not_comparative",
                    "detail": (
                        "A one-group descriptive profile cannot support a RoB 2 comparative "
                        "assessment. Preserve its exact source passage as Evidence and submit "
                        "an unavailable Result with a missing_comparator_result fact based on "
                        "that Evidence."
                    ),
                }
            )
            target_ids = {group.id for group in result.target.comparison_groups}
            if result.reported.group_id not in target_ids:
                result_repairs.append(
                    {
                        "path": f"{path}/reported/group_id",
                        "code": "reported_group_id_not_in_target",
                        "detail": (
                            "single-group category profile group_id must identify one of the "
                            "target comparison groups"
                        ),
                    }
                )
            category_keys = [item.category_axes for item in result.reported.categories]
            if len(category_keys) != len(set(category_keys)):
                result_repairs.append(
                    {
                        "path": f"{path}/reported/categories",
                        "code": "duplicate_category_cell",
                        "detail": (
                            "category values must identify distinct category axes; the "
                            "profile-level denominator applies to every cell"
                        ),
                    }
                )
        return result_repairs

    for index, result in enumerate(draft.results):
        if result.trial_id not in requested_outcomes:
            repairs.append(
                {
                    "path": f"/results/{index}/trial_id",
                    "code": "unknown_trial",
                    "detail": "result trial_id is not in the captured Batch",
                }
            )
            continue
        if isinstance(result, AssessableResultDraft):
            repairs.extend(assessable_repairs(result, f"/results/{index}"))
    return repairs


def _canonical_result(
    result: AssessableResultDraft,
    index: int,
    catalog: dict[str, dict[str, Any]],
    path: str,
    requested_outcome: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    raw = result.model_dump(mode="json")
    if raw.get("applicability") is None:
        raw.pop("applicability", None)
    # Passage references are an input-only convenience. Canonical Result
    # records retain the materialized Evidence items, not the caller's
    # navigation list.
    raw.pop("passage_refs", None)
    evidence = raw.pop("evidence", [])
    if not evidence:
        selected_for_trial = sorted(
            (
                item
                for item in catalog.values()
                if item.get("trial_id") == result.trial_id
                and item.get("kind") in {"narrative", "figure"}
                and isinstance(item.get("handle"), str)
                and (not result.passage_refs or item.get("handle") in set(result.passage_refs))
            ),
            key=lambda item: (str(item.get("identity", "")), str(item["handle"])),
        )
        for selected in selected_for_trial:
            handle = selected["handle"]
            if selected.get("kind") == "figure":
                render = selected.get("render", {})
                evidence.append(
                    {
                        "kind": "figure",
                        "handle": handle,
                        "render_identity": render.get("identity"),
                        "delivery_receipt": selected.get("delivery_receipt"),
                        "region": selected.get("region"),
                        "transcription": selected.get("transcription"),
                        "provenance": selected.get("provenance"),
                    }
                )
            else:
                evidence.append({"kind": "narrative", "handle": handle})
    raw["evidence"] = evidence
    raw["clarity"] = {
        key: "specified"
        for key in (
            "outcome_definition",
            "measurement",
            "time_point",
            "analysis_population",
            "comparison_groups",
            "effect_measure",
            "source_table_meaning",
            "eligible_result_choice",
        )
    }
    raw["requested_outcome"] = requested_outcome
    raw["relation_rationale"] = result.relation_rationale
    target = dict(raw["target"])
    measurement = dict(target["measurement"])
    baseline_subgroup = target.pop("baseline_subgroup")
    target["intended_analysis_population"] = (
        "All randomized participants in the comparison groups"
        if baseline_subgroup is None
        else (
            "All randomized participants in the comparison groups; baseline subgroup: "
            + baseline_subgroup
        )
    )
    target["outcome_definition"] = requested_outcome
    target["measurement"] = {"metric": requested_outcome, "method": measurement["method"]}
    target["effect_of_interest"] = "assignment"
    raw["target"] = target
    defects: list[dict[str, Any]] = []
    for evidence_index, item in enumerate(raw["evidence"]):
        if item["kind"] != "figure":
            continue
        selected = _selected(catalog, item["handle"])
        render = {} if selected is None else selected.get("render", {})
        if selected is None or selected.get("kind") != "figure":
            # Evidence validation owns handle/kind defects.  Keep canonical
            # projection focused on enriching valid figure handles so one bad
            # handle yields one root repair rather than a duplicate.
            continue
        item.update(
            {
                "render_identity": render.get("identity"),
                "delivery_receipt": selected.get("delivery_receipt"),
                "region": selected.get("region"),
                "transcription": selected.get("transcription"),
                "provenance": selected.get("provenance"),
            }
        )
    return raw, defects


def _canonical_results(
    draft: ProposalDraft,
    catalog: dict[str, dict[str, Any]],
    requested_outcomes: dict[str, str],
    batch: object,
) -> tuple[list[dict[str, Any]] | None, list[dict[str, Any]], set[str]]:
    results: list[dict[str, Any]] = []
    defects: list[dict[str, Any]] = []
    used: set[str] = set()
    for index, result in enumerate(draft.results):
        if result.trial_id not in requested_outcomes:
            continue
        if isinstance(result, AssessableResultDraft):
            canonical, result_defects = _canonical_result(
                result,
                index,
                catalog,
                f"/results/{index}",
                requested_outcomes.get(result.trial_id, ""),
            )
            defects.extend(result_defects)
            results.append(canonical)
        else:
            canonical = result.model_dump(mode="json")
            canonical["requested_outcome"] = requested_outcomes.get(result.trial_id, "")
            facts = [item.fact for item in result.missing_facts]
            if len(set(facts)) != len(facts):
                defects.append(
                    {
                        "path": f"/results/{index}/missing_facts",
                        "code": "duplicate_missing_fact",
                        "detail": "each missing fact must be unique",
                    }
                )
            for fact_index, missing in enumerate(result.missing_facts):
                use = missing.basis
                path = f"/results/{index}/missing_facts/{fact_index}/basis"
                if isinstance(use, UnavailableIntakeConditionBasisDraft):
                    if not _valid_no_supported_sources_basis(batch, result.trial_id):
                        defects.append(
                            {
                                "path": path,
                                "code": "intake_condition_basis_invalid",
                                "detail": (
                                    "no_supported_sources must match the exact captured Batch "
                                    "condition for a Trial with zero captured Sources"
                                ),
                            }
                        )
                    else:
                        canonical["missing_facts"][fact_index]["basis"] = use.model_dump(
                            mode="json"
                        )
                    continue
                selected = _selected(catalog, use.evidence)
                if selected is None or selected.get("trial_id") != result.trial_id:
                    defects.append(
                        {
                            "path": f"{path}/evidence",
                            "code": "cross_trial_evidence",
                            "detail": (
                                "Evidence handle must resolve to selected material from this Trial"
                            ),
                        }
                    )
                    continue
                material = str(selected.get("quote", selected.get("transcription", "")))
                source = material
                canonical["missing_facts"][fact_index]["basis"]["evidence"] = selected["identity"]
                canonical["missing_facts"][fact_index]["basis"]["source"] = source
                used.add(use.evidence)
            results.append(canonical)
    return (results or None, defects, used)


def _derived_value(item: dict[str, Any]) -> str:
    values = [_decimal(input["value"]) for input in item["inputs"]]
    if item["operation"] == "sum":
        return _format(sum(values, Decimal("0")))
    if item["operation"] == "difference":
        if len(values) != 2:
            raise InvalidOperation
        return _format(values[0] - values[1])
    if len(values) != 2 or not values[1]:
        raise InvalidOperation
    return _format(values[0] / values[1])


def _validate_evidence(
    result: dict[str, Any],
    catalog: dict[str, dict[str, Any]],
    index: int,
    path: str | None = None,
) -> tuple[list[dict[str, Any]], set[str]]:
    defects: list[dict[str, Any]] = []
    handles: set[str] = set()
    result_path = path or f"/results/{index}"
    for evidence_index, item in enumerate(result["evidence"]):
        prefix = f"{result_path}/evidence/{evidence_index}"
        kind = item["kind"]
        if kind == "derived":
            for input_index, input in enumerate(item["inputs"]):
                selected = _selected(catalog, input["handle"])
                if selected is None or selected.get("trial_id") != result["trial_id"]:
                    defects.append(
                        {
                            "path": f"{prefix}/inputs/{input_index}",
                            "code": "cross_trial_evidence",
                            "detail": (
                                "derived input handle must resolve to selected evidence "
                                "from this Trial"
                            ),
                        }
                    )
                elif not _result_value_contains(
                    str(selected.get("quote", selected.get("transcription", ""))),
                    str(input["value"]),
                ):
                    defects.append(
                        {
                            "path": f"{prefix}/inputs/{input_index}",
                            "code": "derived_input_mismatch",
                            "detail": (
                                "derived input value must occur in the selected evidence "
                                "material after normalization"
                            ),
                        }
                    )
                handles.add(input["handle"])
            try:
                if _derived_value(item) != item["value"]:
                    defects.append(
                        {
                            "path": prefix,
                            "code": "derived_value_mismatch",
                            "detail": (
                                "derived value must equal the server recomputation from "
                                "the exact input values"
                            ),
                        }
                    )
            except (InvalidOperation, ValueError):
                defects.append(
                    {
                        "path": prefix,
                        "code": "invalid_derived_value",
                        "detail": (
                            "derived operation requires finite decimal inputs with the "
                            "declared arity"
                        ),
                    }
                )
            continue
        if kind == "table_multispan":
            spans = item.get("spans", [])
            materials: list[str] = []
            valid_spans = True
            for span_index, span in enumerate(spans):
                handle = span.get("handle") if isinstance(span, dict) else None
                selected = _selected(catalog, handle) if isinstance(handle, str) else None
                if isinstance(handle, str):
                    handles.add(handle)
                required_kind = "narrative" if item.get("basis") == "text" else "figure"
                if selected is None or selected.get("kind") != required_kind:
                    defects.append(
                        {
                            "path": f"{prefix}/spans/{span_index}/handle",
                            "code": "evidence_kind_mismatch",
                            "detail": (
                                "table_multispan handles must resolve to selected server "
                                "evidence of the declared basis"
                            ),
                        }
                    )
                    valid_spans = False
                    continue
                if selected.get("trial_id") != result["trial_id"]:
                    defects.append(
                        {
                            "path": f"{prefix}/spans/{span_index}/handle",
                            "code": "cross_trial_evidence",
                            "detail": "table_multispan evidence must come from this Trial",
                        }
                    )
                    valid_spans = False
                    continue
                materials.append(str(selected.get("quote", selected.get("transcription", ""))))
            fields = (
                [item[key] for key in ("title", "scope", "cohort", "row")]
                + item["columns"]
                + item["group_or_category_axes"]
                + item["cells"]
                + item["units"]
                + item["denominators"]
                + item["footnotes"]
            )
            if valid_spans and any(
                not any(_result_value_contains(material, value) for material in materials)
                for value in fields
            ):
                defects.append(
                    {
                        "path": prefix,
                        "code": "table_material_mismatch",
                        "detail": (
                            "each multi-span table field must occur in one cited span; "
                            "the server does not join spans into a continuous quotation"
                        ),
                    }
                )
            groups = {group["id"] for group in result["target"]["comparison_groups"]}
            if groups & set(item["group_or_category_axes"]):
                defects.append(
                    {
                        "path": prefix,
                        "code": "table_category_axis_is_group",
                        "detail": (
                            "group_or_category_axes must identify categories, not "
                            "comparison-group IDs"
                        ),
                    }
                )
            endpoint = result.get("reported", {}).get("endpoint", {})
            endpoint_name = endpoint.get("name") if isinstance(endpoint, dict) else None
            if isinstance(endpoint_name, str) and _is_generic_table_endpoint(endpoint_name):
                defects.append(
                    {
                        "path": f"{result_path}/reported/endpoint/name",
                        "code": "generic_table_endpoint",
                        "detail": (
                            "a generic table label such as 'Total' cannot stand in for the "
                            "reported endpoint name; use the endpoint stated in a cited span"
                        ),
                    }
                )
            continue

        selected = _selected(catalog, item["handle"])
        handles.add(item["handle"])
        required_kind = {
            "narrative": "narrative",
            "table": "narrative" if item.get("basis") == "text" else "figure",
            "figure": "figure",
        }[kind]
        if selected is None or selected.get("kind") != required_kind:
            defects.append(
                {
                    "path": prefix + "/handle",
                    "code": "evidence_kind_mismatch",
                    "detail": f"{kind} handle must resolve to the selected server evidence kind",
                }
            )
            continue
        if selected.get("trial_id") != result["trial_id"]:
            defects.append(
                {
                    "path": prefix + "/handle",
                    "code": "cross_trial_evidence",
                    "detail": "evidence handle must resolve to selected material from this Trial",
                }
            )
            continue
        material = str(
            selected.get("quote", "")
            if selected.get("kind") == "narrative"
            else selected.get("transcription", "")
        )
        if kind == "narrative":
            # The selected handle is the complete, server-preserved premise.
            # The old caller-authored clauses and value mappings duplicated
            # that premise and created a second, weaker proof surface.
            pass
        elif kind == "table":
            fields = (
                [item[key] for key in ("title", "scope", "cohort", "row")]
                + item["columns"]
                + item["group_or_category_axes"]
                + item["cells"]
                + item["units"]
                + item["denominators"]
                + item["footnotes"]
            )
            if any(not _result_value_contains(material, value) for value in fields):
                defects.append(
                    {
                        "path": prefix,
                        "code": "table_material_mismatch",
                        "detail": "table fields must occur exactly in selected material",
                    }
                )
            groups = {group["id"] for group in result["target"]["comparison_groups"]}
            if groups & set(item["group_or_category_axes"]):
                defects.append(
                    {
                        "path": prefix,
                        "code": "table_category_axis_is_group",
                        "detail": (
                            "group_or_category_axes must identify categories, not "
                            "comparison-group IDs"
                        ),
                    }
                )
        else:
            render = selected.get("render", {})
            if (
                item["render_identity"] != render.get("identity")
                or item.get("delivery_receipt") != selected.get("delivery_receipt")
                or item["region"] != selected.get("region")
                or item["transcription"] != selected.get("transcription")
                or item.get("provenance") != selected.get("provenance")
                or (
                    selected.get("provenance") == "text_corroborated"
                    and item["region"] != [0.0, 0.0, 1.0, 1.0]
                )
                or len(item["region"]) != 4
                or not all(math.isfinite(value) for value in item["region"])
                or not (
                    0 <= item["region"][0] < item["region"][2] <= 1
                    and 0 <= item["region"][1] < item["region"][3] <= 1
                )
            ):
                defects.append(
                    {
                        "path": prefix,
                        "code": "figure_material_mismatch",
                        "detail": (
                            "server-owned render identity, delivery receipt, region, and "
                            "transcription must match the selected figure handle"
                        ),
                    }
                )
    return defects, handles


def _supports_leaf(
    value: Any,
    item: dict[str, Any],
    result: dict[str, Any],
    catalog: dict[str, dict[str, Any]],
    field_path: str | None = None,
) -> bool:
    """Return whether one already-validated selected Evidence supports a leaf."""

    leaf = str(value)
    kind = item["kind"]
    if kind == "derived":
        try:
            return leaf == str(item["value"]) and _derived_value(item) == leaf
        except (InvalidOperation, ValueError, ZeroDivisionError):
            return False
    if kind == "table_multispan":
        return any(
            isinstance(span, dict)
            and isinstance(span.get("handle"), str)
            and isinstance((span_selected := _selected(catalog, span["handle"])), dict)
            and span_selected.get("trial_id") == result["trial_id"]
            and _result_value_contains(
                str(span_selected.get("quote", span_selected.get("transcription", ""))),
                leaf,
                field_path,
            )
            for span in item.get("spans", [])
        )
    selected = _selected(catalog, item.get("handle", ""))
    if selected is None or selected.get("trial_id") != result["trial_id"]:
        return False
    if kind == "narrative":
        material = str(selected.get("quote", ""))
        # Evidence is selected as one immutable passage, not as a character
        # span for each leaf. Numeric fields still need complete expressions;
        # repeated legitimate endpoint names, statistics, and units remain
        # acceptable.
        return _result_value_contains(material, leaf, field_path)
    if kind == "table":
        material = str(selected.get("quote", selected.get("transcription", "")))
        return _result_value_contains(material, leaf, field_path)
    if kind == "figure":
        return _result_value_contains(str(item.get("transcription", "")), leaf, field_path)
    return False


def _is_generic_table_endpoint(value: str) -> bool:
    """Reject aggregation labels where an endpoint name is required."""

    normalized = " ".join(value.casefold().split())
    return normalized in {"total", "overall", "all", "all patients", "all participants"}


def _reported_quantitative_paths(
    reported: dict[str, Any],
) -> list[tuple[tuple[str, Any], ...]]:
    if reported["form"] == "comparative_effect":
        return [
            (
                ("/reported/effect_measure", reported["effect_measure"]),
                ("/reported/estimate", reported["estimate"]),
            ),
            *(
                (
                    (f"/reported/group_values/{index}/statistic", item["statistic"]),
                    (f"/reported/group_values/{index}/value", item["value"]),
                    (f"/reported/group_values/{index}/unit", item["unit"]),
                )
                for index, item in enumerate(reported["group_values"])
            ),
        ]
    if reported["form"] == "group_bound_values":
        return [
            (
                (f"/reported/group_values/{index}/statistic", item["statistic"]),
                (f"/reported/group_values/{index}/value", item["value"]),
                (f"/reported/group_values/{index}/unit", item["unit"]),
            )
            for index, item in enumerate(reported["group_values"])
        ]
    return [
        tuple(
            [
                *(
                    (f"/reported/categories/{index}/category_axes/{axis}", value)
                    for axis, value in enumerate(item["category_axes"])
                ),
                (f"/reported/categories/{index}/value", item["value"]),
            ]
        )
        for index, item in enumerate(reported["categories"])
    ]


def _coherent_anchor_indices(
    result: dict[str, Any],
    catalog: dict[str, dict[str, Any]],
) -> list[int]:
    """Return selected items that join an endpoint identifier to a complete tuple."""

    reported = result["reported"]
    if not isinstance(reported, dict) or not isinstance(reported.get("form"), str):
        return []
    endpoint_name = reported["endpoint"]["name"]

    quantitative_tuples = _reported_quantitative_paths(reported)

    def multi_span_anchor(item: dict[str, Any]) -> bool:
        """Check each cited fragment without treating them as one quotation."""

        spans = item.get("spans", [])
        roles = {
            span.get("role")
            for span in spans
            if isinstance(span, dict) and isinstance(span.get("role"), str)
        }
        if {"header", "quantitative_row"} - roles or _is_generic_table_endpoint(endpoint_name):
            return False

        def supports_roles(value: Any, accepted_roles: set[str], field_path: str) -> bool:
            return any(
                isinstance(span, dict)
                and span.get("role") in accepted_roles
                and _supports_leaf(value, {**item, "spans": [span]}, result, catalog, field_path)
                for span in spans
            )

        return supports_roles(
            endpoint_name,
            {"title_or_definition", "header"},
            "/reported/endpoint/name",
        ) and any(
            all(
                supports_roles(
                    value,
                    {"header", "quantitative_row", "unit", "footnote"},
                    field_path,
                )
                for field_path, value in quantitative
            )
            for quantitative in quantitative_tuples
        )

    anchors = [
        index
        for index, item in enumerate(result["evidence"])
        if (
            multi_span_anchor(item)
            if item.get("kind") == "table_multispan"
            else _supports_leaf(endpoint_name, item, result, catalog, "/reported/endpoint/name")
        )
        and any(
            all(
                _supports_leaf(value, item, result, catalog, field_path)
                for field_path, value in quantitative
            )
            for quantitative in quantitative_tuples
        )
    ]
    endpoint_definition = reported["endpoint"].get("definition")
    if endpoint_definition is None:
        return anchors
    return sorted(
        anchors,
        key=lambda index: (
            not _supports_leaf(
                endpoint_definition,
                result["evidence"][index],
                result,
                catalog,
                "/reported/endpoint/definition",
            )
        ),
    )


def _reported_result_has_coherent_anchor(
    result: dict[str, Any],
    catalog: dict[str, dict[str, Any]],
) -> bool:
    """Require one selected item to join an endpoint identifier to one result tuple."""

    return bool(_coherent_anchor_indices(result, catalog))


def _endpoint_has_joint_support(result: dict[str, Any], catalog: dict[str, dict[str, Any]]) -> bool:
    endpoint = result["reported"]["endpoint"]
    name = endpoint["name"]
    definition = endpoint.get("definition")
    return any(
        _supports_leaf(name, item, result, catalog, "/reported/endpoint/name")
        and (
            definition is None
            or _supports_leaf(definition, item, result, catalog, "/reported/endpoint/definition")
        )
        for item in result["evidence"]
    )


def _derive_bindings(
    result: dict[str, Any],
    catalog: dict[str, dict[str, Any]],
    path: str,
    preserve_handles: set[str] | None = None,
) -> list[dict[str, Any]]:
    leaves = {
        **_source_bound_leaves(result["target"], "/target"),
        **_source_bound_leaves(result["reported"], "/reported"),
    }
    bindings: list[dict[str, Any]] = []
    bound_evidence: set[int] = set()
    category_binding_defects: list[dict[str, Any]] = []
    coherent_anchor_indices = _coherent_anchor_indices(result, catalog)

    def supports_eligible(value: object, item: dict[str, Any], leaf_path: str) -> bool:
        return _supports_leaf(value, item, result, catalog, leaf_path)

    def preferred_indices(leaf_path: str) -> list[int]:
        """Use the endpoint-and-tuple item before generic historical material."""

        if not leaf_path.startswith("/reported/"):
            return list(range(len(result["evidence"])))
        anchors = set(coherent_anchor_indices)
        return coherent_anchor_indices + [
            index for index in range(len(result["evidence"])) if index not in anchors
        ]

    target = result.get("target", {})
    measurement = target.get("measurement", {}) if isinstance(target, dict) else {}
    protected_claims = {
        "/target/measurement/method": measurement.get("method")
        if isinstance(measurement, dict)
        else None,
        "/target/intended_analysis_population": target.get("intended_analysis_population")
        if isinstance(target, dict)
        else None,
    }
    for protected_path, protected_value in protected_claims.items():
        if not isinstance(protected_value, str):
            continue
        eligible_index = next(
            (
                index
                for index, item in enumerate(result["evidence"])
                if supports_eligible(protected_value, item, protected_path)
            ),
            None,
        )
        if eligible_index is not None:
            bound_evidence.add(eligible_index)
            continue
    endpoint_values = {
        "/reported/endpoint/name": result["reported"]["endpoint"]["name"],
    }
    if result["reported"]["endpoint"].get("definition") is not None:
        endpoint_values["/reported/endpoint/definition"] = result["reported"]["endpoint"][
            "definition"
        ]
    common_endpoint_index = next(
        (
            index
            for index in preferred_indices("/reported/endpoint/name")
            for item in [result["evidence"][index]]
            if all(
                supports_eligible(value, item, leaf_path)
                for leaf_path, value in endpoint_values.items()
            )
        ),
        None,
    )
    for leaf_path, value in leaves.items():
        if (
            leaf_path == "/reported/endpoint/definition"
            and result["reported"]["endpoint"].get("definition") is not None
            and common_endpoint_index is None
        ):
            # A definition without a same-passage endpoint/name binding is a
            # proposal defect, not a claim to preserve as a standalone binding.
            continue
        if leaf_path in endpoint_values and common_endpoint_index is not None:
            bindings.append(
                {
                    "field": {"path": leaf_path},
                    "evidence_index": common_endpoint_index,
                    "value_digest": _identity(value),
                }
            )
            bound_evidence.add(common_endpoint_index)
            continue
        evidence_index = next(
            (
                index
                for index in preferred_indices(leaf_path)
                for item in [result["evidence"][index]]
                if supports_eligible(value, item, leaf_path)
            ),
            None,
        )
        if evidence_index is None:
            if not any(
                defect.get("code") in {"evidence_kind_mismatch", "cross_trial_evidence"}
                for defect in result.get("_evidence_defects", [])
            ):
                defect = {
                    "path": f"{path}{leaf_path}",
                    "code": "result_value_not_supported",
                    "detail": (
                        f"leaf {leaf_path} value {value!r} is not supported: no selected "
                        "Evidence contains it after normalization; copy the source wording "
                        "exactly or select Evidence containing it"
                    ),
                }
                if leaf_path.startswith("/reported/categories/"):
                    defect["value"] = str(value)
                    category_binding_defects.append(defect)
                else:
                    result.setdefault("_binding_defects", []).append(defect)
            continue
        bindings.append(
            {
                "field": {"path": leaf_path},
                "evidence_index": evidence_index,
                "value_digest": _identity(value),
            }
        )
        bound_evidence.add(evidence_index)
    if category_binding_defects:
        result.setdefault("_binding_defects", []).append(
            {
                "path": f"{path}/reported/categories",
                "code": "category_profile_values_not_supported",
                "detail": (
                    f"{len(category_binding_defects)} category cell field(s) are not supported "
                    "by the selected Evidence; copy each complete source cell value "
                    "without inventing statistic or unit labels"
                    + "; failing fields: "
                    + ", ".join(
                        f"{item['path']}={item['value']!r}" for item in category_binding_defects
                    )
                ),
            }
        )
    # Selection is durable server state. Keep bound material and explicitly
    # selected passages that preserve provenance for population summaries.
    preserved_indices = {
        index
        for index, item in enumerate(result["evidence"])
        if item.get("handle") in (preserve_handles or set())
    }
    kept_indices = sorted(bound_evidence | preserved_indices)
    remap = {old: new for new, old in enumerate(kept_indices)}
    result["evidence"] = [result["evidence"][index] for index in kept_indices]
    for binding in bindings:
        binding["evidence_index"] = remap[binding["evidence_index"]]
    result["bindings"] = bindings
    return bindings


def _has_local_defect(defects: list[dict[str, Any]], path: str) -> bool:
    return any(
        defect_path == path or defect_path.startswith(path + "/")
        for defect in defects
        if (defect_path := defect.get("path"))
    )


def _bind_result(
    result: dict[str, Any],
    catalog: dict[str, dict[str, Any]],
    index: int,
    path: str,
    semantic_defects: list[dict[str, Any]],
    preserve_handles: set[str] | None = None,
) -> tuple[list[dict[str, Any]], set[str]]:
    defects, _ = _validate_evidence(result, catalog, index, path)
    applicability = result.get("applicability")
    if isinstance(applicability, dict):
        for evidence_index, handle in enumerate(applicability.get("evidence", [])):
            selected = _selected(catalog, str(handle))
            if selected is None or selected.get("trial_id") != result.get("trial_id"):
                defects.append(
                    {
                        "path": f"{path}/applicability/evidence/{evidence_index}",
                        "code": "cross_trial_evidence",
                        "detail": "applicability Evidence must resolve to this Trial",
                    }
                )
    # Keep independent binding defects visible alongside claim defects.  Only
    # unresolved, wrong-kind, or cross-Trial handles make binding impossible;
    # an overreaching clause or stale figure claim must not hide unrelated
    # unsupported Result leaves.
    result["_evidence_defects"] = defects
    if result["reported"]["endpoint"].get(
        "definition"
    ) is not None and not _endpoint_has_joint_support(result, catalog):
        defects.append(
            {
                "path": f"{path}/reported/endpoint/definition",
                "code": "endpoint_definition_not_jointly_supported",
                "detail": (
                    "select a passage that explicitly ties the endpoint name and its exact "
                    "definition, or omit endpoint.definition"
                ),
            }
        )
    if (
        not any(
            defect.get("code") in {"evidence_kind_mismatch", "cross_trial_evidence"}
            for defect in defects
        )
        and not _reported_result_has_coherent_anchor(result, catalog)
        and not any(
            defect.get("code") == "endpoint_definition_not_jointly_supported" for defect in defects
        )
    ):
        detail = (
            "no single selected Evidence item supports the endpoint name and any "
            "provided definition together with one complete quantitative Result tuple. "
            "Do not resubmit the "
            "same cross-passage combination: either use the endpoint identifier exactly "
            "as it appears in the quantitative Evidence, or select one complete table "
            "block or figure containing the endpoint, headers, values, units, and "
            "applicable footnotes"
        )
        gap = _closest_evidence_gap(result, catalog)
        if gap is not None:
            handle, missing = gap
            detail += (
                f" Closest selected Evidence handle {handle!r} is missing required exact "
                "value(s): " + ", ".join(repr(value) for value in missing) + "."
            )
        defects.append(
            {
                "path": f"{path}/reported",
                "code": "incoherent_reported_result",
                "detail": detail,
            }
        )
    _derive_bindings(result, catalog, path, preserve_handles)
    handles = {
        item["handle"]
        for item in result["evidence"]
        if item.get("kind") in {"narrative", "figure", "table"}
    }
    handles.update(
        span["handle"]
        for item in result["evidence"]
        if item.get("kind") == "table_multispan"
        for span in item.get("spans", [])
        if isinstance(span, dict) and isinstance(span.get("handle"), str)
    )
    handles.update(
        input_item["handle"]
        for item in result["evidence"]
        if item.get("kind") == "derived"
        for input_item in item["inputs"]
    )
    if isinstance(applicability, dict):
        handles.update(
            handle for handle in applicability.get("evidence", []) if isinstance(handle, str)
        )
    defects.extend(result.pop("_binding_defects", []))
    result.pop("_evidence_defects", None)
    return defects, handles


def _result_handles(result: dict[str, Any], catalog: dict[str, dict[str, Any]]) -> set[str]:
    """Return selected Evidence handles referenced by one canonical Result."""
    handles: set[str] = set()
    for item in result.get("evidence", []):
        if not isinstance(item, dict):
            continue
        handle = item.get("handle")
        if isinstance(handle, str):
            handles.add(handle)
        if item.get("kind") == "table_multispan":
            handles.update(
                span["handle"]
                for span in item.get("spans", [])
                if isinstance(span, dict) and isinstance(span.get("handle"), str)
            )
        if item.get("kind") == "derived":
            handles.update(
                input_item["handle"]
                for input_item in item.get("inputs", [])
                if isinstance(input_item, dict) and isinstance(input_item.get("handle"), str)
            )
    applicability = result.get("applicability")
    if isinstance(applicability, dict):
        handles.update(
            handle for handle in applicability.get("evidence", []) if isinstance(handle, str)
        )
    for missing in result.get("missing_facts", []):
        if not isinstance(missing, dict):
            continue
        basis = missing.get("basis")
        if not isinstance(basis, dict):
            continue
        identity = basis.get("evidence")
        selected = catalog.get(identity) if isinstance(identity, str) else None
        if isinstance(selected, dict) and isinstance(selected.get("handle"), str):
            handles.add(selected["handle"])
    return handles


def _bound_proposal_evidence(
    catalog: dict[str, dict[str, Any]],
    used_handles: set[str],
    prior: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """Keep prior Evidence bytes where possible, then append newly bound items."""
    prior_evidence = prior.get("evidence", {}) if isinstance(prior, dict) else {}
    bound: dict[str, dict[str, Any]] = {}
    prior_handles: set[str] = set()
    if isinstance(prior_evidence, dict):
        for identity, item in prior_evidence.items():
            if not isinstance(item, dict) or item.get("handle") not in used_handles:
                continue
            bound[identity] = item
            prior_handles.add(str(item["handle"]))
    for identity, item in catalog.items():
        handle = item.get("handle")
        if handle in used_handles and handle not in prior_handles:
            bound[identity] = item
    return bound


def _closest_evidence_gap(
    result: dict[str, Any], catalog: dict[str, dict[str, Any]]
) -> tuple[str, list[str]] | None:
    """Find the selected Evidence item closest to proving one complete tuple."""
    reported = result.get("reported")
    if not isinstance(reported, dict) or not result.get("evidence"):
        return None
    endpoint = reported.get("endpoint", {})
    endpoint_name = endpoint.get("name") if isinstance(endpoint, dict) else None
    if not isinstance(endpoint_name, str):
        return None
    best: tuple[int, int, str, list[str]] | None = None
    for item in result["evidence"]:
        if not isinstance(item, dict):
            continue
        handle = item.get("handle")
        if not isinstance(handle, str) and item.get("kind") == "derived":
            inputs = item.get("inputs", [])
            handle = next(
                (entry.get("handle") for entry in inputs if isinstance(entry, dict)), None
            )
        if not isinstance(handle, str):
            continue
        for quantitative in _reported_quantitative_paths(reported):
            required = (("/reported/endpoint/name", endpoint_name), *quantitative)
            missing = [
                str(value)
                for field_path, value in required
                if not _supports_leaf(value, item, result, catalog, field_path)
            ]
            score = sum(
                _supports_leaf(value, item, result, catalog, field_path)
                for field_path, value in required
            )
            candidate = (score, -len(missing), handle, missing)
            if best is None or candidate[:2] > best[:2]:
                best = (score, -len(missing), handle, missing)
    if best is None or not best[3]:
        return None
    return best[2], best[3]


def save_proposal(
    workspace: str | Path,
    proposal: ProposalDraft,
    *,
    validate_only: bool = False,
) -> dict[str, Any]:
    root = _root(workspace)
    _ensure(root)
    state = _state(root)
    draft = proposal
    catalog = _evidence_catalog(root)
    requested_outcomes = {
        str(item["id"]): str(item["requested_outcome"])
        for item in (state.get("batch") or {}).get("trials", [])
        if isinstance(item, dict) and "id" in item and "requested_outcome" in item
    }
    batch = state.get("batch")
    expected_trials_in_order = [
        str(item["id"])
        for item in (state.get("batch") or {}).get("trials", [])
        if isinstance(item, dict) and "id" in item
    ]
    expected_trials = set(expected_trials_in_order)
    prior_proposal = state.get("proposal")
    pending_review = (
        isinstance(state.get("review"), dict)
        and state["review"].get("purpose") == "proposal"
        and isinstance(prior_proposal, dict)
    )
    revision_base = state.get("proposal_revision_base")
    revising_approved = (
        not pending_review
        and state.get("phase") in {"assessment", "ready_to_finalize"}
        and isinstance(prior_proposal, dict)
        and isinstance(state.get("proposal_acknowledgment"), dict)
    )
    revision_in_progress = isinstance(revision_base, dict)
    merging_proposal = pending_review or revising_approved or revision_in_progress
    read_gaps = main_report_read_gaps(
        root,
        batch.get("trials", []) if isinstance(batch, dict) else [],
        phase="proposal",
    )
    # The approved Result and a current source-bound checkpoint already provide
    # the post-approval orientation needed to revise that proposal.  Requiring
    # the proposal-phase pass again here creates a duplicate reread gate.  Keep
    # the gate for missing/stale notes, and for initial proposal submission.
    current_working_context = revising_approved and all(
        working_checkpoint_status(root, state, trial_id).get("status") == "current"
        for trial_id in {gap["trial_id"] for gap in read_gaps}
    )
    if read_gaps and not current_working_context:
        return _result(
            "repair",
            state,
            repairs=[
                {
                    "path": "/results",
                    "code": "main_report_reading_required",
                    "detail": (
                        "Finish the required bounded text pass before submitting the Proposal. "
                        "Call get_status, read data.main_report_reading[trial_id].required_ranges "
                        "with read_pages, then resubmit the complete Result cards and assessments "
                        "to validate_proposal. Save only after validation succeeds."
                    ),
                }
            ],
        )
    shape_defects = _proposal_shape_repairs(draft, requested_outcomes)
    canonical_results, draft_defects, used = _canonical_results(
        draft, catalog, requested_outcomes, batch
    )
    if canonical_results is None:
        return _result("repair", state, repairs=shape_defects + draft_defects)
    raw = {"results": canonical_results}
    defects: list[dict[str, Any]] = []
    if not merging_proposal and {item["trial_id"] for item in raw["results"]} != expected_trials:
        defects.append(
            {
                "path": "/results",
                "code": "one_result_per_trial_required",
                "detail": "results must contain exactly one entry for every captured Trial",
            }
        )
    defects.extend(shape_defects)
    defects.extend(draft_defects)
    preserve_handles_by_trial = {
        result.trial_id: set(result.passage_refs)
        for result in draft.results
        if isinstance(result, AssessableResultDraft)
    }
    for index, result in enumerate(raw["results"]):
        if result["kind"] == "unavailable":
            continue
        result_defects, handles = _bind_result(
            result,
            catalog,
            index,
            f"/results/{index}",
            shape_defects + draft_defects,
            preserve_handles_by_trial.get(result["trial_id"]),
        )
        defects.extend(result_defects)
        used |= handles
    if defects:
        return _result("repair", state, repairs=defects)
    canonical: list[dict[str, Any]] = []
    canonical_defects: list[dict[str, Any]] = []
    for index, result in enumerate(raw["results"]):
        if result["kind"] == "unavailable":
            canonical.append(result)
            continue
        try:
            canonical.append(AssessableResult.model_validate(result).model_dump(mode="json"))
        except ValidationError as error:
            canonical_defects.extend(
                {
                    "path": "/results/" + "/".join(map(str, item["loc"])),
                    "code": "invalid_canonical_result",
                    "detail": item["msg"],
                }
                for item in error.errors()
            )
    if canonical_defects:
        return _result("repair", state, repairs=canonical_defects)
    if merging_proposal:
        merge_base = (
            prior_proposal
            if pending_review
            else revision_base
            if isinstance(revision_base, dict)
            else prior_proposal
        )
        prior_payload = merge_base.get("payload", {}) if isinstance(merge_base, dict) else {}
        prior_results = prior_payload.get("results", []) if isinstance(prior_payload, dict) else []
        prior_by_trial = {
            item["trial_id"]: item
            for item in prior_results
            if isinstance(item, dict) and isinstance(item.get("trial_id"), str)
        }
        replacement_by_trial = {item["trial_id"]: item for item in canonical}
        if not defects and any(
            trial_id not in prior_by_trial for trial_id in expected_trials_in_order
        ):
            defects.append(
                {
                    "path": "/results",
                    "code": "existing_proposal_incomplete",
                    "detail": (
                        "the pending Proposal must contain one result for every captured Trial"
                    ),
                }
            )
        if defects:
            return _result("repair", state, repairs=defects)
        raw["results"] = [
            replacement_by_trial.get(trial_id, prior_by_trial[trial_id])
            for trial_id in expected_trials_in_order
            if trial_id in replacement_by_trial or trial_id in prior_by_trial
        ]
    else:
        canonical_by_trial = {item["trial_id"]: item for item in canonical}
        raw["results"] = [canonical_by_trial[trial_id] for trial_id in expected_trials_in_order]
    identity = _identity(raw)
    if state.get("phase") != "proposal" and not revising_approved and not revision_in_progress:
        raise ValueError("proposal is not the current operation")
    if (state.get("proposal") or {}).get("identity") == identity:
        return _result("success", state, proposal_identity=identity, retry=True)
    if draft.expected_revision != state.get("revision", 0):
        raise WorkflowConflict(draft.expected_revision, int(state.get("revision", 0)))
    if merging_proposal:
        used = set().union(*(_result_handles(result, catalog) for result in raw["results"]))
    bound = _bound_proposal_evidence(catalog, used, prior_proposal)
    if validate_only:
        return _result(
            "success",
            state,
            proposal_payload=raw,
            proposal_evidence=bound,
            proposal_identity=identity,
        )
    proposal_record = {"identity": identity, "payload": raw, "evidence": bound}
    revised_state = state
    if revising_approved or revision_in_progress:
        baseline = revision_base if isinstance(revision_base, dict) else prior_proposal
        baseline_payload = baseline.get("payload") if isinstance(baseline, dict) else None
        baseline_results = (
            baseline_payload.get("results", []) if isinstance(baseline_payload, dict) else []
        )
        baseline_by_trial = {
            item["trial_id"]: item
            for item in baseline_results
            if isinstance(item, dict) and isinstance(item.get("trial_id"), str)
        }
        changed_trial_ids = {
            trial_id
            for trial_id, result in ((item["trial_id"], item) for item in raw["results"])
            if baseline_by_trial.get(trial_id) != result
        }
        previously_changed = state.get("proposal_revision_trial_ids", [])
        if isinstance(previously_changed, list):
            changed_trial_ids.update(item for item in previously_changed if isinstance(item, str))
        dispositions = dict(state.get("trial_dispositions", {}))
        closed_trial_ids = {
            trial_id
            for trial_id, disposition in dispositions.items()
            if disposition in {"assessed", "needs_input", "unsupported_design", "failed"}
        }
        if changed_trial_ids & closed_trial_ids:
            return _result(
                "condition",
                state,
                condition={
                    "code": "trial_closed",
                    "detail": (
                        "a closed Trial is immutable; prepare a new Batch to replace its Result."
                    ),
                },
            )
        domain_records = dict(state.get("domain_records", {}))
        snapshots = dict(state.get("snapshots", {}))
        terminals = dict(state.get("terminals", {}))
        trial_reviews = dict(state.get("trial_reviews", {}))
        for trial_id in changed_trial_ids:
            if trial_id in expected_trials:
                dispositions[trial_id] = "pending"
                snapshots.pop(trial_id, None)
                trial_reviews.pop(trial_id, None)
            for key in [key for key in domain_records if key.startswith(f"{trial_id}:")]:
                domain_records.pop(key, None)
            for identity_key, terminal in list(terminals.items()):
                if isinstance(terminal, dict) and terminal.get("trial_id") == trial_id:
                    terminals.pop(identity_key, None)
        revised_state = {
            **state,
            "phase": "proposal",
            "trial_dispositions": dispositions,
            "domain_records": domain_records,
            "snapshots": snapshots,
            "terminals": terminals,
            "trial_reviews": trial_reviews,
            "proposal_revision_base": baseline,
            "proposal_revision_trial_ids": sorted(changed_trial_ids),
        }
    review = {
        "kind": "review",
        "purpose": "proposal",
        "workflow_basis": state.get("revision", 0),
        "candidate": {"identity": identity, "proposal": raw, "evidence": bound},
    }
    review["identity"] = _identity(review)
    state = _commit_records(
        root,
        {**revised_state, "proposal": proposal_record, "review": review},
        draft.expected_revision,
        {"proposal": proposal_record, f"review:{review['identity']}": review},
    )
    return _result(
        "review_required",
        state,
        proposal_identity=identity,
        review={"reference": review["identity"], "purpose": "proposal", "authority": "researcher"},
    )


def validate_proposal(
    workspace: str | Path, draft: dict[str, Any] | ProposalReasoningDraft
) -> dict[str, Any]:
    """Validate and persist one source-bound Proposal reasoning record."""
    root = _root(workspace)
    _ensure(root)
    state = _state(root)
    try:
        parsed = (
            draft
            if isinstance(draft, ProposalReasoningDraft)
            else ProposalReasoningDraft.model_validate(draft)
        )
    except ValidationError as error:
        return _result(
            "repair",
            state,
            repairs=[
                {
                    "path": "/" + "/".join(map(str, item["loc"])),
                    "code": "invalid_reasoning_draft",
                    "detail": item["msg"],
                }
                for item in error.errors()
            ],
        )

    result_trials = [item.trial_id for item in parsed.results]
    assessment_trials = [item.trial_id for item in parsed.assessments]
    repairs: list[dict[str, Any]] = []
    if len(set(result_trials)) != len(result_trials):
        repairs.append(
            {
                "path": "/results",
                "code": "duplicate_trial_result",
                "detail": "Submit at most one Result card per Trial.",
            }
        )
    if len(set(assessment_trials)) != len(assessment_trials):
        repairs.append(
            {
                "path": "/assessments",
                "code": "duplicate_trial_assessment",
                "detail": "Submit at most one reasoning assessment per Trial.",
            }
        )
    if set(result_trials) != set(assessment_trials):
        repairs.append(
            {
                "path": "/assessments",
                "code": "assessment_coverage_mismatch",
                "detail": "Submit exactly one reasoning assessment for every Result card.",
            }
        )
    results_by_trial = {item.trial_id: item for item in parsed.results}
    for index, assessment in enumerate(parsed.assessments):
        result = results_by_trial.get(assessment.trial_id)
        if isinstance(result, AssessableResultDraft):
            if not assessment.evidence_basis:
                repairs.append(
                    {
                        "path": f"/assessments/{index}/evidence_basis",
                        "code": "reasoning_evidence_required",
                        "detail": (
                            "Assessable Result reasoning needs at least one same-Trial Evidence "
                            "handle."
                        ),
                    }
                )
            if assessment.scope_justification is None:
                repairs.append(
                    {
                        "path": f"/assessments/{index}/scope_justification",
                        "code": "scope_justification_required",
                        "detail": (
                            "Assessable Result reasoning must explain target relation and time "
                            "window."
                        ),
                    }
                )
            if assessment.population_justification is None:
                repairs.append(
                    {
                        "path": f"/assessments/{index}/population_justification",
                        "code": "population_justification_required",
                        "detail": (
                            "Assessable Result reasoning must distinguish eligibility from "
                            "exclusions or missing observations."
                        ),
                    }
                )
        elif result is not None and assessment.missing_fact_justification is None:
            repairs.append(
                {
                    "path": f"/assessments/{index}/missing_fact_justification",
                    "code": "missing_fact_justification_required",
                    "detail": (
                        "Unavailable Result reasoning must explain the captured missing fact."
                    ),
                }
            )
    catalog = _evidence_catalog(root)
    for index, assessment in enumerate(parsed.assessments):
        for handle_index, handle in enumerate(assessment.evidence_basis):
            selected = _selected(catalog, handle)
            if selected is None:
                repairs.append(
                    {
                        "path": f"/assessments/{index}/evidence_basis/{handle_index}",
                        "code": "unknown_evidence_handle",
                        "detail": ("Reasoning Evidence handle must resolve to selected material."),
                    }
                )
            elif selected.get("trial_id") != assessment.trial_id:
                repairs.append(
                    {
                        "path": f"/assessments/{index}/evidence_basis/{handle_index}",
                        "code": "cross_trial_evidence",
                        "detail": (
                            "Reasoning Evidence must resolve to selected material from this Trial."
                        ),
                    }
                )
        for counterevidence_index, item in enumerate(assessment.counterevidence):
            selected = _selected(catalog, item.evidence)
            path = f"/assessments/{index}/counterevidence/{counterevidence_index}/evidence"
            if selected is None:
                repairs.append(
                    {
                        "path": path,
                        "code": "unknown_counterevidence_handle",
                        "detail": "Counterevidence handle must resolve to selected material.",
                    }
                )
            elif selected.get("trial_id") != assessment.trial_id:
                repairs.append(
                    {
                        "path": path,
                        "code": "cross_trial_counterevidence",
                        "detail": (
                            "Counterevidence must resolve to selected material from this Trial."
                        ),
                    }
                )
    if repairs:
        return _result("repair", state, repairs=repairs)

    proposal_draft = ProposalDraft(
        results=parsed.results,
        expected_revision=parsed.expected_revision,
    )
    validation = save_proposal(root, proposal_draft, validate_only=True)
    if validation.get("outcome") != "success":
        return validation
    payload = parsed.model_dump(mode="json")
    reasoning_id = _identity({"kind": "proposal_reasoning", "draft": payload})
    records = state.get("reasoning_records")
    prior = records.get(reasoning_id) if isinstance(records, dict) else None
    if isinstance(prior, dict):
        if prior.get("save_revision") != state.get("revision"):
            return _result(
                "condition",
                state,
                condition={
                    "code": "reasoning_stale",
                    "detail": (
                        "The Proposal receipt is stale. Call get_status. If work remains active, "
                        "submit complete replacement Result cards and matching assessments to "
                        "validate_proposal, then save its returned receipt. Otherwise follow "
                        "head.next_action."
                    ),
                },
            )
        return _reasoning_proposal_receipt(state, prior)
    if parsed.expected_revision != state.get("revision", 0):
        raise WorkflowConflict(parsed.expected_revision, int(state.get("revision", 0)))
    record = {
        "kind": "proposal_reasoning",
        "identity": reasoning_id,
        "draft": payload,
        "proposal_identity": validation.get("proposal_identity"),
        "save_revision": int(state.get("revision", 0)) + 1,
    }
    reasoning_records = dict(records) if isinstance(records, dict) else {}
    reasoning_records[reasoning_id] = record
    committed = _commit_records(
        root,
        {**state, "reasoning_records": reasoning_records},
        parsed.expected_revision,
        {f"reasoning:{reasoning_id}": record},
    )
    return _reasoning_proposal_receipt(committed, record)


def _reasoning_proposal_receipt(state: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    next_action = {
        "expected_revision": state.get("revision", 0),
    }
    return _result(
        "success",
        state,
        validation_scope="structure_and_references_only",
        repairs=[],
        next_action=next_action,
        continuation={
            "operation": "save_proposal",
            "authority": "host",
            **next_action,
        },
    )

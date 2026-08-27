"""Closed Proposal boundary and exact selected-material Evidence validation."""

import math
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..workflow_models import (
    AssessableResult,
    AssessableResultDraft,
    AssessableTargetRelation,
    CategoryProfileResult,
    ComparativeEffectResult,
    GroupBoundValuesResult,
    ProposalDraft,
    UnavailableIntakeConditionBasisDraft,
    exact_relation_rationale,
    has_missing_reporting_signal,
)
from ._state import _commit_records, _ensure, _identity, _result, _root, _state
from .contracts import WorkflowConflict
from .evidence import (
    _evidence_catalog,
    _is_incomplete_domain_source,
    _normalized_contains,
    _normalized_with_spans,
)


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
    its method, timing, population, and intended measure are not duplicated
    source quotations. The selected passage still proves the reported
    endpoint, arm assignments, and reported values. Caller-owned outcome
    labels, effect-of-interest discriminator, and randomized-arm identifiers
    are structural and are validated separately.
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
            }
            or (leaf_path == "/reported/precision" and leaf is None)
            or (leaf_path == "/reported/endpoint/definition" and leaf is None)
            or (leaf_path.startswith("/target/comparison_groups/") and leaf_path.endswith("/id"))
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
        if result.relation == AssessableTargetRelation.EXACT:
            target_name = requested_outcomes.get(result.trial_id, "")
            reported_name = result.reported.endpoint.name
            if _relation_name(target_name) != _relation_name(reported_name):
                result_repairs.append(
                    {
                        "path": f"{path}/relation",
                        "code": "exact_relation_name_mismatch",
                        "detail": (
                            f"exact relation requires captured target '{target_name}' to match "
                            f"the source-reported endpoint '{reported_name}'; "
                            "use a non-exact relation"
                        ),
                    }
                )
        else:
            pass
        result_repairs.extend(
            _duplicate_values(
                [group.id for group in result.target.comparison_groups],
                f"{path}/target/comparison_groups",
                "duplicate_target_group",
                "target comparison group",
            )
        )
        if isinstance(result.reported, ComparativeEffectResult):
            reported_path = f"{path}/reported/group_values"
            reported_ids = [item.group_id for item in result.reported.group_values]
        elif isinstance(result.reported, GroupBoundValuesResult):
            reported_path = f"{path}/reported/values"
            reported_ids = [item.group_id for item in result.reported.values]
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
        elif isinstance(result.reported, CategoryProfileResult):
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
        if isinstance(result, AssessableResultDraft):
            repairs.extend(assessable_repairs(result, f"/results/{index}"))
        else:
            expected = requested_outcomes.get(result.trial_id)
            if expected is None:
                repairs.append(
                    {
                        "path": f"/results/{index}/trial_id",
                        "code": "unknown_trial",
                        "detail": "result trial_id is not in the captured Batch",
                    }
                )
    return repairs


def _relation_name(value: str) -> str:
    normalized, _ = _normalized_with_spans(value)
    for character in "‐‑‒–—":
        normalized = normalized.replace(character, "-")
    return " ".join(normalized.casefold().replace("-", " ").split())


def _canonical_result(
    result: AssessableResultDraft,
    index: int,
    catalog: dict[str, dict[str, Any]],
    path: str,
    requested_outcome: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    raw = result.model_dump(mode="json")
    evidence: list[dict[str, Any]] = []
    selected_for_trial = sorted(
        (
            item
            for item in catalog.values()
            if item.get("trial_id") == result.trial_id
            and item.get("kind") in {"narrative", "figure"}
            and isinstance(item.get("handle"), str)
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
    raw["relation_rationale"] = (
        exact_relation_rationale(requested_outcome, result.reported.endpoint.name)
        if result.relation == AssessableTargetRelation.EXACT
        else result.relation_rationale
    )
    target = dict(raw["target"])
    measurement = dict(target["measurement"])
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
                incomplete = _is_incomplete_domain_source(source)
                if incomplete:
                    defects.append(
                        {
                            "path": f"{path}/source",
                            "code": "incomplete_unavailable_evidence_source",
                            "detail": (
                                "source must be a complete premise, not a lead-in or "
                                "unfinished list"
                            ),
                        }
                    )
                elif not has_missing_reporting_signal(source):
                    defects.append(
                        {
                            "path": f"{path}/source",
                            "code": "unavailable_source_lacks_missing_signal",
                            "detail": (
                                "source must contain an explicit lexical non-reporting signal "
                                "such as 'not reported', 'missing', or 'not documented'"
                            ),
                        }
                    )
                if not incomplete:
                    canonical["missing_facts"][fact_index]["basis"]["evidence"] = selected[
                        "identity"
                    ]
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
                elif (
                    _normalized_with_spans(
                        str(selected.get("quote", selected.get("transcription", "")))
                    )[0].find(_normalized_with_spans(str(input["value"]))[0])
                    < 0
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
            if any(not _normalized_contains(material, value) for value in fields):
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
                            "server-owned render_identity, region, and transcription "
                            "must match the selected figure handle"
                        ),
                    }
                )
    return defects, handles


def _supports_leaf(
    value: Any,
    item: dict[str, Any],
    result: dict[str, Any],
    catalog: dict[str, dict[str, Any]],
) -> bool:
    """Return whether one already-validated selected Evidence supports a leaf."""

    leaf = str(value)
    kind = item["kind"]
    if kind == "derived":
        try:
            return leaf == str(item["value"]) and _derived_value(item) == leaf
        except (InvalidOperation, ValueError, ZeroDivisionError):
            return False
    selected = _selected(catalog, item.get("handle", ""))
    if selected is None or selected.get("trial_id") != result["trial_id"]:
        return False
    if kind == "narrative":
        material = str(selected.get("quote", ""))
        # Evidence is selected as one immutable passage, not as a character
        # span for each leaf. Exact normalized containment is therefore the
        # right proof: requiring a unique occurrence falsely rejects repeated
        # endpoint names, statistics, and units such as ``months``.
        return _normalized_with_spans(material)[0].find(_normalized_with_spans(leaf)[0]) >= 0
    if kind == "table":
        material = str(selected.get("quote", selected.get("transcription", "")))
        return _normalized_contains(material, leaf)
    if kind == "figure":
        return _normalized_contains(str(item.get("transcription", "")), leaf)
    return False


def _host_visual_leaf_allowed(path: str) -> bool:
    """Keep image-only proof limited to facts literally visible in the image."""

    return (
        path in {"/reported/endpoint/name", "/reported/endpoint/definition"}
        or path.startswith("/reported/")
        or (path.startswith("/target/comparison_groups/") and path.endswith("/assignment"))
        or path.startswith("/target/time_point_or_window/")
    )


def _reported_quantitative_tuples(reported: dict[str, Any]) -> list[tuple[Any, ...]]:
    """Return the complete reported-value tuples used by the Evidence contract."""

    if reported["form"] == "comparative_effect":
        return [
            (reported["effect_measure"], reported["estimate"]),
            *(
                (item["statistic"], item["value"], item["unit"])
                for item in reported["group_values"]
            ),
        ]
    if reported["form"] == "group_bound_values":
        return [(item["statistic"], item["value"], item["unit"]) for item in reported["values"]]
    return [(*item["category_axes"], item["value"]) for item in reported["categories"]]


def _coherent_anchor_indices(
    result: dict[str, Any],
    catalog: dict[str, dict[str, Any]],
) -> list[int]:
    """Return selected items that join an endpoint identifier to a complete tuple."""

    reported = result["reported"]
    if not isinstance(reported, dict) or not isinstance(reported.get("form"), str):
        return []
    endpoint_name = reported["endpoint"]["name"]

    quantitative_tuples = _reported_quantitative_tuples(reported)
    anchors = [
        index
        for index, item in enumerate(result["evidence"])
        if _supports_leaf(endpoint_name, item, result, catalog)
        and any(
            all(_supports_leaf(value, item, result, catalog) for value in quantitative)
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
        _supports_leaf(name, item, result, catalog)
        and (definition is None or _supports_leaf(definition, item, result, catalog))
        for item in result["evidence"]
    )


def _derive_bindings(
    result: dict[str, Any],
    catalog: dict[str, dict[str, Any]],
    path: str,
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
        if not _supports_leaf(value, item, result, catalog):
            return False
        selected = _selected(catalog, item.get("handle", ""))
        return not (
            isinstance(selected, dict)
            and selected.get("kind") == "figure"
            and selected.get("provenance") == "host_visual"
            and not _host_visual_leaf_allowed(leaf_path)
        )

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
        if any(
            _supports_leaf(protected_value, item, result, catalog) for item in result["evidence"]
        ):
            result.setdefault("_binding_defects", []).append(
                {
                    "path": f"{path}{protected_path}",
                    "code": "result_value_not_supported",
                    "detail": (
                        f"leaf {protected_path} value {protected_value!r} occurs only in "
                        "host_visual transcription; select text-corroborated or narrative "
                        "Evidence for analysis method or intended population"
                    ),
                }
            )
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
                supports_eligible(value, item, "/reported/endpoint/name")
                for value in endpoint_values.values()
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
            tier_blocked = any(
                _supports_leaf(value, item, result, catalog)
                and not supports_eligible(value, item, leaf_path)
                for item in result["evidence"]
            )
            if not any(
                defect.get("code") in {"evidence_kind_mismatch", "cross_trial_evidence"}
                for defect in result.get("_evidence_defects", [])
            ):
                defect = {
                    "path": f"{path}{leaf_path}",
                    "code": "result_value_not_supported",
                    "detail": (
                        f"leaf {leaf_path} value {value!r} occurs only in host_visual "
                        "transcription and requires text-corroborated or narrative Evidence; "
                        "select Evidence containing it"
                        if tier_blocked
                        else (
                            f"leaf {leaf_path} value {value!r} is not supported: no selected "
                            "Evidence contains it after normalization; copy the source wording "
                            "exactly or select Evidence containing it"
                        )
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
    # Selection is durable server state. Keep only material that actually
    # supports this Result instead of making the caller curate a second list.
    kept_indices = sorted(bound_evidence)
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
) -> tuple[list[dict[str, Any]], set[str]]:
    defects, _ = _validate_evidence(result, catalog, index, path)
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
                    "definition, or use null for endpoint.definition"
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
        defects.append(
            {
                "path": f"{path}/reported",
                "code": "incoherent_reported_result",
                "detail": (
                    "no single selected Evidence item supports the endpoint name and any "
                    "provided definition together with one complete quantitative Result tuple. "
                    "Do not resubmit the "
                    "same cross-passage combination: either use the endpoint identifier exactly "
                    "as it appears in the quantitative Evidence, or select one complete table "
                    "block or figure containing the endpoint, headers, values, units, and "
                    "applicable footnotes"
                ),
            }
        )
    _derive_bindings(result, catalog, path)
    handles = {
        item["handle"]
        for item in result["evidence"]
        if item.get("kind") in {"narrative", "figure", "table"}
    }
    handles.update(
        input_item["handle"]
        for item in result["evidence"]
        if item.get("kind") == "derived"
        for input_item in item["inputs"]
    )
    defects.extend(result.pop("_binding_defects", []))
    result.pop("_evidence_defects", None)
    return defects, handles


def save_proposal(
    workspace: str | Path,
    proposal: ProposalDraft,
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
    shape_defects = _proposal_shape_repairs(draft, requested_outcomes)
    canonical_results, draft_defects, used = _canonical_results(
        draft, catalog, requested_outcomes, batch
    )
    if canonical_results is None:
        return _result("repair", state, repairs=shape_defects + draft_defects)
    raw = {"results": canonical_results}
    defects: list[dict[str, Any]] = []
    expected_trials = {item["id"] for item in (state.get("batch") or {}).get("trials", [])}
    if {item["trial_id"] for item in raw["results"]} != expected_trials:
        defects.append(
            {
                "path": "/results",
                "code": "one_result_per_trial_required",
                "detail": "results must contain exactly one entry for every captured Trial",
            }
        )
    defects.extend(shape_defects)
    defects.extend(draft_defects)
    for index, result in enumerate(raw["results"]):
        if result["kind"] == "unavailable":
            continue
        result_defects, handles = _bind_result(
            result,
            catalog,
            index,
            f"/results/{index}",
            shape_defects + draft_defects,
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
    raw["results"] = canonical
    identity = _identity(raw)
    if state.get("phase") != "proposal":
        raise ValueError("proposal is not the current operation")
    if (state.get("proposal") or {}).get("identity") == identity:
        return _result("success", state, proposal_identity=identity, retry=True)
    if draft.expected_revision != state.get("revision", 0):
        raise WorkflowConflict(draft.expected_revision, int(state.get("revision", 0)))
    bound = {key: item for key, item in catalog.items() if item.get("handle") in used}
    proposal_record = {"identity": identity, "payload": raw, "evidence": bound}
    review = {
        "kind": "review",
        "purpose": "proposal",
        "workflow_basis": state.get("revision", 0),
        "candidate": {"identity": identity, "proposal": raw, "evidence": bound},
    }
    review["identity"] = _identity(review)
    state = _commit_records(
        root,
        {**state, "proposal": proposal_record, "review": review},
        draft.expected_revision,
        {"proposal": proposal_record, f"review:{review['identity']}": review},
    )
    return _result(
        "review_required",
        state,
        proposal_identity=identity,
        review={"reference": review["identity"], "purpose": "proposal", "authority": "researcher"},
    )

"""Strict deterministic v0.5 held-out evaluation and privacy-safe receipts."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from typing import Any

SCHEMA = "rob2-kit.held-out-evaluation.v0.5"
MANIFEST_SCHEMA = "rob2-kit.evaluation-manifest.v0.5"
CELL_FIELDS = (
    "trial_id",
    "result_identity",
    "outcome_id",
    "domain_id",
    "question_id",
    "run_id",
    "draw",
    "model_family",
    "model_version",
    "kit_revision",
    "intervention_id",
)
EVENT_TYPES = (
    "projection_available",
    "candidate_ranked",
    "passage_surfaced",
    "content_delivered",
    "passage_inspected",
    "evidence_cited",
    "premise_assessed",
    "answer_committed",
)
PASSAGE_STAGES = EVENT_TYPES[1:6]
DOMAIN_IDS = (
    "domain:randomization",
    "domain:deviations",
    "domain:missing",
    "domain:measurement",
    "domain:selection",
)
SHA = re.compile(r"^sha256:[0-9a-f]{64}$")
PRIVATE_FIELDS = {
    "adjudication",
    "coordinate",
    "coordinates",
    "holdout_adjudication",
    "holdout_label",
    "normalized_query",
    "passage_text",
    "query",
    "query_recipe",
    "quote",
    "rationale",
    "reviewer",
    "reviewer_id",
    "source_text",
    "text",
}


def _hash(value: Any) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )


def _closed(value: Any, fields: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{name} has an unclosed field set")
    return value


def _cell(row: dict[str, Any]) -> tuple[str, ...]:
    if any(not isinstance(row.get(key), str) or not row[key] for key in CELL_FIELDS):
        raise ValueError("cell must contain every v0.5 join field")
    return tuple(row[key] for key in CELL_FIELDS)


def _without(cell: tuple[str, ...], *indexes: int) -> tuple[str, ...]:
    return tuple(value for index, value in enumerate(cell) if index not in indexes)


def _scientific_level(row: dict[str, Any]) -> str:
    if row["domain_id"] == "overall" and row["question_id"] == "overall":
        return "overall"
    if row["domain_id"].startswith("domain:") and row["question_id"] == "overall":
        return "domain"
    return "question"


def _rate(n: int | float, d: int | float) -> dict[str, int | float]:
    return {"numerator": n, "denominator": d, "rate": n / d if d else 0.0}


def _scrub(value: Any) -> Any:
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _scrub(item)
            for key, item in value.items()
            if not isinstance(key, str) or key.casefold() not in PRIVATE_FIELDS
        }
    return value


def privacy_safe_receipt(report: dict[str, Any]) -> dict[str, Any]:
    return _scrub(report)


def validate_split_isolation(manifest: dict[str, Any]) -> None:
    splits = manifest.get("splits") if isinstance(manifest, dict) else None
    if not isinstance(splits, list) or not splits:
        raise ValueError("splits must be a non-empty list")
    trials: dict[str, str] = {}
    fingerprints: dict[str, str] = {}
    for row in splits:
        _closed(
            row,
            {
                "trial_id",
                "split",
                "source_fingerprints",
                "projection_fingerprints",
                "document_family_fingerprints",
            },
            "split",
        )
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("trial_id"), str)
            or row.get("split") not in {"development", "holdout"}
        ):
            raise ValueError("split rows need trial_id and development/holdout split")
        if trials.setdefault(row["trial_id"], row["split"]) != row["split"]:
            raise ValueError("Trial crosses development and holdout")
        for field in (
            "source_fingerprints",
            "projection_fingerprints",
            "document_family_fingerprints",
        ):
            values = row.get(field)
            if not isinstance(values, list):
                raise ValueError(f"{field} must be a list")
            for fingerprint in values:
                if not isinstance(fingerprint, str) or not SHA.fullmatch(fingerprint):
                    raise ValueError(f"{field} must contain sha256 values")
                if fingerprints.setdefault(fingerprint, row["split"]) != row["split"]:
                    raise ValueError(
                        "Source/projection fingerprint crosses development and holdout"
                    )


def _validate_dimensions(row: dict[str, Any], manifest: dict[str, Any]) -> None:
    declared_trials = {item["trial_id"] for item in manifest["splits"]}
    if row["trial_id"] not in declared_trials:
        raise ValueError("row Trial is absent from the frozen split manifest")
    if (
        row["model_family"] != manifest["model"]["family"]
        or row["model_version"] != manifest["model"]["version"]
        or row["kit_revision"] != manifest["kit_revision"]
        or row["intervention_id"] not in manifest["interventions"]
    ):
        raise ValueError("row dimensions disagree with the frozen manifest")


def validate_manifest(manifest: dict[str, Any]) -> None:
    fields = {
        "schema",
        "splits",
        "source_hash",
        "projection_hash",
        "corpus_hash",
        "result_mapping_hash",
        "model",
        "prompt_hash",
        "skill_hash",
        "tool_schema_hash",
        "kit_revision",
        "scorer_hash",
        "interventions",
        "budget_hash",
        "selection_rule",
        "primary_metric",
        "coverage_floor",
        "cost_limit",
        "attempt_ids",
    }
    _closed(manifest, fields, "manifest")
    if manifest["schema"] != MANIFEST_SCHEMA:
        raise ValueError("evaluation manifest schema is invalid")
    for key in (
        "source_hash",
        "projection_hash",
        "corpus_hash",
        "result_mapping_hash",
        "prompt_hash",
        "skill_hash",
        "tool_schema_hash",
        "scorer_hash",
        "budget_hash",
    ):
        if not isinstance(manifest[key], str) or not SHA.fullmatch(manifest[key]):
            raise ValueError(f"manifest {key} is invalid")
    if not isinstance(manifest["kit_revision"], str) or not manifest["kit_revision"]:
        raise ValueError("manifest kit_revision is invalid")
    if (
        not isinstance(manifest["model"], dict)
        or set(manifest["model"]) != {"family", "version"}
        or not all(isinstance(item, str) and item for item in manifest["model"].values())
    ):
        raise ValueError("manifest model is invalid")
    if (
        not isinstance(manifest["interventions"], dict)
        or not manifest["interventions"]
        or not all(
            isinstance(key, str) and key and isinstance(value, str) and SHA.fullmatch(value)
            for key, value in manifest["interventions"].items()
        )
    ):
        raise ValueError("manifest interventions are invalid")
    if manifest["selection_rule"] != "lowest_final_attempt_id" or manifest[
        "primary_metric"
    ] not in {"domain_accuracy", "question_accuracy", "overall_accuracy"}:
        raise ValueError("manifest preregistration is invalid")
    if (
        not isinstance(manifest["coverage_floor"], (int, float))
        or not 0 <= manifest["coverage_floor"] <= 1
        or not isinstance(manifest["cost_limit"], (int, float))
        or manifest["cost_limit"] < 0
    ):
        raise ValueError("manifest limits are invalid")
    if (
        not isinstance(manifest["attempt_ids"], list)
        or not manifest["attempt_ids"]
        or len(set(manifest["attempt_ids"])) != len(manifest["attempt_ids"])
        or not all(isinstance(item, str) and item for item in manifest["attempt_ids"])
    ):
        raise ValueError("manifest attempt_ids are invalid")
    validate_split_isolation(manifest)


def _confusion(rows: list[dict[str, Any]]) -> dict[str, Any]:
    labels = sorted({row["label"] for row in rows} | {row["prediction"] for row in rows})
    matrix = {
        actual: {
            predicted: sum(
                row["label"] == actual and row["prediction"] == predicted for row in rows
            )
            for predicted in labels
        }
        for actual in labels
    }
    recalls = [
        matrix[label][label] / sum(matrix[label].values())
        for label in labels
        if sum(matrix[label].values())
    ]
    return {
        "confusion": matrix,
        "accuracy": _rate(sum(row["label"] == row["prediction"] for row in rows), len(rows)),
        "balanced_accuracy": _rate(sum(recalls), len(recalls)),
    }


def evaluate_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
    _closed(
        fixture, {"schema", "manifest", "references", "attempts", "events", "queries"}, "fixture"
    )
    if fixture["schema"] != SCHEMA:
        raise ValueError("evaluation fixture schema is unsupported")
    manifest = fixture["manifest"]
    validate_manifest(manifest)
    if not all(
        isinstance(fixture[key], list) for key in ("references", "attempts", "events", "queries")
    ):
        raise ValueError("fixture collections must be lists")
    refs: dict[tuple[tuple[str, ...], str], dict[str, Any]] = {}
    ref_fields = set(CELL_FIELDS) | {
        "premise_id",
        "status",
        "required",
        "acceptable_evidence_sets",
        "contradiction_ids",
        "source_roles",
        "useful_depth",
    }
    for row in fixture["references"]:
        if set(row) != ref_fields and set(row) != ref_fields | {"restricted"}:
            raise ValueError("reference has an unclosed field set")
        cell = _cell(row)
        _validate_dimensions(row, manifest)
        if (
            not isinstance(row["premise_id"], str)
            or not row["premise_id"]
            or row["status"] not in {"adjudicated", "disputed", "unavailable"}
            or type(row["required"]) is not bool
            or not isinstance(row["source_roles"], list)
            or not all(isinstance(role, str) and role for role in row["source_roles"])
            or not isinstance(row["useful_depth"], int)
            or row["useful_depth"] < 1
            or not isinstance(row["acceptable_evidence_sets"], list)
            or not row["acceptable_evidence_sets"]
            or not all(
                isinstance(option, list)
                and option
                and all(isinstance(item, str) and item for item in option)
                for option in row["acceptable_evidence_sets"]
            )
            or not isinstance(row["contradiction_ids"], list)
            or not all(
                isinstance(identity, str) and identity for identity in row["contradiction_ids"]
            )
        ):
            raise ValueError("reference is invalid")
        if "restricted" in row:
            restricted = row["restricted"]
            if not isinstance(restricted, dict):
                raise ValueError("reference restricted input is invalid")
            answer_label = restricted.get("answer_label")
            support_label = restricted.get("support_label")
            if row["status"] == "adjudicated" and (
                not isinstance(answer_label, str) or not answer_label
            ):
                raise ValueError("adjudicated reference answer label is missing")
            if support_label is not None and support_label not in {
                "full",
                "partial",
                "unsupported",
                "conflicted",
                "unavailable",
            }:
                raise ValueError("reference restricted support label is invalid")
        elif row["status"] == "adjudicated":
            raise ValueError("adjudicated reference restricted labels are missing")
        key = (cell, row["premise_id"])
        if key in refs:
            raise ValueError("duplicate premise")
        refs[key] = row
    attempt_fields = set(CELL_FIELDS) | {
        "attempt_id",
        "disposition",
        "selected",
        "prediction",
        "tool_calls",
        "response_bytes",
        "context_bytes",
        "tokens",
        "latency_ms",
        "cost",
        "repair_count",
        "false_repair",
    }
    attempts: dict[str, dict[str, Any]] = {}
    for row in fixture["attempts"]:
        _closed(row, attempt_fields, "attempt")
        _cell(row)
        _validate_dimensions(row, manifest)
        numeric = (
            "tool_calls",
            "response_bytes",
            "context_bytes",
            "tokens",
            "latency_ms",
            "cost",
            "repair_count",
        )
        if (
            not isinstance(row["attempt_id"], str)
            or not row["attempt_id"]
            or row["attempt_id"] in attempts
            or row["disposition"] not in {"assessed", "needs_input", "failed"}
            or type(row["selected"]) is not bool
            or type(row["false_repair"]) is not bool
            or not all(isinstance(row[key], (int, float)) and row[key] >= 0 for key in numeric)
            or not isinstance(row["prediction"], str)
        ):
            raise ValueError("attempt is invalid")
        attempts[row["attempt_id"]] = row
    if set(attempts) != set(manifest["attempt_ids"]):
        raise ValueError("manifest must freeze every attempt")
    attempts_by_cell: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in attempts.values():
        attempts_by_cell[_cell(row)].append(row)
    for rows in attempts_by_cell.values():
        expected = min(rows, key=lambda value: value["attempt_id"])["attempt_id"]
        selected_ids = [row["attempt_id"] for row in rows if row["selected"]]
        if selected_ids != [expected]:
            raise ValueError(
                "selection rule requires exactly the lowest final attempt_id for every cell"
            )
    selected: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in sorted(attempts.values(), key=lambda value: value["attempt_id"]):
        if row["selected"]:
            if _cell(row) in selected:
                raise ValueError("selection rule selected duplicate cells")
            selected[_cell(row)] = row
    event_fields = set(CELL_FIELDS) | {
        "attempt_id",
        "type",
        "identity",
        "observer",
        "observed",
        "limit",
        "rank",
        "premise_id",
        "support",
    }
    observed: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in fixture["events"]:
        _closed(row, event_fields, "event")
        cell = _cell(row)
        attempt = attempts.get(row["attempt_id"])
        if (
            attempt is None
            or _cell(attempt) != cell
            or row["type"] not in EVENT_TYPES
            or not isinstance(row["identity"], str)
            or not row["identity"]
            or row["observer"] not in {"server", "host", "evaluator"}
            or row["observed"] not in {True, False, None}
            or not isinstance(row["limit"], str)
            or not row["limit"]
            or not isinstance(row["rank"], int)
            or row["rank"] < 1
            or not isinstance(row["premise_id"], str)
            or not row["premise_id"]
            or row["support"] not in {"full", "partial", "unsupported", "conflicted", "unavailable"}
        ):
            raise ValueError("event is invalid")
        observed[(row["attempt_id"], row["type"])].append(row)
    # Every stage must be represented for every scored scientific cell. A
    # host that cannot observe delivery records observed=null rather than
    # fabricating a negative observation.
    reference_cells = {cell for cell, _premise in refs}
    if reference_cells - set(selected):
        raise ValueError("every reference cell requires one preregistered scoring attempt")
    for cell in reference_cells:
        selected_attempt = selected.get(cell)
        if selected_attempt is None:
            continue
        required_premises = {
            premise
            for (current, premise), reference in refs.items()
            if current == cell and reference["status"] == "adjudicated" and reference["required"]
        }
        for premise in required_premises:
            missing = {
                stage
                for stage in EVENT_TYPES
                if not any(
                    row["premise_id"] == premise
                    for row in observed[(selected_attempt["attempt_id"], stage)]
                )
            }
            if missing:
                raise ValueError("missing required event stages: " + ", ".join(sorted(missing)))
    adjudicated_refs = {
        key: ref for key, ref in refs.items() if ref["status"] == "adjudicated" and ref["required"]
    }
    eligible = len(adjudicated_refs)
    evidence_by_stage: dict[str, dict[tuple[tuple[str, ...], str], set[str]]] = {
        stage: defaultdict(set) for stage in PASSAGE_STAGES
    }
    stages: dict[str, Any] = {}
    stage_roles: dict[str, Counter[str]] = {stage: Counter() for stage in PASSAGE_STAGES}
    stage_depth: dict[str, dict[str, int]] = {
        stage: {"numerator": 0, "denominator": eligible} for stage in PASSAGE_STAGES
    }
    needed_ranks: list[int] = []
    for stage in EVENT_TYPES:
        rows = [
            (_cell(attempts[attempt_id]), row)
            for (attempt_id, kind), values in observed.items()
            if kind == stage
            for row in values
            if attempts[attempt_id]["selected"]
        ]
        known = [row for _cell_key, row in rows if row["observed"] is not None]
        stages[stage] = {
            "observed": _rate(sum(row["observed"] is True for row in known), len(known)),
            "unknown": len(rows) - len(known),
        }
        if stage not in PASSAGE_STAGES:
            continue
        for cell, row in rows:
            if row["observed"] is True:
                evidence_by_stage[stage][(cell, row["premise_id"])].add(row["identity"])
        complete_at_stage = partial_at_stage = 0
        for key, reference in adjudicated_refs.items():
            found = evidence_by_stage[stage][key]
            options = [set(option) for option in reference["acceptable_evidence_sets"]]
            complete_at_stage += any(option <= found for option in options)
            partial_at_stage += any(option & found for option in options)
            acceptable = set().union(*options)
            relevant_rows = [
                row
                for cell, row in rows
                if (cell, row["premise_id"]) == key
                and row["observed"] is True
                and row["identity"] in acceptable
            ]
            if relevant_rows:
                stage_roles[stage].update(reference["source_roles"])
                stage_depth[stage]["numerator"] += any(
                    row["rank"] <= reference["useful_depth"] for row in relevant_rows
                )
                if stage == "candidate_ranked":
                    needed_ranks.extend(row["rank"] for row in relevant_rows)
        stages[stage]["complete_evidence_sets"] = _rate(complete_at_stage, eligible)
        stages[stage]["partial_evidence_sets"] = _rate(partial_at_stage, eligible)

    premise_predictions: dict[tuple[tuple[str, ...], str], str] = {}
    support_pairs: list[dict[str, Any]] = []
    premise_full = premise_partial = premise_unsupported = premise_conflicted = 0
    contradictions_eligible = contradictions_handled = 0
    cited = evidence_by_stage["evidence_cited"]
    roles: Counter[str] = Counter()
    cited_complete = cited_partial = 0
    for key, reference in adjudicated_refs.items():
        options = [set(option) for option in reference["acceptable_evidence_sets"]]
        found = cited[key]
        is_complete = any(option <= found for option in options)
        is_partial = any(option & found for option in options)
        cited_complete += is_complete
        cited_partial += is_partial
        if is_partial:
            roles.update(reference["source_roles"])
        premise_rows = [
            row
            for row in observed[(selected[key[0]]["attempt_id"], "premise_assessed")]
            if row["premise_id"] == key[1] and row["observed"] is True
        ]
        if len(premise_rows) > 1:
            raise ValueError(
                "premise_assessed must contain one observed classification per premise"
            )
        prediction = premise_rows[0]["support"] if premise_rows else "unavailable"
        premise_predictions[key] = prediction
        premise_full += prediction == "full"
        premise_partial += prediction in {"full", "partial"}
        premise_unsupported += prediction == "unsupported"
        premise_conflicted += prediction == "conflicted"
        restricted = reference.get("restricted", {})
        label = restricted.get("support_label") if isinstance(restricted, dict) else None
        if isinstance(label, str):
            support_pairs.append({"label": label, "prediction": prediction})
        contradiction_ids = set(reference["contradiction_ids"])
        if contradiction_ids:
            contradictions_eligible += 1
            contradictions_handled += contradiction_ids <= found and prediction in {
                "full",
                "conflicted",
            }
    query_fields = set(CELL_FIELDS) | {
        "attempt_id",
        "query_hash",
        "result_ids",
        "source_ids",
        "stop",
    }
    seen: set[tuple[tuple[str, ...], str]] = set()
    prior_results: dict[tuple[str, ...], set[str]] = defaultdict(set)
    prior_sources: dict[tuple[str, ...], set[str]] = defaultdict(set)
    repeats = result_overlap = result_novel = source_overlap = source_novel = no_progress = 0
    selected_query_count = 0
    stops: Counter[str] = Counter()
    for row in fixture["queries"]:
        _closed(row, query_fields, "query")
        cell = _cell(row)
        attempt = attempts.get(row["attempt_id"])
        if (
            attempt is None
            or _cell(attempt) != cell
            or not isinstance(row["query_hash"], str)
            or not SHA.fullmatch(row["query_hash"])
            or not isinstance(row["result_ids"], list)
            or not isinstance(row["source_ids"], list)
            or not all(
                isinstance(item, str) and item for item in row["result_ids"] + row["source_ids"]
            )
            or not isinstance(row["stop"], str)
            or not row["stop"]
        ):
            raise ValueError("query is invalid")
        if not attempt["selected"]:
            continue
        selected_query_count += 1
        results = set(row["result_ids"])
        sources = set(row["source_ids"])
        repeats += (cell, row["query_hash"]) in seen
        result_overlap += len(results & prior_results[cell])
        source_overlap += len(sources & prior_sources[cell])
        new_results = results - prior_results[cell]
        new_sources = sources - prior_sources[cell]
        result_novel += len(new_results)
        source_novel += len(new_sources)
        no_progress += not new_results and not new_sources
        seen.add((cell, row["query_hash"]))
        prior_results[cell].update(results)
        prior_sources[cell].update(sources)
        stops[row["stop"]] += 1

    reference_statuses: dict[tuple[str, ...], set[str]] = defaultdict(set)
    reference_labels: dict[tuple[str, ...], str] = {}
    scientific_truth: dict[tuple[str, ...], str] = {}
    for (cell, _premise), reference in refs.items():
        reference_statuses[cell].add(reference["status"])
        if reference["status"] != "adjudicated":
            continue
        label = reference["restricted"]["answer_label"]
        if cell in reference_labels and reference_labels[cell] != label:
            raise ValueError("adjudicated references disagree on the cell answer label")
        reference_labels[cell] = label
        scientific_cell = _without(cell, 5, 6, 7, 8, 9, 10)
        if scientific_cell in scientific_truth and scientific_truth[scientific_cell] != label:
            raise ValueError("adjudicated truth changes across experimental dimensions")
        scientific_truth[scientific_cell] = label
    eligible_cells = set(reference_labels)
    scored = [
        {**row, "label": reference_labels[cell]}
        for cell, row in selected.items()
        if cell in eligible_cells and row["disposition"] == "assessed"
    ]
    question_rows = [row for row in scored if _scientific_level(row) == "question"]
    domain_rows = [row for row in scored if _scientific_level(row) == "domain"]
    overall_rows = [row for row in scored if _scientific_level(row) == "overall"]
    by_question = {
        key: _confusion([row for row in question_rows if row["question_id"] == key])
        for key in sorted({row["question_id"] for row in question_rows})
    }
    by_domain = {
        key: _confusion([row for row in domain_rows if row["domain_id"] == key])
        for key in sorted({row["domain_id"] for row in domain_rows})
    }
    vectors: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in domain_rows:
        vectors[_without(_cell(row), 3, 4)].append(row)
    full_vectors = []
    for rows in vectors.values():
        vector_by_domain = {row["domain_id"]: row for row in rows}
        if set(vector_by_domain) == set(DOMAIN_IDS):
            full_vectors.append([vector_by_domain[domain_id] for domain_id in DOMAIN_IDS])
    repeated_draws: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in scored:
        repeated_draws[_without(_cell(row), 5, 6)].append(row)
    vector_rows = [
        {
            "label": " | ".join(row["label"] for row in rows),
            "prediction": " | ".join(row["prediction"] for row in rows),
        }
        for rows in full_vectors
    ]

    def baselines(rows: list[dict[str, Any]], *, always: str | None = None) -> dict[str, Any]:
        labels = [row["label"] for row in rows]
        majority = max(Counter(labels), key=lambda key: (Counter(labels)[key], key), default=None)
        result: dict[str, Any] = {
            "majority": {
                "label": majority,
                **_rate(
                    sum(row["label"] == majority for row in rows) if majority is not None else 0,
                    len(rows),
                ),
            }
        }
        if always is not None:
            result["always_low"] = _rate(sum(row["label"] == always for row in rows), len(rows))
        return result

    friction = {
        key: sum(row[key] for row in attempts.values())
        for key in (
            "tool_calls",
            "response_bytes",
            "context_bytes",
            "tokens",
            "latency_ms",
            "cost",
            "repair_count",
        )
    }
    paired: dict[str, Any] = {}
    baseline = (
        "base" if "base" in manifest["interventions"] else sorted(manifest["interventions"])[0]
    )
    cells_by_intervention: dict[str, dict[tuple[str, ...], dict[str, Any]]] = defaultdict(dict)
    for row in scored:
        pair_key = _without(_cell(row), 5, 10)
        cells_by_intervention[row["intervention_id"]][pair_key] = row
    for intervention, rows in cells_by_intervention.items():
        if intervention == baseline:
            continue
        matched = sorted(set(rows) & set(cells_by_intervention[baseline]))
        deltas = [
            int(rows[key]["label"] == rows[key]["prediction"])
            - int(
                cells_by_intervention[baseline][key]["label"]
                == cells_by_intervention[baseline][key]["prediction"]
            )
            for key in matched
        ]
        by_trial: dict[str, list[int]] = defaultdict(list)
        for key, delta in zip(matched, deltas, strict=True):
            by_trial[key[0]].append(delta)
        trial_deltas = [sum(values) / len(values) for values in by_trial.values()]
        paired[intervention] = {
            "baseline": baseline,
            "matched_trial_cells": len(matched),
            "accuracy_delta": _rate(sum(deltas), len(deltas)),
            "trial_clusters": len(trial_deltas),
            "mean_trial_accuracy_delta": _rate(sum(trial_deltas), len(trial_deltas)),
        }
    report = {
        "schema": SCHEMA,
        "fixture_sha256": _hash(fixture),
        "manifest_sha256": _hash(manifest),
        "scientific": {
            "questions": by_question,
            "domains": by_domain,
            "overall": _confusion(overall_rows),
            "exact_vector": {
                "agreement": _rate(
                    sum(row["label"] == row["prediction"] for row in vector_rows),
                    len(vector_rows),
                ),
                **_confusion(vector_rows),
            },
            "baselines": {
                "questions": baselines(question_rows),
                "domains": baselines(domain_rows, always="low"),
                "overall": baselines(overall_rows, always="low"),
            },
            "no_information": {
                "reference": _rate(
                    sum(row["label"] == "no_information" for row in question_rows),
                    len(question_rows),
                ),
                "predicted": _rate(
                    sum(row["prediction"] == "no_information" for row in question_rows),
                    len(question_rows),
                ),
            },
            "workflow_abstention": _rate(
                sum(row["disposition"] != "assessed" for row in selected.values()), len(selected)
            ),
        },
        "coverage": {
            "completion": _rate(
                sum(row["disposition"] == "assessed" for row in selected.values()), len(selected)
            ),
            "scientific_completion": _rate(len(scored), len(eligible_cells)),
            "passage_alternative_complete": _rate(cited_complete, eligible),
            "passage_alternative_partial": _rate(cited_partial, eligible),
            "premise_complete": _rate(premise_full, eligible),
            "premise_partial": _rate(premise_partial, eligible),
            "unsupported_premise": _rate(premise_unsupported, eligible),
            "conflicted_premise": _rate(premise_conflicted, eligible),
            "contradiction_handled": _rate(contradictions_handled, contradictions_eligible),
            "premise_support_confusion": _confusion(support_pairs),
            "stages": stages,
            "source_roles": dict(roles),
            "stage_source_roles": {stage: dict(values) for stage, values in stage_roles.items()},
            "useful_depth": {
                stage: _rate(values["numerator"], values["denominator"])
                for stage, values in stage_depth.items()
            },
        },
        "retrieval": {"best_rank": min(needed_ranks) if needed_ranks else None},
        "queries": {
            "exact_repeats": _rate(repeats, selected_query_count),
            "result_overlap": result_overlap,
            "result_novel": result_novel,
            "source_overlap": source_overlap,
            "source_novel": source_novel,
            "no_progress": no_progress,
            "stops": dict(stops),
        },
        "reliability": {
            "any_correct": _rate(
                sum(
                    any(row["label"] == row["prediction"] for row in rows)
                    for rows in repeated_draws.values()
                ),
                len(repeated_draws),
            ),
            "all_correct": _rate(
                sum(
                    all(row["label"] == row["prediction"] for row in rows)
                    for rows in repeated_draws.values()
                ),
                len(repeated_draws),
            ),
            "draws_per_cell": dict(
                sorted(Counter(len(rows) for rows in repeated_draws.values()).items())
            ),
        },
        "paired_interventions": paired,
        "friction": friction,
        "audit": {
            "attempt_count": len(attempts),
            "false_repairs": sum(row["false_repair"] for row in attempts.values()),
            "dispositions": dict(Counter(row["disposition"] for row in attempts.values())),
            "reference_eligibility": dict(
                Counter(
                    "eligible"
                    if "adjudicated" in statuses
                    else "disputed"
                    if "disputed" in statuses
                    else "unavailable"
                    for statuses in reference_statuses.values()
                )
            )
            | {"missing": sum(cell not in reference_statuses for cell in selected)},
        },
    }
    return privacy_safe_receipt(report)

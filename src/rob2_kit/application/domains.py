import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..logic.evaluator import active_questions, evaluate_domain, evaluate_overall
from ..models import ResponseFramework, canonical_json_bytes
from ..packs import SCIENTIFIC_PACK
from ..workflow_models import DomainDraft
from ._state import (
    _canonical_evidence_records,
    _commit_records,
    _db,
    _ensure,
    _identity,
    _result,
    _root,
    _state,
)
from .contracts import WorkflowConflict
from .evidence import (
    _associated_search_ranks,
    _evidence_catalog,
    _evidence_for_handles,
    _search_continuation,
    _search_receipt,
    main_report_reading_status,
)
from .status import _active_trial_and_domain, _continuation

_DOMAIN_RECOVERABLE_NARRATIVE_TEXT_BUDGET = 12_288


def _main_report_recovery(
    root: Path, state: dict[str, Any], trial_id: str, *, include_budget: bool = False
) -> dict[str, Any] | None:
    batch = state.get("batch")
    trials = batch.get("trials", []) if isinstance(batch, dict) else []
    trial = next(
        (item for item in trials if isinstance(item, dict) and item.get("id") == trial_id), None
    )
    if trial is None:
        return None
    proposal = state.get("proposal")
    payload = proposal.get("payload", {}) if isinstance(proposal, dict) else {}
    scopes = payload.get("main_report_scopes", []) if isinstance(payload, dict) else []
    status = main_report_reading_status(
        root,
        [trial],
        phase="assessment",
        scopes=scopes if isinstance(scopes, list) else None,
    ).get(trial_id, {})
    gaps = status.get("required_ranges", [])
    if not gaps and not (include_budget and status.get("status") == "budget_limited"):
        return None
    candidate_windows = gaps or status.get("unread_ranges", [])
    return {
        "operation": "read_pages",
        "trial_id": trial_id,
        "windows": [
            {key: item[key] for key in ("source_id", "page", "start_line", "end_line")}
            for item in candidate_windows[:20]
        ],
        "window_count": len(candidate_windows),
        "status": status.get("status", "required"),
        "unread_ranges": [
            {key: item[key] for key in ("source_id", "page", "start_line", "end_line")}
            for item in status.get("unread_ranges", [])[:20]
        ],
        "unread_range_count": len(status.get("unread_ranges", [])),
    }


_REGISTRY_FIELD_PATHS = {
    "studyFirstPostDateStruct": "protocolSection.statusModule.studyFirstPostDateStruct",
    "lastUpdatePostDateStruct": "protocolSection.statusModule.lastUpdatePostDateStruct",
    "startDateStruct": "protocolSection.statusModule.startDateStruct",
    "armsInterventionsModule": "protocolSection.armsInterventionsModule",
}


def _registry_navigation(
    root: Path, trial_id: str, sources: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Expose captured JSON leaf paths with exact read-pages recovery windows."""

    registry_sources = {
        item["id"]
        for item in sources
        if isinstance(item, dict)
        and item.get("role") == "registry"
        and isinstance(item.get("id"), str)
    }
    if not registry_sources:
        return {}
    found: dict[str, dict[str, Any]] = {}
    with _db(root, "derivative.sqlite3") as connection:
        for source_id in sorted(registry_sources):
            rows = connection.execute(
                "SELECT page, text FROM pages WHERE source_id=? ORDER BY page",
                (source_id,),
            ).fetchall()
            paths: set[str] = set()
            ranges: dict[tuple[str, int], list[int]] = {}
            for row in rows:
                page = int(row["page"])
                for line_number, line in enumerate(str(row["text"]).splitlines(), 1):
                    for path in _REGISTRY_FIELD_PATHS.values():
                        if line.startswith(path + ".") or line.startswith(path + ":"):
                            paths.add(path)
                            bounds = ranges.setdefault((path, page), [line_number, line_number])
                            bounds[0] = min(bounds[0], line_number)
                            bounds[1] = max(bounds[1], line_number)
                            break
            if paths:
                all_windows = [
                    {
                        "source_id": source_id,
                        "page": page,
                        "start_line": bounds[0],
                        "end_line": bounds[1],
                    }
                    for (path, page), bounds in sorted(ranges.items())
                ]
                windows = tuple(all_windows[:20])
                found[source_id] = {
                    "paths": tuple(sorted(paths)),
                    "recovery": {
                        "operation": "read_pages",
                        "trial_id": trial_id,
                        "windows": windows,
                    },
                    "window_count": len(all_windows),
                }
    return found


def _evidence_text_bytes(item: dict[str, Any]) -> int:
    """Count source-bound Evidence text, not serialized JSON bytes."""

    kind = item.get("kind")
    if kind == "narrative":
        values = (item.get("quote"),)
    elif kind == "figure":
        values = (item.get("transcription"),)
    elif kind == "table":
        values = (
            item.get("title"),
            item.get("scope"),
            item.get("cohort"),
            item.get("row"),
            *(item.get("columns") or ()),
            *(item.get("group_or_category_axes") or ()),
            *(item.get("cells") or ()),
            *(item.get("units") or ()),
            *(item.get("denominators") or ()),
            *(item.get("footnotes") or ()),
        )
    elif kind == "derived":
        values = [item.get("value")]
        values.extend(
            input_item.get("value")
            for input_item in (item.get("inputs") or ())
            if isinstance(input_item, dict)
        )
    else:
        values = ()
    return sum(len(value.encode("utf-8")) for value in values if isinstance(value, str))


def _compact_domain_evidence(context: dict[str, Any]) -> dict[str, Any]:
    """Bound only the model-facing Evidence text; canonical rows stay untouched."""

    # Checkpoint bases historically repeated the complete Evidence quote in a
    # ``source`` field.  The identity and projected Evidence are sufficient;
    # remove the duplicate from this presentation while retaining its byte
    # count in omitted_narrative_text_bytes.
    checkpoint_source_bytes = 0
    answers = context.get("answers")
    if isinstance(answers, list):
        answers = [dict(answer) if isinstance(answer, dict) else answer for answer in answers]
        for answer in answers:
            if not isinstance(answer, dict):
                continue
            bases = answer.get("bases")
            if not isinstance(bases, list):
                continue
            copied_bases = []
            for basis in bases:
                if not isinstance(basis, dict):
                    copied_bases.append(basis)
                    continue
                copied_basis = dict(basis)
                source = copied_basis.pop("source", None)
                if isinstance(source, str):
                    checkpoint_source_bytes += len(source.encode("utf-8"))
                copied_bases.append(copied_basis)
            answer["bases"] = copied_bases
        context["answers"] = answers
    evidence = context.get("evidence")
    if not isinstance(evidence, list):
        return context
    # Allocate the byte budget by priority without reordering Evidence.
    tier = {
        "result": 0,
        "checkpoint": 1,
        "contradiction": 2,
        "explicit_carry_forward": 3,
        "active_domain_candidate": 4,
        "question_candidate": 4,
    }
    indexed = list(enumerate(evidence))
    indexed.sort(key=lambda pair: (tier.get(str(pair[1].get("inclusion_reason")), 5), pair[0]))
    remaining = _DOMAIN_RECOVERABLE_NARRATIVE_TEXT_BUDGET
    recoverable_narrative_bytes = omitted = omitted_count = unrecoverable_inline = 0
    projected: dict[int, dict[str, Any]] = {}
    for index, original in indexed:
        if not isinstance(original, dict):
            continue
        item = dict(original)
        size = _evidence_text_bytes(item)
        kind = item.get("kind")
        has_exact_recovery = (
            kind == "narrative"
            and all(isinstance(item.get(key), int) for key in ("page", "start_line", "end_line"))
            and isinstance(item.get("source_id"), str)
            and isinstance(item.get("trial_id"), str)
        )
        # Visual transcription and derived/table values have no exact existing
        # recovery operation, so preserve them inline even when large.
        include = not has_exact_recovery or size <= remaining
        if include:
            if has_exact_recovery:
                remaining -= size
            if has_exact_recovery:
                recoverable_narrative_bytes += size
            else:
                unrecoverable_inline += size
            if kind == "narrative":
                item["text_status"] = "complete"
        else:
            item["quote"] = None
            item["text_status"] = "omitted"
            item["recovery"] = {
                "operation": "read_pages",
                "trial_id": item["trial_id"],
                "windows": [
                    {
                        "source_id": item["source_id"],
                        "page": item["page"],
                        "start_line": item["start_line"],
                        "end_line": item["end_line"],
                    }
                ],
            }
            omitted += size
            omitted_count += 1
        projected[index] = item
    result = context.get("result")
    if isinstance(result, dict):
        unrecoverable_inline += sum(
            _evidence_text_bytes(item)
            for item in result.get("evidence", [])
            if isinstance(item, dict) and item.get("kind") == "derived"
        )
    omitted += checkpoint_source_bytes
    context["evidence"] = [projected.get(index, item) for index, item in enumerate(evidence)]
    workspace = context.get("evidence_workspace")
    if isinstance(workspace, dict):
        workspace = dict(workspace)
        workspace["selection_policy_version"] = "rob2-kit.domain-projection.v0.6"
        workspace["recoverable_narrative_text_budget"] = _DOMAIN_RECOVERABLE_NARRATIVE_TEXT_BUDGET
        workspace["recoverable_narrative_text_bytes"] = recoverable_narrative_bytes
        workspace["omitted_narrative_text_bytes"] = omitted
        workspace["omitted_narrative_text_count"] = omitted_count
        workspace["unrecoverable_inline_text_bytes"] = unrecoverable_inline
        context["evidence_workspace"] = workspace
    return context


_DOMAIN_GUIDANCE = (
    "For each active question, review the inspected passages against its exact proposition "
    "and check material contradictions. Reuse adequate Evidence. When a premise remains "
    "unresolved, use bounded discovery across relevant Sources, including a protocol or SAP "
    "when available. Read positive hits before using them. A limitation requires an exact "
    "Trial-scoped, untruncated search receipt. Absence requires a scoped untruncated "
    "no-hit receipt.",
    "For each selected Evidence basis, cite items containing the complete exact "
    "premises that support the active question. One passage may support several facts; combine "
    "separate passages when the answer depends on separate facts, and keep their boundaries "
    "distinct.",
    "When inference, conflict, or uncertainty connects Evidence to an answer, include a concise "
    "question-specific justification. State what the cited "
    "passages establish, what remains unresolved or conflicting, and why the selected answer "
    "follows. This is a scientific explanation, not a reasoning transcript or a duplicate ledger.",
    "A definitive yes or no needs direct_support, indirect_support, or contradiction; "
    "a limitation or absence alone supports uncertainty, not a definitive answer.",
    "A relationship kind describes how the premise relates to the answer; it never adds "
    "an explanation or scientific fact.",
    "You make the scientific judgment from reported facts and trial circumstances. The server "
    "checks structure and Evidence identity. State the inference connecting source facts to "
    "the answer and preserve unresolved facts under the question's uncertainty rule.",
)
_DOMAIN_TRAPS = (
    "A relationship label never permits a broader clause than the selected source supports.",
    "A planned method does not prove conduct; a time origin or analysis population does "
    "not prove complete follow-up or equal assessment.",
    "An endpoint label or definition does not prove objectivity, blinding, "
    "prespecification, or no alternative analyses.",
    "A treatment assignment or visibly different intervention does not by itself prove "
    "that participants or personnel knew the assignment.",
    "Different treatment or visit schedules do not by themselves prove that outcome "
    "measurement differed between groups.",
    "One endpoint definition does not prove that there were no multiple eligible "
    "measurements or analyses.",
    "Stratification does not prove allocation concealment.",
)

_RESPONSE_FRAMEWORK = ResponseFramework(
    version="22 August 2019",
    source_locator="Full guidance p. 3, sections 1.1 and 1.1.1",
    response_options=("yes", "probably_yes", "probably_no", "no", "no_information"),
    firm_evidence_rule=(
        "The definitive versions (‘Yes’ and ‘No’) would typically imply that firm evidence "
        "is available in relation to the signalling question."
    ),
    probable_judgment_rule=(
        "The ‘Probably’ versions would typically imply that a judgement has been made. "
        "‘Yes’ and ‘Probably yes’ have the same implications for risk of bias, as do ‘No’ "
        "and ‘Probably no’."
    ),
    no_information_rule=(
        "Use ‘No information’ only when both (i) insufficient details are reported to permit "
        "a response of ‘Probably yes’ or ‘Probably no’, and (ii) in the absence of these "
        "details it would be unreasonable to respond ‘Probably yes’ or ‘Probably no’ in the "
        "circumstances of the trial."
    ),
    independence_rule=(
        "Signalling questions should be answered independently: the answer to one question "
        "should not affect answers to other questions in the same or other domains other than "
        "through determining which subsequent questions are answered."
    ),
    quotation_rule=(
        "Brief direct quotations from the text of the study report should be used whenever "
        "possible to support the answer."
    ),
)


_OPTION_SEMANTICS_VERSION = "rob2-kit.answer-option.v0.6"


def _answer_option(question: Any, answer: Any) -> dict[str, Any]:
    """Build one exact, self-describing option from the current scientific pack."""
    value = answer.value
    if value in {"yes", "no"}:
        proposition, certainty = ("true" if value == "yes" else "false"), "certain"
    elif value in {"probably_yes", "probably_no"}:
        proposition, certainty = ("true" if value == "probably_yes" else "false"), "probable"
    else:
        proposition, certainty = "unknown", "unknown"
    decision_table_value = (
        "yes"
        if value in {"yes", "probably_yes"}
        else "no"
        if value in {"no", "probably_no"}
        else "no_information"
    )
    anchor_answer = (
        next(
            candidate
            for candidate in question.allowed_answers
            if candidate.value == ("yes" if value == "probably_yes" else "no")
        )
        if value in {"probably_yes", "probably_no"}
        else answer
    )
    anchor = (
        question.guidance.operational.no_information_rule
        if value == "no_information"
        else next(
            item.text
            for item in question.guidance.operational.answer_anchors
            if item.answer == anchor_answer
        )
    )
    if certainty == "probable":
        anchor = "Probable judgment from the reported facts and trial circumstances: " + anchor
    elif value == "no_information":
        anchor = (
            "Use only when neither probable answer is reasonable from the available facts "
            "and trial circumstances. " + anchor
        )
    dependents = tuple(
        candidate.id
        for candidate in SCIENTIFIC_PACK.questions
        if candidate.domain_id == question.domain_id
        and candidate.activation.kind == "rule"
        and any(
            predicate.question_id == question.id and answer in predicate.accepted_answers
            for predicate in candidate.activation.predicates
        )
    )
    consequence = (
        f"The Domain decision table treats this as {decision_table_value}. "
        + (
            "It activates dependent questions: " + ", ".join(dependents) + "."
            if dependents
            else "It activates no dependent questions."
        )
        + " The Domain judgment is derived only from the complete active answer path."
    )
    payload = {
        "semantics_version": _OPTION_SEMANTICS_VERSION,
        "pack_version": SCIENTIFIC_PACK.version,
        "question_id": question.id,
        "question_wording": question.wording,
        "official_answer": value,
        "anchor": anchor,
        "proposition": proposition,
        "certainty": certainty,
        "decision_table_value": decision_table_value,
        "activates": dependents,
    }
    return {
        "id": "opt_" + _identity(payload).removeprefix("sha256:")[:24],
        "official_answer": value,
        "proposition": proposition,
        "certainty": certainty,
        "decision_table_value": decision_table_value,
        "meaning": (
            "The exact question proposition is unknown."
            if certainty == "unknown"
            else (
                "The exact question proposition is "
                f"{('probably ' if certainty == 'probable' else '')}{proposition}."
            )
        ),
        "activates": dependents,
        "anchor": anchor,
        "consequence": consequence,
    }


def _comparison_cards(
    domain_id: str,
    result: dict[str, Any],
    catalog: dict[str, dict[str, Any]],
    checkpoint_answers: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    preview_missing_data: list[dict[str, Any]] | None = None,
    registry_navigation: dict[str, dict[str, Any]] | None = None,
    registry_capture: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return a small deterministic read projection for D2/D3/D5.

    The slots deliberately stay descriptive. The server aligns known source
    coordinates and compatible counts, but never fills a causal or bias
    conclusion from prose.
    """
    question_by_domain = {
        "domain:deviations": "sq:deviations:context-deviations",
        "domain:missing": "sq:missing:data-available",
        "domain:selection": "sq:selection:prespecified-analysis",
    }
    names = {
        "domain:deviations": (
            "intended_intervention",
            "observed_conduct",
            "trial_context_cause",
            "protocol_consistency",
            "outcome_effect",
            "group_balance",
        ),
        "domain:missing": (
            "approved_outcome",
            "randomized",
            "observed",
            "follow_up_availability",
            "censoring",
            "missingness_reason",
        ),
        "domain:selection": (
            "reported_result",
            "analysis_plan",
            "unblinded_access",
            "amendment",
            "correspondence",
        ),
    }
    if domain_id not in question_by_domain:
        return []
    refs = []
    for item in catalog.values():
        if not isinstance(item, dict) or item.get("kind") != "narrative":
            continue
        if not all(
            isinstance(item.get(key), (str, int)) for key in ("handle", "source_id", "page")
        ):
            continue
        refs.append(
            {
                "handle": item["handle"],
                "source_id": item["source_id"],
                "page": item["page"],
                "start_line": item.get("start_line", 1),
                "end_line": item.get("end_line", item.get("start_line", 1)),
            }
        )
    refs.sort(
        key=lambda value: (value["source_id"], value["page"], value["start_line"], value["handle"])
    )
    refs_by_identity = {
        item["identity"]: ref
        for item in catalog.values()
        if isinstance(item, dict) and isinstance(item.get("identity"), str)
        for ref in refs
        if ref["handle"] == item.get("handle")
    }
    result_evidence = result.get("evidence", [])

    def bound_refs(*prefixes: str) -> list[dict[str, Any]]:
        handles: list[str] = []
        for binding in result.get("bindings", []):
            if not isinstance(binding, dict):
                continue
            field = binding.get("field")
            path = field.get("path") if isinstance(field, dict) else None
            index = binding.get("evidence_index")
            if (
                not isinstance(path, str)
                or not any(path == prefix or path.startswith(prefix + "/") for prefix in prefixes)
                or not isinstance(index, int)
                or isinstance(index, bool)
                or not isinstance(result_evidence, list)
                or not 0 <= index < len(result_evidence)
            ):
                continue
            evidence = result_evidence[index]
            handle = evidence.get("handle") if isinstance(evidence, dict) else None
            if isinstance(handle, str) and handle not in handles:
                handles.append(handle)
        return [ref for handle in handles for ref in refs if ref["handle"] == handle]

    source_by_id = {
        item["id"]: item
        for item in sources
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    source_ids = {item["source_id"] for item in refs}
    if domain_id == "domain:selection":
        source_ids.update(
            item["id"]
            for item in sources
            if isinstance(item, dict)
            and isinstance(item.get("id"), str)
            and item.get("role") in {"registry", "protocol", "sap"}
        )
    passage_groups = []
    for source_id in sorted(source_ids):
        source = source_by_id.get(source_id, {})
        passages = []
        seen_ranges: set[tuple[int, int, int]] = set()
        for item in (value for value in refs if value["source_id"] == source_id):
            coordinate = (item["page"], item["start_line"], item["end_line"])
            if coordinate in seen_ranges:
                continue
            seen_ranges.add(coordinate)
            passages.append(item)
        passage_groups.append(
            {
                "source_id": source_id,
                "source_role": source.get("role", "other"),
                "source_label": source.get("label", source_id),
                "logical_path": source.get("logical_path", source_id),
                "page_count": source.get("page_count", 1),
                "sha256": source.get("sha256"),
                "projection_hash": source.get("projection_hash"),
                "source_origin": source.get("origin", "local_dossier"),
                "registry_url": (
                    registry_capture.get("url")
                    if source.get("origin") == "registry"
                    and isinstance(registry_capture, dict)
                    and registry_capture.get("kind") == "matched"
                    else None
                ),
                "registry_retrieved_at": (
                    registry_capture.get("retrieved_at")
                    if source.get("origin") == "registry"
                    and isinstance(registry_capture, dict)
                    and registry_capture.get("kind") == "matched"
                    else None
                ),
                "registry_field_paths": tuple(
                    (registry_navigation or {}).get(source_id, {}).get("paths", ())
                ),
                "registry_recovery": (registry_navigation or {}).get(source_id, {}).get("recovery"),
                "registry_window_count": (registry_navigation or {})
                .get(source_id, {})
                .get("window_count", 0),
                "passages": passages,
            }
        )

    target = result.get("target", {})
    reported = result.get("reported", {})
    slots = [
        {"name": name, "status": "unknown", "value": None, "passages": []}
        for name in names[domain_id]
    ]

    def support(name: str, value: str, passages: list[dict[str, Any]]) -> None:
        slot = next(item for item in slots if item["name"] == name)
        slot.update(status="supported", value=value, passages=passages)

    if domain_id == "domain:deviations":
        groups = target.get("comparison_groups", [])
        if isinstance(groups, list) and groups:
            support(
                "intended_intervention",
                "; ".join(
                    f"{item['id']}: {item['assignment']}"
                    for item in groups
                    if isinstance(item, dict)
                    and isinstance(item.get("id"), str)
                    and isinstance(item.get("assignment"), str)
                ),
                bound_refs("/target/comparison_groups"),
            )
    elif domain_id == "domain:missing":
        timing = target.get("time_point_or_window", {})
        timing_description = timing.get("description") if isinstance(timing, dict) else None
        outcome_parts = [
            target.get("outcome_definition"),
            timing_description,
            target.get("intended_analysis_population"),
        ]
        scope = " | ".join(item for item in outcome_parts if isinstance(item, str) and item)
        if scope:
            support(
                "approved_outcome",
                scope,
                bound_refs(
                    "/target/outcome_definition",
                    "/target/measurement",
                    "/target/time_point_or_window",
                    "/target/intended_analysis_population",
                ),
            )
    else:
        endpoint = reported.get("endpoint", {})
        endpoint_name = endpoint.get("name") if isinstance(endpoint, dict) else None
        result_summary = " | ".join(
            item
            for item in (reported.get("form"), endpoint_name, reported.get("effect_measure"))
            if isinstance(item, str) and item
        )
        if result_summary:
            support("reported_result", result_summary, bound_refs("/reported"))

    missing_data = None
    if domain_id == "domain:missing":
        answer = next(
            (
                item
                for item in checkpoint_answers
                if item.get("question_id") == "sq:missing:data-available"
            ),
            None,
        )
        if preview_missing_data is not None:
            missing_data = reconcile_missing_data(preview_missing_data)
            answer = {"missing_data": missing_data}
        if isinstance(answer, dict) and isinstance(answer.get("missing_data"), dict):
            missing_data = answer["missing_data"]
            for field in ("randomized", "observed"):
                rows = [
                    row
                    for row in missing_data.get("rows", [])
                    if isinstance(row, dict) and isinstance(row.get(field), int)
                ]
                if not rows:
                    continue
                field_conflicted = any(
                    len(
                        {
                            report.get(field)
                            for report in conflict.get("reports", [])
                            if isinstance(report, dict)
                        }
                    )
                    > 1
                    for conflict in missing_data.get("conflicts", [])
                    if isinstance(conflict, dict)
                )
                slot = next(item for item in slots if item["name"] == field)
                slot["status"] = "conflicted" if field_conflicted else "supported"
                slot["value"] = "; ".join(
                    f"{row['scope']['arm']} | {row['scope']['population']} | "
                    f"{row['scope']['unit']} | {row['scope']['time_point']}: {row[field]}"
                    for row in rows
                )
                slot["passages"] = [
                    {
                        key: evidence[key]
                        for key in ("handle", "source_id", "page", "start_line", "end_line")
                    }
                    for row in rows
                    for identity in row.get("basis", [])
                    for evidence in (refs_by_identity.get(identity),)
                    if isinstance(evidence, dict)
                    and all(
                        key in evidence
                        for key in ("handle", "source_id", "page", "start_line", "end_line")
                    )
                ]

    card_id = _identity(
        {
            "version": "rob2-kit.comparison-card.v0.5",
            "domain_id": domain_id,
            "question_id": question_by_domain[domain_id],
            "result": _identity(result),
        }
    )
    return [
        {
            "card_id": card_id,
            "question_id": question_by_domain[domain_id],
            "result_identity": _identity(result),
            "passage_groups": passage_groups,
            "slots": slots,
            "missing_data": missing_data,
            "prompt": (
                "Use the exact passages and server-known scope above. Classify only the remaining "
                "scientific propositions; do not infer causation, follow-up availability, "
                "informative censoring, or plan correspondence from Source role or wording alone."
            ),
        }
    ]


def reconcile_missing_data(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Reconcile comparable participant-flow reports without guessing scope.

    This bounded clerical helper is deliberately not a scientific classifier.
    A difference is calculated only for rows sharing arm, population, unit,
    and time-point scope. Unknown values, imputation, overlapping exclusions,
    and conflicting reports remain visible for the host to interpret.
    """
    normalized: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    seen: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        scope = tuple(row.get(key) for key in ("arm", "population", "unit", "time_point"))
        randomized = row.get("randomized")
        observed = row.get("observed")
        item = {
            "scope": {
                "arm": scope[0],
                "population": scope[1],
                "unit": scope[2],
                "time_point": scope[3],
            },
            "randomized": randomized,
            "observed": observed,
            "analyzed": row.get("analyzed"),
            "imputed": row.get("imputed"),
            "exclusions": (
                list(row.get("exclusions", []))
                if isinstance(row.get("exclusions", []), list)
                else []
            ),
            "basis": list(row.get("basis", [])) if isinstance(row.get("basis", []), list) else [],
        }
        key = scope
        prior = seen.get(key)
        compared_fields = ("randomized", "observed", "analyzed", "imputed", "exclusions")
        if prior is not None and tuple(prior[field] for field in compared_fields) != tuple(
            item[field] for field in compared_fields
        ):
            conflicts.append({"scope": item["scope"], "reports": [prior, item]})
        else:
            seen[key] = item
        if (
            isinstance(randomized, int)
            and not isinstance(randomized, bool)
            and isinstance(observed, int)
            and not isinstance(observed, bool)
            and randomized >= observed >= 0
        ):
            item["missing"] = randomized - observed
            item["missing_fraction"] = (randomized - observed) / randomized if randomized else 0.0
        else:
            item["missing"] = None
            item["missing_fraction"] = None
        normalized.append(item)
    return {"rows": normalized, "conflicts": conflicts}


def _canonical_preview_rows(
    rows: list[dict[str, Any]], catalog: dict[str, dict[str, Any]], trial_id: str
) -> list[dict[str, Any]]:
    """Resolve preview Evidence handles to same-Trial canonical identities."""

    if not rows:
        return []
    by_handle = {
        item["handle"]: item
        for item in catalog.values()
        if isinstance(item, dict) and isinstance(item.get("handle"), str)
    }
    normalized: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"missing_data preview row {index} is invalid")
        basis = row.get("basis")
        if not isinstance(basis, list) or not basis:
            raise ValueError(f"missing_data preview row {index} requires Evidence basis")
        identities: list[str] = []
        for reference in basis:
            selected = by_handle.get(reference)
            if not isinstance(selected, dict) or selected.get("trial_id") != trial_id:
                raise ValueError(
                    f"missing_data preview row {index} has unknown or cross-Trial Evidence"
                )
            identities.append(str(selected["identity"]))
        normalized.append({**row, "basis": identities})
    return normalized


def _repairs(error: ValidationError) -> list[dict[str, Any]]:
    return [
        {
            "path": "/" + "/".join(map(str, item["loc"])),
            "code": "invalid_draft",
            "detail": item["msg"],
        }
        for item in error.errors()
    ]


def _repair(path: str, code: str, detail: str) -> dict[str, str]:
    return {"path": path, "code": code, "detail": detail}


def _duplicate_repairs(values: list[str], path: str, code: str, label: str) -> list[dict[str, str]]:
    seen: dict[str, int] = {}
    repairs: list[dict[str, str]] = []
    for index, value in enumerate(values):
        first = seen.get(value)
        if first is None:
            seen[value] = index
            continue
        repairs.append(
            _repair(
                f"{path}/{index}",
                code,
                f"{label} '{value}' duplicates item {first}; keep one entry.",
            )
        )
    return repairs


def _ids(values: list[str]) -> str:
    return ", ".join(values) if values else "none"


def _domain_identity(record: dict[str, Any]) -> str:
    fields = (
        "trial_id",
        "domain_id",
        "answers",
        "supersedes",
        "revision_basis",
        "search_accounts",
        "active_questions",
        "inactive_questions",
        "judgment",
        "trace",
    )
    return _identity({key: record[key] for key in fields})


def _canonical_observed_at(root: Path, identity: str) -> str | None:
    """Reuse immutable metadata when the same semantic checkpoint is replayed.

    ``observed_at`` is provenance metadata, not part of a Domain's semantic
    identity.  A discarded run can therefore legitimately produce the same
    checkpoint identity.  Reusing the existing canonical payload keeps the
    content-addressed ledger exact instead of generating a different payload
    under an already occupied identity.
    """

    with _db(root, "canonical.sqlite3") as connection:
        row = connection.execute(
            "SELECT payload FROM canonical_records WHERE identity=? AND kind='domain'",
            (identity,),
        ).fetchone()
    if row is None:
        return None
    try:
        prior = json.loads(bytes(row[0]))
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("canonical Domain checkpoint is corrupt") from error
    observed_at = prior.get("observed_at") if isinstance(prior, dict) else None
    if not isinstance(observed_at, str) or not observed_at.strip():
        raise ValueError("canonical Domain checkpoint metadata is corrupt")
    return observed_at


def save_domain_judgment(
    workspace: str | Path, draft: dict[str, Any] | DomainDraft
) -> dict[str, Any]:
    """Validate and atomically persist one structured Domain checkpoint."""
    root = _root(workspace)
    _ensure(root)
    state = _state(root)
    try:
        parsed = draft if isinstance(draft, DomainDraft) else DomainDraft.model_validate(draft)
    except ValidationError as error:
        return _result("repair", state, repairs=_repairs(error))
    if state.get("phase") not in {"assessment", "ready_to_finalize"}:
        raise ValueError("Domain work is not active")
    is_revision = parsed.supersedes is not None
    records = state.get("domain_records") or {}
    existing_domain = f"{parsed.trial_id}:{parsed.domain_id}" in records
    trial_has_checkpoint = any(
        isinstance(key, str) and key.startswith(f"{parsed.trial_id}:") for key in records
    )
    disposition = state.get("trial_dispositions", {}).get(parsed.trial_id)
    if disposition == "assessed" and (is_revision or not existing_domain):
        raise ValueError("Trial AssessmentSnapshot is final; Domain revisions are closed")
    active_trial, active_domain = _active_trial_and_domain(state)
    if not existing_domain and parsed.trial_id != active_trial:
        return _result(
            "repair",
            state,
            repairs=[
                _repair(
                    "/trial_id",
                    "trial_out_of_sequence",
                    f"complete Trial '{active_trial}' before Trial '{parsed.trial_id}'",
                )
            ],
        )
    if not existing_domain and parsed.domain_id != active_domain:
        return _result(
            "repair",
            state,
            repairs=[
                _repair(
                    "/domain_id",
                    "domain_out_of_sequence",
                    f"complete Domain '{active_domain}' before Domain '{parsed.domain_id}'",
                )
            ],
        )
    if disposition not in {"pending", "assessed"}:
        raise ValueError("Trial is not available for Domain assessment")
    if state.get("phase") == "assessment" and not trial_has_checkpoint:
        recovery = _main_report_recovery(root, state, parsed.trial_id)
        if recovery is not None:
            return _result(
                "repair",
                state,
                repairs=[
                    {
                        "path": "/answers",
                        "code": "post_approval_main_report_reading_required",
                        "detail": (
                            "Finish the post-approval bounded text pass before saving this Trial's "
                            "first Domain. Call get_domain_context to receive the typed "
                            "reading_recovery windows, use them with read_pages, then retry."
                        ),
                    }
                ],
            )
    if parsed.domain_id not in {item.id for item in SCIENTIFIC_PACK.domains}:
        raise ValueError("unknown Domain")

    questions_by_id = {
        question.id: question
        for question in SCIENTIFIC_PACK.questions
        if question.domain_id == parsed.domain_id
    }
    option_cards = {
        question.id: tuple(_answer_option(question, answer) for answer in question.allowed_answers)
        for question in questions_by_id.values()
    }
    option_tables = {
        question_id: {option["id"]: option["official_answer"] for option in options}
        for question_id, options in option_cards.items()
    }
    allowed = {question_id: set(options.values()) for question_id, options in option_tables.items()}
    answer_items = list(parsed.answers)
    items_by_question: dict[str, list[tuple[int, Any]]] = {}
    for index, item in enumerate(answer_items):
        items_by_question.setdefault(item.question_id, []).append((index, item))
    repairs: list[dict[str, Any]] = []
    for question_id, items in items_by_question.items():
        if question_id in questions_by_id:
            continue
        for index, _item in items:
            repairs.append(
                _repair(
                    f"/answers/{index}/question_id",
                    "invalid_answer_question",
                    f"question '{question_id}' is not in Domain '{parsed.domain_id}'.",
                )
            )

    answers: dict[str, str] = {}
    active: list[str] = []
    processed: set[str] = set()
    while True:
        active = [
            question_id for question_id in active_questions(answers) if question_id in allowed
        ]
        pending = [question_id for question_id in active if question_id not in processed]
        if not pending:
            break
        for question_id in pending:
            processed.add(question_id)
            items = items_by_question.get(question_id, [])
            if len(items) > 1:
                repairs.append(
                    _repair(
                        "/answers",
                        "duplicate_answer",
                        f"answer question '{question_id}' occurs {len(items)} times.",
                    )
                )
            if not items:
                continue
            index, item = items[0]
            resolved = option_tables[question_id].get(item.option_id)
            if resolved is None:
                permitted = "; ".join(
                    f"{option['id']}={option['official_answer']} ({option['meaning']})"
                    for option in option_cards[question_id]
                )
                repairs.append(
                    _repair(
                        f"/answers/{index}/option_id",
                        "invalid_answer_option",
                        f"option '{item.option_id}' is not current for question '{question_id}'. "
                        f"Use one current card option: {permitted}",
                    )
                )
                continue
            answers[question_id] = resolved
    active = [question_id for question_id in active_questions(answers) if question_id in allowed]
    missing_active = [item for item in active if item not in answers]
    if missing_active:
        repairs.append(
            _repair(
                "/answers",
                "answers_must_match_active_questions",
                "active IDs: "
                f"[{_ids(active)}]; missing active IDs: [{_ids(missing_active)}]. "
                "Supplied inactive branch answers are ignored.",
            )
        )
    active_answer_items = [
        items_by_question[question_id][0] for question_id in active if question_id in answers
    ]

    proposal_catalog = {
        key: value
        for key, value in (state.get("proposal") or {}).get("evidence", {}).items()
        if isinstance(value, dict) and value.get("trial_id") == parsed.trial_id
    }
    referenced_handles: set[str] = set()
    for _, answer in active_answer_items:
        for basis in answer.bases:
            evidence_handle = getattr(basis, "evidence", None)
            if isinstance(evidence_handle, str):
                referenced_handles.add(evidence_handle)
        for row in answer.missing_data or ():
            referenced_handles.update(row.basis)
    if parsed.revision_basis is not None and parsed.revision_basis.kind == "new_evidence":
        referenced_handles.add(parsed.revision_basis.evidence)
    catalog = dict(proposal_catalog)
    missing_handles = {
        handle
        for handle in referenced_handles
        if not any(item.get("handle") == handle for item in catalog.values())
    }
    for handle in sorted(missing_handles):
        try:
            catalog.update(_evidence_for_handles(root, {handle}, parsed.trial_id))
        except ValueError:
            # The exact answer/revision path below reports every unresolved
            # handle without discarding independent option or basis defects.
            continue
    catalog_by_handle = {
        item["handle"]: item for item in catalog.values() if isinstance(item, dict)
    }
    canonical_answers: list[dict[str, Any]] = []
    search_accounts: dict[str, dict[str, Any]] = {}
    for answer_index, answer_item in active_answer_items:
        answer = answer_item.model_dump(mode="json", exclude_none=True)
        # Canonical checkpoints retain the standard official RoB code. The
        # compact option identity is a transport selection, not a second
        # scientific field in the artifact.
        answer.pop("option_id", None)
        answer["answer"] = answers[answer_item.question_id]
        if answer_item.missing_data is not None:
            # Keep the caller's typed rows small and source-oriented, while
            # persisting one deterministic clerical reconciliation that can
            # be replayed by the bundle verifier.
            answer_evidence: list[str] = []
            for basis in answer_item.bases:
                evidence_handle = getattr(basis, "evidence", None)
                if isinstance(evidence_handle, str):
                    answer_evidence.append(evidence_handle)
            missing_data_rows: list[dict[str, Any]] = []
            for row_index, row_model in enumerate(answer_item.missing_data):
                row = row_model.model_dump(mode="json", exclude_none=True)
                handles = list(dict.fromkeys(row["basis"] or answer_evidence))
                resolved: list[str] = []
                for handle in handles:
                    evidence = catalog_by_handle.get(handle) or catalog.get(handle)
                    if evidence is None or evidence.get("trial_id") != parsed.trial_id:
                        repairs.append(
                            _repair(
                                f"/answers/{answer_index}/missing_data/{row_index}/basis",
                                "invalid_evidence",
                                f"Evidence '{handle}' does not resolve to captured evidence "
                                f"for Trial '{parsed.trial_id}'.",
                            )
                        )
                        continue
                    resolved.append(evidence["identity"])
                if not resolved:
                    repairs.append(
                        _repair(
                            f"/answers/{answer_index}/missing_data/{row_index}/basis",
                            "missing_data_basis_required",
                            "each participant-flow row needs Evidence; attach it to the row "
                            "or to the containing answer.",
                        )
                    )
                row["basis"] = resolved
                missing_data_rows.append(row)
            answer["missing_data"] = reconcile_missing_data(missing_data_rows)
        bases: list[dict[str, Any]] = []
        direct_basis = False
        uncertainty_basis = False
        seen_basis: set[bytes] = set()
        for basis_index, basis_model in enumerate(answer_item.bases):
            basis = basis_model.model_dump(mode="json", exclude_none=True)
            path = f"/answers/{answer_index}/bases/{basis_index}"
            if basis["kind"] == "limitation":
                try:
                    receipt = _search_receipt(root, basis["search_receipt"])
                    if receipt.get("trial_id") != parsed.trial_id:
                        raise ValueError("search receipt is outside the Trial")
                    if receipt.get("truncated") is not False:
                        raise ValueError(
                            "limitation requires a non-truncated search; refine the search "
                            "before using its receipt"
                        )
                    uncertainty_basis = True
                    basis["search_receipt"] = receipt["identity"]
                    search_accounts[receipt["identity"]] = receipt
                except (KeyError, ValueError) as error:
                    repairs.append(
                        _repair(
                            f"{path}/search_receipt",
                            "invalid_search_receipt",
                            f"question '{answer_item.question_id}' has an invalid search receipt "
                            f"for Trial '{parsed.trial_id}': {error}. Attach the exact "
                            "search_receipt handle returned by the scoped search for this "
                            "question; do not reuse a stale or mismatched receipt.",
                        )
                    )
            elif basis["kind"] == "absence":
                try:
                    receipt = _search_receipt(root, basis["search_receipt"])
                    if receipt.get("trial_id") != parsed.trial_id:
                        raise ValueError("search receipt is outside the Trial")
                    if (
                        receipt.get("truncated") is not False
                        or receipt.get("total_matches") != 0
                        or receipt.get("condition") != "no_hits"
                    ):
                        raise ValueError(
                            "absence requires an untruncated no-hit search; refine the search "
                            "and confirm total_matches=0 before using it"
                        )
                    uncertainty_basis = True
                    # Keep the disposable handle at the MCP boundary only.
                    # Checkpoints and their identities refer to the validated
                    # receipt content, so later finalization and verification
                    # do not depend on a navigation token.
                    basis["search_receipt"] = receipt["identity"]
                    search_accounts[receipt["identity"]] = receipt
                except (KeyError, ValueError) as error:
                    repairs.append(
                        _repair(
                            f"{path}/search_receipt",
                            "invalid_search_receipt",
                            f"question '{answer_item.question_id}' has an invalid search receipt "
                            f"for Trial '{parsed.trial_id}': {error}. Attach the exact "
                            "search_receipt handle returned by the scoped search for this "
                            "question; do not reuse a stale or mismatched receipt.",
                        )
                    )
            else:
                if basis["kind"] in {"direct_support", "indirect_support", "contradiction"}:
                    direct_basis = True
                elif basis["kind"] in {"context", "inference"}:
                    uncertainty_basis = True
                evidence = catalog_by_handle.get(basis["evidence"]) or catalog.get(
                    basis["evidence"]
                )
                if evidence is None or evidence.get("trial_id") != parsed.trial_id:
                    repairs.append(
                        _repair(
                            f"{path}/evidence",
                            "invalid_evidence",
                            f"Evidence '{basis['evidence']}' does not resolve to captured evidence "
                            f"for Trial '{parsed.trial_id}'.",
                        )
                    )
                else:
                    basis["evidence"] = evidence["identity"]
                    material = str(evidence.get("quote", evidence.get("transcription", "")))
                    basis["source"] = material
            key = canonical_json_bytes(basis)
            if key in seen_basis:
                repairs.append(
                    _repair(
                        path,
                        "duplicate_answer_basis",
                        "each answer basis must be unique within its question response.",
                    )
                )
            seen_basis.add(key)
            bases.append(basis)
        if answer["answer"] in {"yes", "no"} and not direct_basis:
            repairs.append(
                _repair(
                    f"/answers/{answer_index}/bases",
                    "answer_requires_direct_basis",
                    f"question '{answer_item.question_id}' has definitive answer "
                    f"'{answer['answer']}', which needs a direct, indirect, or contradictory "
                    "Evidence basis; use probably_yes/probably_no or no_information when the "
                    "question card allows it, with a limitation, valid scoped no-hit receipt, "
                    "or exact context/inference premise for uncertainty.",
                )
            )
        elif answer["answer"] in {"probably_yes", "probably_no"} and not (
            direct_basis or uncertainty_basis
        ):
            repairs.append(
                _repair(
                    f"/answers/{answer_index}/bases",
                    "answer_requires_uncertainty_basis",
                    "a probable answer needs direct evidence, a limitation, a valid scoped no-hit "
                    "receipt, or an exact context/inference premise; use no_information when "
                    "the question card allows it.",
                )
            )
        answer["bases"] = bases
        canonical_answers.append(answer)
    if repairs:
        return _result("repair", state, repairs=repairs)

    canonical_answer_values = {
        item.question_id: answers[item.question_id] for _, item in active_answer_items
    }
    evaluation = evaluate_domain(parsed.domain_id, canonical_answer_values)
    existing_rows = state.get("domain_records", {})
    key = f"{parsed.trial_id}:{parsed.domain_id}"
    existing_record = existing_rows.get(key)
    if existing_record is None and (
        parsed.supersedes is not None or parsed.revision_basis is not None
    ):
        return _result(
            "condition",
            state,
            code="domain_initial_checkpoint_cannot_have_revision",
            detail=(
                "an initial Domain checkpoint must omit supersedes and revision_basis; "
                "correction reasons apply only when replacing the exact current checkpoint"
            ),
        )
    revision_basis = (
        parsed.revision_basis.model_dump(mode="json") if parsed.revision_basis is not None else None
    )
    # Evidence handles are disposable navigation identities.  Canonicalize a
    # revision basis before constructing the candidate checkpoint identity so
    # a retry of a successful new-evidence revision compares equal to the
    # committed checkpoint even when the caller repeats the handle form.
    if revision_basis is not None and revision_basis["kind"] == "new_evidence":
        basis_evidence = catalog_by_handle.get(revision_basis["evidence"]) or catalog.get(
            revision_basis["evidence"]
        )
        if basis_evidence is not None and basis_evidence.get("trial_id") == parsed.trial_id:
            revision_basis["evidence"] = basis_evidence["identity"]
    if existing_record is not None and not isinstance(existing_record, dict):
        raise ValueError("Domain checkpoint ledger is corrupt")
    existing_judgments = {
        domain.id: existing_rows[f"{parsed.trial_id}:{domain.id}"]["judgment"]
        for domain in SCIENTIFIC_PACK.domains
        if f"{parsed.trial_id}:{domain.id}" in existing_rows
    }
    proposed_judgments = {**existing_judgments, parsed.domain_id: evaluation.judgment.value}
    all_domains_proposed = len(proposed_judgments) == len(SCIENTIFIC_PACK.domains)
    multiple_concerns = None
    if all_domains_proposed:
        concern_count = sum(value == "some_concerns" for value in proposed_judgments.values())
        has_high = "high" in proposed_judgments.values()
        if concern_count >= 2 and not has_high:
            if parsed.multiple_concerns is None:
                concerned = [
                    domain.id
                    for domain in SCIENTIFIC_PACK.domains
                    if proposed_judgments[domain.id] == "some_concerns"
                ]
                return _result(
                    "repair",
                    state,
                    repairs=[
                        _repair(
                            "/multiple_concerns",
                            "multiple_concerns_decision_required",
                            "Provide raises_overall_to_high and a concise rationale for the "
                            "multiple Some concerns Domains: " + ", ".join(concerned) + ".",
                        )
                    ],
                )
            multiple_concerns = parsed.multiple_concerns.model_dump(mode="json")
        elif parsed.multiple_concerns is not None:
            return _result(
                "repair",
                state,
                repairs=[
                    _repair(
                        "/multiple_concerns",
                        "multiple_concerns_decision_not_applicable",
                        "The decision applies only when at least two Domains are "
                        "some_concerns and none is high; remove it for the proposed "
                        "Domain judgments.",
                    )
                ],
            )
    record = {
        "trial_id": parsed.trial_id,
        "domain_id": parsed.domain_id,
        "answers": canonical_answers,
        "supersedes": parsed.supersedes,
        "revision_basis": revision_basis,
        "search_accounts": [search_accounts[key] for key in sorted(search_accounts)],
        "active_questions": active,
        "inactive_questions": [key for key in allowed if key not in active],
        "judgment": evaluation.judgment.value,
        "trace": list(evaluation.trace),
        "observed_at": datetime.now(UTC).isoformat(),
    }
    record["identity"] = _domain_identity(record)
    prior_observed_at = _canonical_observed_at(root, record["identity"])
    if prior_observed_at is not None:
        record["observed_at"] = prior_observed_at
    rows = dict(state.get("domain_records", {}))
    if rows.get(key, {}).get("identity") == record["identity"]:
        current_snapshot = (state.get("snapshots") or {}).get(parsed.trial_id)
        if isinstance(current_snapshot, dict) and current_snapshot.get("multiple_concerns") != (
            parsed.multiple_concerns.model_dump(mode="json") if parsed.multiple_concerns else None
        ):
            return _result(
                "condition",
                state,
                condition={
                    "code": "domain_revision_basis_required",
                    "detail": (
                        "this Domain checkpoint is already committed; a different save must "
                        "name its exact superseded identity and a closed revision basis."
                    ),
                },
            )
        return _result("success", state, checkpoint=rows[key], retry=True)
    if existing_record is not None:
        if parsed.supersedes != existing_record.get("identity"):
            return _result(
                "condition",
                state,
                condition={
                    "code": "domain_revision_basis_required",
                    "detail": (
                        f"supersedes must name the exact current checkpoint identity "
                        f"'{existing_record.get('identity')}'."
                    ),
                },
            )
        if revision_basis is None:
            return _result(
                "condition",
                state,
                condition={
                    "code": "domain_revision_basis_required",
                    "detail": (
                        "a changed Domain save requires revision_basis kind 'new_evidence' "
                        "or 'self_correction'."
                    ),
                },
            )
        if revision_basis["kind"] == "new_evidence":
            evidence = catalog_by_handle.get(revision_basis["evidence"]) or catalog.get(
                revision_basis["evidence"]
            )
            prior_evidence = {
                basis.get("evidence")
                for answer in existing_record.get("answers", [])
                if isinstance(answer, dict)
                for basis in answer.get("bases", [])
                if isinstance(basis, dict) and isinstance(basis.get("evidence"), str)
            }
            revised_evidence = {
                basis.get("evidence")
                for answer in canonical_answers
                for basis in answer.get("bases", [])
                if isinstance(basis, dict) and isinstance(basis.get("evidence"), str)
            }
            if (
                evidence is None
                or evidence.get("trial_id") != parsed.trial_id
                or evidence.get("identity") in prior_evidence
                or evidence.get("identity") not in revised_evidence
            ):
                return _result(
                    "condition",
                    state,
                    condition={
                        "code": "domain_revision_basis_invalid",
                        "detail": (
                            "new_evidence must reference selected Evidence from this Trial "
                            "that is not present in the superseded checkpoint."
                        ),
                    },
                )
            revision_basis["evidence"] = evidence["identity"]
        record["revision_basis"] = revision_basis
        record["identity"] = _domain_identity(record)
        prior_observed_at = _canonical_observed_at(root, record["identity"])
        if prior_observed_at is not None:
            record["observed_at"] = prior_observed_at
        if rows.get(key, {}).get("identity") == record["identity"]:
            return _result("success", state, checkpoint=rows[key], retry=True)
    if parsed.expected_revision != state.get("revision", 0):
        raise WorkflowConflict(parsed.expected_revision, int(state.get("revision", 0)))

    rows[key] = record
    history = dict(state.get("domain_history", {}))
    history.setdefault(key, []).append(record["identity"])
    history_records = dict(state.get("domain_history_records", {}))
    history_records.setdefault(key, []).append(record)
    state = {
        **state,
        "domain_records": rows,
        "domain_history": history,
        "domain_history_records": history_records,
    }
    snapshot: dict[str, Any] | None = None
    if all(f"{parsed.trial_id}:{item.id}" in rows for item in SCIENTIFIC_PACK.domains):
        checkpoints = [
            rows[f"{parsed.trial_id}:{item.id}"]["identity"] for item in SCIENTIFIC_PACK.domains
        ]
        judgments = {
            item.id: rows[f"{parsed.trial_id}:{item.id}"]["judgment"]
            for item in SCIENTIFIC_PACK.domains
        }
        snapshot = {
            "trial_id": parsed.trial_id,
            "checkpoints": checkpoints,
            "provisional": False,
            "domain_judgments": judgments,
            "multiple_concerns": multiple_concerns,
        }
        snapshot["overall"] = evaluate_overall(
            judgments,
            combined_concerns=(
                multiple_concerns["raises_overall_to_high"]
                if multiple_concerns is not None
                else None
            ),
        ).judgment.value
        snapshot["identity"] = _identity(snapshot)
        current_snapshots = state.get("snapshots")
        snapshots: dict[str, Any] = (
            dict(current_snapshots) if isinstance(current_snapshots, dict) else {}
        )
        snapshots[parsed.trial_id] = snapshot
        current_history = state.get("snapshot_history")
        snapshot_history: dict[str, list[str]] = (
            {str(key): list(value) for key, value in current_history.items()}
            if isinstance(current_history, dict)
            else {}
        )
        snapshot_history.setdefault(parsed.trial_id, []).append(snapshot["identity"])
        current_history_records = state.get("snapshot_history_records")
        snapshot_history_records: dict[str, list[dict[str, Any]]] = (
            {str(key): list(value) for key, value in current_history_records.items()}
            if isinstance(current_history_records, dict)
            else {}
        )
        snapshot_history_records.setdefault(parsed.trial_id, []).append(snapshot)
        state = {
            **state,
            "snapshots": snapshots,
            "snapshot_history": snapshot_history,
            "snapshot_history_records": snapshot_history_records,
            "trial_dispositions": {
                **state.get("trial_dispositions", {}),
                parsed.trial_id: "assessed",
            },
        }
    current_dispositions = state.get("trial_dispositions")
    dispositions = current_dispositions if isinstance(current_dispositions, dict) else {}
    if not any(value == "pending" for value in dispositions.values()):
        state = {**state, "phase": "ready_to_finalize"}
    promoted_evidence = {
        item["identity"]: item
        for item in catalog.values()
        if isinstance(item, dict)
        and (item.get("handle") in referenced_handles or item.get("identity") in referenced_handles)
    }
    records = {
        f"domain:{key}:{record['identity']}": record,
        **{f"evidence:{identity}": item for identity, item in promoted_evidence.items()},
    }
    if snapshot is not None:
        records[f"snapshot:{snapshot['identity']}"] = snapshot
    state = _commit_records(root, state, parsed.expected_revision, records)
    return _result(
        "success",
        state,
        checkpoint=record,
        trial_completed=snapshot is not None,
        continuation=_continuation(state),
    )


def get_domain_context(
    workspace: str | Path,
    trial_id: str | None = None,
    domain_id: str | None = None,
    preview_missing_data: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    root = _root(workspace)
    _ensure(root)
    state = _state(root)
    if state.get("phase") not in {"assessment", "ready_to_finalize"}:
        raise ValueError("Domain work is not active")
    active_trial, active_domain = _active_trial_and_domain(state)
    if active_trial is None:
        raise ValueError("no Trial is available")
    if trial_id is not None and trial_id != active_trial:
        raise ValueError(f"complete Trial '{active_trial}' before Trial '{trial_id}'")
    trial_id = active_trial
    records = state.get("domain_records") or {}
    if domain_id is None:
        domain_id = active_domain
    elif domain_id != active_domain and f"{trial_id}:{domain_id}" not in records:
        raise ValueError(f"complete Domain '{active_domain}' before Domain '{domain_id}'")
    if domain_id is None:
        raise ValueError("no Domain is available")
    if domain_id not in {item.id for item in SCIENTIFIC_PACK.domains}:
        raise ValueError("unknown Domain")
    result = next(
        (
            item
            for item in (state.get("proposal") or {}).get("payload", {}).get("results", [])
            if item.get("trial_id") == trial_id
        ),
        None,
    )
    if not isinstance(result, dict):
        raise ValueError("approved Result is unavailable")
    trial_sources = next(
        (
            item.get("sources", [])
            for item in (state.get("batch") or {}).get("trials", [])
            if isinstance(item, dict) and item.get("id") == trial_id
        ),
        [],
    )
    trial_registry = next(
        (
            item.get("registry")
            for item in (state.get("batch") or {}).get("trials", [])
            if isinstance(item, dict) and item.get("id") == trial_id
        ),
        None,
    )
    existing = (state.get("domain_records") or {}).get(f"{trial_id}:{domain_id}", {})
    trial_has_checkpoint = any(
        isinstance(key, str) and key.startswith(f"{trial_id}:")
        for key in (state.get("domain_records") or {})
    )
    answer_rows = existing.get("answers", []) if isinstance(existing, dict) else []
    answers = {
        item["question_id"]: item["answer"]
        for item in answer_rows
        if isinstance(item, dict)
        and isinstance(item.get("question_id"), str)
        and isinstance(item.get("answer"), str)
    }
    active = (
        set(active_questions(answers))
        if answers
        else {
            item.id
            for item in SCIENTIFIC_PACK.questions
            if item.domain_id == domain_id and item.activation.kind == "always"
        }
    )
    handles = {
        item.get("handle")
        for item in (result or {}).get("evidence", [])
        if isinstance(item, dict) and isinstance(item.get("handle"), str)
    }
    result_handles = {
        item.get("handle")
        for item in result.get("evidence", [])
        if isinstance(item, dict) and isinstance(item.get("handle"), str)
    }
    result_handles.update(
        input_item.get("handle")
        for item in result.get("evidence", [])
        if isinstance(item, dict) and item.get("kind") == "derived"
        for input_item in item.get("inputs", [])
        if isinstance(input_item, dict) and isinstance(input_item.get("handle"), str)
    )
    handles.update(result_handles)
    checkpoint_answers = [
        answer
        for answer in (existing.get("answers", []) if isinstance(existing, dict) else [])
        if isinstance(answer, dict)
    ]
    checkpoint_identities = {
        basis.get("evidence")
        for answer in checkpoint_answers
        for basis in answer.get("bases", [])
        if isinstance(basis, dict) and isinstance(basis.get("evidence"), str)
    }
    checkpoint_identities.update(
        evidence_identity
        for answer in checkpoint_answers
        for row in (answer.get("missing_data") or {}).get("rows", [])
        if isinstance(row, dict) and isinstance(row.get("basis"), list)
        for evidence_identity in row["basis"]
        if isinstance(evidence_identity, str)
    )
    proposal_catalog = {
        key: value
        for key, value in (state.get("proposal") or {}).get("evidence", {}).items()
        if isinstance(value, dict)
        and value.get("trial_id") == trial_id
        and value.get("handle") in result_handles
    }
    # Disposable candidates are selected by the active Domain association,
    # never by latest-row recency. Canonical Result/checkpoint Evidence is
    # added below as a separate non-competing tier.
    disposable = _evidence_catalog(root, trial_id=trial_id, limit=None)
    associated_ranks = _associated_search_ranks(root, trial_id, domain_id)
    explicit_carry_forward = [
        value
        for value in disposable.values()
        if isinstance(value, dict)
        and not isinstance(value.get("search_session"), str)
        and value.get("handle") not in result_handles
        and value.get("identity") not in checkpoint_identities
    ]
    associated = [
        value
        for value in disposable.values()
        if isinstance(value, dict)
        and isinstance(value.get("search_session"), str)
        and isinstance(value.get("candidate_rank"), int)
        and (value["search_session"], value["candidate_rank"]) in associated_ranks
    ]
    # Handles selected explicitly through the existing Evidence boundary do
    # not carry a search association. Preserve those manual selections when
    # no scoped candidates exist, but do not fall back to search fragments from
    # an earlier Domain.
    associated.sort(
        key=lambda value: (
            int(value.get("candidate_rank", 2**31 - 1)),
            str(value.get("search_session")),
            str(value.get("source_id")),
            int(value.get("page", 0)),
            int(value.get("start", 0)),
            str(value.get("identity")),
        )
    )
    explicit_carry_forward.sort(
        key=lambda value: (
            str(value.get("source_id")),
            int(value.get("page", 0)),
            int(value.get("start_line", 0)),
            int(value.get("end_line", 0)),
            str(value.get("identity")),
        )
    )

    # Repeated searches can materialize the same exact passage under distinct
    # disposable session identities. Keep one visible copy without merging
    # partial overlaps or changing any source-bound quote.
    seen_coordinates: set[tuple[Any, ...]] = {
        (
            value.get("source_id"),
            value.get("page"),
            value.get("start_line"),
            value.get("end_line"),
        )
        for value in proposal_catalog.values()
        if all(
            value.get(key) is not None for key in ("source_id", "page", "start_line", "end_line")
        )
    }

    def unique_passages(values: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
        unique: list[dict[str, Any]] = []
        duplicates = 0
        for value in values:
            coordinate = (
                value.get("source_id"),
                value.get("page"),
                value.get("start_line"),
                value.get("end_line"),
            )
            key = (
                coordinate
                if all(item is not None for item in coordinate)
                else ("identity", value.get("identity"))
            )
            if key in seen_coordinates:
                duplicates += 1
                continue
            seen_coordinates.add(key)
            unique.append(value)
        return unique, duplicates

    associated, associated_duplicates = unique_passages(associated)
    explicit_carry_forward, explicit_duplicates = unique_passages(explicit_carry_forward)
    projection_budget = 64

    # Recoverable explicit selections take priority over search candidates
    # within the shared item budget. Non-reconstructible selections remain
    # inline outside it, as do Result/checkpoint Evidence.
    def has_exact_read_recovery(value: dict[str, Any]) -> bool:
        return (
            value.get("kind") == "narrative"
            and all(isinstance(value.get(key), int) for key in ("page", "start_line", "end_line"))
            and isinstance(value.get("source_id"), str)
            and isinstance(value.get("trial_id"), str)
        )

    recoverable_explicit = [
        value for value in explicit_carry_forward if has_exact_read_recovery(value)
    ]
    unrecoverable_explicit = [
        value for value in explicit_carry_forward if not has_exact_read_recovery(value)
    ]
    selected_recoverable_explicit = recoverable_explicit[:projection_budget]
    selected_explicit = [*unrecoverable_explicit, *selected_recoverable_explicit]
    remaining_budget = projection_budget - len(selected_recoverable_explicit)
    selected_candidates = associated[:remaining_budget]
    omitted_explicit = recoverable_explicit[len(selected_recoverable_explicit) :]
    included_candidate_ranks = {
        (value["search_session"], value["candidate_rank"]) for value in selected_candidates
    }
    omitted_candidate_ranks = associated_ranks - included_candidate_ranks
    omitted_evidence_count = len(omitted_candidate_ranks) + len(omitted_explicit)
    omitted_by_category = {
        "result": 0,
        "checkpoint": 0,
        "contradiction": 0,
        "active_domain_candidate": len(omitted_candidate_ranks),
        "explicit_carry_forward": len(omitted_explicit),
        "deduplicated": associated_duplicates + explicit_duplicates,
    }
    catalog = dict(proposal_catalog)
    for value in [*selected_candidates, *selected_explicit]:
        catalog[value["identity"]] = value
    missing_handles = {
        handle
        for handle in handles
        if not any(item.get("handle") == handle for item in catalog.values())
    }
    if missing_handles:
        catalog.update(_evidence_for_handles(root, missing_handles, trial_id))
    # A restart or compaction must not discard the evidence already used by
    # the active checkpoint. Those records are canonical and can be recovered
    # even when the disposable handle cache was rebuilt.
    catalog.update(_canonical_evidence_records(root, checkpoint_identities))

    preview_handles = {
        reference
        for row in (preview_missing_data or [])
        if isinstance(row, dict)
        for reference in row.get("basis", [])
        if isinstance(reference, str) and reference.startswith("eh_")
    }
    if preview_handles:
        catalog.update(_evidence_for_handles(root, preview_handles, trial_id))

    canonical_handles = {
        item.get("handle")
        for item in catalog.values()
        if isinstance(item, dict) and item.get("identity") in checkpoint_identities
    }
    contradiction_identities = {
        basis.get("evidence")
        for answer in checkpoint_answers
        for basis in answer.get("bases", [])
        if isinstance(basis, dict)
        and basis.get("kind") == "contradiction"
        and isinstance(basis.get("evidence"), str)
    }
    for value in catalog.values():
        if not isinstance(value, dict):
            continue
        handle = value.get("handle")
        if handle in result_handles:
            value.setdefault("inclusion_reason", "result")
        elif value.get("identity") in contradiction_identities:
            value.setdefault("inclusion_reason", "contradiction")
        elif handle in canonical_handles:
            value.setdefault("inclusion_reason", "checkpoint")
        elif (
            isinstance(value.get("search_session"), str)
            and isinstance(value.get("candidate_rank"), int)
            and (value["search_session"], value["candidate_rank"]) in associated_ranks
        ):
            value.setdefault("inclusion_reason", "active_domain_candidate")
            value.setdefault("domain_id", domain_id)
            value.setdefault("returned_previously", True)
        elif not isinstance(value.get("search_session"), str):
            value.setdefault("inclusion_reason", "explicit_carry_forward")
            value.setdefault("domain_id", domain_id)

    domain_question_ids = tuple(
        item.id for item in SCIENTIFIC_PACK.questions if item.domain_id == domain_id
    )
    questions_by_evidence: dict[str, set[str]] = {}
    for answer in checkpoint_answers:
        question_id = answer.get("question_id")
        if not isinstance(question_id, str):
            continue
        for basis in answer.get("bases", []):
            if isinstance(basis, dict) and isinstance(basis.get("evidence"), str):
                questions_by_evidence.setdefault(basis["evidence"], set()).add(question_id)
        missing_data = answer.get("missing_data")
        if isinstance(missing_data, dict):
            for row in missing_data.get("rows", []):
                if not isinstance(row, dict):
                    continue
                for evidence_identity in row.get("basis", []):
                    if isinstance(evidence_identity, str):
                        questions_by_evidence.setdefault(evidence_identity, set()).add(question_id)

    evidence_continuations: list[dict[str, Any]] = []
    search_continuations = _search_continuation(
        root,
        trial_id,
        domain_id,
        included_candidate_ranks,
        projection_budget,
    )
    evidence_continuations.extend(search_continuations)
    if omitted_explicit:
        windows: list[dict[str, Any]] = []
        seen_windows: set[tuple[str, int, int, int]] = set()
        for value in omitted_explicit:
            source_id = value.get("source_id")
            page = value.get("page")
            start_line = value.get("start_line")
            end_line = value.get("end_line")
            if (
                not isinstance(source_id, str)
                or not isinstance(page, int)
                or not isinstance(start_line, int)
                or not isinstance(end_line, int)
            ):
                continue
            window = (source_id, page, start_line, end_line)
            if window in seen_windows:
                continue
            seen_windows.add(window)
            windows.append(
                {
                    "source_id": source_id,
                    "page": page,
                    "start_line": start_line,
                    "end_line": end_line,
                }
            )
            if len(windows) == 20:
                evidence_continuations.append(
                    {
                        "operation": "read_pages",
                        "trial_id": trial_id,
                        "windows": windows,
                    }
                )
                windows = []
        if windows:
            evidence_continuations.append(
                {
                    "operation": "read_pages",
                    "trial_id": trial_id,
                    "windows": windows,
                }
            )
    evidence_continuation = next(
        (
            action
            for action in evidence_continuations
            if action.get("operation") in {"search_sources", "read_pages"}
        ),
        None,
    )
    workspace_groups = []
    for reason in (
        "result",
        "checkpoint",
        "contradiction",
        "active_domain_candidate",
        "explicit_carry_forward",
    ):
        if reason == "result":
            items = [
                value
                for value in catalog.values()
                if isinstance(value, dict) and value.get("handle") in result_handles
            ]
        elif reason == "contradiction":
            items = [
                value
                for value in catalog.values()
                if isinstance(value, dict) and value.get("identity") in contradiction_identities
            ]
        elif reason == "checkpoint":
            items = [
                value
                for value in catalog.values()
                if isinstance(value, dict)
                and value.get("identity") in checkpoint_identities
                and value.get("identity") not in contradiction_identities
            ]
        else:
            items = [
                value
                for value in catalog.values()
                if isinstance(value, dict) and value.get("inclusion_reason") == reason
            ]
        if not items:
            continue
        scoped_questions = (
            sorted(
                {
                    question_id
                    for value in items
                    for question_id in questions_by_evidence.get(value["identity"], set())
                }
            )
            if reason in {"checkpoint", "contradiction"}
            else list(domain_question_ids)
            if reason in {"active_domain_candidate", "explicit_carry_forward"}
            else []
        )
        workspace_groups.append(
            {
                "inclusion_reason": reason,
                "question_ids": scoped_questions,
                "evidence_handles": sorted(value["handle"] for value in items),
            }
        )

    def result_projection(value: dict[str, Any]) -> dict[str, Any]:
        if value.get("kind") == "unavailable":
            return value
        reported = value["reported"]
        references = []
        for evidence_item in value.get("evidence", []):
            if not isinstance(evidence_item, dict):
                continue
            if evidence_item.get("kind") == "derived":
                references.append(dict(evidence_item))
                continue
            handle = evidence_item.get("handle")
            selected = next(
                (item for item in catalog.values() if item.get("handle") == handle), None
            )
            if not isinstance(handle, str) or not isinstance(selected, dict):
                raise ValueError("Result Evidence handle is unavailable")
            references.append(
                {
                    "kind": evidence_item.get("kind"),
                    "handle": handle,
                    "identity": selected["identity"],
                }
            )
        projection = {
            key: value[key]
            for key in (
                "kind",
                "trial_id",
                "requested_outcome",
                "relation",
                "relation_rationale",
                "target",
                "clarity",
            )
        }
        projection["reported"] = reported
        return projection | {
            "evidence": references,
        }

    continuation: dict[str, Any] = {
        "operation": "save_domain_judgment",
        "authority": "host",
        "trial_id": trial_id,
        "domain_id": domain_id,
        "expected_revision": int(state.get("revision", 0)),
        "caller_inputs": ["answers", "multiple_concerns"],
    }
    # A correction continuation names the exact active checkpoint to replace.
    # The model therefore never has to infer a parent from the historical
    # digest list, and a stale or unrelated checkpoint cannot be selected by
    # guessing.
    if isinstance(existing, dict) and isinstance(existing.get("identity"), str):
        continuation["supersedes"] = existing["identity"]
        continuation["caller_inputs"] = [
            "answers",
            "multiple_concerns",
            "revision_basis",
        ]
    canonical_preview = (
        _canonical_preview_rows(preview_missing_data, catalog, trial_id)
        if preview_missing_data
        else None
    )
    context = {
        "outcome": "success",
        "trial_id": trial_id,
        "domain_id": domain_id,
        "state_revision": state.get("revision", 0),
        "result": result_projection(result),
        "evidence": list(catalog.values()),
        "answers": answer_rows,
        "current_checkpoint": (existing.get("identity") if isinstance(existing, dict) else None),
        "guidance": [
            (
                "Answer every initially active question plus each dependent question whose "
                "activation predicate is met by your earlier answers. Extra inactive branch "
                "answers are ignored and never committed. Preserve the approved Result target."
            ),
            *_DOMAIN_GUIDANCE,
        ],
        "response_framework": _RESPONSE_FRAMEWORK.model_dump(mode="json"),
        "traps": [
            "A no-hit search describes one lexical query, not scientific absence.",
            *_DOMAIN_TRAPS,
        ],
        "questions": [
            {
                "id": item.id,
                "wording": item.wording,
                "options": [_answer_option(item, answer) for answer in item.allowed_answers],
                "active": item.id in active,
                "activation": item.activation.model_dump(mode="json"),
                "official_guidance": item.guidance.official.source_excerpt,
                "source_locator": item.guidance.official.source_locator,
                "decision_rule": item.guidance.operational.decision_rule,
                "evidence_needed": item.guidance.operational.evidence_needed,
                "no_information_rule": item.guidance.operational.no_information_rule,
                "considerations": item.guidance.operational.considerations,
                "invalid_shortcuts": item.guidance.operational.invalid_shortcuts,
                "query_suggestions": tuple(
                    suggestion.model_dump(mode="json")
                    for suggestion in item.guidance.operational.query_suggestions
                ),
            }
            for item in SCIENTIFIC_PACK.questions
            if item.domain_id == domain_id
        ],
        "completion_rule": (
            "Ground each active proposition and its uncertainty in inspected Evidence or bounded "
            "discovery for unresolved premises. Supply every question activated by the submitted "
            "answer path with an Evidence use, scoped absence receipt, or limitation. "
            "Inactive extras are ignored."
        ),
        "evidence_workspace": {
            "selection_policy_version": "rob2-kit.domain-projection.v0.6",
            "groups": workspace_groups,
            "omitted_count": omitted_evidence_count,
            "omitted_by_category": omitted_by_category,
            "continuation": evidence_continuation,
            "continuations": evidence_continuations,
        },
        "comparison_cards": _comparison_cards(
            domain_id,
            result,
            catalog,
            checkpoint_answers,
            trial_sources,
            canonical_preview,
            _registry_navigation(root, trial_id, trial_sources)
            if domain_id == "domain:selection"
            else None,
            trial_registry if isinstance(trial_registry, dict) else None,
        ),
        "reading_recovery": (
            _main_report_recovery(root, state, trial_id, include_budget=True)
            if not trial_has_checkpoint
            else None
        ),
        "continuation": continuation,
    }
    return _compact_domain_evidence(context)

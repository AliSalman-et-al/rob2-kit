import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..logic.evaluator import active_questions, evaluate_domain, evaluate_overall
from ..models import ResponseFramework, canonical_json_bytes
from ..packs import SCIENTIFIC_PACK
from ..workflow_models import DomainDraft, DomainReasoningDraft
from ._state import (
    _canonical_evidence_records,
    _commit_records,
    _db,
    _ensure,
    _identity,
    _ordered_sources,
    _result,
    _root,
    _state,
)
from .contracts import WorkflowConflict
from .evidence import (
    _associated_search_evidence,
    _associated_search_ranks,
    _evidence_catalog,
    _evidence_for_handles,
    _search_continuation,
    _search_evidence_identities,
    _search_receipt,
    _unassigned_search_continuation,
    _unassigned_search_evidence,
    main_report_reading_status,
)
from .missing_data import reconcile_missing_data as reconcile_typed_missing_data
from .status import _active_trial_and_domain, _continuation
from .working import investigation_projection, working_checkpoint_status

_DOMAIN_RECOVERABLE_NARRATIVE_TEXT_BUDGET = 12_288


def _domain_context_delivery(
    root: Path,
    trial_id: str,
    domain_id: str,
    state_revision: int | None,
    *,
    prefer_views: bool = True,
) -> dict[str, Any] | None:
    state = _state(root)
    batch = state.get("batch")
    batch_id = batch.get("identity") if isinstance(batch, dict) else None
    if not isinstance(batch_id, str):
        return None
    with _db(root, "derivative.sqlite3") as connection:
        if prefer_views:
            view_row = connection.execute(
                "SELECT view_id,batch_id,trial_id,domain_id,state_revision,digest,page_size,"
                "page_count,"
                "next_index,next_cursor,complete,snapshot,preview_scope,basis_identity "
                "FROM domain_context_views WHERE batch_id=? AND trial_id=? AND domain_id=? "
                "AND (? IS NULL OR state_revision=?) ORDER BY complete DESC,rowid DESC LIMIT 1",
                (batch_id, trial_id, domain_id, state_revision, state_revision),
            ).fetchone()
            if view_row is not None:
                return _decode_domain_context_delivery_row(view_row)
        if state_revision is None:
            row = connection.execute(
                "SELECT batch_id,trial_id,domain_id,state_revision,digest,page_size,page_count,"
                "next_index,next_cursor,complete,snapshot,preview_scope,basis_identity "
                "FROM domain_context_delivery WHERE batch_id=? AND trial_id=? AND domain_id=? "
                "ORDER BY state_revision DESC LIMIT 1",
                (batch_id, trial_id, domain_id),
            ).fetchone()
        else:
            row = connection.execute(
                "SELECT batch_id,trial_id,domain_id,state_revision,digest,page_size,page_count,"
                "next_index,next_cursor,complete,snapshot,preview_scope,basis_identity "
                "FROM domain_context_delivery "
                "WHERE batch_id=? AND trial_id=? AND domain_id=? AND state_revision=?",
                (batch_id, trial_id, domain_id, state_revision),
            ).fetchone()
    if row is None:
        return None
    return _decode_domain_context_delivery_row(row)


def _decode_domain_context_delivery_row(row: Any) -> dict[str, Any]:
    delivery = {key: row[key] for key in row.keys()}
    raw_snapshot = delivery.get("snapshot")
    if raw_snapshot is None:
        delivery["snapshot"] = None
    else:
        try:
            snapshot = json.loads(
                raw_snapshot if isinstance(raw_snapshot, str) else bytes(raw_snapshot)
            )
        except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(
                "domain_context_delivery_unavailable: context snapshot is corrupt"
            ) from error
        if not isinstance(snapshot, dict):
            raise ValueError("domain_context_delivery_unavailable: context snapshot is corrupt")
        delivery["snapshot"] = snapshot
    raw_preview = delivery.get("preview_scope")
    if raw_preview is None:
        delivery["preview_scope"] = None
    else:
        try:
            preview = json.loads(
                raw_preview if isinstance(raw_preview, str) else bytes(raw_preview)
            )
        except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(
                "domain_context_delivery_unavailable: preview scope is corrupt"
            ) from error
        if not isinstance(preview, list) or not all(isinstance(row, dict) for row in preview):
            raise ValueError("domain_context_delivery_unavailable: preview scope is corrupt")
        delivery["preview_scope"] = preview
    return delivery


def _domain_context_view(root: Path, view_id: str) -> dict[str, Any] | None:
    with _db(root, "derivative.sqlite3") as connection:
        row = connection.execute(
            "SELECT view_id,batch_id,trial_id,domain_id,state_revision,digest,page_size,page_count,"
            "next_index,next_cursor,complete,snapshot,preview_scope,basis_identity "
            "FROM domain_context_views WHERE view_id=?",
            (view_id,),
        ).fetchone()
    return _decode_domain_context_delivery_row(row) if row is not None else None


def _record_domain_context_view(
    root: Path,
    view_id: str,
    trial_id: str,
    domain_id: str,
    state_revision: int,
    digest: str,
    page_size: int,
    page_count: int,
    page_index: int,
    next_cursor: str | None,
    cursor: str | None,
    basis_identity: str,
    snapshot: dict[str, Any] | None = None,
    preview_scope: list[dict[str, Any]] | None = None,
) -> None:
    """Persist one opaque context view without sharing a cursor chain."""

    state = _state(root)
    batch = state.get("batch")
    batch_id = batch.get("identity") if isinstance(batch, dict) else None
    if not isinstance(batch_id, str):
        raise ValueError("domain_context_delivery_unavailable: Batch identity is missing")
    with _db(root, "derivative.sqlite3") as connection:
        row = connection.execute(
            "SELECT digest,page_size,page_count,next_index,next_cursor,complete "
            "FROM domain_context_views WHERE view_id=?",
            (view_id,),
        ).fetchone()
        if cursor is None:
            if row is not None:
                return
            connection.execute(
                "INSERT INTO domain_context_views "
                "(view_id,batch_id,trial_id,domain_id,state_revision,digest,page_size,page_count,"
                "next_index,next_cursor,complete,snapshot,preview_scope,basis_identity) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    view_id,
                    batch_id,
                    trial_id,
                    domain_id,
                    state_revision,
                    digest,
                    page_size,
                    page_count,
                    page_index + 1,
                    next_cursor,
                    int(page_index + 1 >= page_count),
                    canonical_json_bytes(snapshot) if isinstance(snapshot, dict) else None,
                    canonical_json_bytes(preview_scope)
                    if isinstance(preview_scope, list)
                    else None,
                    basis_identity,
                ),
            )
            return
        if row is None:
            raise ValueError("domain_context_cursor_expired: context view is unavailable")
        if (
            row["digest"] != digest
            or int(row["page_size"]) != page_size
            or int(row["page_count"]) != page_count
        ):
            raise ValueError("domain_context_cursor_stale: context view changed")
        expected_index = int(row["next_index"])
        if page_index > expected_index:
            raise ValueError(
                f"domain_context_delivery_out_of_order: expected_cursor={row['next_cursor']}"
            )
        if page_index < expected_index:
            return
        if row["next_cursor"] != cursor:
            raise ValueError(
                f"domain_context_delivery_out_of_order: expected_cursor={row['next_cursor']}"
            )
        connection.execute(
            "UPDATE domain_context_views SET next_index=?,next_cursor=?,complete=? WHERE view_id=?",
            (page_index + 1, next_cursor, int(page_index + 1 >= page_count), view_id),
        )


def _record_domain_context_delivery(
    root: Path,
    trial_id: str,
    domain_id: str,
    state_revision: int,
    digest: str,
    page_size: int,
    page_count: int,
    page_index: int,
    next_cursor: str | None,
    cursor: str | None,
    basis_identity: str,
    snapshot: dict[str, Any] | None = None,
    preview_scope: list[dict[str, Any]] | None = None,
) -> None:
    state = _state(root)
    batch = state.get("batch")
    batch_id = batch.get("identity") if isinstance(batch, dict) else None
    if not isinstance(batch_id, str):
        raise ValueError("domain_context_delivery_unavailable: Batch identity is missing")
    with _db(root, "derivative.sqlite3") as connection:
        row = connection.execute(
            "SELECT digest,page_size,page_count,next_index,next_cursor,complete,snapshot,"
            "preview_scope,basis_identity "
            "FROM domain_context_delivery WHERE batch_id=? AND trial_id=? AND domain_id=? "
            "AND state_revision=?",
            (batch_id, trial_id, domain_id, state_revision),
        ).fetchone()
        if cursor is None:
            preview_payload = (
                canonical_json_bytes(preview_scope) if isinstance(preview_scope, list) else None
            )
            if (
                row is not None
                and bool(row["complete"])
                and row["digest"] == digest
                and int(row["page_size"]) == page_size
                and int(row["page_count"]) == page_count
                and row["snapshot"] is not None
                and row["preview_scope"] == preview_payload
                and row["basis_identity"] == basis_identity
            ):
                return
            # Result, pack, preview, or same-Domain changes invalidate prior
            # snapshots; unrelated workflow revisions keep their own chains.
            connection.execute(
                "DELETE FROM domain_context_delivery WHERE batch_id=? AND trial_id=? "
                "AND domain_id=? AND basis_identity<>?",
                (batch_id, trial_id, domain_id, basis_identity),
            )
            snapshot_payload = (
                canonical_json_bytes(snapshot) if isinstance(snapshot, dict) else None
            )
            connection.execute(
                "INSERT OR REPLACE INTO domain_context_delivery "
                "(batch_id,trial_id,domain_id,state_revision,digest,page_size,page_count,"
                "next_index,next_cursor,complete,snapshot,preview_scope,basis_identity) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    batch_id,
                    trial_id,
                    domain_id,
                    state_revision,
                    digest,
                    page_size,
                    page_count,
                    page_index + 1,
                    next_cursor,
                    int(page_index + 1 >= page_count),
                    snapshot_payload,
                    preview_payload,
                    basis_identity,
                ),
            )
            return
        if row is None:
            raise ValueError("domain_context_delivery_unavailable: restart with the first page")
        if (
            row["digest"] != digest
            or int(row["page_size"]) != page_size
            or int(row["page_count"]) != page_count
            or row["basis_identity"] != basis_identity
        ):
            if bool(row["complete"]):
                return
            raise ValueError("domain_context_delivery_stale: restart with the first page")
        expected_index = int(row["next_index"])
        if page_index > expected_index:
            expected_cursor = row["next_cursor"]
            raise ValueError(
                f"domain_context_delivery_out_of_order: expected_cursor={expected_cursor}"
            )
        if page_index < expected_index:
            return
        if row["next_cursor"] != cursor:
            raise ValueError(
                f"domain_context_delivery_out_of_order: expected_cursor={row['next_cursor']}"
            )
        connection.execute(
            "UPDATE domain_context_delivery SET next_index=?,next_cursor=?,complete=? "
            "WHERE batch_id=? AND trial_id=? AND domain_id=? AND state_revision=?",
            (
                page_index + 1,
                next_cursor,
                int(page_index + 1 >= page_count),
                batch_id,
                trial_id,
                domain_id,
                state_revision,
            ),
        )


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
    status = main_report_reading_status(
        root,
        [trial],
        phase="assessment",
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
        "trial_discovery": 4,
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
    # Keep the source-bound decision material in the same order as the
    # context contract: approved Result Evidence, checkpoint/contradictory
    # premises, then discovery support.  This is a presentation ordering only;
    # Evidence identities and the canonical ledger remain unchanged.
    context["evidence"] = [
        projected.get(index, evidence[index])
        for index, _item in sorted(
            enumerate(evidence),
            key=lambda pair: (tier.get(str(pair[1].get("inclusion_reason")), 5), pair[0]),
        )
    ]
    workspace = context.get("evidence_workspace")
    if isinstance(workspace, dict):
        workspace = dict(workspace)
        workspace["selection_policy_version"] = "rob2-kit.domain-projection.v0.7"
        workspace["recoverable_narrative_text_budget"] = _DOMAIN_RECOVERABLE_NARRATIVE_TEXT_BUDGET
        workspace["recoverable_narrative_text_bytes"] = recoverable_narrative_bytes
        workspace["omitted_narrative_text_bytes"] = omitted
        workspace["omitted_narrative_text_count"] = omitted_count
        workspace["unrecoverable_inline_text_bytes"] = unrecoverable_inline
        context["evidence_workspace"] = workspace
    return context


_DOMAIN_GUIDANCE = (
    "Evaluate activated questions in question order. Submit every activated question with a "
    "justification, unknowns, and counterevidence. Review the inspected passages against its "
    "exact proposition "
    "and check material contradictions. Reuse adequate Evidence. When a premise remains "
    "unresolved, state the unresolved premise and why you stopped, and use bounded discovery "
    "across relevant Sources, including a protocol or SAP when relevant. Inspect returned "
    "passages before using them. A limitation requires that explicit premise and stopping "
    "rationale; include a Trial-scoped search receipt when retrieval provenance is useful, "
    "but a direct read does not require a search receipt. Absence "
    "requires a scoped untruncated no-hit receipt.",
    "Cite complete premises for the active question. One passage may support several facts. "
    "When an answer depends on separate passages, cite each with its own boundaries. "
    "A relationship kind describes the use of Evidence; it adds no scientific fact.",
    "When inference, conflict, or uncertainty connects Evidence to an answer, include a concise "
    "question-specific justification. State what the passages establish, what remains unresolved, "
    "and why the selected option follows. Any support relationship is host-asserted: the server "
    "checks structure, ownership, and exact Evidence provenance but does not independently judge "
    "semantic entailment.",
    "Working premise records are source-grounded resumable notes. Reuse them only when the "
    "working checkpoint is current for this exact approved Result and captured Source projection; "
    "a stale checkpoint requires the stated recovery action and never carries a prior Domain "
    "judgment into this assessment.",
    "A definitive yes or no needs direct_support, indirect_support, or contradiction; "
    "a limitation or absence alone supports uncertainty, not a definitive answer.",
    "Evaluate activation against your draft answers. If validation reports missing active "
    "question IDs, add those questions with allowed answer values and supported bases, then "
    "resubmit the complete active set in one validation call. The server commits only active "
    "answers.",
    "Apply every reported repair and retain other drafted answers. Add missing questions to "
    "the existing answer set. Resolve further activation from the repaired answers before "
    "resubmitting. The server ignores inactive answers.",
)
_DOMAIN_TRAPS = (
    "A planned method does not prove conduct; a time origin or analysis population does "
    "not prove complete follow-up or equal assessment.",
    "An endpoint label or definition does not prove objectivity, blinding, "
    "prespecification, or no alternative analyses.",
    "A treatment assignment or visibly different intervention does not by itself prove "
    "that participants or personnel knew the assignment.",
    "Different treatment or visit schedules do not by themselves prove that outcome "
    "measurement differed between groups.",
    "Stratification does not prove allocation concealment.",
)


def _official_guidance_recovery(domain_id: str) -> dict[str, Any]:
    """Expose the captured official rubric without generating a replacement summary."""

    sections = [
        {
            "question_ids": (question.id,),
            "source_version": question.guidance.official.version,
            "source_sha256": question.guidance.official.source_sha256,
            "source_locator": question.guidance.official.source_locator,
            "excerpt": question.guidance.official.source_excerpt,
        }
        for question in SCIENTIFIC_PACK.questions
        if question.domain_id == domain_id
    ]
    if not sections:
        raise ValueError("official guidance is unavailable for Domain")
    return {
        "pack": {
            "id": SCIENTIFIC_PACK.id,
            "version": SCIENTIFIC_PACK.version,
            "content_hash": SCIENTIFIC_PACK.content_hash,
        },
        "sections": sections,
        "complete": True,
        "next_cursor": None,
    }


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
        "domain:measurement": "sq:measurement:method-inappropriate",
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
        "domain:measurement": (
            "approved_outcome",
            "measurement_method",
            "measurement_suitability",
            "detection_opportunity",
            "assessor_identity",
            "assessor_awareness",
            "susceptibility",
            "influence_possible",
            "influence_likely",
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

    proposition_specs = {
        "domain:deviations": (
            (
                "sq:deviations:context-deviations",
                "protocol_inconsistency",
                "The observed change was inconsistent with the trial protocol.",
                (),
            ),
            (
                "sq:deviations:context-deviations",
                "trial_context_cause",
                "The trial context caused the protocol-inconsistent change.",
                ("sq:deviations:context-deviations",),
            ),
            (
                "sq:deviations:affected-outcome",
                "outcome_pathway",
                "The identified trial-context deviation could affect the approved outcome.",
                ("sq:deviations:context-deviations",),
            ),
            (
                "sq:deviations:balanced",
                "group_balance",
                "The identified deviation was balanced between randomized groups.",
                ("sq:deviations:context-deviations", "sq:deviations:affected-outcome"),
            ),
        ),
        "domain:missing": (
            (
                "sq:missing:data-available",
                "availability",
                "Outcome data were available for all or nearly all randomized participants.",
                (),
            ),
            (
                "sq:missing:evidence-unbiased",
                "mitigation",
                "The approved Result was not biased by missing outcome data.",
                ("sq:missing:data-available",),
            ),
            (
                "sq:missing:true-value-dependent",
                "possible_dependence",
                "Missingness could depend on the true outcome value.",
                ("sq:missing:evidence-unbiased",),
            ),
            (
                "sq:missing:likely-dependent",
                "likely_dependence",
                "Missingness likely depended on the true outcome value.",
                ("sq:missing:true-value-dependent",),
            ),
        ),
        "domain:measurement": (
            (
                "sq:measurement:method-inappropriate",
                "suitability",
                "The measurement method was inappropriate for the approved outcome.",
                (),
            ),
            (
                "sq:measurement:differential",
                "differential_detection",
                "Outcome measurement or detection could differ between groups.",
                (),
            ),
            (
                "sq:measurement:assessor-aware",
                "assessor_awareness",
                "The relevant outcome assessor knew the assigned intervention.",
                (),
            ),
            (
                "sq:measurement:influence-possible",
                "susceptibility",
                "Knowledge of assignment could influence this outcome assessment.",
                ("sq:measurement:assessor-aware",),
            ),
            (
                "sq:measurement:influence-likely",
                "likely_influence",
                "Knowledge of assignment likely influenced this outcome assessment.",
                ("sq:measurement:influence-possible",),
            ),
        ),
        "domain:selection": (
            (
                "sq:selection:prespecified-analysis",
                "document_availability",
                "A plan or SAP describing the approved Result is available in the captured "
                "Sources.",
                (),
            ),
            (
                "sq:selection:prespecified-analysis",
                "plan_applicability",
                "The plan applies to the exact comparison, cohort, endpoint, population, window, "
                "analysis, and effect measure.",
                ("sq:selection:prespecified-analysis",),
            ),
            (
                "sq:selection:prespecified-analysis",
                "chronology",
                "Plan finalization preceded access to unblinded outcome data.",
                ("sq:selection:prespecified-analysis",),
            ),
            (
                "sq:selection:multiple-measurements",
                "eligible_measurements",
                "The eligible outcome measurements and the reported subset are known.",
                ("sq:selection:prespecified-analysis",),
            ),
            (
                "sq:selection:multiple-analyses",
                "eligible_analyses",
                "The eligible analyses and the reported analysis are known.",
                ("sq:selection:prespecified-analysis",),
            ),
            (
                "sq:selection:multiple-analyses",
                "results_based_selection",
                "The reported measurement or analysis was selected because of its result.",
                ("sq:selection:multiple-measurements", "sq:selection:multiple-analyses"),
            ),
        ),
    }
    paired_examples_by_domain = {
        "domain:deviations": (
            {
                "pair_id": "d2-permitted-versus-context-caused",
                "changed_premise": "protocol consistency and trial-context cause",
                "left_facts": (
                    "Rescue treatment was permitted after progression.",
                    "The later treatment was not caused by trial participation.",
                ),
                "right_facts": (
                    "Rescue treatment was prohibited by the protocol.",
                    "Trial staff encouraged the change during participation.",
                ),
                "reasoning_focus": (
                    "Require both protocol inconsistency and a trial-context cause before "
                    "classifying the deviation."
                ),
            },
        ),
        "domain:missing": (
            {
                "pair_id": "d3-complete-versus-unresolved-availability",
                "changed_premise": "whether the approved outcome was actually ascertained",
                "left_facts": (
                    "The outcome was ascertained for every randomized participant at the "
                    "approved window.",
                ),
                "right_facts": (
                    "The report gives an analysis denominator but does not establish outcome "
                    "ascertainment.",
                ),
                "reasoning_focus": (
                    "Keep observed outcome availability separate from analysis membership and "
                    "preserve No information when extent is unresolved."
                ),
            },
            {
                "pair_id": "d3-administrative-versus-informative-censoring",
                "changed_premise": "why outcome follow-up ended",
                "left_facts": (
                    "Administrative censoring occurred at a common cutoff after the approved "
                    "window.",
                ),
                "right_facts": (
                    "Participants stopped follow-up after worsening symptoms before the "
                    "approved window.",
                ),
                "reasoning_focus": (
                    "Separate administrative censoring from a mechanism that could depend on "
                    "the true outcome."
                ),
            },
        ),
        "domain:measurement": (
            {
                "pair_id": "d4-objective-versus-judgment-dependent",
                "changed_premise": "whether the assessor must exercise outcome judgment",
                "left_facts": (
                    "An independent registry establishes all-cause mortality.",
                    "The detection opportunity is the same in both groups.",
                ),
                "right_facts": (
                    "A participant reports symptom severity on a standardized questionnaire.",
                    "The assessor interprets a judgment-dependent threshold.",
                ),
                "reasoning_focus": (
                    "Assess suitability, detection opportunity, awareness, susceptibility, and "
                    "likely influence as separate propositions."
                ),
            },
            {
                "pair_id": "d4-equal-versus-differential-detection",
                "changed_premise": "whether the opportunity to detect the approved outcome differs",
                "left_facts": ("Both groups use the same ascertainment method and schedule.",),
                "right_facts": (
                    "One intervention causes additional visits that can detect the approved "
                    "outcome.",
                ),
                "reasoning_focus": (
                    "A different opportunity matters only through an explicit pathway to "
                    "differential detection; do not infer a risk label automatically."
                ),
            },
        ),
        "domain:selection": (
            {
                "pair_id": "d5-applicable-versus-inapplicable-plan",
                "changed_premise": "whether the located plan covers the approved Result",
                "left_facts": (
                    "The SAP names the approved comparison, cohort, endpoint, window, population, "
                    "analysis, and effect measure.",
                ),
                "right_facts": (
                    "A platform master plan names a different cohort and intervention phase.",
                ),
                "reasoning_focus": (
                    "Assess plan applicability before using its dates or content for chronology."
                ),
            },
            {
                "pair_id": "d5-multiplicity-versus-selection",
                "changed_premise": "whether reporting choice depended on the result",
                "left_facts": (
                    "Adjusted and complete-case analyses were both reported with no evidence of "
                    "selective choice.",
                ),
                "right_facts": (
                    "Several eligible analyses were performed but only the favorable analysis "
                    "was reported.",
                ),
                "reasoning_focus": (
                    "Multiplicity alone does not establish likely results-based selection."
                ),
            },
        ),
    }
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
    # Source roles are navigation hints, not an exhaustive description of a
    # document. A supplement or combined document may contain the needed
    # premise even when no passage has been selected yet. Keep every captured
    # Source addressable from the card while leaving passage selection and
    # slot classification evidence-bound.
    source_ids = {
        item["id"] for item in sources if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
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
    elif domain_id == "domain:selection":
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
    elif domain_id == "domain:measurement":
        outcome = target.get("outcome_definition")
        measurement = target.get("measurement", {})
        method = measurement.get("method") if isinstance(measurement, dict) else None
        target_refs = bound_refs(
            "/target/outcome_definition",
            "/target/measurement",
            "/target/time_point_or_window",
            "/target/intended_analysis_population",
        )
        if isinstance(outcome, str) and outcome:
            support("approved_outcome", outcome, target_refs)
        if isinstance(method, str) and method:
            support("measurement_method", method, target_refs)

    result_scope = None
    timing = target.get("time_point_or_window", {})
    timing_description = timing.get("description") if isinstance(timing, dict) else None
    groups = target.get("comparison_groups", [])
    group_descriptions = tuple(
        f"{item['id']}: {item['assignment']}"
        for item in groups
        if isinstance(item, dict)
        and isinstance(item.get("id"), str)
        and isinstance(item.get("assignment"), str)
    )
    measurement = target.get("measurement", {})
    measurement_method = measurement.get("method") if isinstance(measurement, dict) else None
    if (
        isinstance(target.get("outcome_definition"), str)
        and isinstance(measurement_method, str)
        and isinstance(timing_description, str)
        and isinstance(target.get("intended_analysis_population"), str)
        and isinstance(target.get("intended_effect_measure"), str)
        and len(group_descriptions) >= 2
    ):
        result_scope = {
            "result_identity": _identity(result),
            "endpoint": target["outcome_definition"],
            "measurement": measurement_method,
            "time_window": timing_description,
            "population": target["intended_analysis_population"],
            "comparison_groups": group_descriptions,
            "effect_measure": target["intended_effect_measure"],
        }

    proposition_rows = []
    for question_id, name, proposition, depends_on in proposition_specs[domain_id]:
        proposition_rows.append(
            {
                "question_id": question_id,
                "name": name,
                "proposition": proposition,
                "status": "unknown",
                "depends_on": depends_on,
                "passages": [],
            }
        )

    # A row-backed count establishes a quantitative premise, not an answer.
    # Expose every stage so the host cannot silently substitute analysis or
    # event membership for outcome availability.
    participant_flow: list[dict[str, Any]] = []
    if isinstance(missing_data, dict):
        rows = [row for row in missing_data.get("rows", []) if isinstance(row, dict)]
        conflict_fields: dict[tuple[Any, ...], set[str]] = {}
        for conflict in missing_data.get("conflicts", []):
            if not isinstance(conflict, dict) or not isinstance(conflict.get("scope"), dict):
                continue
            scope = conflict["scope"]
            row_scope = tuple(scope.get(key) for key in ("arm", "population", "unit", "time_point"))
            reports = [item for item in conflict.get("reports", []) if isinstance(item, dict)]
            conflict_fields[row_scope] = {
                field
                for field in (
                    "result_identity",
                    "endpoint",
                    "severity",
                    "window",
                    "randomized",
                    "eligible",
                    "treated",
                    "observed",
                    "analyzed",
                    "imputed",
                    "excluded",
                    "event_count",
                    "event_definition",
                )
                if len({report.get(field) for report in reports}) > 1
            }
        flow_fields = (
            ("randomized", "randomized"),
            ("eligible", "eligible"),
            ("treated", "treated"),
            ("observed", "observed"),
            ("analyzed", "analyzed"),
            ("imputed", "imputed"),
            ("excluded", "excluded"),
            ("event", "event_count"),
        )
        projected_unknown_stages: set[str] = set()
        for row in rows:
            scope = row.get("scope")
            if not isinstance(scope, dict):
                continue
            row_scope = tuple(scope.get(key) for key in ("arm", "population", "unit", "time_point"))
            basis_passages = [
                {
                    key: evidence[key]
                    for key in ("handle", "source_id", "page", "start_line", "end_line")
                }
                for identity in row.get("basis", [])
                for evidence in (refs_by_identity.get(identity),)
                if isinstance(evidence, dict)
                and all(
                    key in evidence
                    for key in ("handle", "source_id", "page", "start_line", "end_line")
                )
            ]
            for kind, field in flow_fields:
                value = row.get(field)
                # The reconciled row already preserves a null for every
                # unreported stage. Repeat each unknown stage once in this
                # explanatory projection instead of duplicating the same
                # empty fact for every arm/window.
                if not isinstance(value, int):
                    if kind in projected_unknown_stages:
                        continue
                    projected_unknown_stages.add(kind)
                participant_flow.append(
                    {
                        "kind": kind,
                        "value": value,
                        "status": (
                            "conflicted"
                            if field in conflict_fields.get(row_scope, set())
                            or (
                                kind == "event"
                                and "event_count" in conflict_fields.get(row_scope, set())
                            )
                            else "supported"
                            if isinstance(value, int)
                            else "unknown"
                        ),
                        "result_identity": row.get("result_identity"),
                        "endpoint": row.get("endpoint"),
                        "severity": row.get("severity"),
                        "window": row.get("window", scope.get("time_point")),
                        "scope": scope,
                        "passages": basis_passages,
                    }
                )

    # Counts expose the availability inputs but never establish the scientific
    # proposition that data were available for all or nearly all participants.
    # Even 10 observed of 100 randomized needs a host judgement, while an
    # analyzed-only or event-only row says nothing about ascertainment.
    if participant_flow:
        availability = next(
            (item for item in proposition_rows if item["name"] == "availability"), None
        )
        if availability is not None:
            availability["status"] = (
                "conflicted"
                if any(
                    item["kind"] in {"randomized", "observed"} and item["status"] == "conflicted"
                    for item in participant_flow
                )
                else "unknown"
            )

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
            "result_scope": result_scope,
            "passage_groups": passage_groups,
            "slots": slots,
            "propositions": proposition_rows,
            "paired_examples": list(paired_examples_by_domain[domain_id]),
            "participant_flow": participant_flow,
            "missing_data": missing_data,
            "prompt": (
                "Use the exact Result scope, passages, and quantities above. Classify only the "
                "remaining propositions; do not infer causation, availability, censoring, "
                "measurement influence, plan correspondence, or risk from metadata, arithmetic, "
                "or wording alone. An empty passage group is unopened, not a no-hit; inspect "
                "relevant Sources before recording an information limitation."
            ),
        }
    ]


def _coverage_search_accounts(
    root: Path,
    trial_id: str,
    domain_id: str,
    existing: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Include validated receipt history in the context coverage projection."""

    accounts = dict(existing)
    with _db(root, "derivative.sqlite3") as connection:
        rows = connection.execute(
            "SELECT payload FROM search_receipts ORDER BY identity"
        ).fetchall()
    for row in rows:
        try:
            payload = json.loads(bytes(row[0]))
        except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or payload.get("trial_id") != trial_id:
            continue
        purpose = payload.get("purpose_domain_id")
        if purpose not in (None, domain_id):
            continue
        handle = payload.get("handle")
        if not isinstance(handle, str):
            continue
        try:
            receipt = _search_receipt(root, handle)
        except (KeyError, ValueError):
            continue
        identity = receipt.get("identity")
        if isinstance(identity, str):
            accounts.setdefault(identity, receipt)
    return accounts


def _search_session_complete(accounts: list[dict[str, Any]]) -> bool:
    """Return whether a receipt session delivered every ranked candidate."""

    terminal = [
        account
        for account in accounts
        if account.get("truncated") is False
        and account.get("next_cursor") is None
        and account.get("exhausted", True) is True
    ]
    if not terminal:
        return False
    ranks = {
        candidate.get("rank")
        for account in accounts
        for candidate in account.get("returned_candidates", [])
        if isinstance(candidate, dict) and isinstance(candidate.get("rank"), int)
    }
    candidate_counts: list[int] = []
    for account in terminal:
        candidate_count = account.get("candidate_count")
        if isinstance(candidate_count, int):
            candidate_counts.append(candidate_count)
    expected_count = max(
        candidate_counts,
        default=max(ranks, default=0),
    )
    return ranks == set(range(1, expected_count + 1))


def _source_coverage(
    trial_id: str,
    sources: list[dict[str, Any]],
    catalog: dict[str, dict[str, Any]],
    search_accounts: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Project bounded retrieval state without making a scientific claim.

    Search receipts are scoped to the captured Source inventory.  Selected
    Evidence proves that a passage was delivered and chosen, while search
    candidates only prove that a navigator surfaced a location.  Unopened
    Sources stay explicitly visible so a relevant protocol or SAP is not
    mistaken for an absent premise.
    """

    result: list[dict[str, Any]] = []
    for source in _ordered_sources(sources):
        source_id = source.get("id")
        if not isinstance(source_id, str):
            continue
        selected = [
            item
            for item in catalog.values()
            if isinstance(item, dict)
            and item.get("source_id") == source_id
            and item.get("inclusion_reason")
            in {"result", "checkpoint", "contradiction", "explicit_carry_forward"}
        ]
        candidates = [
            item
            for item in catalog.values()
            if isinstance(item, dict)
            and item.get("source_id") == source_id
            and item.get("inclusion_reason") in {"active_domain_candidate", "trial_discovery"}
        ]
        search_state = "unsearched"
        searched_match = False
        searched_no_match = False
        searched_any = False
        search_incomplete = False
        sessions: dict[str, list[dict[str, Any]]] = {}
        for account in search_accounts.values():
            if not isinstance(account, dict) or account.get("trial_id") != trial_id:
                continue
            scoped_sources = {
                item.get("id") for item in account.get("sources", []) if isinstance(item, dict)
            }
            if source_id not in scoped_sources:
                continue
            session_id = account.get("session_id")
            session_key = (
                session_id
                if isinstance(session_id, str)
                else f"receipt:{account.get('identity', len(sessions))}"
            )
            sessions.setdefault(session_key, []).append(account)
        for accounts in sessions.values():
            searched_any = True
            complete = _search_session_complete(accounts)
            search_incomplete = search_incomplete or not complete
            hit_for_source = any(
                isinstance(hit, dict) and hit.get("source_id") == source_id
                for account in accounts
                for hit in account.get("hits", [])
            )
            if hit_for_source:
                searched_match = True
            elif complete:
                # The session exhausted every ranked candidate across its
                # Source set; no hit for this Source is not a match borrowed
                # from another Source.
                searched_no_match = True
        if searched_match:
            search_state = "searched_match"
        elif search_incomplete:
            search_state = "retrieval_incomplete"
        elif searched_no_match:
            search_state = "searched_no_match"
        elif searched_any:
            search_state = "searched_match"

        # Selecting one passage proves that a passage was inspected, not that
        # the entire Source was read.  Keep this conservative until an
        # explicit source-wide read receipt exists.
        read_state = "partially_read" if selected else "unread"
        render_state = (
            "render_delivered"
            if any(item.get("kind") == "figure" for item in selected)
            else "not_delivered"
        )
        recovery: list[dict[str, Any]] = []
        for item in candidates[:20]:
            if all(isinstance(item.get(key), int) for key in ("page", "start_line", "end_line")):
                recovery.append(
                    {
                        "operation": "read_pages",
                        "trial_id": trial_id,
                        "windows": [
                            {
                                "source_id": source_id,
                                "page": item["page"],
                                "start_line": item["start_line"],
                                "end_line": item["end_line"],
                            }
                        ],
                    }
                )
        if render_state == "render_delivered":
            status = "render_delivered"
        elif read_state == "partially_read":
            status = "partially_read"
        elif search_incomplete:
            status = "retrieval_incomplete"
        elif candidates:
            status = "candidate_only"
        elif search_state == "searched_match":
            status = "candidate_only"
        elif search_state == "searched_no_match":
            status = "searched_no_match"
        else:
            status = "unsearched"
        result.append(
            {
                "source_id": source_id,
                "source_role": source.get("role", "other"),
                "page_count": source.get("page_count", 1),
                "status": status,
                "search": (
                    "retrieval_incomplete"
                    if search_incomplete
                    else "candidate_only"
                    if candidates
                    else search_state
                ),
                "read": read_state,
                "render": render_state,
                "recovery": recovery,
            }
        )
    return result


def reconcile_missing_data(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Reconcile endpoint-availability facts at the domain boundary."""

    return reconcile_typed_missing_data(rows)


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


def _approved_result(state: dict[str, Any], trial_id: str) -> dict[str, Any]:
    results = (state.get("proposal") or {}).get("payload", {}).get("results", [])
    result = next(
        (item for item in results if isinstance(item, dict) and item.get("trial_id") == trial_id),
        None,
    )
    if not isinstance(result, dict):
        raise ValueError("approved Result is unavailable")
    return result


def _domain_context_basis_identity(
    state: dict[str, Any],
    trial_id: str,
    domain_id: str,
    preview_missing_data: list[dict[str, Any]] | None,
    working_checkpoint: dict[str, Any] | None = None,
) -> str:
    batch = state.get("batch")
    current = (state.get("domain_records") or {}).get(f"{trial_id}:{domain_id}")
    return _identity(
        {
            "batch_identity": batch.get("identity") if isinstance(batch, dict) else None,
            "trial_id": trial_id,
            "domain_id": domain_id,
            "result_identity": _identity(_approved_result(state, trial_id)),
            "pack_identity": _pack_identity(),
            "checkpoint_identity": current.get("identity") if isinstance(current, dict) else None,
            # A premise checkpoint is reusable only inside the exact Result and
            # Source projection that produced it.  Include its full status in
            # the context basis so a stale workspace cannot silently feed a
            # new Domain view.
            "working_checkpoint": working_checkpoint,
            "preview_identity": _identity(preview_missing_data or []),
        }
    )


def _pack_identity() -> str:
    return _identity(
        {
            "id": SCIENTIFIC_PACK.id,
            "version": SCIENTIFIC_PACK.version,
            "content_hash": SCIENTIFIC_PACK.content_hash,
        }
    )


def _domain_premise_status(status: dict[str, Any]) -> dict[str, Any]:
    """Project only the reusable, source-grounded fields into Domain context."""

    result = {
        key: status.get(key)
        for key in ("status", "reason", "trial_id", "checkpoint_identity", "recovery")
    }
    checkpoint = status.get("checkpoint")
    if isinstance(checkpoint, dict):
        result["checkpoint"] = {
            key: checkpoint.get(key)
            for key in ("identity", "result_identity", "source_scope", "premise_records")
        }
    else:
        result["checkpoint"] = None
    return result


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
        "driver_questions",
        "evidence_sufficiency",
    )
    if "result_identity" in record:
        fields = (*fields, "result_identity")
    return _identity({key: record[key] for key in fields})


def _evidence_sufficiency(
    answers: list[dict[str, Any]], search_accounts: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Derive durable claim support without changing scientific evaluation."""
    claims: list[dict[str, Any]] = []
    for answer in answers:
        evidence: list[str] = []
        receipts: list[str] = []
        unresolved: list[str] = []
        kinds: set[str] = set()
        incomplete = False
        for basis in answer.get("bases", []):
            if not isinstance(basis, dict):
                continue
            kind = basis.get("kind")
            if isinstance(kind, str):
                kinds.add(kind)
            reference = basis.get("evidence")
            if isinstance(reference, str):
                evidence.append(reference)
            receipt = basis.get("search_receipt")
            if isinstance(receipt, str):
                receipts.append(receipt)
                account = search_accounts.get(receipt, {})
                incomplete = incomplete or bool(
                    account.get("truncated")
                    or not account.get("ranking_complete", True)
                    or account.get("next_cursor")
                    or not account.get("exhausted", True)
                )
            if kind == "limitation":
                premise = basis.get("unresolved_premise")
                if isinstance(premise, str) and premise.strip():
                    unresolved.append(premise)
        if "contradiction" in kinds:
            status = "contradicted"
        elif incomplete:
            status = "retrieval_incomplete"
        elif "limitation" in kinds:
            status = "unresolved"
        elif "absence" in kinds:
            # A no-hit query is evidence about the query, not proof that the
            # trial did not report the premise. Keep that distinction durable
            # so downstream aggregation cannot silently turn retrieval limits
            # into a scientific absence claim.
            status = "unresolved"
        elif "indirect_support" in kinds:
            status = "indirect"
        elif "direct_support" in kinds:
            status = "supported"
        else:
            status = "unresolved"
        claims.append(
            {
                "question_id": answer["question_id"],
                "status": status,
                "evidence": tuple(dict.fromkeys(evidence)),
                "search_receipts": tuple(dict.fromkeys(receipts)),
                "unresolved_premises": tuple(dict.fromkeys(unresolved)),
            }
        )
    summary = {"claims": tuple(claims)}
    summary["identity"] = _identity(summary)
    return summary


def _host_asserted_sufficiency(summary: dict[str, Any] | None) -> dict[str, Any] | None:
    """Annotate a model-facing receipt without changing canonical history.

    Historical bundles and the standalone verifier intentionally retain the
    compact, versioned evidence-sufficiency shape.  The attribution belongs to
    the transport projection, where it prevents a structural receipt from
    being mistaken for an independently judged scientific conclusion.
    """

    if not isinstance(summary, dict):
        return summary
    claims = summary.get("claims")
    if not isinstance(claims, (list, tuple)):
        return summary
    return {
        **summary,
        "claims": tuple(
            {
                **claim,
                "support_attribution": (
                    "host_asserted"
                    if isinstance(claim, dict)
                    and (
                        claim.get("evidence")
                        or claim.get("search_receipts")
                        or claim.get("unresolved_premises")
                    )
                    else "not_established"
                ),
            }
            if isinstance(claim, dict)
            else claim
            for claim in claims
        ),
    }


def _investigation_sufficiency(summary: dict[str, Any] | None) -> tuple[str, str]:
    """Map the host's submitted basis into an advisory investigation status."""

    claims = summary.get("claims", []) if isinstance(summary, dict) else []
    statuses = {
        item.get("status")
        for item in claims
        if isinstance(item, dict) and isinstance(item.get("status"), str)
    }
    if not statuses:
        return "not_established", "not_established"
    if "contradicted" in statuses:
        return "contradicted", "host_asserted"
    if "retrieval_incomplete" in statuses:
        return "unresolved", "host_asserted"
    if "unresolved" in statuses:
        bounded = any(isinstance(item, dict) and item.get("unresolved_premises") for item in claims)
        return "bounded" if bounded else "unresolved", "host_asserted"
    return "supported", "host_asserted"


def _counterfactual_answer_branch(
    domain_id: str,
    answers: dict[str, str],
    question_id: str,
    replacement: str,
) -> tuple[dict[str, str], tuple[str, ...], tuple[str, ...]]:
    """Project a one-step alternative onto the branch it activates."""

    alternative_answers = dict(answers)
    alternative_answers[question_id] = replacement
    domain_question_ids = {
        question.id for question in SCIENTIFIC_PACK.questions if question.domain_id == domain_id
    }
    active = tuple(
        item for item in active_questions(alternative_answers) if item in domain_question_ids
    )
    projected = {
        question_id: alternative_answers[question_id]
        for question_id in active
        if question_id in alternative_answers
    }
    missing = tuple(question_id for question_id in active if question_id not in projected)
    return projected, active, missing


def _counterfactual_missing_reason(missing: tuple[str, ...]) -> str:
    return f"missing active question IDs: [{_ids(list(missing))}]"


def _overall_receipt(
    trial_id: str,
    records: dict[str, Any],
    judgments: dict[str, str],
    overall_evaluation: Any,
) -> dict[str, Any]:
    """Build a diagnostic aggregation receipt without changing the saved labels.

    The receipt deliberately references Domain checkpoint identities and keeps
    hypothetical answer changes separate from the official deterministic
    evaluation.  It is therefore useful for audit and calibration without
    becoming a second decision table.
    """

    driver_rows: list[dict[str, Any]] = []
    for domain in SCIENTIFIC_PACK.domains:
        if domain.id not in overall_evaluation.driver_domains:
            continue
        record = records.get(f"{trial_id}:{domain.id}")
        if not isinstance(record, dict):
            continue
        answers = {
            item.get("question_id"): item
            for item in record.get("answers", [])
            if isinstance(item, dict) and isinstance(item.get("question_id"), str)
        }
        driver_questions = [
            question_id
            for question_id in record.get("driver_questions", [])
            if isinstance(question_id, str)
        ]
        driver_rows.append(
            {
                "domain_id": domain.id,
                "checkpoint": record.get("identity"),
                "judgment": record.get("judgment"),
                "trace": list(record.get("trace", [])),
                "driver_questions": driver_questions,
                "driver_answers": [
                    {
                        "question_id": question_id,
                        "answer": answers[question_id].get("answer"),
                    }
                    for question_id in driver_questions
                    if question_id in answers
                ],
                "evidence_sufficiency": record.get("evidence_sufficiency"),
            }
        )

    alternatives: list[dict[str, Any]] = []
    for domain in SCIENTIFIC_PACK.domains:
        record = records.get(f"{trial_id}:{domain.id}")
        if not isinstance(record, dict):
            continue
        answer_items = {
            item.get("question_id"): item
            for item in record.get("answers", [])
            if isinstance(item, dict) and isinstance(item.get("question_id"), str)
        }
        sufficiency = record.get("evidence_sufficiency")
        claims = sufficiency.get("claims", []) if isinstance(sufficiency, dict) else []
        claim_status = {
            claim.get("question_id"): claim.get("status")
            for claim in claims
            if isinstance(claim, dict) and isinstance(claim.get("question_id"), str)
        }
        for question_id, answer_item in answer_items.items():
            if answer_item.get("answer") != "no_information" and claim_status.get(
                question_id
            ) not in {"unresolved", "retrieval_incomplete", "not_reported"}:
                continue
            for replacement in ("probably_yes", "probably_no"):
                alternative_answers = {
                    key: value.get("answer")
                    for key, value in answer_items.items()
                    if isinstance(value.get("answer"), str)
                }
                alternative_answers[question_id] = replacement
                alternative: dict[str, Any] = {
                    "domain_id": domain.id,
                    "question_id": question_id,
                    "from_answer": answer_item.get("answer"),
                    "to_answer": replacement,
                    "diagnostic_only": True,
                    "hypothetical_domain_judgment": None,
                    "hypothetical_overall": None,
                }
                try:
                    (
                        projected_answers,
                        _alternative_active,
                        missing_active,
                    ) = _counterfactual_answer_branch(
                        domain.id,
                        alternative_answers,
                        question_id,
                        replacement,
                    )
                    if missing_active:
                        alternative["status"] = "requires_reassessment"
                        alternative["reason"] = _counterfactual_missing_reason(missing_active)
                    else:
                        domain_evaluation = evaluate_domain(domain.id, projected_answers)
                        hypothetical_judgments = dict(judgments)
                        hypothetical_judgments[domain.id] = domain_evaluation.judgment.value
                        alternative["status"] = "evaluated"
                        alternative["reason"] = None
                        alternative["hypothetical_domain_judgment"] = (
                            domain_evaluation.judgment.value
                        )
                        alternative["hypothetical_overall"] = evaluate_overall(
                            hypothetical_judgments
                        ).judgment.value
                except (KeyError, TypeError, ValueError) as error:
                    alternative["status"] = "requires_reassessment"
                    alternative["reason"] = str(error)
                alternatives.append(alternative)

    evaluated_overalls = {
        item.get("hypothetical_overall")
        for item in alternatives
        if item.get("status") == "evaluated"
    }
    has_pending = any(item.get("status") == "requires_reassessment" for item in alternatives)
    current_overall = overall_evaluation.judgment.value
    if not alternatives:
        stability = "not_assessed"
    elif any(value != current_overall for value in evaluated_overalls):
        stability = "sensitive"
    elif has_pending:
        stability = "requires_reassessment"
    else:
        stability = "stable"
    return {
        "rule": overall_evaluation.trace[0],
        "driver_domains": list(overall_evaluation.driver_domains),
        "drivers": driver_rows,
        "alternatives": alternatives,
        "stability": stability,
        "diagnostic_only": True,
    }


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
    workspace: str | Path,
    draft: dict[str, Any] | DomainDraft,
    *,
    validate_only: bool = False,
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
        raise ValueError("Trial is closed; Domain revisions are not allowed")
    if disposition == "reviewable" and not existing_domain:
        raise ValueError("Trial is ready for review; all required Domain checkpoints already exist")
    active_trial, _ = _active_trial_and_domain(state)
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
    if disposition not in {"pending", "reviewable", "assessed"}:
        raise ValueError("Trial is not available for Domain assessment")
    if state.get("phase") == "assessment" and not trial_has_checkpoint:
        notes = working_checkpoint_status(root, state, parsed.trial_id)
        recovery = (
            None
            if notes.get("status") == "current"
            else _main_report_recovery(root, state, parsed.trial_id)
        )
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
    allowed = {
        question.id: {answer.value for answer in question.allowed_answers}
        for question in questions_by_id.values()
    }
    answer_items = list(parsed.answers)
    items_by_question: dict[str, list[tuple[int, Any]]] = {}
    for index, item in enumerate(answer_items):
        items_by_question.setdefault(item.question_id, []).append((index, item))
    repairs: list[dict[str, Any]] = []
    for question_id, items in items_by_question.items():
        if question_id in questions_by_id:
            permitted = allowed[question_id]
            for index, item in items:
                if item.answer.value not in permitted:
                    repairs.append(
                        _repair(
                            f"/answers/{index}/answer",
                            "invalid_answer",
                            f"Submitted answer '{item.answer.value}' is not allowed for question "
                            f"'{question_id}'. Current choices are: "
                            f"{', '.join(sorted(permitted))}. "
                            "Choose only if supported by your evidence; this repair does not alter "
                            "the submitted proposition.",
                        )
                    )
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
            resolved = item.answer.value
            if resolved not in allowed[question_id]:
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
                uncertainty_basis = True
                if basis.get("search_receipt") is not None:
                    try:
                        receipt = _search_receipt(root, basis["search_receipt"])
                        if receipt.get("trial_id") != parsed.trial_id:
                            raise ValueError("search receipt is outside the Trial")
                        basis["search_receipt"] = receipt["identity"]
                        search_accounts[receipt["identity"]] = receipt
                    except (KeyError, ValueError) as error:
                        repairs.append(
                            _repair(
                                f"{path}/search_receipt",
                                "invalid_search_receipt",
                                f"question '{answer_item.question_id}' has an invalid "
                                "search receipt "
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
                            "absence requires an untruncated no-hit search with total_matches=0. "
                            "Continue the returned next_cursor first when deeper ranked passages "
                            "could resolve the premise; change the query only when its wording "
                            "or the premise warrants it."
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
                    "Evidence basis. The submitted answer is unchanged; add the required "
                    "support or reconsider the answer from the evidence.",
                )
            )
        elif answer["answer"] in {"probably_yes", "probably_no"} and not (
            direct_basis or uncertainty_basis
        ):
            repairs.append(
                _repair(
                    f"/answers/{answer_index}/bases",
                    "answer_requires_uncertainty_basis",
                    f"the submitted probable answer '{answer['answer']}' needs direct evidence, "
                    "a limitation, a valid scoped no-hit receipt, or an exact context/inference "
                    "premise. The submitted answer is unchanged.",
                )
            )
        if answer["answer"] in {"yes", "no"} and any(
            item.get("kind") == "limitation" for item in bases
        ):
            repairs.append(
                _repair(
                    f"/answers/{answer_index}/bases",
                    "complete_claim_has_unresolved_premise",
                    "a definitive claim cannot be saved while a required premise is unresolved; "
                    "use a probable answer or resolve the limitation first.",
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
    record = {
        "trial_id": parsed.trial_id,
        "domain_id": parsed.domain_id,
        "result_identity": _identity(_approved_result(state, parsed.trial_id)),
        "answers": canonical_answers,
        "supersedes": parsed.supersedes,
        "revision_basis": revision_basis,
        "search_accounts": [search_accounts[key] for key in sorted(search_accounts)],
        "active_questions": active,
        "inactive_questions": [key for key in allowed if key not in active],
        "judgment": evaluation.judgment.value,
        "trace": list(evaluation.trace),
        "driver_questions": list(evaluation.driver_questions),
        "observed_at": datetime.now(UTC).isoformat(),
    }
    record["evidence_sufficiency"] = _evidence_sufficiency(canonical_answers, search_accounts)
    record["identity"] = _domain_identity(record)
    prior_observed_at = _canonical_observed_at(root, record["identity"])
    if prior_observed_at is not None:
        record["observed_at"] = prior_observed_at
    rows = dict(state.get("domain_records", {}))
    if rows.get(key, {}).get("identity") == record["identity"]:
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
                        "a changed Domain save requires a revision_basis of kind "
                        "'new_evidence', 'self_correction', or 'mechanical_repair'."
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
    current_revision = int(state.get("revision", 0))
    proposal_review = state.get("proposal_review")
    proposal_basis = (
        proposal_review.get("workflow_basis") if isinstance(proposal_review, dict) else None
    )
    if (
        validate_only
        and isinstance(proposal_basis, int)
        and parsed.expected_revision < proposal_basis
    ):
        return _result(
            "condition",
            state,
            condition={
                "code": "result_scope_stale",
                "detail": "Reload this Domain context after the approved Result changed.",
            },
        )
    if parsed.expected_revision != current_revision:
        raise WorkflowConflict(parsed.expected_revision, int(state.get("revision", 0)))

    if validate_only:
        return _result(
            "success",
            state,
            checkpoint=record,
            active_question_ids=active,
            validation_scope="structure_and_references_only",
        )

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
    trial_reviews = dict(state.get("trial_reviews", {}))
    trial_reviews.pop(parsed.trial_id, None)
    state["trial_reviews"] = trial_reviews
    snapshot: dict[str, Any] | None = None
    if all(f"{parsed.trial_id}:{item.id}" in rows for item in SCIENTIFIC_PACK.domains):
        checkpoints = [
            rows[f"{parsed.trial_id}:{item.id}"]["identity"] for item in SCIENTIFIC_PACK.domains
        ]
        judgments = {
            item.id: rows[f"{parsed.trial_id}:{item.id}"]["judgment"]
            for item in SCIENTIFIC_PACK.domains
        }
        overall_evaluation = evaluate_overall(judgments)
        snapshot = {
            "trial_id": parsed.trial_id,
            "result_identity": _identity(_approved_result(state, parsed.trial_id)),
            "checkpoints": checkpoints,
            "domain_judgments": judgments,
            "overall": overall_evaluation.judgment.value,
            "overall_trace": list(overall_evaluation.trace),
            "overall_driver_domains": list(overall_evaluation.driver_domains),
            "overall_receipt": _overall_receipt(
                parsed.trial_id,
                rows,
                judgments,
                overall_evaluation,
            ),
        }
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
                parsed.trial_id: "reviewable",
            },
        }
    current_dispositions = state.get("trial_dispositions")
    dispositions = current_dispositions if isinstance(current_dispositions, dict) else {}
    if not any(value in {"pending", "reviewable"} for value in dispositions.values()):
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
        trial_ready_for_review=snapshot is not None,
        continuation=_continuation(state),
    )


def validate_domain_assessment(
    workspace: str | Path, draft: dict[str, Any] | DomainReasoningDraft
) -> dict[str, Any]:
    """Validate and persist one mandatory, source-bound Domain reasoning record."""
    root = _root(workspace)
    _ensure(root)
    state = _state(root)
    try:
        parsed = (
            draft
            if isinstance(draft, DomainReasoningDraft)
            else DomainReasoningDraft.model_validate(draft)
        )
    except ValidationError as error:
        return _result("repair", state, repairs=_repairs(error))

    payload = parsed.model_dump(mode="json")
    reasoning_id = _identity({"kind": "domain_reasoning", "draft": payload})
    records = state.get("reasoning_records")
    prior = records.get(reasoning_id) if isinstance(records, dict) else None
    if isinstance(prior, dict):
        if not _domain_reasoning_matches_current(root, prior, state):
            return _result(
                "condition",
                state,
                condition={
                    "code": "reasoning_stale",
                    "detail": (
                        "The Domain receipt is stale. Refresh the explicit Trial and Domain, "
                        "complete every returned context page, revalidate the complete draft, "
                        "and save the returned receipt. Otherwise follow head.next_action."
                    ),
                },
            )
        return _reasoning_receipt(state, prior)

    current_revision = int(state.get("revision", 0))
    if parsed.expected_revision != current_revision:
        raise WorkflowConflict(parsed.expected_revision, int(state.get("revision", 0)))
    delivery = _domain_context_delivery(root, parsed.trial_id, parsed.domain_id, None)
    if delivery is not None:
        preview_scope = delivery.get("preview_scope")
        premise_status = working_checkpoint_status(root, state, parsed.trial_id)
        current_basis = _domain_context_basis_identity(
            state,
            parsed.trial_id,
            parsed.domain_id,
            preview_scope if isinstance(preview_scope, list) else None,
            premise_status,
        )
        if delivery.get("basis_identity") != current_basis:
            return _result(
                "condition",
                state,
                condition={
                    "code": "domain_context_delivery_stale",
                    "detail": (
                        "The approved Result, RoB 2 pack, current Domain checkpoint, or preview "
                        "changed. Restart get_domain_context before validating this assessment."
                    ),
                },
            )
    if delivery is not None and not bool(delivery.get("complete")):
        next_cursor = delivery.get("next_cursor")
        if not isinstance(next_cursor, str) or not next_cursor:
            return _result(
                "condition",
                state,
                condition={
                    "code": "domain_context_delivery_invalid",
                    "detail": "The Domain context delivery is unrecoverable. Report the failure.",
                },
            )
        return _result(
            "condition",
            state,
            condition={
                "code": "domain_context_delivery_pending",
                "detail": "Fetch the complete Domain context before reasoning about this draft.",
                "recovery": {
                    "operation": "get_domain_context",
                    "arguments": {
                        "trial_id": parsed.trial_id,
                        "domain_id": parsed.domain_id,
                        "cursor": next_cursor,
                        "max_response_bytes": delivery["page_size"],
                    },
                },
            },
        )

    validation = save_domain_judgment(root, payload, validate_only=True)
    if validation.get("outcome") != "success":
        return validation
    checkpoint = validation.get("checkpoint")
    if not isinstance(checkpoint, dict):
        raise ValueError("validated Domain reasoning is missing its checkpoint")
    predecessor = (state.get("domain_records") or {}).get(f"{parsed.trial_id}:{parsed.domain_id}")
    active_ids = set(checkpoint.get("active_questions", ()))
    reasoning_repairs: list[dict[str, Any]] = []
    for answer_index, answer in enumerate(parsed.answers):
        if answer.question_id not in active_ids:
            continue
        if answer.justification is None:
            reasoning_repairs.append(
                _repair(
                    f"/answers/{answer_index}/justification",
                    "justification_required",
                    "Every active answer needs a concise source-bound justification.",
                )
            )
        if answer.unknowns is None:
            reasoning_repairs.append(
                _repair(
                    f"/answers/{answer_index}/unknowns",
                    "unknowns_required",
                    "Every active answer needs an unknowns array; use [] when none are identified.",
                )
            )
        if answer.counterevidence is None:
            reasoning_repairs.append(
                _repair(
                    f"/answers/{answer_index}/counterevidence",
                    "counterevidence_required",
                    (
                        "Every active answer needs a counterevidence array; use [] when none "
                        "are identified."
                    ),
                )
            )
            continue
        counterevidence_indexes = {item.basis_index for item in answer.counterevidence}
        for item in answer.counterevidence:
            if item.basis_index >= len(answer.bases):
                reasoning_repairs.append(
                    _repair(
                        f"/answers/{answer_index}/counterevidence",
                        "counterevidence_basis_index_invalid",
                        (
                            f"basis_index {item.basis_index} does not reference a basis "
                            "in this answer."
                        ),
                    )
                )
        for basis_index, basis in enumerate(answer.bases):
            if basis.kind == "contradiction" and basis_index not in counterevidence_indexes:
                reasoning_repairs.append(
                    _repair(
                        f"/answers/{answer_index}/counterevidence",
                        "contradiction_counterevidence_required",
                        (
                            f"basis {basis_index} is a contradiction and needs a "
                            "counterevidence implication."
                        ),
                    )
                )
    if reasoning_repairs:
        return _result("repair", state, repairs=reasoning_repairs)
    record = {
        "kind": "domain_reasoning",
        "identity": reasoning_id,
        "trial_id": parsed.trial_id,
        "domain_id": parsed.domain_id,
        "draft": payload,
        "checkpoint_identity": checkpoint["identity"],
        "predecessor_identity": (
            predecessor.get("identity") if isinstance(predecessor, dict) else None
        ),
        "result_identity": checkpoint["result_identity"],
        "pack_identity": _pack_identity(),
        "active_question_ids": list(checkpoint["active_questions"]),
        "validation_scope": "structure_and_references_only",
        "created_revision": current_revision,
        "save_revision": current_revision + 1,
    }
    reasoning_records = dict(records) if isinstance(records, dict) else {}
    reasoning_records[reasoning_id] = record
    committed = _commit_records(
        root,
        {**state, "reasoning_records": reasoning_records},
        current_revision,
        {f"reasoning:{reasoning_id}": record},
    )
    receipt = _reasoning_receipt(committed, record)
    receipt["investigation"] = investigation_projection(
        root,
        committed,
        parsed.trial_id,
        parsed.domain_id,
        workflow_permission={
            "permitted": True,
            "operation": "save_domain_judgment",
            "authority": "host",
            "detail": (
                "The structurally validated draft may be saved; this permission does not "
                "establish scientific sufficiency."
            ),
        },
        sufficiency=_investigation_sufficiency(checkpoint.get("evidence_sufficiency")),
    )
    return receipt


def _reasoning_receipt(state: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    next_action = {
        "trial_id": record["trial_id"],
        "domain_id": record["domain_id"],
        "expected_revision": record["save_revision"],
    }
    continuation = {
        "operation": "save_domain_judgment",
        "authority": "host",
        **next_action,
    }
    return _result(
        "success",
        state,
        active_question_ids=record["active_question_ids"],
        validation_scope=record["validation_scope"],
        repairs=[],
        next_action=next_action,
        continuation=continuation,
    )


def _domain_reasoning_matches_current(
    root: Path, record: dict[str, Any], state: dict[str, Any] | None = None
) -> bool:
    draft = record.get("draft")
    if (
        not isinstance(draft, dict)
        or record.get("pack_identity") != _pack_identity()
        or record.get("result_identity") is None
    ):
        return False
    state = state if state is not None else _state(root)
    current = (state.get("domain_records") or {}).get(
        f"{record.get('trial_id')}:{record.get('domain_id')}"
    )
    current_identity = current.get("identity") if isinstance(current, dict) else None
    if current_identity not in {
        record.get("predecessor_identity"),
        record.get("checkpoint_identity"),
    }:
        return False
    if _identity(_approved_result(state, str(record["trial_id"]))) != record["result_identity"]:
        return False
    if int(state.get("revision", 0)) == record.get("save_revision"):
        return True

    draft = {**draft, "expected_revision": int(state.get("revision", 0))}
    validation = save_domain_judgment(root, draft, validate_only=True)
    checkpoint = validation.get("checkpoint")
    if (
        validation.get("outcome") != "success"
        or not isinstance(checkpoint, dict)
        or checkpoint.get("identity") != record.get("checkpoint_identity")
        or checkpoint.get("result_identity") != record.get("result_identity")
    ):
        return False
    return True


def get_domain_context(
    workspace: str | Path,
    trial_id: str | None = None,
    domain_id: str | None = None,
    preview_missing_data: list[dict[str, Any]] | None = None,
    include_candidates: bool = False,
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
    if domain_id is None:
        domain_id = active_domain
    if domain_id is None:
        raise ValueError("no Domain is available")
    if domain_id not in {item.id for item in SCIENTIFIC_PACK.domains}:
        raise ValueError("unknown Domain")
    result = _approved_result(state, trial_id)
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
    premise_status = working_checkpoint_status(root, state, trial_id)
    checkpoint_identity = existing.get("identity") if isinstance(existing, dict) else None
    if not isinstance(checkpoint_identity, str):
        checkpoint_identity = None
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
    result_handles.update(
        span.get("handle")
        for item in result.get("evidence", [])
        if isinstance(item, dict) and item.get("kind") == "table_multispan"
        for span in item.get("spans", [])
        if isinstance(span, dict) and isinstance(span.get("handle"), str)
    )
    applicability = result.get("applicability")
    if isinstance(applicability, dict):
        result_handles.update(
            handle for handle in applicability.get("evidence", []) if isinstance(handle, str)
        )
    result_handles.update(
        basis.get("evidence")
        for fact in result.get("missing_facts", [])
        if isinstance(fact, dict)
        and isinstance((basis := fact.get("basis")), dict)
        and isinstance(basis.get("evidence"), str)
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
    # Search rank/session are disposable discovery associations.  Evidence
    # records intentionally never carry them: selecting the same Source span
    # through another query must retain its exact Evidence identity.
    associated_rows = _associated_search_evidence(root, trial_id, domain_id)
    associated_identities = {identity for identity, _session, _rank in associated_rows}
    unassigned_rows = _unassigned_search_evidence(root, trial_id)
    search_evidence_identities = _search_evidence_identities(root, trial_id)
    explicit_carry_forward = [
        value
        for value in disposable.values()
        if isinstance(value, dict)
        and value.get("identity") not in associated_identities
        and value.get("identity") not in search_evidence_identities
        and value.get("handle") not in result_handles
        and value.get("identity") not in checkpoint_identities
    ]
    associated = [
        {
            **value,
            "search_session": session_identity,
            "candidate_rank": rank,
        }
        for identity, session_identity, rank in associated_rows
        for value in (disposable.get(identity),)
        if isinstance(value, dict) and (session_identity, rank) in associated_ranks
    ]
    unassigned = [
        {
            **value,
            "search_session": session_identity,
            "candidate_rank": rank,
        }
        for identity, session_identity, rank in unassigned_rows
        for value in (disposable.get(identity),)
        if isinstance(value, dict)
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
    unassigned.sort(
        key=lambda value: (
            str(value.get("search_session")),
            int(value.get("candidate_rank", 2**31 - 1)),
            str(value.get("source_id")),
            int(value.get("page", 0)),
            int(value.get("start", 0)),
            str(value.get("identity")),
        )
    )

    # Repeated searches can materialize the same exact passage under distinct
    # disposable session identities. Keep one visible copy without merging
    # partial overlaps or changing any source-bound quote.
    def exact_span_key(value: dict[str, Any]) -> tuple[Any, ...]:
        """Deduplicate only a source-versioned raw span, never a line window."""

        if value.get("kind") == "narrative" and all(
            value.get(key) is not None
            for key in ("source_id", "source_version", "page", "start", "end")
        ):
            return (
                "narrative",
                value["source_id"],
                value["source_version"],
                value["page"],
                value["start"],
                value["end"],
            )
        return ("identity", value.get("identity"))

    seen_coordinates: set[tuple[Any, ...]] = {
        exact_span_key(value) for value in proposal_catalog.values() if isinstance(value, dict)
    }

    def unique_passages(values: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
        unique: list[dict[str, Any]] = []
        duplicates = 0
        for value in values:
            key = exact_span_key(value)
            if key in seen_coordinates:
                duplicates += 1
                continue
            seen_coordinates.add(key)
            unique.append(value)
        return unique, duplicates

    associated, associated_duplicates = unique_passages(associated)
    explicit_carry_forward, explicit_duplicates = unique_passages(explicit_carry_forward)
    unassigned, unassigned_duplicates = unique_passages(unassigned)
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
    selected_recoverable_explicit = (
        recoverable_explicit[:projection_budget] if include_candidates else []
    )
    selected_explicit = [*unrecoverable_explicit, *selected_recoverable_explicit]
    remaining_budget = projection_budget - len(selected_recoverable_explicit)
    selected_candidates = associated[:remaining_budget] if include_candidates else []
    remaining_budget -= len(selected_candidates)
    selected_discoveries = unassigned[:remaining_budget] if include_candidates else []
    omitted_explicit = (
        recoverable_explicit[len(selected_recoverable_explicit) :]
        if include_candidates
        else recoverable_explicit
    )
    omitted_discoveries = (
        unassigned[len(selected_discoveries) :] if include_candidates else unassigned
    )
    included_candidate_ranks = {
        (value["search_session"], value["candidate_rank"]) for value in selected_candidates
    }
    unassigned_ranks = {
        (session_identity, rank) for _identity, session_identity, rank in unassigned_rows
    }
    included_discovery_ranks = {
        (value["search_session"], value["candidate_rank"]) for value in selected_discoveries
    }
    omitted_candidate_ranks = associated_ranks - included_candidate_ranks
    omitted_evidence_count = (
        len(omitted_candidate_ranks) + len(omitted_explicit) + len(omitted_discoveries)
    )
    omitted_by_category = {
        "result": 0,
        "checkpoint": 0,
        "contradiction": 0,
        "active_domain_candidate": len(omitted_candidate_ranks),
        "explicit_carry_forward": len(omitted_explicit),
        "trial_discovery": len(omitted_discoveries),
        "deduplicated": associated_duplicates + explicit_duplicates + unassigned_duplicates,
    }
    catalog = dict(proposal_catalog)
    for value in [*selected_candidates, *selected_discoveries, *selected_explicit]:
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
        elif (
            isinstance(value.get("search_session"), str)
            and isinstance(value.get("candidate_rank"), int)
            and (value["search_session"], value["candidate_rank"]) in unassigned_ranks
        ):
            value.setdefault("inclusion_reason", "trial_discovery")
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
    evidence_continuations.extend(
        _unassigned_search_continuation(
            root,
            trial_id,
            included_discovery_ranks,
            projection_budget,
        )
    )
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
        "trial_discovery",
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
            if evidence_item.get("kind") == "table_multispan":
                spans = []
                for span in evidence_item.get("spans", []):
                    if not isinstance(span, dict) or not isinstance(span.get("handle"), str):
                        raise ValueError("Result multi-span table Evidence is malformed")
                    selected = next(
                        (item for item in catalog.values() if item.get("handle") == span["handle"]),
                        None,
                    )
                    if not isinstance(selected, dict):
                        raise ValueError("Result multi-span table Evidence handle is unavailable")
                    spans.append(
                        {
                            "role": span.get("role"),
                            "handle": span["handle"],
                            "identity": selected["identity"],
                            "source_id": selected["source_id"],
                            "page": selected.get("page", selected.get("render", {}).get("page")),
                            "start": selected.get("start", 0),
                            "end": selected.get("end", 0),
                            "start_line": selected.get("start_line"),
                            "end_line": selected.get("end_line"),
                        }
                    )
                references.append(
                    {
                        "kind": "table_multispan",
                        "basis": evidence_item.get("basis"),
                        "spans": spans,
                    }
                )
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
        "operation": "validate_domain_assessment",
        "authority": "host",
        "trial_id": trial_id,
        "domain_id": domain_id,
        "expected_revision": int(state.get("revision", 0)),
        "caller_inputs": ["answers"],
    }
    # A correction continuation names the exact active checkpoint to replace.
    # The model therefore never has to infer a parent from the historical
    # digest list, and a stale or unrelated checkpoint cannot be selected by
    # guessing.
    if isinstance(existing, dict) and isinstance(existing.get("identity"), str):
        continuation["supersedes"] = existing["identity"]
        continuation["caller_inputs"] = [
            "answers",
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
        "pack": {
            "id": SCIENTIFIC_PACK.id,
            "version": SCIENTIFIC_PACK.version,
            "content_hash": SCIENTIFIC_PACK.content_hash,
        },
        "official_guidance": _official_guidance_recovery(domain_id),
        "state_revision": state.get("revision", 0),
        "result": result_projection(result),
        "evidence": list(catalog.values()),
        "answers": answer_rows,
        "investigation": investigation_projection(
            root,
            state,
            trial_id,
            domain_id,
            workflow_permission={
                "permitted": True,
                "operation": "validate_domain_assessment",
                "authority": "host",
                "detail": (
                    "The Domain draft may be structurally validated; this permission does not "
                    "establish scientific sufficiency."
                ),
            },
        ),
        "working_checkpoint": _domain_premise_status(premise_status),
        "evidence_sufficiency": _host_asserted_sufficiency(
            existing.get("evidence_sufficiency") if isinstance(existing, dict) else None
        ),
        "current_checkpoint": checkpoint_identity,
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
                "options": [answer.value for answer in item.allowed_answers],
                "activation_status": (
                    "always_active"
                    if item.activation.kind == "always"
                    else "dependent_on_draft_answers"
                    if checkpoint_identity is None
                    else (
                        "active_in_saved_checkpoint"
                        if item.id in active
                        else "inactive_in_saved_checkpoint"
                    )
                ),
                "activation": item.activation.model_dump(mode="json"),
                "official_guidance": item.guidance.official.source_excerpt,
                "source_locator": item.guidance.official.source_locator,
                "bias_construct": item.guidance.operational.bias_construct,
                "decision_rule": item.guidance.operational.decision_rule,
                "evidence_needed": item.guidance.operational.evidence_needed,
                "no_information_rule": item.guidance.operational.no_information_rule,
                "answer_anchors": tuple(
                    anchor.model_dump(mode="json")
                    for anchor in item.guidance.operational.answer_anchors
                ),
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
            "selection_policy_version": "rob2-kit.domain-projection.v0.7",
            "groups": workspace_groups,
            "omitted_count": omitted_evidence_count if include_candidates else 0,
            "omitted_by_category": omitted_by_category
            if include_candidates
            else {
                "result": 0,
                "checkpoint": 0,
                "contradiction": 0,
                "active_domain_candidate": 0,
                "explicit_carry_forward": 0,
                "trial_discovery": 0,
                "deduplicated": 0,
            },
            "continuation": evidence_continuation if include_candidates else None,
            "continuations": evidence_continuations if include_candidates else [],
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
        "coverage": _source_coverage(
            trial_id,
            trial_sources,
            catalog,
            _coverage_search_accounts(
                root,
                trial_id,
                domain_id,
                {
                    item.get("identity"): item
                    for item in (
                        existing.get("search_accounts", []) if isinstance(existing, dict) else []
                    )
                    if isinstance(item, dict) and isinstance(item.get("identity"), str)
                },
            ),
        ),
        "reading_recovery": (
            (
                None
                if working_checkpoint_status(root, state, trial_id).get("status") == "current"
                else _main_report_recovery(root, state, trial_id, include_budget=True)
            )
            if not trial_has_checkpoint
            else None
        ),
        "continuation": continuation,
    }
    projected = _compact_domain_evidence(context)
    projected["_context_basis_identity"] = _domain_context_basis_identity(
        state, trial_id, domain_id, preview_missing_data, premise_status
    )
    return projected

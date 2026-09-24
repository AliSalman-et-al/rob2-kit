"""Reviewable and immutable Trial lifecycle transitions."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..packs import SCIENTIFIC_PACK
from ..workflow_models import NeedsInputTerminalRequest, TrialClosureRequest, TrialReviewRequest
from ._state import _commit_records, _ensure, _identity, _result, _root, _state
from .contracts import WorkflowConflict
from .finalization import _valid_proposal_gate
from .status import _active_trial_and_domain, _continuation

_OUT_OF_SCOPE_DESIGNS = {"cluster_randomized", "crossover"}

_REVIEW_CONFLICT_MARKERS = {
    "population_mismatch": ("population mismatch", "different population", "population differs"),
    "endpoint_mismatch": ("endpoint mismatch", "different endpoint", "endpoint differs"),
    "window_mismatch": ("window mismatch", "different window", "window differs"),
    "chronology_conflict": ("chronology conflict", "chronology mismatch", "chronology differs"),
}
_REVIEW_FACT_TEXT_LIMIT = 4_000
_REVIEW_FACT_EXCERPT_MARKER = " … [excerpt; use evidence_expansions to inspect full Evidence]"


def _approved_result(state: dict[str, Any], trial_id: str) -> dict[str, Any]:
    results = (state.get("proposal") or {}).get("payload", {}).get("results", [])
    result = next(
        (item for item in results if isinstance(item, dict) and item.get("trial_id") == trial_id),
        None,
    )
    if not isinstance(result, dict):
        raise ValueError("approved Result is unavailable")
    return result


def _checkpoint_ids(state: dict[str, Any], trial_id: str) -> list[str]:
    records = state.get("domain_records") or {}
    return [
        records[f"{trial_id}:{domain.id}"]["identity"]
        for domain in SCIENTIFIC_PACK.domains
        if isinstance(records.get(f"{trial_id}:{domain.id}"), dict)
    ]


def _domain_attribution(state: dict[str, Any], trial_id: str) -> list[dict[str, Any]]:
    """Summarize the stored basis of each current Domain checkpoint."""

    records = state.get("domain_records") or {}
    summary: list[dict[str, Any]] = []
    for domain in SCIENTIFIC_PACK.domains:
        record = records.get(f"{trial_id}:{domain.id}")
        if not isinstance(record, dict) or not isinstance(record.get("identity"), str):
            continue
        basis = record.get("revision_basis")
        kind = basis.get("kind") if isinstance(basis, dict) else None
        attribution = (
            kind
            if kind
            in {
                "new_evidence",
                "self_correction",
                "mechanical_repair",
            }
            else "unchanged"
        )
        item: dict[str, Any] = {
            "domain_id": domain.id,
            "attribution": attribution,
            "checkpoint_identity": record["identity"],
        }
        if isinstance(record.get("supersedes"), str):
            item["supersedes"] = record["supersedes"]
        if isinstance(basis, dict) and attribution != "unchanged":
            item["revision_basis"] = dict(basis)
        summary.append(item)
    return summary


def _review_domain_findings(
    root: Path, state: dict[str, Any], trial_id: str
) -> list[dict[str, Any]]:
    """Project current checkpoint support without creating a second answer authority."""

    from .evidence import _evidence_catalog, _search_receipt

    try:
        evidence_by_identity = _evidence_catalog(root, trial_id=trial_id)
    except ValueError:
        # Review remains useful when a disposable handle cache is damaged; the
        # checkpoint identities and answer text are still authoritative, while
        # the missing expansion is left for the ordinary recovery path.
        evidence_by_identity = {}
    records = state.get("domain_records") or {}
    # Working premise notes are reusable only while their own checkpoint still
    # matches the approved Result and captured Source projection.  A stale
    # checkpoint is deliberately absent from final review rather than being
    # treated as a prior Domain judgment.
    from .working import (
        _stored_checkpoint,
        investigation_projection,
        working_checkpoint_status,
    )

    premise_status = working_checkpoint_status(root, state, trial_id)
    premise_checkpoint = (
        premise_status.get("checkpoint") if premise_status.get("status") == "current" else None
    )
    if premise_checkpoint is None and premise_status.get("reason") == "canonical_newer":
        stored = _stored_checkpoint(root, state, trial_id)
        premise_checkpoint = (
            stored.model_dump(mode="json", exclude_none=True) if stored is not None else None
        )
    premise_checkpoint_identity = (
        premise_status.get("checkpoint_identity") if isinstance(premise_checkpoint, dict) else None
    )

    def evidence_reference(identity: object) -> dict[str, str] | None:
        if not isinstance(identity, str):
            return None
        evidence = evidence_by_identity.get(identity)
        if not isinstance(evidence, dict) or not isinstance(evidence.get("handle"), str):
            return None
        return {"handle": evidence["handle"], "identity": identity}

    def evidence_text(identity: object, basis: dict[str, Any]) -> str | None:
        source = basis.get("source")
        if isinstance(source, str) and source.strip():
            text = source
        else:
            evidence = evidence_by_identity.get(identity) if isinstance(identity, str) else None
            if not isinstance(evidence, dict):
                return None
            values: list[str] = []
            for key in (
                "quote",
                "transcription",
                "title",
                "scope",
                "cohort",
                "row",
                "value",
                "event_definition",
            ):
                value = evidence.get(key)
                if isinstance(value, str) and value.strip():
                    values.append(value)
            for key in ("columns", "group_or_category_axes", "cells", "units", "denominators"):
                values.extend(value for value in evidence.get(key, ()) if isinstance(value, str))
            text = " | ".join(values)
        if not text:
            return None
        if len(text) > _REVIEW_FACT_TEXT_LIMIT:
            text = (
                text[: _REVIEW_FACT_TEXT_LIMIT - len(_REVIEW_FACT_EXCERPT_MARKER)].rstrip()
                + _REVIEW_FACT_EXCERPT_MARKER
            )
        return text

    def report_evidence(reports: list[dict[str, Any]]) -> tuple[dict[str, str], ...]:
        references: list[dict[str, str]] = []
        seen: set[str] = set()
        for report in reports:
            for identity in report.get("basis", ()):
                reference = evidence_reference(identity)
                if reference is not None and reference["identity"] not in seen:
                    seen.add(reference["identity"])
                    references.append(reference)
        return tuple(references)

    def structured_scope_conflicts(answer: dict[str, Any]) -> list[dict[str, Any]]:
        missing_data = answer.get("missing_data")
        raw_conflicts = missing_data.get("conflicts", ()) if isinstance(missing_data, dict) else ()
        conflicts: list[dict[str, Any]] = []
        for raw_conflict in raw_conflicts:
            if not isinstance(raw_conflict, dict):
                continue
            reports = [item for item in raw_conflict.get("reports", ()) if isinstance(item, dict)]
            if len(reports) < 2:
                continue
            dimensions: list[tuple[str, list[object]]] = []
            dimensions.append(
                (
                    "population_mismatch",
                    [
                        item.get("scope", {}).get("population")
                        for item in reports
                        if isinstance(item.get("scope"), dict)
                    ],
                )
            )
            dimensions.extend(
                (
                    kind,
                    [item.get(field) for item in reports],
                )
                for kind, field in (
                    ("endpoint_mismatch", "endpoint"),
                    ("window_mismatch", "window"),
                )
            )
            found = False
            for kind, values in dimensions:
                normalized = {str(value).strip() for value in values if value is not None}
                if len(normalized) > 1:
                    conflicts.append(
                        {
                            "kind": kind,
                            "detail": (
                                "Host-recorded reports disagree on the answer's "
                                f"{kind.removesuffix('_mismatch')} scope."
                            ),
                            "evidence": report_evidence(reports),
                        }
                    )
                    found = True
            if not found:
                conflicts.append(
                    {
                        "kind": "contradiction",
                        "detail": (
                            "Host-recorded Evidence reports conflict within the answer scope."
                        ),
                        "evidence": report_evidence(reports),
                    }
                )
        return conflicts

    def host_scope_conflicts(
        answer: dict[str, Any], references: tuple[dict[str, str], ...]
    ) -> list[dict[str, Any]]:
        texts = [
            value
            for value in (
                answer.get("justification"),
                *(answer.get("unknowns") or ()),
                *(
                    item.get("implication")
                    for item in (answer.get("counterevidence") or ())
                    if isinstance(item, dict)
                ),
            )
            if isinstance(value, str)
        ]
        joined = " ".join(texts).lower()
        return [
            {
                "kind": kind,
                "detail": f"Host-reported {kind.replace('_', ' ')}.",
                "evidence": references,
            }
            for kind, markers in _REVIEW_CONFLICT_MARKERS.items()
            if any(marker in joined for marker in markers)
        ]

    def participant_flow_scope_conflicts(answer: dict[str, Any]) -> list[dict[str, Any]]:
        """Flag source-bound flow rows that visibly differ from the approved Result scope."""

        missing_data = answer.get("missing_data")
        rows = missing_data.get("rows", ()) if isinstance(missing_data, dict) else ()
        if not isinstance(rows, (list, tuple)):
            return []
        try:
            approved = _approved_result(state, trial_id)
        except ValueError:
            return []
        target_value = approved.get("target")
        target = target_value if isinstance(target_value, dict) else {}
        timing = target.get("time_point_or_window")
        expected_values = {
            "result identity": _identity(approved),
            "population": target.get("intended_analysis_population"),
            "endpoint": target.get("outcome_definition"),
            "window": timing.get("description") if isinstance(timing, dict) else None,
        }

        def comparable(value: object) -> str | None:
            if not isinstance(value, str) or not value.strip():
                return None
            return " ".join(value.casefold().split())

        conflicts: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            scope = row.get("scope") if isinstance(row.get("scope"), dict) else {}
            observed_values = {
                "result identity": row.get("result_identity"),
                "population": scope.get("population"),
                "endpoint": row.get("endpoint") or row.get("event_definition"),
                "window": row.get("window") or scope.get("time_point"),
            }
            differences = [
                field
                for field, expected in expected_values.items()
                if comparable(expected) is not None
                and comparable(observed_values[field]) is not None
                and comparable(expected) != comparable(observed_values[field])
            ]
            row_references = report_evidence([{"basis": row.get("basis", ())}])
            if differences and row_references:
                conflicts.append(
                    {
                        "kind": "potential_scope_mismatch",
                        "detail": (
                            "The server found source-bound participant-flow text differing from "
                            "the approved Result on: "
                            + ", ".join(differences)
                            + ". Interpret the cited passages before relying on these quantities."
                        ),
                        "assertion": "server_derived",
                        "evidence": row_references,
                    }
                )
        return conflicts

    def premise_routes(
        domain_id: str,
        answer: dict[str, Any],
        premise_records: tuple[dict[str, Any], ...],
        unread_ranges: tuple[dict[str, Any], ...],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        routes: list[dict[str, Any]] = []
        conflicts: list[dict[str, Any]] = []
        incomplete_searches: set[str] = set()
        for basis in answer.get("bases", ()):
            if not isinstance(basis, dict):
                continue
            handle = basis.get("search_receipt")
            if not isinstance(handle, str):
                continue
            receipt_handle = (
                "sr_" + handle.removeprefix("sha256:")[:16]
                if handle.startswith("sha256:")
                else handle
            )
            try:
                receipt = _search_receipt(root, receipt_handle)
            except (KeyError, ValueError):
                continue
            if (
                receipt.get("truncated")
                or receipt.get("next_cursor")
                or receipt.get("exhausted") is False
            ):
                incomplete_searches.add(handle)
        unresolved = any(
            isinstance(item, dict)
            and item.get("question_id") in {None, answer.get("question_id")}
            and item.get("status") in {"unresolved", "bounded", "contradiction"}
            for item in premise_records
        )
        if not unresolved:
            unresolved = any(item.get("kind") == "limitation" for item in answer.get("bases", ()))
        for basis in answer.get("bases", ()):
            if not isinstance(basis, dict) or basis.get("kind") != "limitation":
                continue
            receipt = basis.get("search_receipt")
            if isinstance(receipt, str) and receipt in incomplete_searches:
                routes.append(
                    {
                        "operation": "search_sources",
                        "detail": (
                            "Continue or reformulate the scoped search before treating the "
                            "limitation as closed."
                        ),
                        "search_receipt": receipt,
                    }
                )
        if unresolved and (unread_ranges or incomplete_searches):
            for premise in premise_records:
                if not isinstance(premise, dict):
                    continue
                if premise.get("question_id") not in {None, answer.get("question_id")}:
                    continue
                next_action = premise.get("next_action")
                if isinstance(next_action, str) and next_action.strip():
                    routes.append(
                        {
                            "operation": "search_sources",
                            "detail": next_action,
                        }
                    )
            if not routes and unread_ranges:
                routes.append(
                    {
                        "operation": "read_pages",
                        "detail": (
                            "Read the accessible unread Source range before accepting this "
                            "limitation."
                        ),
                    }
                )
        unique_routes: list[dict[str, Any]] = []
        seen_routes: set[tuple[object, object, object]] = set()
        for route in routes:
            key = (route.get("operation"), route.get("detail"), route.get("search_receipt"))
            if key in seen_routes:
                continue
            seen_routes.add(key)
            unique_routes.append(route)
            conflicts.append(
                {
                    "kind": "accessible_uninvestigated_route",
                    "detail": str(route["detail"]),
                    "evidence": [],
                }
            )
        return unique_routes, conflicts

    findings: list[dict[str, Any]] = []
    for domain in SCIENTIFIC_PACK.domains:
        record = records.get(f"{trial_id}:{domain.id}")
        if not isinstance(record, dict) or not isinstance(record.get("identity"), str):
            continue
        answer_findings: list[dict[str, Any]] = []
        investigation = investigation_projection(
            root,
            state,
            trial_id,
            domain.id,
            workflow_permission={
                "permitted": True,
                "operation": "validate_domain_assessment",
                "authority": "host",
                "detail": (
                    "Revise this Domain through ordinary validation before refreshing Trial "
                    "review; review itself is not semantic approval."
                ),
            },
        )
        domain_premises: tuple[dict[str, Any], ...] = ()
        unread_ranges: tuple[dict[str, Any], ...] = ()
        if isinstance(premise_checkpoint, dict):
            domain_premises = tuple(
                item
                for item in premise_checkpoint.get("premise_records", ())
                if isinstance(item, dict) and item.get("domain_id") == domain.id
            )
            unread_ranges = tuple(
                item
                for item in premise_checkpoint.get("unread_ranges", ())
                if isinstance(item, dict)
            )
        if investigation is not None and investigation.get("stale"):
            domain_premises = tuple(
                {
                    **{
                        key: value
                        for key, value in item.items()
                        if key not in {"inference", "stopping_rationale"}
                    },
                    "status": "unresolved",
                    "unresolved_component": item.get("unresolved_component")
                    or "The prior inference must be revisited after the Domain revision.",
                }
                for item in domain_premises
            )
        for answer in record.get("answers", []):
            if not isinstance(answer, dict) or not isinstance(answer.get("question_id"), str):
                continue
            references: list[dict[str, Any]] = []
            basis_findings: list[dict[str, Any]] = []
            facts: list[dict[str, Any]] = []
            limitations: list[dict[str, Any]] = []
            expansions: list[dict[str, Any]] = []
            seen_evidence: set[str] = set()
            for basis_index, basis in enumerate(answer.get("bases", [])):
                if not isinstance(basis, dict) or not isinstance(basis.get("kind"), str):
                    continue
                basis_finding: dict[str, Any] = {
                    "kind": basis["kind"],
                    "assertion": "host_asserted",
                }
                evidence_identity = basis.get("evidence")
                fact_role = (
                    "counterevidence"
                    if basis["kind"] == "contradiction"
                    else "context"
                    if basis["kind"] in {"context", "inference", "absence", "limitation"}
                    else "support"
                )
                if isinstance(evidence_identity, str):
                    basis_finding["evidence"] = None
                    evidence = evidence_by_identity.get(evidence_identity)
                    if isinstance(evidence, dict) and isinstance(evidence.get("handle"), str):
                        handle = evidence["handle"]
                        basis_finding["evidence"] = {
                            "handle": handle,
                            "identity": evidence_identity,
                        }
                        if evidence_identity not in seen_evidence:
                            seen_evidence.add(evidence_identity)
                            references.append({"handle": handle, "identity": evidence_identity})
                            source_id = evidence.get("source_id")
                            page = evidence.get("page")
                            if (
                                evidence.get("kind") in {"narrative", "table"}
                                and isinstance(source_id, str)
                                and isinstance(page, int)
                                and isinstance(evidence.get("start_line"), int)
                                and isinstance(evidence.get("end_line"), int)
                            ):
                                expansions.append(
                                    {
                                        "operation": "read_pages",
                                        "evidence": handle,
                                        "trial_id": trial_id,
                                        "windows": [
                                            {
                                                "source_id": source_id,
                                                "page": page,
                                                "start_line": evidence["start_line"],
                                                "end_line": evidence["end_line"],
                                            }
                                        ],
                                    }
                                )
                            elif evidence.get("kind") == "figure" and isinstance(source_id, str):
                                render = evidence.get("render")
                                figure_page = (
                                    render.get("page") if isinstance(render, dict) else None
                                )
                                if isinstance(figure_page, int):
                                    expansions.append(
                                        {
                                            "operation": "render_page",
                                            "evidence": handle,
                                            "trial_id": trial_id,
                                            "source_id": source_id,
                                            "page": figure_page,
                                        }
                                    )
                        fact_text = evidence_text(evidence_identity, basis)
                        if fact_text is not None:
                            facts.append(
                                {
                                    "text": fact_text,
                                    "evidence": basis_finding["evidence"],
                                    "role": fact_role,
                                }
                            )
                elif basis["kind"] == "limitation" and isinstance(
                    basis.get("unresolved_premise"), str
                ):
                    facts.append(
                        {
                            "text": basis["unresolved_premise"],
                            "role": "context",
                        }
                    )
                if basis["kind"] == "limitation" and isinstance(
                    basis.get("unresolved_premise"), str
                ):
                    limitations.append(
                        {
                            "unresolved_premise": basis["unresolved_premise"],
                            "stopping_rationale": basis.get("stopping_rationale"),
                            "search_receipt": basis.get("search_receipt"),
                        }
                    )
                if isinstance(basis.get("search_receipt"), str):
                    basis_finding["search_receipt"] = basis["search_receipt"]
                for key in ("unresolved_premise", "stopping_rationale"):
                    if isinstance(basis.get(key), str):
                        basis_finding[key] = basis[key]
                basis_findings.append(basis_finding)
            review_references = tuple(references)
            conflicts = (
                structured_scope_conflicts(answer)
                + host_scope_conflicts(answer, review_references)
                + participant_flow_scope_conflicts(answer)
            )
            if any(
                basis.get("kind") in {"direct_support", "indirect_support", "contradiction"}
                and not isinstance(basis.get("evidence"), str)
                for basis in answer.get("bases", ())
                if isinstance(basis, dict)
            ):
                conflicts.append(
                    {
                        "kind": "unsupported_link",
                        "detail": (
                            "A host support relationship has no resolvable Evidence identity."
                        ),
                        "evidence": review_references,
                    }
                )
            if any(
                basis.get("kind") == "contradiction"
                for basis in answer.get("bases", ())
                if isinstance(basis, dict)
            ):
                conflicts.append(
                    {
                        "kind": "contradiction",
                        "detail": "The host recorded contradictory Evidence against this answer.",
                        "evidence": review_references,
                    }
                )
            routes, route_conflicts = premise_routes(
                domain.id, answer, domain_premises, unread_ranges
            )
            conflicts.extend(route_conflicts)
            answer_findings.append(
                {
                    "question_id": answer["question_id"],
                    "answer": answer.get("answer"),
                    "facts": facts,
                    "warrant": answer.get("justification"),
                    "justification": answer.get("justification"),
                    "unknowns": list(answer.get("unknowns") or []),
                    "counterevidence": list(answer.get("counterevidence") or []),
                    "limitations": limitations,
                    "conflicts": conflicts,
                    "uninvestigated_routes": routes,
                    "evidence": references,
                    "bases": basis_findings,
                    "evidence_expansions": expansions,
                }
            )
        if answer_findings:
            findings.append(
                {
                    "domain_id": domain.id,
                    "checkpoint_identity": record["identity"],
                    "judgment": record.get("judgment"),
                    "answers": answer_findings,
                    "premise_checkpoint_identity": premise_checkpoint_identity,
                    "premise_records": domain_premises,
                    "investigation": investigation,
                }
            )
    return findings


def _automatic_terminal(result: dict[str, Any]) -> tuple[str, str, list[str]] | None:
    if result.get("kind") == "unavailable":
        return (
            "needs_input",
            "The requested Result is not assessable from the captured Sources.",
            [
                item.get("fact", "") if isinstance(item, dict) else str(item)
                for item in result.get("missing_facts", [])
            ],
        )
    applicability = result.get("applicability")
    design = applicability.get("design") if isinstance(applicability, dict) else None
    rationale = (
        str(applicability.get("rationale", "")).strip() if isinstance(applicability, dict) else ""
    )
    if design in _OUT_OF_SCOPE_DESIGNS:
        facts = ["A RoB 2 pack supporting the documented Trial design is required."]
        if rationale:
            facts.insert(0, f"Applicability rationale: {rationale}")
        return (
            "unsupported_design",
            "The captured Trial design is unsupported by the installed "
            f"parallel-assignment pack ({design}).",
            facts,
        )
    if design == "unclear":
        facts = [
            "Source information establishing the Trial design and unit of randomization "
            "is required."
        ]
        if rationale:
            facts.insert(0, f"Applicability rationale: {rationale}")
        return (
            "needs_input",
            "The captured Trial design could not be established for the installed "
            "parallel-assignment pack.",
            facts,
        )
    return None


def _review_payload(
    state: dict[str, Any],
    trial_id: str,
    disposition: str,
    reason: str | None,
    facts: list[str],
) -> dict[str, Any]:
    return {
        "trial_id": trial_id,
        "result_identity": _identity(_approved_result(state, trial_id)),
        "checkpoint_ids": _checkpoint_ids(state, trial_id),
        "domain_attribution": _domain_attribution(state, trial_id),
        "disposition": disposition,
        "reason": reason,
        "facts": facts,
    }


def _review_record_is_current(state: dict[str, Any], review: dict[str, Any]) -> bool:
    try:
        payload = _review_payload(
            state,
            str(review["trial_id"]),
            str(review["disposition"]),
            review.get("reason"),
            list(review.get("facts", [])),
        )
    except (KeyError, TypeError, ValueError):
        return False
    current = review.get("identity") == _identity(payload) and all(
        review.get(key) == value for key, value in payload.items()
    )
    if current:
        return True
    # Reviews written before domain attribution was added remain valid when
    # their original payload still matches the current Result and checkpoints.
    legacy = dict(payload)
    legacy.pop("domain_attribution", None)
    return review.get("identity") == _identity(legacy) and all(
        review.get(key) == value for key, value in legacy.items()
    )


def _review_output(review: dict[str, Any]) -> dict[str, Any]:
    """Return the immutable review, including its workflow provenance rows."""

    output = dict(review)
    attribution = output.get("domain_attribution")
    if isinstance(attribution, list):
        output["domain_attribution"] = [
            {
                key: item[key]
                for key in ("domain_id", "attribution", "checkpoint_identity")
                if isinstance(item, dict) and key in item
            }
            for item in attribution
        ]
    return output


def review_trial(
    workspace: str | Path,
    request: TrialReviewRequest,
    *,
    precommit_validator: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Bind the current Result and Domain checkpoint set for explicit review."""
    root = _root(workspace)
    _ensure(root)
    state = _state(root)
    def validated_retry(review_record: dict[str, Any]) -> dict[str, Any]:
        response = _result(
            "success",
            state,
            review=_review_output(review_record),
            result=_approved_result(state, request.trial_id),
            domain_findings=_review_domain_findings(root, state, request.trial_id),
            retry=True,
        )
        if precommit_validator is not None:
            precommit_validator(response)
        return response

    if not _valid_proposal_gate(
        state.get("proposal_review"),
        state.get("proposal_acknowledgment"),
        state.get("proposal"),
        _identity,
    ):
        raise ValueError("Trial review requires an approved Proposal Review")
    dispositions = state.get("trial_dispositions", {})
    current_disposition = (
        dispositions.get(request.trial_id) if isinstance(dispositions, dict) else None
    )
    if current_disposition not in {"pending", "reviewable"}:
        current_review = (state.get("trial_reviews") or {}).get(request.trial_id)
        closure = (state.get("trial_closures") or {}).get(request.trial_id)
        if (
            isinstance(current_review, dict)
            and isinstance(closure, dict)
            and current_review.get("identity") == closure.get("review_identity")
        ):
            return validated_retry(current_review)
        raise ValueError("Trial is not available for review")
    active_trial, _ = _active_trial_and_domain(state)
    if request.trial_id != active_trial:
        raise ValueError(f"review Trial '{active_trial}' before Trial '{request.trial_id}'")
    result = _approved_result(state, request.trial_id)
    checkpoint_ids = _checkpoint_ids(state, request.trial_id)
    terminal = _automatic_terminal(result)
    if request.request is not None:
        if len(checkpoint_ids) == len(SCIENTIFIC_PACK.domains):
            raise ValueError("all five Domain checkpoints are complete; omit request")
        if terminal is not None:
            raise ValueError("the current Result already determines review; omit request")
        terminal_request = request.request
        disposition = terminal_request.disposition
        reason = terminal_request.reason
        facts = list(
            terminal_request.missing_facts
            if isinstance(terminal_request, NeedsInputTerminalRequest)
            else terminal_request.facts
        )
    elif len(checkpoint_ids) == len(SCIENTIFIC_PACK.domains):
        disposition, reason, facts = "assessed", None, []
        snapshot = (state.get("snapshots") or {}).get(request.trial_id)
        if not isinstance(snapshot, dict):
            raise ValueError("the Trial AssessmentSnapshot is unavailable")
    elif terminal is not None:
        disposition, reason, facts = terminal
    else:
        raise ValueError("complete all five Domains or provide a typed terminal request")
    if disposition == "assessed" and len(checkpoint_ids) != len(SCIENTIFIC_PACK.domains):
        raise ValueError("an assessed Trial review requires all five current Domain checkpoints")
    if disposition == "assessed":
        snapshot = (state.get("snapshots") or {}).get(request.trial_id)
        if (
            not isinstance(snapshot, dict)
            or snapshot.get("result_identity") != _identity(result)
            or snapshot.get("checkpoints") != checkpoint_ids
        ):
            raise ValueError("the Trial AssessmentSnapshot does not match its current checkpoints")
    review = _review_payload(state, request.trial_id, disposition, reason, facts)
    review["identity"] = _identity(review)
    existing = (state.get("trial_reviews") or {}).get(request.trial_id)
    if isinstance(existing, dict) and existing.get("identity") == review["identity"]:
        return validated_retry(existing)
    if request.expected_revision != state.get("revision", 0):
        raise WorkflowConflict(request.expected_revision, int(state.get("revision", 0)))
    reviews = dict(state.get("trial_reviews", {}))
    reviews[request.trial_id] = review
    next_state = {**state, "trial_reviews": reviews}
    records: dict[str, dict[str, Any]] = {f"trial_review:{review['identity']}": review}
    if precommit_validator is not None:
        pending_state = {**next_state, "revision": int(state.get("revision", 0)) + 1}
        precommit_validator(
            _result(
                "success",
                pending_state,
                review=_review_output(review),
                result=result,
                domain_findings=_review_domain_findings(root, pending_state, request.trial_id),
                continuation=_continuation(pending_state),
            )
        )
    state = _commit_records(
        root,
        next_state,
        request.expected_revision,
        records,
    )
    return _result(
        "success",
        state,
        review=_review_output(review),
        result=result,
        domain_findings=_review_domain_findings(root, state, request.trial_id),
        continuation=_continuation(state),
    )


def close_trial(
    workspace: str | Path,
    request: TrialClosureRequest,
) -> dict[str, Any]:
    """Close a Trial only against its exact current review reference."""
    root = _root(workspace)
    _ensure(root)
    state = _state(root)
    closures = state.get("trial_closures", {})
    closed = closures.get(request.trial_id) if isinstance(closures, dict) else None
    if isinstance(closed, dict):
        if closed.get("review_identity") == request.review_reference:
            return _result("success", state, closure=closed, retry=True)
        return _result(
            "condition",
            state,
            condition={
                "code": "trial_closed",
                "detail": "this Trial is already closed; start a new Batch to reassess it.",
            },
        )
    reviews = state.get("trial_reviews", {})
    review = reviews.get(request.trial_id) if isinstance(reviews, dict) else None
    if (
        not isinstance(review, dict)
        or review.get("identity") != request.review_reference
        or not _review_record_is_current(state, review)
    ):
        return _result(
            "condition",
            state,
            condition={
                "code": "trial_review_stale",
                "detail": (
                    "the review no longer matches the approved Result and current Domain "
                    "checkpoints; refresh it."
                ),
            },
        )
    if not _valid_proposal_gate(
        state.get("proposal_review"),
        state.get("proposal_acknowledgment"),
        state.get("proposal"),
        _identity,
    ):
        return _result(
            "condition",
            state,
            condition={
                "code": "proposal_approval_required",
                "detail": "the current Proposal must be approved before closing a Trial.",
            },
        )
    if request.expected_revision != state.get("revision", 0):
        raise WorkflowConflict(request.expected_revision, int(state.get("revision", 0)))
    active_trial, _ = _active_trial_and_domain(state)
    if request.trial_id != active_trial:
        raise ValueError(
            f"review and close Trial '{active_trial}' before Trial '{request.trial_id}'"
        )
    if review["disposition"] == "assessed" and len(review["checkpoint_ids"]) != len(
        SCIENTIFIC_PACK.domains
    ):
        raise ValueError("assessed closure requires all five current Domain checkpoints")
    closure = {
        "trial_id": request.trial_id,
        "review_identity": request.review_reference,
        "disposition": review["disposition"],
    }
    closure["identity"] = _identity(closure)
    trial_closures = dict(closures)
    trial_closures[request.trial_id] = closure
    dispositions = dict(state.get("trial_dispositions", {}))
    dispositions[request.trial_id] = review["disposition"]
    records: dict[str, dict[str, Any]] = {f"trial_closure:{closure['identity']}": closure}
    terminals = dict(state.get("terminals", {}))
    if review["disposition"] != "assessed":
        terminal = {
            "trial_id": request.trial_id,
            "disposition": review["disposition"],
            "reason": review["reason"],
            "facts": list(review["facts"]),
            "review_identity": request.review_reference,
        }
        terminal["identity"] = _identity(terminal)
        terminals[terminal["identity"]] = terminal
        records[f"terminal:{terminal['identity']}"] = terminal
    still_open = any(value in {"pending", "reviewable"} for value in dispositions.values())
    next_state = {
        **state,
        "phase": "assessment" if still_open else "ready_to_finalize",
        "trial_dispositions": dispositions,
        "trial_closures": trial_closures,
        "terminals": terminals,
    }
    state = _commit_records(root, next_state, request.expected_revision, records)
    return _result("success", state, closure=closure, continuation=_continuation(state))

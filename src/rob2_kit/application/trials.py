"""Reviewable and immutable Trial lifecycle transitions."""

from pathlib import Path
from typing import Any

from ..packs import SCIENTIFIC_PACK
from ..workflow_models import NeedsInputTerminalRequest, TrialClosureRequest, TrialReviewRequest
from ._state import _commit_records, _ensure, _identity, _result, _root, _state
from .contracts import WorkflowConflict
from .finalization import _valid_proposal_gate
from .status import _active_trial_and_domain, _continuation

_OUT_OF_SCOPE_DESIGNS = {"cluster_randomized", "crossover"}


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
        attribution = kind if kind in {
            "new_evidence",
            "self_correction",
            "mechanical_repair",
        } else "unchanged"
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

    from .evidence import _evidence_catalog

    try:
        evidence_by_identity = _evidence_catalog(root, trial_id=trial_id)
    except ValueError:
        # Review remains useful when a disposable handle cache is damaged; the
        # checkpoint identities and answer text are still authoritative, while
        # the missing expansion is left for the ordinary recovery path.
        evidence_by_identity = {}
    records = state.get("domain_records") or {}
    findings: list[dict[str, Any]] = []
    for domain in SCIENTIFIC_PACK.domains:
        record = records.get(f"{trial_id}:{domain.id}")
        if not isinstance(record, dict) or not isinstance(record.get("identity"), str):
            continue
        answer_findings: list[dict[str, Any]] = []
        for answer in record.get("answers", []):
            if not isinstance(answer, dict) or not isinstance(answer.get("question_id"), str):
                continue
            references: list[dict[str, Any]] = []
            expansions: list[dict[str, Any]] = []
            seen_evidence: set[str] = set()
            for basis in answer.get("bases", []):
                if not isinstance(basis, dict) or not isinstance(basis.get("evidence"), str):
                    continue
                evidence_identity = basis["evidence"]
                if evidence_identity in seen_evidence:
                    continue
                seen_evidence.add(evidence_identity)
                evidence = evidence_by_identity.get(evidence_identity)
                if not isinstance(evidence, dict) or not isinstance(evidence.get("handle"), str):
                    continue
                handle = evidence["handle"]
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
                elif (
                    evidence.get("kind") == "figure"
                    and isinstance(source_id, str)
                    and isinstance(page, int)
                ):
                    expansions.append(
                        {
                            "operation": "render_page",
                            "evidence": handle,
                            "trial_id": trial_id,
                            "source_id": source_id,
                            "page": page,
                        }
                    )
            answer_findings.append(
                {
                    "question_id": answer["question_id"],
                    "answer": answer.get("answer"),
                    "justification": answer.get("justification"),
                    "unknowns": list(answer.get("unknowns") or []),
                    "counterevidence": list(answer.get("counterevidence") or []),
                    "evidence": references,
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
) -> dict[str, Any]:
    """Bind the current Result and Domain checkpoint set for explicit review."""
    root = _root(workspace)
    _ensure(root)
    state = _state(root)
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
            return _result(
                "success",
                state,
                review=_review_output(current_review),
                domain_findings=_review_domain_findings(root, state, request.trial_id),
                retry=True,
            )
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
        return _result(
            "success",
            state,
            review=_review_output(existing),
            domain_findings=_review_domain_findings(root, state, request.trial_id),
            retry=True,
        )
    if request.expected_revision != state.get("revision", 0):
        raise WorkflowConflict(request.expected_revision, int(state.get("revision", 0)))
    reviews = dict(state.get("trial_reviews", {}))
    reviews[request.trial_id] = review
    next_state = {**state, "trial_reviews": reviews}
    records: dict[str, dict[str, Any]] = {f"trial_review:{review['identity']}": review}
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

"""Proposal submission, provenance enforcement, and patchable drafts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ._state import identity, read_json, write_json
from .contracts import EvidenceReference, RecordReference
from .drafts import ProposalDraftCommand, create_draft, patch_draft, read_draft
from .evidence import TextEvidenceRecord, VisualEvidenceRecord, resolve_evidence
from .proposal import (
    ApprovalRequest,
    ProposalInput,
    ProposalRepairReceipt,
    ResultCardInput,
    approve_batch,
    save_proposal,
)
from .provenance import (
    ProvenanceDeclaration,
    _reported_atoms,
    normalize,
    validate_complete_reported_provenance,
    value_is_present,
)
from .transport import validation_repairs


def _evidence_text(workspace: str | Path, reference: EvidenceReference) -> str:
    record = resolve_evidence(workspace, reference)
    if isinstance(record, TextEvidenceRecord):
        return record.quote
    if isinstance(record, VisualEvidenceRecord):
        return record.transcription
    raise ValueError("unsupported Evidence record")


def _card_evidence_ids(card: ResultCardInput) -> set[str]:
    result: set[str] = set()
    for name in ("target_basis", "reported_values", "reported_context", "population_basis"):
        result.update(item.identity for item in getattr(card.evidence, name))
    return result


def _implicit_defects(
    workspace: str | Path, card: ResultCardInput
) -> list[dict[str, object]]:
    """Compatibility bridge for clients not yet emitting explicit bindings."""

    reported_values = tuple(card.evidence.reported_values)
    texts = [_evidence_text(workspace, reference) for reference in reported_values]
    combined = "\n".join(texts)
    raw = card.model_dump(mode="json")
    defects: list[dict[str, object]] = []
    for pointer, value in _reported_atoms(raw):
        if pointer.endswith("/denominator_basis"):
            continue
        if not value_is_present(combined, value):
            defects.append(
                {
                    "pointer": pointer,
                    "code": "value_not_in_reported_evidence",
                    "detail": (
                        f"structured reported atom {value!r} is absent from "
                        "reported-values Evidence; add exact field provenance or "
                        "remove the unsupported atom"
                    ),
                }
            )
    effect_measure = getattr(card.reported, "effect_measure", None)
    if effect_measure and normalize(effect_measure) not in normalize(combined):
        defects.append(
            {
                "pointer": "/reported/effect_measure",
                "code": "label_not_in_reported_evidence",
                "detail": "reported effect measure is absent from reported-values Evidence",
            }
        )
    return defects


def _extract(raw: Mapping[str, Any]) -> tuple[dict[str, object], dict[str, object]]:
    if "proposal" in raw:
        proposal = raw.get("proposal")
        provenance = raw.get("provenance", {})
        if not isinstance(proposal, Mapping) or not isinstance(provenance, Mapping):
            raise TypeError("proposal and provenance must be objects")
        proposal_payload = dict(proposal)
        explicit = dict(provenance)
    else:
        proposal_payload = dict(raw)
        explicit = {}
    results = proposal_payload.get("results", ())
    if not isinstance(results, Sequence) or isinstance(results, str | bytes | bytearray):
        raise TypeError("proposal.results must be an array")
    clean_results: list[dict[str, object]] = []
    for item in results:
        if not isinstance(item, Mapping):
            raise TypeError("each Proposal Result must be an object")
        result = dict(item)
        declaration = result.pop("provenance", None)
        trial_id = result.get("trial_id")
        if declaration is not None and isinstance(trial_id, str):
            explicit[trial_id] = declaration
        clean_results.append(result)
    proposal_payload["results"] = clean_results
    return proposal_payload, explicit


def _persist(
    workspace: str | Path,
    review: RecordReference,
    declarations: Mapping[str, object],
    implicit_trials: Sequence[str],
) -> dict[str, object]:
    payload = {
        "kind": "proposal_provenance",
        "review": review.model_dump(mode="json"),
        "declarations": dict(declarations),
        "implicit_trials": sorted(set(implicit_trials)),
    }
    provenance_identity = identity(payload)
    record = {**payload, "identity": provenance_identity}
    write_json(
        workspace,
        f"proposal-provenance-{review.identity.removeprefix('sha256:')}.json",
        record,
    )
    return record


def read_review_provenance(
    workspace: str | Path, review: RecordReference
) -> dict[str, object] | None:
    raw = read_json(
        workspace,
        f"proposal-provenance-{review.identity.removeprefix('sha256:')}.json",
    )
    if not isinstance(raw, dict):
        return None
    if raw.get("review") != review.model_dump(mode="json"):
        return None
    payload = {key: raw[key] for key in ("kind", "review", "declarations", "implicit_trials")}
    if identity(payload) != raw.get("identity"):
        return None
    return raw


def submit_proposal(workspace: str | Path, raw: Mapping[str, Any]) -> object:
    if "draft_operation" in raw:
        try:
            command = ProposalDraftCommand.model_validate(raw)
        except ValidationError as error:
            return validation_repairs(error)
        if command.draft_operation == "create":
            assert command.proposal is not None
            return create_draft(workspace, command.proposal)
        if command.draft_operation == "read":
            assert command.draft_id is not None
            return read_draft(workspace, command.draft_id)
        if command.draft_operation == "patch":
            assert command.draft_id is not None
            return patch_draft(workspace, command.draft_id, command.patches)
        assert command.draft_id is not None
        return submit_proposal(workspace, read_draft(workspace, command.draft_id).proposal)

    try:
        proposal_payload, explicit_payload = _extract(raw)
        proposal = ProposalInput.model_validate(proposal_payload)
    except ValidationError as error:
        return validation_repairs(error)
    except (TypeError, ValueError) as error:
        return {
            "outcome": "repair",
            "repairs": [{"pointer": "", "code": "wrong_type", "detail": str(error)}],
        }

    defects: list[dict[str, object]] = []
    persisted: dict[str, object] = {}
    implicit_trials: list[str] = []
    by_trial = {item.trial_id: item for item in proposal.results}
    for trial_index, (trial_id, card) in enumerate(by_trial.items()):
        raw_declaration = explicit_payload.get(trial_id)
        if raw_declaration is None:
            form = getattr(card.reported, "form", "")
            if form == "single_group_category_profile":
                defects.append(
                    {
                        "pointer": f"/results/{trial_index}/provenance",
                        "code": "table_provenance_required",
                        "detail": (
                            "single-group/table Results require explicit row, column, "
                            "population, denominator, and required-cell provenance"
                        ),
                    }
                )
            else:
                defects.extend(_implicit_defects(workspace, card))
                implicit_trials.append(trial_id)
            continue
        try:
            declaration = ProvenanceDeclaration.model_validate(raw_declaration)
        except ValidationError as error:
            receipt = validation_repairs(error, prefix=f"/results/{trial_index}/provenance")
            defects.extend(item.model_dump(mode="json") for item in receipt.repairs)
            continue
        card_ids = _card_evidence_ids(card)
        declaration_ids = {
            reference.identity
            for binding in declaration.field_bindings
            for reference in binding.evidence
        } | {cell.evidence.identity for cell in declaration.table_cells}
        outside = sorted(declaration_ids - card_ids)
        if outside:
            defects.append(
                {
                    "pointer": f"/results/{trial_index}/provenance",
                    "code": "evidence_outside_result_set",
                    "detail": f"provenance references Evidence not declared by the Result: {outside!r}",
                }
            )
            continue
        found = validate_complete_reported_provenance(
            card.model_dump(mode="json"),
            declaration,
            lambda reference: _evidence_text(workspace, reference),
        )
        defects.extend(item.model_dump(mode="json") for item in found)
        persisted[trial_id] = declaration.model_dump(mode="json")

    if defects:
        draft = create_draft(workspace, dict(raw))
        unique = {
            (str(item.get("pointer")), str(item.get("code")), str(item.get("detail"))): item
            for item in defects
        }
        return {
            "outcome": "repair",
            "draft_id": draft.draft_id,
            "repairs": [unique[key] for key in sorted(unique)],
            "next_action": "patch_or_submit",
        }

    saved = save_proposal(workspace, proposal)
    if isinstance(saved, ProposalRepairReceipt):
        draft = create_draft(workspace, dict(raw))
        payload = saved.model_dump(mode="json", exclude_none=True)
        payload["draft_id"] = draft.draft_id
        payload["next_action"] = "patch_or_submit"
        return payload
    provenance = _persist(workspace, saved.review, persisted, implicit_trials)
    payload = saved.model_dump(mode="json", exclude_none=True)
    payload["provenance"] = {
        "kind": provenance["kind"],
        "identity": provenance["identity"],
    }
    return payload


def approve_proposal(
    workspace: str | Path,
    transition: object,
    acknowledgment: object,
) -> object:
    from .contracts import ReviewAcknowledgmentReference, TransitionReference

    request = ApprovalRequest(
        transition=TransitionReference.model_validate(transition),
        acknowledgment=ReviewAcknowledgmentReference.model_validate(acknowledgment),
    )
    proposal = read_json(workspace, "proposal_review.json") or {}
    review = RecordReference.model_validate(
        {
            "kind": "proposal_review",
            "identity": proposal.get("identity"),
            "uri": f"rob2://detail/proposal_review/{proposal.get('identity')}",
        }
    )
    provenance = read_review_provenance(workspace, review)
    if provenance is None:
        return {
            "outcome": "condition",
            "code": "proposal_provenance_unavailable",
            "detail": "the reviewed Proposal lacks verified field-level provenance",
            "next_action": "save_proposal",
        }
    return approve_batch(workspace, request)
"""Strict Proposal runtime requiring explicit field-level provenance."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .drafts import ProposalDraftCommand, create_draft, read_draft
from .transport import validation_repairs
from . import proposal_runtime_legacy as _legacy

approve_proposal = _legacy.approve_proposal
read_review_provenance = _legacy.read_review_provenance


def _missing_provenance(raw: Mapping[str, Any]) -> tuple[tuple[int, str], ...]:
    proposal = raw.get("proposal", raw)
    top_level = raw.get("provenance", {}) if "proposal" in raw else {}
    if not isinstance(proposal, Mapping) or not isinstance(top_level, Mapping):
        return ()
    results = proposal.get("results", ())
    if not isinstance(results, Sequence) or isinstance(
        results, str | bytes | bytearray
    ):
        return ()
    missing: list[tuple[int, str]] = []
    for index, item in enumerate(results):
        if not isinstance(item, Mapping):
            continue
        trial_id = item.get("trial_id")
        if not isinstance(trial_id, str):
            continue
        if item.get("provenance") is None and top_level.get(trial_id) is None:
            missing.append((index, trial_id))
    return tuple(missing)


def submit_proposal(workspace: str | Path, raw: Mapping[str, Any]) -> object:
    """Submit or patch a Proposal, never accepting implicit Result provenance."""

    if "draft_operation" in raw:
        try:
            command = ProposalDraftCommand.model_validate(raw)
        except ValidationError as error:
            return validation_repairs(error)
        if command.draft_operation != "submit":
            return _legacy.submit_proposal(workspace, raw)
        assert command.draft_id is not None
        return submit_proposal(workspace, read_draft(workspace, command.draft_id).proposal)

    missing = _missing_provenance(raw)
    if missing:
        draft = create_draft(workspace, dict(raw))
        return {
            "outcome": "repair",
            "draft_id": draft.identity,
            "repairs": [
                {
                    "pointer": f"/results/{index}/provenance",
                    "code": "field_provenance_required",
                    "detail": (
                        "every Result requires explicit field-level Evidence bindings; "
                        "table Results additionally require row, column, population, "
                        "denominator, and required-cell provenance"
                    ),
                }
                for index, _trial_id in missing
            ],
            "next_action": {
                "operation": "save_proposal",
                "draft_operation": "patch",
                "draft_id": draft.identity,
            },
        }
    return _legacy.submit_proposal(workspace, raw)


__all__ = ["approve_proposal", "read_review_provenance", "submit_proposal"]

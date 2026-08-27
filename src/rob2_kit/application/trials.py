from pathlib import Path
from typing import Any

from ..workflow_models import TerminalRequestEnvelope
from ._state import _commit_records, _ensure, _identity, _result, _root, _state
from .contracts import WorkflowConflict
from .finalization import _valid_proposal_gate
from .status import _continuation


def _proposal_gate_is_approved(state: dict[str, Any]) -> bool:
    """Require the persisted, exact Proposal gate before terminal mutation."""

    if state.get("phase") not in {"assessment", "ready_to_finalize", "finalized"}:
        return False
    proposal = state.get("proposal")
    review = state.get("proposal_review")
    acknowledgment = state.get("proposal_acknowledgment")
    return _valid_proposal_gate(review, acknowledgment, proposal, _identity)


def request_trial_terminal(
    workspace: str | Path,
    envelope: TerminalRequestEnvelope,
) -> dict[str, Any]:
    request = envelope.request
    trial_id = request.trial_id
    disposition = request.disposition
    reason = request.reason
    payload = request.model_dump(mode="json")
    missing_facts = list(payload.get("missing_facts", payload.get("facts", ())))
    expected_revision = envelope.expected_revision
    root = _root(workspace)
    _ensure(root)
    state = _state(root)
    if not _proposal_gate_is_approved(state):
        raise ValueError("terminal requests require an approved Proposal Review")
    terminal_identity = _identity(
        {
            "trial_id": trial_id,
            "disposition": disposition,
            "reason": reason,
            "missing_facts": missing_facts,
        }
    )
    existing = next(
        (
            item
            for item in (state.get("terminals") or {}).values()
            if isinstance(item, dict) and item.get("identity") == terminal_identity
        ),
        None,
    )
    if existing is not None:
        return _result("success", state, terminal=existing, retry=True)
    if expected_revision != state.get("revision", 0):
        raise WorkflowConflict(expected_revision, int(state.get("revision", 0)))
    if state.get("phase") != "assessment":
        raise ValueError("terminal request is not the current operation")
    if disposition not in {"needs_input", "failed"}:
        raise ValueError("terminal disposition must be needs_input or failed")
    if not reason.strip() or not missing_facts:
        raise ValueError("terminal reason and missing facts are required")
    if (
        trial_id not in state.get("trial_dispositions", {})
        or state["trial_dispositions"][trial_id] != "pending"
    ):
        raise ValueError("Trial is not pending")
    if disposition == "needs_input" and not all(
        isinstance(item, str) and item.strip() for item in missing_facts
    ):
        raise ValueError("needs-input facts must be stable nonempty strings")
    terminal = {
        "identity": terminal_identity,
        "trial_id": trial_id,
        "disposition": disposition,
        "reason": reason,
        "missing_facts": missing_facts,
    }
    dispositions = dict(state.get("trial_dispositions", {}))
    dispositions[trial_id] = disposition
    terminals = dict(state.get("terminals", {}))
    terminals[terminal_identity] = terminal
    phase = (
        "ready_to_finalize"
        if not any(value == "pending" for value in dispositions.values())
        else "assessment"
    )
    state = _commit_records(
        root,
        {
            **state,
            "phase": phase,
            "trial_dispositions": dispositions,
            "terminals": terminals,
        },
        expected_revision,
        {f"terminal:{terminal['identity']}": terminal},
    )
    return _result(
        "success",
        state,
        terminal=terminal,
        continuation=_continuation(state),
    )

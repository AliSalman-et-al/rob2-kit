"""Recognize a saved proposal awaiting its actual researcher gate."""

from collections.abc import Mapping
from typing import Any


def proposal_saved_for_review(tool: str, result: Mapping[str, Any]) -> bool:
    """Require the saved-tool receipt and its explicit researcher Review action."""
    head = result.get("head")
    action = head.get("next_action") if isinstance(head, Mapping) else None
    return (
        tool == "save_proposal"
        and result.get("outcome") in {"success", "review_required"}
        and isinstance(action, Mapping)
        and action.get("operation") == "researcher_review"
        and action.get("authority") == "researcher"
        and action.get("purpose") == "proposal"
        and isinstance(action.get("reference"), str)
        and bool(action["reference"])
    )

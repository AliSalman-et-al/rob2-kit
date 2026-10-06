"""A persisted proposal must stop before the researcher gate, not after approval."""

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "proposal_probe_terminal", Path(__file__).parents[1] / "scripts/proposal_probe_terminal.py"
)
assert _spec is not None and _spec.loader is not None
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
proposal_saved_for_review = _module.proposal_saved_for_review


def test_actual_saved_receipt_stops_but_validation_and_conditions_do_not() -> None:
    import json

    archive = (
        Path(__file__).parents[1] / "docs/archive/evaluation/2026-10-03-exscel-proposal-bd92ec8"
    )
    calls = json.loads((archive / "proposal-requests-and-receipts.json").read_text())
    for call in calls:
        result = call["result"]["structured_content"]
        assert proposal_saved_for_review(call["tool"], result) == (call["tool"] == "save_proposal")
    assert not proposal_saved_for_review("save_proposal", {"outcome": "success"})
    assert not proposal_saved_for_review("save_proposal", {"outcome": "condition"})


def test_wrong_authority_or_missing_review_reference_cannot_stop_as_saved() -> None:
    action = {
        "operation": "researcher_review",
        "authority": "researcher",
        "purpose": "proposal",
        "reference": "sha256:review",
    }
    receipt = {"outcome": "review_required", "head": {"next_action": action}}
    assert proposal_saved_for_review("save_proposal", receipt)
    action["authority"] = "host"
    assert not proposal_saved_for_review("save_proposal", receipt)
    action["authority"] = "researcher"
    action.pop("reference")
    assert not proposal_saved_for_review("save_proposal", receipt)

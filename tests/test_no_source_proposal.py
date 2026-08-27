from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from rob2_kit.application._state import _state
from rob2_kit.application.finalization import finalize_batch, verify_bundle
from rob2_kit.application.intake import approve_review, prepare_batch_for_outcome
from rob2_kit.application.proposal import save_proposal
from rob2_kit.workflow_models import ProposalDraft, UnavailableResult


def _unavailable(trial_id: str, *, basis_kind: str = "intake_condition") -> dict[str, object]:
    basis: dict[str, str] = {"kind": basis_kind}
    if basis_kind == "intake_condition":
        basis["code"] = "no_supported_sources"
    else:
        basis["evidence"] = "eh_0000000000000000"
    return {
        "kind": "unavailable",
        "trial_id": trial_id,
        "relation": "unavailable",
        "missing_facts": [{"fact": "the requested endpoint", "basis": basis}],
    }


def test_zero_source_trial_reaches_needs_input_and_finalizes(tmp_path: Path) -> None:
    (tmp_path / "input" / "trial").mkdir(parents=True)
    prepared = prepare_batch_for_outcome(tmp_path, "requested outcome", 0)
    assert prepared["conditions"] == [{"code": "no_supported_sources", "trial_id": "trial"}]

    proposal = save_proposal(
        tmp_path,
        ProposalDraft.model_validate(
            {
                "results": [_unavailable("trial")],
                "expected_revision": _state(tmp_path)["revision"],
            }
        ),
    )
    assert proposal["outcome"] == "review_required"
    saved = _state(tmp_path)["proposal"]["payload"]["results"][0]
    assert saved["missing_facts"][0]["basis"] == {
        "kind": "intake_condition",
        "code": "no_supported_sources",
    }
    UnavailableResult.model_validate(saved)

    approved = approve_review(tmp_path, proposal["review"]["reference"])
    assert approved["outcome"] == "success"
    state = _state(tmp_path)
    assert state["phase"] == "ready_to_finalize"
    assert state["trial_dispositions"] == {"trial": "needs_input"}

    finalized = finalize_batch(tmp_path, state["revision"])
    artifact = tmp_path / finalized["artifact"]["path"]
    assert verify_bundle(artifact)
    standalone = subprocess.run(
        [sys.executable, "scripts/verify_bundle.py", str(artifact)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert standalone.returncode == 0, standalone.stderr or standalone.stdout


def test_intake_condition_basis_is_repaired_for_a_trial_with_sources(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "trial"
    trial.mkdir(parents=True)
    (trial / "source.txt").write_text("A captured source.", encoding="utf-8")
    prepare_batch_for_outcome(tmp_path, "requested outcome", 0)

    repaired = save_proposal(
        tmp_path,
        ProposalDraft.model_validate(
            {
                "results": [_unavailable("trial")],
                "expected_revision": _state(tmp_path)["revision"],
            }
        ),
    )
    assert repaired["outcome"] == "repair"
    assert any(item["code"] == "intake_condition_basis_invalid" for item in repaired["repairs"])
    assert _state(tmp_path).get("proposal") is None

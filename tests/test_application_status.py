from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from rob2_kit.application._state import identity, read_json, write_jsons
from rob2_kit.application.proposal import (
    NeedsInputReason,
    PreapprovalNeedsInput,
    ProposalInput,
    ProposalRepairReceipt,
    acknowledge_proposal,
    save_proposal,
)
from rob2_kit.application.status import current_status, status_json


def test_cli_and_status_projection_match_on_restart(tmp_path: Path) -> None:
    expected = json.loads(status_json(tmp_path))
    environment = os.environ.copy()
    environment["ROB2_WORKSPACE"] = str(tmp_path)
    first = subprocess.check_output(
        [sys.executable, "-m", "rob2_kit.interfaces.cli.app", "status"],
        env=environment,
        text=True,
    )
    second = subprocess.check_output(
        [sys.executable, "-m", "rob2_kit.interfaces.cli.app", "status"],
        env=environment,
        text=True,
    )
    assert json.loads(first) == expected == json.loads(second)


def test_restart_status_fails_closed_for_unresolved_legacy_proposal(tmp_path: Path) -> None:
    from test_application_proposal import _captured_evidence, _card

    evidence = _captured_evidence(tmp_path)
    card = _card().model_copy(
        update={
            "trial_id": "chaarted",
            "target": _card().target.model_copy(
                update={
                    "outcome_definition": "Adverse events",
                    "effect_of_interest": "effect on Adverse events",
                }
            ),
            "source_table_meaning": "Reported outcome: Adverse events",
            "evidence": evidence,
        }
    )
    review = save_proposal(
        tmp_path,
        ProposalInput(
            outcome_statement="Adverse events",
            results=(card,),
            needs_input=(
                PreapprovalNeedsInput(
                    trial_id="chaarted",
                    reason=NeedsInputReason.COMPARATOR_UNAVAILABLE,
                    missing_facts=("ADT-alone comparator unavailable",),
                ),
            ),
        ),
    )
    assert not isinstance(review, ProposalRepairReceipt)
    acknowledge_proposal(tmp_path, review.review, caller="server:interactive")

    raw = read_json(tmp_path, "proposal_review.json")
    assert raw is not None
    raw["needs_input"] = []
    raw["identity"] = identity(
        {
            key: value
            for key, value in raw.items()
            if key not in {"identity", "review", "transition", "kind"}
        }
    )
    raw["transition"] = {
        "operation": "approve_batch",
        "identity": identity({"operation": "approve_batch", "review": raw["identity"]}),
    }
    write_jsons(tmp_path, {"proposal_review.json": raw})

    status = current_status(tmp_path)
    restart_status = json.loads(status_json(tmp_path))

    assert status.presentation.code == "proposal_compatibility_unresolved"
    assert status.continuation is not None
    assert status.continuation.operation == "save_proposal"
    assert restart_status["presentation"]["code"] == "proposal_compatibility_unresolved"
    assert "transition" not in restart_status["continuation"]
    assert restart_status["conditions"][0]["code"] == "proposal_compatibility_unresolved"


def test_status_fails_closed_when_current_domain_packet_is_missing_or_corrupt(
    tmp_path: Path,
) -> None:
    from test_application_domains import _captured

    approved = _captured(tmp_path)
    state = read_json(tmp_path, "state.json")
    assert state is not None
    state.update(
        {
            "approved_batch_identity": approved.identity,
            "work_packet_identity": "sha256:" + "1" * 64,
        }
    )
    write_jsons(tmp_path, {"state.json": state})

    result = current_status(tmp_path)

    assert result.presentation.code == "work_packet_unavailable"
    assert result.continuation is None
    assert result.conditions[0].code == "work_packet_unavailable"
    assert "invalid Domain work packet identity" not in result.conditions[0].detail

    packet_identity = state["work_packet_identity"]
    write_jsons(
        tmp_path,
        {
            f"domain-packet-{str(packet_identity).removeprefix('sha256:')}.json": {
                "kind": "work_packet",
                "identity": packet_identity,
            }
        },
    )
    corrupt = current_status(tmp_path)

    assert corrupt.presentation.code == "work_packet_unavailable"
    assert corrupt.continuation is None
    assert corrupt.conditions[0].code == "work_packet_unavailable"


def test_status_fails_closed_when_domain_checkpoint_lacks_current_packet(tmp_path: Path) -> None:
    from test_application_domains import _captured

    _captured(tmp_path)
    state = read_json(tmp_path, "state.json")
    assert state is not None
    state["domains"] = {"trial:result:domain:randomization": ["sha256:" + "2" * 64]}
    write_jsons(tmp_path, {"state.json": state})

    result = current_status(tmp_path)

    assert result.presentation.code == "work_packet_unavailable"
    assert result.continuation is None
    assert "no current Domain work packet identity" in result.conditions[0].detail

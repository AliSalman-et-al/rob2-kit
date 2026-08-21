from __future__ import annotations

import pytest
from pydantic import ValidationError

from rob2_kit.application.contracts import (
    EvidenceReference,
    RecordReference,
    ReviewAcknowledgmentReference,
    ReviewAuthority,
    TrialDisposition,
    WorkflowPhase,
)


def test_workflow_and_disposition_are_closed_and_separate() -> None:
    assert tuple(item.value for item in WorkflowPhase) == (
        "empty",
        "intake",
        "proposal",
        "assessment",
        "ready_to_finalize",
        "finalized",
    )
    assert tuple(item.value for item in TrialDisposition) == (
        "pending",
        "assessed",
        "needs_input",
        "failed",
    )
    with pytest.raises(ValidationError):
        RecordReference.model_validate(
            {
                "kind": "intake_plan",
                "identity": "sha256:" + "0" * 64,
                "uri": "rob2://detail/intake_plan/sha256:" + "0" * 64,
                "actor": "forbidden",
            }
        )
    assert ReviewAuthority.RESEARCHER.value == "researcher"


@pytest.mark.parametrize(
    "model,payload",
    (
        (EvidenceReference, {"identity": "sha256:" + "0" * 64}),
        (
            ReviewAcknowledgmentReference,
            {
                "identity": "sha256:" + "0" * 64,
                "uri": "rob2://detail/review_ack/sha256:" + "0" * 64,
            },
        ),
    ),
)
def test_reference_discriminators_are_required(model, payload: object) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload)

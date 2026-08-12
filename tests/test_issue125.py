"""v3 question-evidence request validation regressions (#125)."""

import pytest
from pydantic import ValidationError

from rob2_kit.application.contracts import RunOperation, SubmitQuestionStepRequest
from rob2_kit.application.question_evidence_bundle import (
    QuestionEvidenceBundleMaterializationError,
    materialize_question_evidence_bundle,
)
from tests.test_issue167_question_bundle import _input


def _step_payload() -> dict[str, object]:
    return {
        "contract_version": "3.0.0",
        "run_id": "run:issue125",
        "work_token": {
            "token": "work-token:issue125",
            "run_id": "run:issue125",
            "work_item_id": "work-item:issue125",
            "operation": RunOperation.SUBMIT_QUESTION_STEP,
            "dependency_fingerprint": "sha256:" + "3" * 64,
        },
        "idempotency_key": "idempotency:issue125",
        "result_id": "result:issue125",
        "domain_id": "domain:issue125",
        "question_id": "sq:issue125",
        "session_content_hash": "sha256:" + "1" * 64,
        "frontier_entry_hash": "sha256:" + "2" * 64,
    }


@pytest.mark.parametrize(
    ("updates", "message"),
    (
        ({"answer": "yes", "rationale": "Attributed."}, "Evidence Bundle"),
        ({"answer": "yes", "diagnostic_stop": True, "rationale": "Attributed."}, "exactly one"),
        ({"diagnostic_stop": True, "rationale": "Not an answer."}, "cannot carry"),
    ),
)
def test_submit_question_step_rejects_ambiguous_or_unbound_outcomes(updates, message) -> None:
    with pytest.raises(ValidationError, match=message):
        SubmitQuestionStepRequest.model_validate(_step_payload() | updates)


def test_bundle_conflicts_must_name_distinct_current_question_items(tmp_path) -> None:
    input = _input(tmp_path).model_copy(
        update={"conflict_item_groups": (("claim:not-present", "claim:also-not-present"),)}
    )

    with pytest.raises(QuestionEvidenceBundleMaterializationError, match="outside this question"):
        materialize_question_evidence_bundle(input)

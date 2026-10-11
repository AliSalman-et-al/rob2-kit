from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from support.rob2 import _assessment_workspace, _call, _domain_draft

from rob2_kit.workflow_models import DomainSaveAnswer

REJECTED = json.loads(
    (Path(__file__).parent / "fixtures/monarch-plus-rejected-submissions.json").read_text()
)


@pytest.mark.parametrize(
    "change",
    [
        {"limitations": [{"premise": " ", "stopping_rationale": "stopped"}]},
        {"bases": [{"role": "context", "evidence": ""}]},
        {"bases": [{"kind": "limitation", "unresolved_premise": "unknown"}]},
        {"answer": "invented_answer"},
        {"counterevidence": [{"basis_indexes": [1], "implication": "counterpoint"}]},
        {"counterevidence": [0]},
    ],
)
def test_new_submission_rejects_invalid_scientific_or_citation_content(change: dict) -> None:
    value = {
        "question_id": "sq:missing:data-available",
        "answer": "no_information",
        "bases": [{"role": "context", "evidence": "eh_0123456789abcdef"}],
        "justification": "Availability remains unresolved.",
        "unknowns": ["Observed count"],
        "counterevidence": [],
        **change,
    }
    with pytest.raises(ValidationError):
        DomainSaveAnswer.model_validate(value)


def test_mcp_rejects_d32_no_information_without_changing_answer(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    draft = _domain_draft("trial", "domain:missing", revision, evidence)
    draft["answers"][1]["answer"] = "no_information"
    response = _call(workspace, "save_domain_judgment", draft)
    assert response["outcome"] == "repair"
    assert any(r["code"] == "invalid_answer" for r in response["repairs"])
    assert draft["answers"][1]["answer"] == "no_information"
    assert response["head"]["state_revision"] == revision


@pytest.mark.parametrize("handles", [[], ["eh_0123456789abcdef"] * 2, ["not-a-handle"], [0]])
def test_joint_counterpoints_validate_every_selected_support(handles: list) -> None:
    with pytest.raises(ValidationError):
        DomainSaveAnswer.model_validate(
            {
                "question_id": "sq:selection:prespecified-analysis",
                "answer": "probably_no",
                "justification": "The inspected passages challenge timing.",
                "unknowns": [],
                "counterevidence": [{"evidence": handles, "implication": "Joint chronology."}],
            }
        )

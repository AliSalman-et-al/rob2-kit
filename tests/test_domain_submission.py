from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from support.rob2 import _assessment_workspace, _call, _domain_draft

from rob2_kit.workflow_models import DomainAnswer, DomainSaveAnswer

REJECTED = json.loads(
    (Path(__file__).parent / "fixtures/monarch-plus-rejected-submissions.json").read_text()
)


@pytest.mark.parametrize("draft", REJECTED)
def test_captured_malformed_calls_are_not_coerced_into_scientific_answers(draft: dict) -> None:
    with pytest.raises(ValidationError):
        for answer in draft["answers"]:
            DomainSaveAnswer.model_validate(answer)


def test_explicit_information_limit_preserves_failed_run_science_and_evidence() -> None:
    original = REJECTED[-1]["answers"][0]
    submitted = copy.deepcopy(original)
    mixed = submitted["bases"].pop()
    submitted["limitations"] = [
        {
            ("premise" if key == "unresolved_premise" else key): value
            for key, value in mixed["limitation"].items()
        }
    ]
    submitted["bases"] = [
        {"evidence": basis["evidence"], "role": basis["kind"]} for basis in submitted["bases"]
    ]
    # Its redundant evidence citation already occurs in the first selected basis.
    assert mixed["evidence"] == submitted["bases"][0]["evidence"]
    parsed = DomainSaveAnswer.model_validate(submitted)
    canonical = DomainAnswer.model_validate(parsed.canonical_payload())
    assert canonical.answer.value == original["answer"]
    assert canonical.justification == original["justification"]
    assert canonical.unknowns == tuple(original["unknowns"])
    assert [basis.model_dump() for basis in canonical.bases[:2]] == original["bases"][:2]
    assert canonical.bases[-1].model_dump(exclude_none=True) == {
        "kind": "limitation",
        **mixed["limitation"],
    }


@pytest.mark.parametrize(
    "change",
    [
        {"limitations": [{"premise": " ", "stopping_rationale": "stopped"}]},
        {"bases": [{"role": "context", "evidence": ""}]},
        {"bases": [{"kind": "limitation", "unresolved_premise": "unknown"}]},
        {"answer": "invented_answer"},
        {"counterevidence": [{"basis_index": 1, "implication": "counterpoint"}]},
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


def test_limitation_only_does_not_authorize_definitive_science(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    draft = _domain_draft("trial", "domain:randomization", revision, evidence)
    draft["answers"][0]["answer"] = "yes"
    draft["answers"][0]["bases"] = []
    draft["answers"][0]["limitations"] = [
        {
            "premise": "Sequence method remains unknown.",
            "stopping_rationale": "The bounded sources were inspected.",
        }
    ]
    response = _call(workspace, "save_domain_judgment", draft)
    assert response["outcome"] == "repair"
    assert any(item["code"] == "answer_requires_direct_basis" for item in response["repairs"])


def test_explicit_roles_and_information_limits_need_no_semantic_coercion() -> None:
    attempts = json.loads(
        (
            Path(__file__).parent / "fixtures/monarch-plus-separated-rejected-submissions.json"
        ).read_text()
    )
    for original in attempts[0]["answers"]:
        submission = DomainSaveAnswer.model_validate(original)
        saved = DomainAnswer.model_validate(submission.canonical_payload())
        assert saved.answer.value == original["answer"]
        assert saved.justification == original["justification"]
        assert saved.unknowns == tuple(original["unknowns"])
        assert [basis.model_dump() for basis in saved.bases[: len(original["bases"])]] == [
            {"kind": citation["role"], "evidence": citation["evidence"]}
            for citation in original["bases"]
        ]
    with pytest.raises(ValidationError):
        DomainSaveAnswer.model_validate(attempts[1]["answers"][0])


def test_direct_citation_does_not_erase_an_explicit_information_limit(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    draft = _domain_draft("trial", "domain:randomization", revision, evidence)
    draft["answers"][0]["answer"] = "yes"
    draft["answers"][0]["limitations"] = [
        {
            "premise": "The sequence-generation premise remains unresolved.",
            "stopping_rationale": "The scoped source review did not resolve it.",
        }
    ]
    response = _call(workspace, "save_domain_judgment", draft)
    assert response["outcome"] == "repair"
    assert any(
        item["code"] == "complete_claim_has_unresolved_premise" for item in response["repairs"]
    )

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


@pytest.mark.parametrize("role", ["direct_support", "context"])
def test_d32_no_can_retain_unknown_bias_with_inspected_evidence(tmp_path: Path, role: str) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    draft = _domain_draft("trial", "domain:missing", revision, evidence)
    answer = draft["answers"][1]
    assert answer["question_id"] == "sq:missing:evidence-unbiased"
    answer["bases"][0]["kind"] = role
    answer["justification"] = (
        "Inspected reporting does not establish protection from missing-data bias."
    )
    answer["unknowns"] = ["Whether missing outcomes biased the result."]
    answer["limitations"] = [
        {
            "premise": "Whether an informative sensitivity analysis exists elsewhere.",
            "stopping_rationale": "The bounded source review remains incomplete.",
        }
    ]
    response = _call(workspace, "save_domain_judgment", draft)
    assert response["outcome"] == "success", response


@pytest.mark.parametrize("index, value", [(1, "yes"), (0, "no"), (2, "no")])
def test_unresolved_positive_reassurance_and_missingness_claims_remain_rejected(
    tmp_path: Path,
    index: int,
    value: str,
) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    draft = _domain_draft("trial", "domain:missing", revision, evidence)
    draft["answers"][index]["answer"] = value
    draft["answers"][index]["limitations"] = [
        {
            "premise": "The premise necessary for this claim remains unresolved.",
            "stopping_rationale": "The bounded review did not resolve it.",
        }
    ]
    # A Yes at D3.2 or No at D3.3 deactivates the later questions.
    if index in {1, 2}:
        draft["answers"] = draft["answers"][: index + 1]
    response = _call(workspace, "save_domain_judgment", draft)
    assert response["outcome"] == "repair"
    assert any(r["code"] == "complete_claim_has_unresolved_premise" for r in response["repairs"])


def test_d32_no_still_requires_inspected_evidence_or_valid_search(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    draft = _domain_draft("trial", "domain:missing", revision, evidence)
    draft["answers"][1]["bases"] = []
    draft["answers"][1]["limitations"] = [
        {
            "premise": "No reassuring analysis is known.",
            "stopping_rationale": "No source was inspected for this premise.",
        }
    ]
    response = _call(workspace, "save_domain_judgment", draft)
    assert any(r["code"] == "answer_requires_direct_basis" for r in response["repairs"])


@pytest.mark.parametrize("invalid", ["evidence", "search_receipt"])
def test_d32_negative_evidence_exception_does_not_bypass_handle_validation(
    tmp_path: Path,
    invalid: str,
) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    draft = _domain_draft("trial", "domain:missing", revision, evidence)
    if invalid == "evidence":
        draft["answers"][1]["bases"] = [{"kind": "context", "evidence": "eh_ffffffffffffffff"}]
    else:
        draft["answers"][1]["bases"] = [
            {"kind": "absence", "search_receipt": "sr_ffffffffffffffff"}
        ]
    response = _call(workspace, "save_domain_judgment", draft)
    assert response["outcome"] == "repair"
    assert response["head"]["state_revision"] == revision


@pytest.mark.parametrize(
    "domain_id, question_id, definite",
    [
        ("domain:deviations", "sq:deviations:context-deviations", "no"),
        ("domain:deviations", "sq:deviations:appropriate-analysis", "yes"),
        ("domain:deviations", "sq:deviations:substantial-impact", "no"),
        ("domain:missing", "sq:missing:likely-dependent", "no"),
        ("domain:selection", "sq:selection:prespecified-analysis", "yes"),
        ("domain:selection", "sq:selection:multiple-measurements", "no"),
        ("domain:selection", "sq:selection:multiple-analyses", "no"),
    ],
)
@pytest.mark.parametrize("probable", [False, True])
def test_required_unknowns_are_not_negative_evidence_exemptions(
    tmp_path: Path,
    domain_id: str,
    question_id: str,
    definite: str,
    probable: bool,
) -> None:
    from rob2_kit.logic import active_questions

    workspace, evidence, revision = _assessment_workspace(tmp_path)
    draft = _domain_draft("trial", domain_id, revision, evidence)
    target = next(a for a in draft["answers"] if a["question_id"] == question_id)
    target["answer"] = f"probably_{definite}" if probable else definite
    target["limitations"] = [
        {
            "premise": "A premise required to establish this response remains unresolved.",
            "stopping_rationale": "Bounded source inspection did not resolve that premise.",
        }
    ]
    active = active_questions({a["question_id"]: a["answer"] for a in draft["answers"]})
    draft["answers"] = [a for a in draft["answers"] if a["question_id"] in active]
    response = _call(workspace, "save_domain_judgment", draft)
    if probable:
        assert response["outcome"] == "success", response
    else:
        assert any(
            r["code"] == "complete_claim_has_unresolved_premise" for r in response["repairs"]
        )


def test_mcp_rejects_d32_no_information_without_changing_answer(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    draft = _domain_draft("trial", "domain:missing", revision, evidence)
    draft["answers"][1]["answer"] = "no_information"
    response = _call(workspace, "save_domain_judgment", draft)
    assert response["outcome"] == "repair"
    assert any(r["code"] == "invalid_answer" for r in response["repairs"])
    assert draft["answers"][1]["answer"] == "no_information"
    assert response["head"]["state_revision"] == revision

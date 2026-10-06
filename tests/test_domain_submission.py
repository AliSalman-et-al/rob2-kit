from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from support.rob2 import _assessment_workspace, _call, _domain_draft

from rob2_kit.application._state import _state
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


def test_limitation_only_preserves_host_answer_without_semantic_certification(
    tmp_path: Path,
) -> None:
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
    assert response["outcome"] == "success", response
    record = _state(workspace)["domain_records"]["trial:" + draft["domain_id"]]
    submitted = draft["answers"][0]
    stored = next(a for a in record["answers"] if a["question_id"] == submitted["question_id"])
    assert stored["answer"] == submitted["answer"]
    assert any(b["kind"] == "limitation" for b in stored["bases"])


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
    assert response["outcome"] == "success", response
    record = _state(workspace)["domain_records"]["trial:" + draft["domain_id"]]
    submitted = draft["answers"][0]
    stored = next(a for a in record["answers"] if a["question_id"] == submitted["question_id"])
    assert stored["answer"] == submitted["answer"]
    assert any(b["kind"] == "limitation" for b in stored["bases"])


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
def test_source_limits_are_preserved_for_both_question_polarities(
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
    assert response["outcome"] == "success", response
    record = _state(workspace)["domain_records"]["trial:" + draft["domain_id"]]
    submitted = draft["answers"][index]
    stored = next(a for a in record["answers"] if a["question_id"] == submitted["question_id"])
    assert stored["answer"] == submitted["answer"]
    assert any(b["kind"] == "limitation" for b in stored["bases"])


def test_d32_no_requires_an_explicit_material_premise(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    draft = _domain_draft("trial", "domain:missing", revision, evidence)
    draft["answers"][1]["bases"] = []
    before = _state(workspace)
    response = _call(workspace, "save_domain_judgment", draft)
    assert response["outcome"] == "repair", response
    assert any(r["path"] == "/answers/1/bases" for r in response["repairs"])
    assert _state(workspace) == before


@pytest.mark.parametrize("invalid", ["evidence", "search_receipt", "counterpoint"])
def test_d32_negative_evidence_exception_does_not_bypass_handle_validation(
    tmp_path: Path,
    invalid: str,
) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    draft = _domain_draft("trial", "domain:missing", revision, evidence)
    if invalid == "evidence":
        draft["answers"][1]["bases"] = [{"kind": "context", "evidence": "eh_ffffffffffffffff"}]
    elif invalid == "search_receipt":
        draft["answers"][1]["bases"] = [
            {"kind": "absence", "search_receipt": "sr_ffffffffffffffff"}
        ]
    else:
        draft["answers"][1]["counterevidence"] = [
            {"evidence": ["eh_ffffffffffffffff"], "implication": "Unowned counterclaim."}
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
def test_required_unknowns_remain_visible_for_definite_and_probable_answers(
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
    assert response["outcome"] == "success", response
    stored = _state(workspace)["domain_records"]["trial:" + domain_id]
    answer = next(a for a in stored["answers"] if a["question_id"] == question_id)
    assert answer["answer"] == target["answer"]
    assert any(b["kind"] == "limitation" for b in answer["bases"])


def test_mcp_rejects_d32_no_information_without_changing_answer(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    draft = _domain_draft("trial", "domain:missing", revision, evidence)
    draft["answers"][1]["answer"] = "no_information"
    response = _call(workspace, "save_domain_judgment", draft)
    assert response["outcome"] == "repair"
    assert any(r["code"] == "invalid_answer" for r in response["repairs"])
    assert draft["answers"][1]["answer"] == "no_information"
    assert response["head"]["state_revision"] == revision


def test_captured_an_counterpoints_preserve_science_without_aliases() -> None:
    draft = json.loads(
        (Path(__file__).parent / "fixtures/an-d2-rejected-counterpoints.json").read_text()
    )
    for original in draft["answers"]:
        if original["counterevidence"]:
            with pytest.raises(ValidationError):
                DomainSaveAnswer.model_validate(original)
        else:
            DomainSaveAnswer.model_validate(original)
        translated = copy.deepcopy(original)
        translated["counterevidence"] = [
            {
                "evidence": [
                    original["bases"][index]["evidence"] for index in point["basis_indexes"]
                ],
                "implication": point["implication"],
            }
            for point in original["counterevidence"]
        ]
        public = DomainSaveAnswer.model_validate(translated)
        canonical = DomainAnswer.model_validate(public.canonical_payload())
        assert canonical.answer.value == original["answer"]
        assert canonical.justification == original["justification"]
        assert canonical.unknowns == tuple(original["unknowns"])
        assert canonical.counterevidence is not None
        assert [point.model_dump() for point in canonical.counterevidence] == [
            {"basis_index": index, "implication": point["implication"]}
            for point in original["counterevidence"]
            for index in point["basis_indexes"]
        ]


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


def test_joint_counterpoint_keeps_all_citations_and_the_same_implication() -> None:
    implication = "The plan date and unblinding date together challenge prespecification."
    public = DomainSaveAnswer.model_validate(
        {
            "question_id": "sq:selection:prespecified-analysis",
            "answer": "probably_no",
            "justification": "The inspected chronology supports a probable answer.",
            "unknowns": [],
            "bases": [{"role": "contradiction", "evidence": "eh_0123456789abcdef"}],
            "counterevidence": [
                {
                    "evidence": ["eh_0123456789abcdef", "eh_fedcba9876543210"],
                    "implication": implication,
                }
            ],
        }
    )
    canonical = DomainAnswer.model_validate(public.canonical_payload())
    assert [basis.kind for basis in canonical.bases] == ["contradiction", "context"]
    assert [(p.basis_index, p.implication) for p in canonical.counterevidence or ()] == [
        (0, implication),
        (1, implication),
    ]
    with pytest.raises(ValidationError):
        DomainSaveAnswer.model_validate(
            {
                **public.model_dump(),
                "counterevidence": [{"basis_indexes": [0], "implication": implication}],
            }
        )


@pytest.mark.parametrize("field", ["justification", "unknowns", "counterevidence"])
def test_public_answer_schema_requires_all_reasoning_fields(field: str) -> None:
    answer = {
        "question_id": "sq:missing:data-available",
        "answer": "no_information",
        "justification": "The captured evidence leaves availability unresolved.",
        "unknowns": [],
        "counterevidence": [],
    }
    del answer[field]
    with pytest.raises(ValidationError, match=field):
        DomainSaveAnswer.model_validate(answer)


@pytest.mark.parametrize(
    "value, judgment",
    [("probably_yes", "high"), ("probably_no", "some_concerns"), ("no_information", "high")],
)
@pytest.mark.parametrize("valid_evidence", [True, False])
def test_d45_contextual_answers_preserve_calibration_and_evidence_binding(
    tmp_path: Path, value: str, judgment: str, valid_evidence: bool
) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    draft = _domain_draft("trial", "domain:measurement", revision, evidence)
    answer = draft["answers"][-1]
    assert answer["question_id"] == "sq:measurement:influence-likely"
    answer["answer"] = value
    answer["bases"] = [
        {
            "kind": "inference",
            "evidence": evidence["handle"] if valid_evidence else "eh_0000000000000000",
        }
    ]
    answer["justification"] = (
        "The cited context bears on likelihood; direct evidence of changed ratings is unavailable."
    )
    answer["unknowns"] = ["Whether individual ratings actually changed."]
    response = _call(workspace, "save_domain_judgment", draft)
    if valid_evidence:
        assert response["outcome"] == "success", response
        record = _state(workspace)["domain_records"]["trial:domain:measurement"]
        assert record["answers"][-1]["answer"] == value
        assert record["judgment"] == judgment
        assert record["answers"][-1]["unknowns"] == answer["unknowns"]
    else:
        assert response["outcome"] == "repair", response
        assert any(item["code"] == "invalid_evidence" for item in response["repairs"])

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest
from fastmcp.exceptions import ToolError
from support.rob2 import (
    _assessment_workspace,
    _call,
    _domain_draft,
    _prepared_evidence,
    _proposal_args,
    _read_required_main_reports,
    _result,
    _review,
    _workspace,
)

from rob2_kit.application._state import _state
from rob2_kit.application.evidence import _search_receipt
from rob2_kit.interfaces.mcp import server
from rob2_kit.interfaces.mcp.contracts import MissingDataReconciliation
from rob2_kit.packs import SCIENTIFIC_PACK


def _save_all_domains(workspace: Path, evidence: dict, revision: int) -> int:
    for domain in SCIENTIFIC_PACK.domains:
        saved = _call(
            workspace,
            "save_domain_judgment",
            _domain_draft("trial", domain.id, revision, evidence),
        )
        assert saved["outcome"] == "success", saved
        revision = int(saved["head"]["state_revision"])
    return revision


def test_long_selected_evidence_has_bounded_review_fact_and_exact_expansion(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Figure label")
    figure_path = workspace / "input" / "trial" / "figure.pdf"
    document.save(figure_path)
    document.close()
    evidence = _prepared_evidence(workspace)
    figure_source = next(
        item
        for item in _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
        if item["label"] == "figure.pdf"
    )
    rendered = _call(
        workspace,
        "render_page",
        {"trial_id": "trial", "source_id": figure_source["id"], "page": 1},
    )
    long_visual = _call(
        workspace,
        "select_visual_evidence",
        {
            "trial_id": "trial",
            "source_id": figure_source["id"],
            "delivery_receipt": rendered["data"]["delivery_receipt"],
            "transcription": "x" * 5_000,
            "region": [0.1, 0.1, 0.9, 0.9],
        },
    )["data"]["evidence"]
    assert len(long_visual["transcription"]) > 4_000
    saved = _call(workspace, "save_proposal", _proposal_args(workspace, [_result(evidence)]))
    assert saved["outcome"] == "review_required", saved
    _review(workspace)
    _read_required_main_reports(workspace)
    revision = int(_call(workspace, "get_status", {})["head"]["state_revision"])
    revision = _save_all_domains(workspace, long_visual, revision)

    selected_domain = SCIENTIFIC_PACK.domains[0]
    selected_question = _domain_draft("trial", selected_domain.id, revision, long_visual)[
        "answers"
    ][0]["question_id"]
    reviewed = _call(
        workspace,
        "review_trial",
        {
            "trial_id": "trial",
            "expected_revision": revision,
            "domain_id": selected_domain.id,
            "question_id": selected_question,
        },
    )

    assert reviewed["outcome"] == "success", reviewed
    answer = reviewed["data"]["domain_findings"][0]["answers"][0]
    fact = next(
        item
        for item in answer["facts"]
        if item.get("evidence", {}).get("handle") == long_visual["handle"]
    )
    assert len(fact["text"]) <= 4_000
    assert fact["text"].endswith(" … [excerpt; use evidence_expansions to inspect full Evidence]")
    expansion = next(
        item for item in answer["evidence_expansions"] if item["evidence"] == long_visual["handle"]
    )
    assert expansion == {
        "operation": "render_page",
        "evidence": long_visual["handle"],
        "trial_id": "trial",
        "source_id": figure_source["id"],
        "page": 1,
    }


def test_review_projection_failure_does_not_commit_review(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    revision = _save_all_domains(workspace, evidence, revision)
    before = int(_call(workspace, "get_status", {})["head"]["state_revision"])
    assert before == revision
    original_validate = server.validate_output

    def fail_review_projection(name: str, value: dict) -> dict:
        if name == "review_trial" and value.get("outcome") == "success":
            raise ValueError("injected review projection failure")
        return original_validate(name, value)

    monkeypatch.setattr(server, "validate_output", fail_review_projection)
    with pytest.raises(ToolError, match="internal_output_contract_error"):
        _call(
            workspace,
            "review_trial",
            {"trial_id": "trial", "expected_revision": revision},
        )

    assert _state(workspace)["revision"] == before
    assert "trial" not in (_state(workspace).get("trial_reviews") or {})


def test_review_retry_validates_existing_projection_without_committing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    revision = _save_all_domains(workspace, evidence, revision)
    first = _call(
        workspace,
        "review_trial",
        {"trial_id": "trial", "expected_revision": revision},
    )
    assert first["outcome"] == "success", first
    before = int(_call(workspace, "get_status", {})["head"]["state_revision"])
    original_validate = server.validate_output

    def fail_retry_projection(name: str, value: dict) -> dict:
        if name == "review_trial" and value.get("outcome") == "success":
            raise ValueError("injected retry projection failure")
        return original_validate(name, value)

    monkeypatch.setattr(server, "validate_output", fail_retry_projection)
    with pytest.raises(ToolError, match="internal_output_contract_error"):
        _call(
            workspace,
            "review_trial",
            {"trial_id": "trial", "expected_revision": before},
        )

    assert _state(workspace)["revision"] == before
    assert "trial" in (_state(workspace).get("trial_reviews") or {})


@pytest.mark.parametrize(("partial_search", "expect_search_route"), [(False, False), (True, True)])
def test_trial_review_only_keeps_search_routes_that_remain_open(
    partial_search: bool,
    expect_search_route: bool,
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    if partial_search:
        (workspace / "input" / "trial" / "supplement.txt").write_text(
            "The requested outcome was also described in this supplement.", encoding="utf-8"
        )
    evidence = _prepared_evidence(workspace)
    proposed = _call(workspace, "save_proposal", _proposal_args(workspace, [_result(evidence)]))
    assert proposed["outcome"] == "review_required", proposed
    source = next(
        item
        for item in _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
        if item["label"] == "main.txt"
    )
    query = "The requested outcome" if partial_search else "phrase absent from the report"
    searched = _call(
        workspace,
        "search_sources",
        {
            "trial_id": "trial",
            "query": query,
            "mode": "phrase" if partial_search else "literal",
            "purpose_domain_id": "domain:randomization",
            "limit": 1,
        },
    )
    assert searched["outcome"] == "success", searched
    search_receipt = searched["data"]["search_receipt"]
    assert isinstance(search_receipt, str)
    assert _search_receipt(workspace, search_receipt)["truncated"] is partial_search

    note = {
        "text": "Allocation concealment was not resolved in the saved review.",
        "sources": [{"source_id": source["id"], "page": 1, "start_line": 1, "end_line": 1}],
        "domain_id": "domain:randomization",
        "question_id": "sq:randomization:concealment",
    }
    checkpoint = {
        "trial_id": "trial",
        "observations": [note],
        "unread_ranges": [],
        "premise_records": [
            {
                "proposition": "Allocation remained concealed until assignment.",
                "status": "bounded",
                "observations": [note],
                "unresolved_component": "The concealment procedure is not reported.",
                "stopping_rationale": "The captured report leaves the procedure unresolved.",
                "next_action": "Continue the scoped search for a discriminating passage.",
                "domain_id": "domain:randomization",
                "question_id": "sq:randomization:concealment",
            }
        ],
    }
    saved_checkpoint = _call(workspace, "save_working_checkpoint", {"checkpoint": checkpoint})
    assert saved_checkpoint["outcome"] == "success", saved_checkpoint
    _review(workspace)
    _read_required_main_reports(workspace)
    revision = int(_call(workspace, "get_status", {})["head"]["state_revision"])
    for domain in SCIENTIFIC_PACK.domains:
        draft = (
            _domain_draft("trial", domain.id, revision, search_receipt=search_receipt)
            if domain.id == "domain:randomization"
            else _domain_draft("trial", domain.id, revision, evidence)
        )
        saved_domain = _call(workspace, "save_domain_judgment", draft)
        assert saved_domain["outcome"] == "success", saved_domain
        revision = int(saved_domain["head"]["state_revision"])

    reviewed = _call(
        workspace,
        "review_trial",
        {
            "trial_id": "trial",
            "expected_revision": revision,
            "domain_id": "domain:randomization",
            "question_id": "sq:randomization:concealment",
        },
    )

    assert reviewed["outcome"] == "success", reviewed
    randomization = next(
        item
        for item in reviewed["data"]["domain_findings"]
        if item["domain_id"] == "domain:randomization"
    )
    concealment = next(
        item
        for item in randomization["answers"]
        if item["question_id"] == "sq:randomization:concealment"
    )
    assert bool(concealment["uninvestigated_routes"]) is expect_search_route


def test_review_flags_source_bound_participant_flow_scope_without_host_marker(
    tmp_path: Path,
) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    for domain in SCIENTIFIC_PACK.domains:
        draft = _domain_draft("trial", domain.id, revision, evidence)
        if domain.id == "domain:deviations":
            answer = next(
                item
                for item in draft["answers"]
                if item["question_id"] == "sq:deviations:context-deviations"
            )
            answer["missing_data"] = [
                {
                    "arm": "active",
                    "population": "per-protocol participants",
                    "unit": "participants",
                    "time_point": "end of follow-up",
                    "randomized": 90,
                    "observed": 86,
                    "basis": [evidence["handle"]],
                }
            ]
        saved = _call(workspace, "save_domain_judgment", draft)
        assert saved["outcome"] == "success", saved
        revision = int(saved["head"]["state_revision"])

    reviewed = _call(
        workspace,
        "review_trial",
        {
            "trial_id": "trial",
            "expected_revision": revision,
            "domain_id": "domain:deviations",
            "question_id": "sq:deviations:context-deviations",
        },
    )

    assert reviewed["outcome"] == "success", reviewed
    deviations = next(
        item
        for item in reviewed["data"]["domain_findings"]
        if item["domain_id"] == "domain:deviations"
    )
    answer = next(
        item
        for item in deviations["answers"]
        if item["question_id"] == "sq:deviations:context-deviations"
    )
    mismatch = next(
        item for item in answer["conflicts"] if item["kind"] == "potential_scope_mismatch"
    )
    assert "population" in mismatch["detail"]
    assert mismatch["assertion"] == "server_derived"
    assert "text differing" in mismatch["detail"]
    assert "Interpret the cited passages" in mismatch["detail"]
    assert mismatch["evidence"] == [
        {"handle": evidence["handle"], "identity": evidence["identity"]}
    ]


def test_trial_review_keeps_result_and_judgment_driving_question_with_its_basis(
    tmp_path: Path,
) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    revision = _save_all_domains(workspace, evidence, revision)

    summary = _call(
        workspace,
        "review_trial",
        {"trial_id": "trial", "expected_revision": revision},
    )

    assert summary["outcome"] == "success", summary
    if "review_page" in summary["data"]:
        assert summary["data"]["review_page"]["mode"] in {"summary", "complete"}
    driver = next(
        answer
        for finding in summary["data"]["domain_findings"]
        for answer in finding["answers"]
        if answer["driver"]
    )
    finding = next(
        item
        for item in summary["data"]["domain_findings"]
        if any(answer["question_id"] == driver["question_id"] for answer in item["answers"])
    )
    reviewed = _call(
        workspace,
        "review_trial",
        {
            "trial_id": "trial",
            "expected_revision": summary["head"]["state_revision"],
            "domain_id": finding["domain_id"],
            "question_id": driver["question_id"],
        },
    )

    assert reviewed["outcome"] == "success", reviewed
    approved = _state(workspace)["proposal"]["payload"]["results"][0]
    assert reviewed["data"]["result"] == approved
    driver = reviewed["data"]["domain_findings"][0]["answers"][0]
    question = next(item for item in SCIENTIFIC_PACK.questions if item.id == driver["question_id"])
    assert driver["question"] == question.wording
    assert driver["facts"]
    assert driver["facts"][0]["evidence"]["handle"] == evidence["handle"]
    assert driver["warrant"]
    assert "counterevidence" in driver
    assert "unknowns" in driver


def test_trial_review_challenges_analysis_denominator_as_availability_without_changing_judgment(
    tmp_path: Path,
) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    missing_draft = _domain_draft("trial", "domain:missing", revision, evidence)
    availability = next(
        answer
        for answer in missing_draft["answers"]
        if answer["question_id"] == "sq:missing:data-available"
    )
    availability["answer"] = "yes"
    availability["justification"] = (
        "The analysis denominator shows outcome data were available for all participants."
    )
    availability["missing_data"] = [
        {
            "arm": "intervention",
            "population": "randomized participants",
            "unit": "participants",
            "time_point": "end of follow-up",
            "randomized": 100,
            "analyzed": 100,
            "event_count": 40,
            "event_definition": "death",
            "basis": [evidence["handle"]],
        }
    ]

    findings = {}
    for domain in SCIENTIFIC_PACK.domains:
        saved = _call(
            workspace,
            "save_domain_judgment",
            {
                **(
                    missing_draft
                    if domain.id == "domain:missing"
                    else _domain_draft("trial", domain.id, revision, evidence)
                ),
                "expected_revision": revision,
            },
        )
        assert saved["outcome"] == "success", saved
        revision = int(saved["head"]["state_revision"])
        findings[domain.id] = saved["data"]["checkpoint"]["judgment"]

    reviewed = _call(
        workspace,
        "review_trial",
        {
            "trial_id": "trial",
            "expected_revision": revision,
            "domain_id": "domain:missing",
            "question_id": "sq:missing:data-available",
        },
    )

    assert reviewed["outcome"] == "success", reviewed
    missing = next(
        finding
        for finding in reviewed["data"]["domain_findings"]
        if finding["domain_id"] == "domain:missing"
    )
    availability = next(
        answer
        for answer in missing["answers"]
        if answer["question_id"] == "sq:missing:data-available"
    )
    conflict = next(
        item for item in availability["conflicts"] if item["kind"] == "unsupported_link"
    )
    assert conflict["assertion"] == "server_derived"
    assert conflict["evidence"] == [
        {"handle": evidence["handle"], "identity": evidence["identity"]}
    ]
    assert "do not establish outcome availability" in conflict["detail"]
    assert availability["answer"] == "yes"
    assert missing["judgment"] == findings["domain:missing"]


def test_review_retains_scoped_count_arithmetic_and_unknown_ascertainment(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    for domain in SCIENTIFIC_PACK.domains:
        draft = _domain_draft("trial", domain.id, revision, evidence)
        if domain.id == "domain:missing":
            availability = next(
                answer
                for answer in draft["answers"]
                if answer["question_id"] == "sq:missing:data-available"
            )
            availability["missing_data"] = [
                {
                    "arm": "intervention",
                    "population": "randomized participants",
                    "unit": "participants",
                    "time_point": "day 90",
                    "randomized": 100,
                    "observed": 90,
                    "analyzed": 95,
                    "event_count": 12,
                    "event_definition": "requested outcome",
                    "basis": [evidence["handle"]],
                },
                {
                    "arm": "control",
                    "population": "randomized participants",
                    "unit": "participants",
                    "time_point": "day 90",
                    "randomized": 120,
                    "analyzed": 120,
                    "event_count": 20,
                    "event_definition": "requested outcome",
                    "semantics": {
                        "outcome_status": "unknown",
                        "censoring": {
                            "kind": "administrative",
                            "count": 25,
                            "timing": "common cutoff",
                        },
                    },
                    "basis": [evidence["handle"]],
                },
            ]
        saved = _call(workspace, "save_domain_judgment", draft)
        assert saved["outcome"] == "success", saved
        revision = int(saved["head"]["state_revision"])
    before = _state(workspace)["domain_records"]
    reviewed = _call(
        workspace,
        "review_trial",
        {"trial_id": "trial", "expected_revision": revision, "domain_id": "domain:missing"},
    )
    assert reviewed["outcome"] == "success", reviewed
    missing = next(
        finding
        for finding in reviewed["data"]["domain_findings"]
        if finding["domain_id"] == "domain:missing"
    )
    availability = next(
        answer
        for answer in missing["answers"]
        if answer["question_id"] == "sq:missing:data-available"
    )
    saved_availability = next(
        answer
        for answer in before["trial:domain:missing"]["answers"]
        if answer["question_id"] == "sq:missing:data-available"
    )
    # Existing public serialization expands absent optional semantic fields to null.
    expected_counts = MissingDataReconciliation.model_validate(
        saved_availability["missing_data"]
    ).model_dump(mode="json")
    assert availability["missing_data"] == expected_counts
    observed, censored = availability["missing_data"]["rows"]
    assert observed["missing"] == 10
    assert observed["missing_fraction"] == 0.1
    assert observed["analyzed"] == 95
    assert observed["event_count"] == 12
    assert observed["basis"] == [evidence["identity"]]
    assert observed["scope"]["time_point"] == "day 90"
    assert censored["observed"] is None
    assert censored["missing"] is None
    assert censored["missing_fraction"] is None
    assert censored["semantics"]["censoring"]["count"] == 25
    assert availability["answer"] == saved_availability["answer"]
    assert _state(workspace)["domain_records"] == before
    retry = _call(
        workspace,
        "review_trial",
        {
            "trial_id": "trial",
            "expected_revision": reviewed["head"]["state_revision"],
            "domain_id": "domain:missing",
        },
    )
    assert retry["outcome"] == "success", retry
    assert retry["data"]["domain_findings"] == reviewed["data"]["domain_findings"]
    assert _state(workspace)["domain_records"] == before


def test_review_leads_with_saved_drivers_without_inventing_low_drivers(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    for domain in SCIENTIFIC_PACK.domains:
        draft = _domain_draft("trial", domain.id, revision, evidence)
        if domain.id == "domain:deviations":
            values = {
                "sq:deviations:participants-aware": "no",
                "sq:deviations:personnel-aware": "no",
                "sq:deviations:appropriate-analysis": "yes",
            }
            draft["answers"] = [
                {**answer, "answer": values[answer["question_id"]]}
                for answer in draft["answers"]
                if answer["question_id"] in values
            ]
        saved = _call(workspace, "save_domain_judgment", draft)
        assert saved["outcome"] == "success", saved
        revision = int(saved["head"]["state_revision"])
    before = _state(workspace)["domain_records"]
    reviewed = _call(
        workspace, "review_trial", {"trial_id": "trial", "expected_revision": revision}
    )
    assert reviewed["outcome"] == "success", reviewed
    for finding in reviewed["data"]["domain_findings"]:
        answers = finding["answers"]
        assert [answer["driver"] for answer in answers] == sorted(
            [answer["driver"] for answer in answers], reverse=True
        )
        saved = before[f"trial:{finding['domain_id']}"]
        assert {answer["question_id"] for answer in answers} == {
            answer["question_id"] for answer in saved["answers"]
        }
        for is_driver in (True, False):
            assert [
                answer["question_id"] for answer in answers if answer["driver"] is is_driver
            ] == [
                answer["question_id"]
                for answer in saved["answers"]
                if (answer["question_id"] in saved["driver_questions"]) is is_driver
            ]
        assert all("missing_data" not in answer for answer in answers)
    deviations = next(
        finding
        for finding in reviewed["data"]["domain_findings"]
        if finding["domain_id"] == "domain:deviations"
    )
    assert deviations["judgment"] == "low"
    # The deterministic Low branch has no driver question IDs. Review must not invent them.
    assert not any(answer["driver"] for answer in deviations["answers"])
    assert _state(workspace)["domain_records"] == before

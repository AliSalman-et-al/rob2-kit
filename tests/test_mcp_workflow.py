"""Black-box MCP workflow behavior tests."""

# Shared private helpers keep caller setup out of the scenarios.
# ruff: noqa: F405

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from support.rob2 import *  # noqa: F401,F403

from rob2_kit.application._state import _state
from rob2_kit.application.contracts import COUNTERS
from rob2_kit.application.evidence import _search_receipt
from rob2_kit.application.intake import prepare_batch as application_prepare_batch
from rob2_kit.application.status import get_status
from rob2_kit.packs import SCIENTIFIC_PACK
from rob2_kit.workflow_models import ProposalDraft, TrialDeclaration


def test_prepare_rejects_malformed_intake_before_durable_state_commit(tmp_path: Path) -> None:
    workspace = tmp_path
    trial = workspace / "input" / "trial"
    trial.mkdir(parents=True)
    (trial / "main.txt").write_text("captured source", encoding="utf-8")
    (trial / "sources.toml").write_text(
        'omissions = [{path = "main.txt", reason = "not-a-reason", rationale = "bad"}]\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        application_prepare_batch(
            workspace,
            [
                TrialDeclaration(
                    id="trial",
                    label="trial",
                    requested_outcome="requested outcome",
                )
            ],
            expected_revision=0,
        )
    assert _state(workspace).get("batch") is None


def test_verify_cli_checks_product_bundle_and_returns_status(tmp_path: Path) -> None:
    artifact = _assessed_artifact(_workspace(tmp_path))
    from rob2_kit.interfaces.cli.app import main as cli_main

    assert cli_main(["verify", str(artifact)]) == 0
    assert cli_main(["verify", str(tmp_path / "missing.rob2.zip")]) == 1


def test_domain_query_suggestions_execute_alternative_wording_after_literal_no_hit(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "input" / "trial" / "main.txt").write_text(
        "The requested outcome was not reported; only an alternate endpoint was measured. "
        "death ascertainment; end of follow-up; assigned to intervention; assigned to control; "
        "randomized population; risk ratio; The requested outcome was measured in the analyzed "
        "population.; risk; 1; events; 2. The intent-to-treat analysis included all randomized "
        "patients.\n",
        encoding="utf-8",
    )
    evidence = _prepared_evidence(workspace)
    _call(workspace, "save_proposal", _proposal_args(workspace, [_result(evidence)]))
    _review(workspace)
    _read_required_main_reports(workspace)
    revision = int(_call(workspace, "get_domain_context", {})["head"]["state_revision"])
    first_domain = SCIENTIFIC_PACK.domains[0].id
    saved = _call(
        workspace,
        "save_domain_judgment",
        _domain_draft("trial", first_domain, revision, evidence),
    )
    assert saved["outcome"] == "success"

    context = _call(workspace, "get_domain_context", {})["data"]
    question = next(
        item for item in context["questions"] if item["id"] == "sq:deviations:appropriate-analysis"
    )
    suggestions = question["query_suggestions"]
    exact = next(item for item in suggestions if item["query"] == "intention-to-treat")
    alternative = next(item for item in suggestions if item["query"] == "intent-to-treat")

    porter_match = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": exact["query"], "mode": exact["mode"]},
    )
    assert porter_match["outcome"] == "success"
    assert porter_match["data"]["hits"]

    no_hit = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": exact["query"], "mode": "literal"},
    )
    assert no_hit["outcome"] == "success"
    assert no_hit["data"]["condition"] == "no_hits"

    visible = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": alternative["query"], "mode": "literal"},
    )
    assert visible["outcome"] == "success"
    assert visible["data"]["hits"]

    refreshed = _call(workspace, "get_domain_context", {})["data"]
    refreshed_question = next(
        item
        for item in refreshed["questions"]
        if item["id"] == "sq:deviations:appropriate-analysis"
    )
    assert refreshed_question["query_suggestions"] == suggestions


def test_proposal_rejects_object_group_value_fields_in_the_closed_reported_form(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    evidence = _prepared_evidence(workspace)
    result = _result(evidence)
    result["reported"]["group_values"][0] = {
        "group_id": "a",
        "statistic": "risk",
        "value": {"number": "1"},
        "unit": "events",
    }
    with pytest.raises(ValidationError):
        ProposalDraft.model_validate(
            {"results": [result], "expected_revision": int(get_status(workspace)["state_revision"])}
        )


def test_proposal_cannot_use_another_trials_selected_evidence(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    second = workspace / "input" / "second"
    second.mkdir(parents=True)
    (second / "main.txt").write_text("The requested outcome was measured.", encoding="utf-8")
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    _read_required_main_reports(workspace)
    source = _call(workspace, "list_sources", {"trial_id": "second"})["data"]["sources"][0]
    foreign = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "second",
            "source_id": source["id"],
            "page": 1,
            "start_line": 1,
            "end_line": 1,
        },
    )["data"]["evidence"]
    result = _result(foreign)
    unavailable = _unavailable_result(foreign, "Researcher must select the intended result.")
    unavailable["trial_id"] = "second"
    repair = _call(workspace, "save_proposal", _proposal_args(workspace, [result, unavailable]))
    assert repair["outcome"] == "repair"
    assert repair["repairs"] == [
        {
            "path": "/assessments/0/evidence_basis/0",
            "code": "cross_trial_evidence",
            "detail": "Reasoning Evidence must resolve to selected material from this Trial.",
            "answer_path": None,
        }
    ]


def test_search_receipts_are_verified_disposable_derivatives(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    COUNTERS["extraction_calls"] = 0
    hit = _call(
        workspace, "search_sources", {"trial_id": "trial", "query": "requested", "mode": "any"}
    )
    retry = _call(
        workspace, "search_sources", {"trial_id": "trial", "query": "requested", "mode": "any"}
    )
    assert hit["data"]["hits"][0]["source_role"] == "main_article"
    assert hit["data"]["hits"][0]["source_label"] == "main.txt"
    assert (
        _search_receipt(workspace, hit["data"]["search_receipt"])["identity"]
        == _search_receipt(workspace, retry["data"]["search_receipt"])["identity"]
    )
    no_hit = _call(
        workspace, "search_sources", {"trial_id": "trial", "query": "absent", "mode": "any"}
    )
    changed = _call(
        workspace, "search_sources", {"trial_id": "trial", "query": "requested", "mode": "all"}
    )
    assert no_hit["outcome"] == "success"
    assert no_hit["data"]["condition"] == "no_hits"
    assert no_hit["data"]["search_receipt"].startswith("sr_")
    assert (
        _search_receipt(workspace, changed["data"]["search_receipt"])["identity"]
        != _search_receipt(workspace, hit["data"]["search_receipt"])["identity"]
    )
    assert COUNTERS["extraction_calls"] == 0
    with pytest.raises(ValueError):
        _search_receipt(workspace, "sr_" + "0" * 16)
    derivative = workspace / ".rob2-kit" / "derivative.sqlite3"
    derivative.unlink()
    rebuilt = _call(
        workspace, "search_sources", {"trial_id": "trial", "query": "requested", "mode": "any"}
    )
    assert (
        _search_receipt(workspace, rebuilt["data"]["search_receipt"])["identity"]
        == _search_receipt(workspace, hit["data"]["search_receipt"])["identity"]
    )
    assert COUNTERS["extraction_calls"] > 0

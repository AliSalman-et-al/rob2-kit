"""Black-box MCP workflow behavior tests."""

# Shared private helpers keep caller setup out of the scenarios.
# ruff: noqa: F405

from __future__ import annotations

from pathlib import Path
from typing import Any

import pymupdf
import pytest
from pydantic import ValidationError
from support.rob2 import *  # noqa: F401,F403

from rob2_kit.application._state import _state
from rob2_kit.application.contracts import COUNTERS
from rob2_kit.application.evidence import _search_receipt
from rob2_kit.application.intake import prepare_batch as application_prepare_batch
from rob2_kit.application.status import get_status
from rob2_kit.interfaces.mcp import server
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


def test_finalize_value_error_is_preserved_when_finalization_is_next(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail() -> dict[str, Any]:
        raise ValueError("final bundle integrity failed")

    monkeypatch.setattr(
        server,
        "_get_status_head",
        lambda _workspace: {"continuation": {"operation": "finalize_batch"}},
    )
    monkeypatch.setattr(server, "_content", lambda _tool, value: value)

    receipt: Any = server._invoke("finalize_batch", fail)

    assert receipt["condition"] == "final bundle integrity failed"


def test_verify_cli_checks_product_bundle_and_returns_status(tmp_path: Path) -> None:
    artifact = _assessed_artifact(_workspace(tmp_path))
    from rob2_kit.interfaces.cli.app import main as cli_main

    assert cli_main(["verify", str(artifact)]) == 0
    assert cli_main(["verify", str(tmp_path / "missing.rob2.zip")]) == 1


def test_cli_exports_packaged_skill(tmp_path: Path) -> None:
    from rob2_kit.interfaces.cli.app import main as cli_main

    destination = tmp_path / ".claude" / "skills" / "rob2-assess"

    assert cli_main(["export-skill", "--output", str(destination)]) == 0
    assert (destination / "SKILL.md").is_file()
    assert (destination / "references" / "randomization.md").is_file()


def test_domain_questions_include_typed_premise_rules_and_shortcuts(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    questions: dict[str, dict[str, Any]] = {}
    for domain in SCIENTIFIC_PACK.domains:
        context = _call(workspace, "get_domain_context", {})["data"]
        assert context["domain_id"] == domain.id
        questions.update({item["id"]: item for item in context["questions"]})
        saved = _call(
            workspace,
            "save_domain_judgment",
            _domain_draft("trial", domain.id, revision, evidence),
        )
        assert saved["outcome"] == "success", saved
        revision = int(saved["head"]["state_revision"])
    expected = {
        "sq:randomization:sequence": "underwent randomization",
        "sq:deviations:participants-aware": "completed treatment",
        "sq:deviations:context-deviations": "nonadherence alone",
        "sq:deviations:affected-outcome": "an ITT analysis",
        "sq:selection:prespecified-analysis": "an objective definition",
        "sq:selection:multiple-analyses": "a single ITT analysis",
    }
    fidelity_markers = {
        "sq:randomization:sequence": "random component",
        "sq:randomization:concealment": "remote or centrally",
        "sq:randomization:baseline-imbalance": "compatible with chance",
        "sq:deviations:participants-aware": "side effects",
        "sq:deviations:personnel-aware": "carers",
        "sq:deviations:context-deviations": "trial context",
        "sq:deviations:affected-outcome": "effect estimate",
        "sq:deviations:balanced": "balanced between",
        "sq:deviations:appropriate-analysis": "intention-to-treat",
        "sq:deviations:substantial-impact": "5%",
        "sq:missing:data-available": "95%",
        "sq:missing:evidence-unbiased": "last-observation",
        "sq:missing:true-value-dependent": "health status",
        "sq:missing:likely-dependent": "censoring",
        "sq:measurement:method-inappropriate": "sensitive",
        "sq:measurement:differential": "Comparable methods",
        "sq:measurement:assessor-aware": "blinded",
        "sq:measurement:influence-possible": "participant-reported",
        "sq:measurement:influence-likely": "strong levels of belief",
        "sq:selection:prespecified-analysis": "unblinded outcome data",
        "sq:selection:multiple-measurements": "multiple eligible",
        "sq:selection:multiple-analyses": "multiple eligible ways",
    }
    assert set(questions) == set(fidelity_markers)
    compact_fields = {
        "id",
        "wording",
        "options",
        "active",
        "activation",
        "official_guidance",
        "source_locator",
        "decision_rule",
        "evidence_needed",
        "no_information_rule",
        "considerations",
        "invalid_shortcuts",
        "query_suggestions",
        "search_previews",
    }
    assert all(set(question) == compact_fields for question in questions.values())
    for question_id, shortcut in expected.items():
        question = questions[question_id]
        assert question["activation"]["kind"] in {"always", "rule"}
        assert question["source_locator"].startswith("Full guidance ")
        assert shortcut in question["invalid_shortcuts"]
        assert question["decision_rule"]
        assert question["options"]
        assert question["no_information_rule"]
        pack_question = next(item for item in SCIENTIFIC_PACK.questions if item.id == question_id)
        assert pack_question.guidance.official.source_excerpt == question["official_guidance"]
        assert pack_question.guidance.official.source_locator == question["source_locator"]
        assert pack_question.guidance.operational.decision_rule == question["decision_rule"]
        assert pack_question.guidance.operational.evidence_needed == tuple(
            question["evidence_needed"]
        )
        assert {option["official_answer"] for option in question["options"]} == {
            answer.value for answer in pack_question.allowed_answers
        }
        assert (
            pack_question.guidance.operational.no_information_rule
            == question["no_information_rule"]
        )
        assert pack_question.guidance.operational.considerations == tuple(
            question["considerations"]
        )
        assert pack_question.guidance.operational.invalid_shortcuts == tuple(
            question["invalid_shortcuts"]
        )
        assert tuple(question["query_suggestions"]) == tuple(
            item.model_dump(mode="json")
            for item in pack_question.guidance.operational.query_suggestions
        )
    for question_id, marker in fidelity_markers.items():
        guidance = questions[question_id]
        assert marker.lower() in guidance["official_guidance"].lower()
        allowed = {
            answer.value
            for answer in next(
                item for item in SCIENTIFIC_PACK.questions if item.id == question_id
            ).allowed_answers
        }
        assert all(option["official_answer"] in allowed for option in guidance["options"])


def test_domain_query_suggestions_include_executable_alternative_wording(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
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
    assert all(
        item["query"] and item["mode"] in {"all", "phrase", "any", "prefix"} for item in suggestions
    )
    assert {item["query"] for item in suggestions} >= {
        "intention-to-treat",
        "all randomized patients",
    }
    assert (
        next(item for item in suggestions if item["query"] == "intention-to-treat")["mode"]
        == "phrase"
    )
    assert (
        next(item for item in suggestions if item["query"] == "all randomized patients")["mode"]
        == "all"
    )


def test_d3_availability_suggestions_find_unknown_mortality_status_in_supplement(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    trial = workspace / "input" / "trial"
    (trial / "supplement.txt").write_text(
        "Table S5: mortality status unknown at day 29.\n",
        encoding="utf-8",
    )
    (trial / "sources.toml").write_text(
        'roles = { "supplement.txt" = "supplement" }\n',
        encoding="utf-8",
    )
    evidence = _prepared_evidence(workspace)
    _call(workspace, "save_proposal", _proposal_args(workspace, [_result(evidence)]))
    _review(workspace)
    _read_required_main_reports(workspace)

    revision = int(_call(workspace, "get_status", {})["head"]["state_revision"])
    for domain_id in ("domain:randomization", "domain:deviations"):
        saved = _call(
            workspace,
            "save_domain_judgment",
            _domain_draft("trial", domain_id, revision, evidence),
        )
        assert saved["outcome"] == "success", saved
        revision = int(saved["head"]["state_revision"])

    context = _call(workspace, "get_domain_context", {})["data"]
    question = next(
        item for item in context["questions"] if item["id"] == "sq:missing:data-available"
    )
    unknown = next(
        item
        for item in question["query_suggestions"]
        if item["query"] == "mortality status unknown"
    )
    assert unknown["mode"] == "all"
    assert unknown["source_role"] == "supplement"
    result = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": unknown["query"], "mode": unknown["mode"]},
    )
    assert result["outcome"] == "success"
    assert result["data"]["hits"]
    assert result["data"]["hits"][0]["source_id"] != evidence["source_id"]


def test_domain_query_suggestions_execute_alternative_wording_after_exact_no_hit(
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

    no_hit = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": exact["query"], "mode": exact["mode"]},
    )
    assert no_hit["outcome"] == "success"
    assert no_hit["data"]["condition"] == "no_hits"

    visible = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": alternative["query"], "mode": alternative["mode"]},
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


def test_unsupported_result_leaves_are_aggregated_repairs(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    evidence = _prepared_evidence(workspace)
    result = _result(evidence)
    result["target"]["comparison_groups"][0]["assignment"] = "unsupported assignment"
    result["reported"]["values"][0]["statistic"] = "unsupported statistic"
    repair = _call(workspace, "save_proposal", _proposal_args(workspace, [result]))
    assert repair["outcome"] == "repair"
    unsupported = [
        item for item in repair["repairs"] if item["code"] == "result_value_not_supported"
    ]
    paths = {item["path"] for item in unsupported}
    assert "/results/0/target/comparison_groups/0/assignment" not in paths
    assert "/results/0/reported/values/0/statistic" in paths


def test_fastmcp_resolves_text_and_figure_evidence_handles(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    table_text = "Unrelated appendix prose"
    (workspace / "input" / "trial" / "table.txt").write_text(table_text, encoding="utf-8")
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Figure plot")
    (workspace / "input" / "trial" / "figure.pdf").write_bytes(pdf.tobytes())
    pdf.close()
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    _read_required_main_reports(workspace)
    sources = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
    main_source = next(source for source in sources if source["label"] == "main.txt")
    narrative = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": main_source["id"],
            "page": 1,
            "start_line": 1,
            "end_line": 1,
        },
    )["data"]["evidence"]
    table_source = next(source for source in sources if source["label"] == "table.txt")
    figure_source = next(source for source in sources if source["label"] == "figure.pdf")
    table_selection = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": table_source["id"],
            "page": 1,
            "start_line": 1,
            "end_line": 1,
        },
    )["data"]["evidence"]
    render = _call(
        workspace,
        "render_page",
        {"trial_id": "trial", "source_id": figure_source["id"], "page": 1},
    )["data"]["render"]
    figure_selection = _call(
        workspace,
        "select_visual_evidence",
        {
            "trial_id": "trial",
            "source_id": figure_source["id"],
            "render_identity": render["identity"],
            "transcription": "Unrelated figure plot",
            "region": [0.1, 0.1, 0.9, 0.9],
        },
    )["data"]["evidence"]
    result = _result(narrative)
    typed = _call(workspace, "save_proposal", _proposal_args(workspace, [result]))
    assert typed["outcome"] == "review_required"
    stored = _state(workspace)["review"]["candidate"]["proposal"]["results"][0]
    stored_handles = {item["handle"] for item in stored["evidence"]}
    assert narrative["handle"] in stored_handles
    assert table_selection["handle"] not in stored_handles
    assert figure_selection["handle"] not in stored_handles


def test_proposal_rejects_object_group_value_fields_in_the_closed_reported_form(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    evidence = _prepared_evidence(workspace)
    result = _result(evidence)
    result["reported"]["values"][0] = {"group_id": "a", "value": "1"}
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
            "path": "/results/0/applicability/evidence/0",
            "code": "cross_trial_evidence",
            "detail": "applicability Evidence must resolve to this Trial",
        }
    ]


def test_counters_capture_structural_work(tmp_path: Path) -> None:
    for name in COUNTERS:
        COUNTERS[name] = 0
    workspace = _workspace(tmp_path)
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "A rendered table")
    (workspace / "input" / "trial" / "table.pdf").write_bytes(pdf.tobytes(garbage=4, deflate=True))
    pdf.close()
    evidence = _prepared_evidence(workspace)
    pdf_source = next(
        item
        for item in _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
        if item["label"] == "table.pdf"
    )
    _call(
        workspace,
        "read_pages",
        {"trial_id": "trial", "source_id": evidence["source_id"], "pages": [1]},
    )
    _call(
        workspace,
        "render_page",
        {"trial_id": "trial", "source_id": pdf_source["id"], "page": 1},
    )
    counters = COUNTERS
    for name in (
        "extraction_calls",
        "source_projection_verifications",
        "database_queries",
        "serialized_bytes",
        "render_bytes",
        "elapsed_ms",
    ):
        assert counters[name] > 0, name


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
    assert hit["data"]["hits"][0]["source_role"] == "other"
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

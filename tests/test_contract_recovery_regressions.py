from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError
from support.rob2 import (
    _assessment_workspace,
    _call,
    _domain_draft,
)

from rob2_kit.application import domains
from rob2_kit.interfaces.mcp.contracts import EvidenceRecovery, MainReportRecovery


def _verifier():
    path = Path("scripts/verify_bundle.py").resolve()
    spec = importlib.util.spec_from_file_location("verify_bundle_regressions", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _result(applicability: object = None, *, include_applicability: bool = True) -> dict:
    result = {
        "kind": "assessable",
        "trial_id": "trial",
        "requested_outcome": "mortality",
        "relation": "broader",
        "relation_rationale": "The reported endpoint is broader than the requested outcome.",
        "target": {
            "outcome_definition": "mortality",
            "measurement": {"metric": "mortality", "method": "ascertainment"},
            "time_point_or_window": {"kind": "described", "description": "follow-up"},
            "effect_of_interest": "assignment",
            "comparison_groups": [
                {"id": "a", "assignment": "intervention"},
                {"id": "b", "assignment": "control"},
            ],
            "intended_analysis_population": "randomized participants",
            "intended_effect_measure": "risk ratio",
        },
        "reported": {
            "form": "group_bound_values",
            "analysis_population": "analyzed participants",
            "endpoint": {"name": "all-cause mortality", "definition": "death"},
            "values": [
                {"group_id": "a", "statistic": "risk", "value": "1", "unit": "%"},
                {"group_id": "b", "statistic": "risk", "value": "2", "unit": "%"},
            ],
        },
        "clarity": {
            key: "specified"
            for key in (
                "outcome_definition",
                "measurement",
                "time_point",
                "analysis_population",
                "comparison_groups",
                "effect_measure",
                "source_table_meaning",
                "eligible_result_choice",
            )
        },
        "evidence": [],
        "bindings": [],
    }
    if include_applicability:
        result["applicability"] = applicability
    return result


def test_v06_verifier_requires_nonnull_applicability_and_source_basis() -> None:
    verifier = _verifier()
    version = "rob2-kit.result-semantics.v0.6"
    assert not verifier._valid_result_shape(
        _result(include_applicability=False), "mortality", version
    )
    assert not verifier._valid_result_shape(_result(None), "mortality", version)
    assert not verifier._valid_result_shape(
        _result(
            {
                "design": "individual_parallel",
                "status": "supported",
                "rationale": "The allocation was individual and parallel.",
                "evidence": [],
            }
        ),
        "mortality",
        version,
    )
    assert verifier._valid_result_shape(
        _result(
            {
                "design": "individual_parallel",
                "status": "supported",
                "rationale": "The allocation was individual and parallel.",
                "evidence": ["eh_0000000000000000"],
            }
        ),
        "mortality",
        version,
    )


def test_main_report_recovery_is_bounded_but_reports_total_counts(
    monkeypatch, tmp_path: Path
) -> None:
    ranges = [
        {"source_id": "source_" + "a" * 64, "page": i, "start_line": 1, "end_line": 1}
        for i in range(1, 26)
    ]
    monkeypatch.setattr(
        domains,
        "main_report_reading_status",
        lambda *args, **kwargs: {
            "trial": {
                "status": "budget_limited",
                "required_ranges": [],
                "unread_ranges": ranges,
            }
        },
    )
    recovery = domains._main_report_recovery(
        tmp_path,
        {"batch": {"trials": [{"id": "trial"}]}},
        "trial",
        include_budget=True,
    )
    assert recovery is not None
    assert len(recovery["windows"]) == 20
    assert recovery["window_count"] == 25
    assert recovery["unread_range_count"] == 25


def test_registry_navigation_keeps_first_twenty_windows_and_count(tmp_path: Path) -> None:
    internal = tmp_path / ".rob2-kit"
    internal.mkdir()
    connection = sqlite3.connect(internal / "derivative.sqlite3")
    connection.execute("CREATE TABLE pages (page INTEGER, text TEXT, source_id TEXT)")
    source_id = "source_" + "b" * 64
    for page in range(1, 26):
        connection.execute(
            "INSERT INTO pages VALUES (?, ?, ?)",
            (page, "protocolSection.statusModule.studyFirstPostDateStruct.value", source_id),
        )
    connection.commit()
    connection.close()
    found = domains._registry_navigation(
        tmp_path,
        "trial",
        [{"id": source_id, "role": "registry"}],
    )
    recovery = found[source_id]["recovery"]
    assert len(recovery["windows"]) == 20
    assert found[source_id]["window_count"] == 25


def test_evidence_recovery_shape_stays_compatible_with_older_projections() -> None:
    recovery = EvidenceRecovery(
        operation="read_pages",
        trial_id="trial",
        windows=[{"source_id": "sh_" + "c" * 16, "page": 1, "start_line": 1, "end_line": 1}],
    )
    assert set(recovery.model_dump()) == {"operation", "trial_id", "windows"}
    with pytest.raises(ValidationError):
        MainReportRecovery(
            operation="read_pages",
            trial_id="trial",
            windows=[],
        )


def test_preview_basis_must_be_explicit_and_same_trial() -> None:
    catalog = {
        "sha256:" + "a" * 64: {
            "identity": "sha256:" + "a" * 64,
            "handle": "eh_0000000000000000",
            "trial_id": "trial",
        },
        "sha256:" + "b" * 64: {
            "identity": "sha256:" + "b" * 64,
            "handle": "eh_1111111111111111",
            "trial_id": "other",
        },
    }
    row = {
        "arm": "A",
        "population": "randomized",
        "unit": "participants",
        "time_point": "follow-up",
        "randomized": 10,
        "observed": 8,
        "basis": ["eh_0000000000000000"],
    }
    assert domains._canonical_preview_rows([row], catalog, "trial")[0]["basis"] == [
        "sha256:" + "a" * 64
    ]
    with pytest.raises(ValueError, match="requires Evidence basis"):
        domains._canonical_preview_rows([{**row, "basis": []}], catalog, "trial")
    with pytest.raises(ValueError, match="unknown or cross-Trial"):
        domains._canonical_preview_rows(
            [{**row, "basis": ["eh_1111111111111111"]}], catalog, "trial"
        )


def test_public_preview_recovers_handle_outside_active_domain_projection(
    monkeypatch, tmp_path: Path
) -> None:
    extra_source = tmp_path / "input" / "trial" / "extra.txt"
    extra_source.parent.mkdir(parents=True)
    extra_source.write_text(
        "Participant flow reports 100 randomized and 95 observed participants.\n",
        encoding="utf-8",
    )
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    for domain_id in ("domain:randomization", "domain:deviations"):
        saved = _call(
            workspace,
            "save_domain_judgment",
            _domain_draft("trial", domain_id, revision, evidence),
        )
        assert saved["outcome"] == "success", saved
        revision = int(saved["head"]["state_revision"])

    source = next(
        item
        for item in _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
        if item["label"] == "extra.txt"
    )
    preview_evidence = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": source["id"],
            "page": 1,
            "start_line": 1,
            "end_line": 1,
        },
    )["data"]["evidence"]
    before = domains._state(tmp_path)
    monkeypatch.setattr(domains, "_evidence_catalog", lambda *args, **kwargs: {})

    without_preview = _call(
        workspace,
        "get_domain_context",
        {"trial_id": "trial", "domain_id": "domain:missing"},
    )
    assert without_preview["outcome"] == "success", without_preview
    assert preview_evidence["handle"] not in {
        item["handle"] for item in without_preview["data"]["evidence"]
    }

    context = _call(
        workspace,
        "get_domain_context",
        {
            "trial_id": "trial",
            "domain_id": "domain:missing",
            "missing_data": [
                {
                    "arm": "intervention",
                    "population": "randomized participants",
                    "unit": "participants",
                    "time_point": "follow-up",
                    "randomized": 100,
                    "observed": 95,
                    "basis": [preview_evidence["handle"]],
                }
            ],
        },
    )

    assert context["outcome"] == "success", context
    card = next(
        item
        for item in context["data"]["comparison_cards"]
        if item["question_id"] == "sq:missing:data-available"
    )
    row = card["missing_data"]["rows"][0]
    assert row["missing"] == 5
    assert row["basis"] == [preview_evidence["identity"]]
    visible = {item["handle"]: item for item in context["data"]["evidence"]}
    assert visible[preview_evidence["handle"]]["identity"] == preview_evidence["identity"]
    assert domains._state(tmp_path) == before

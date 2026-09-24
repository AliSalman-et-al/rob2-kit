from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import runpy
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastmcp import Client
from support.rob2 import (
    _call,
    _prepared_evidence,
    _proposal_args,
    _result,
    _review,
    _workspace,
)

from rob2_kit.application._state import _identity, _state
from rob2_kit.interfaces.mcp.server import mcp

SCRIPTS = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

_rsi_helpers = runpy.run_path(str(SCRIPTS / "prepare_rsi_workspace.py"))
prepare_workspace = _rsi_helpers["prepare_workspace"]
approved_scope_record = _rsi_helpers["approved_scope_record"]
_phase1_run_dir_is_retryable = runpy.run_path(str(SCRIPTS / "run_rsi_case.py"))[
    "_phase1_run_dir_is_retryable"
]
_missing_result_scope_dimensions = runpy.run_path(str(SCRIPTS / "benchmark_contract.py"))[
    "missing_result_scope_dimensions"
]
_prepare_index_helpers = runpy.run_path(str(SCRIPTS / "prepare_trial_specific_benchmark.py"))
_load_benchmark_rows = _prepare_index_helpers["_load_rows"]
_load_source_case = _prepare_index_helpers["_load_source_case"]

_structured_response = runpy.run_path(
    str(Path(__file__).parents[1] / "scripts" / "summarize_rsi_case.py")
)["_structured_response"]


def test_strict_isolation_rejects_windows_without_uac(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "scripts"))
    runner_helpers = runpy.run_path(str(Path(__file__).parents[1] / "scripts" / "run_rsi_case.py"))
    monkeypatch.setitem(
        runner_helpers["_preflight_isolation"].__globals__, "_is_windows", lambda: True
    )
    with pytest.raises(RuntimeError, match="without UAC"):
        runner_helpers["_preflight_isolation"](Path("codex"), True)


def test_strict_isolation_explicitly_denies_the_sentinel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "scripts"))
    runner = runpy.run_path(str(Path(__file__).parents[1] / "scripts" / "run_rsi_case.py"))
    monkeypatch.setitem(runner["_preflight_isolation"].__globals__, "_is_windows", lambda: False)
    captured: dict[str, str] = {}

    def denied(command, **kwargs):
        config = Path(kwargs["env"]["CODEX_HOME"]) / "config.toml"
        captured["profile"] = config.read_text(encoding="utf-8")
        return (
            "ENV:clean\nALLOWED:read_write\nDENIED:sentinel\nDENIED_WRITE:sentinel\n"
            "DENIED:run_inputs\nDENIED_WRITE:run_inputs\nDENIED:approved_scope\n"
            "DENIED_WRITE:approved_scope\nDENIED:codex_auth\nDENIED_WRITE:codex_auth\n"
            "DENIED:execution\nDENIED_WRITE:execution\nDENIED:source_auth\n"
            "DENIED_WRITE:source_auth\nDENIED:sibling_codex_auth\n"
            "DENIED_WRITE:sibling_codex_auth\nDENIED:sibling_run_inputs\n"
            "DENIED_WRITE:sibling_run_inputs\nDENIED:outside_temp\n"
            "DENIED_WRITE:outside_temp\n"
        )

    monkeypatch.setattr(subprocess, "check_output", denied)

    result = runner["_preflight_isolation"](Path("codex"), True)

    assert result["sentinel"] == "denied"
    assert any(
        "forbidden sentinel.txt" in line and line.endswith('= "deny"')
        for line in captured["profile"].splitlines()
    )


def test_strict_isolation_does_not_treat_the_sentinel_name_as_a_denial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "scripts"))
    runner = runpy.run_path(str(Path(__file__).parents[1] / "scripts" / "run_rsi_case.py"))
    monkeypatch.setitem(runner["_preflight_isolation"].__globals__, "_is_windows", lambda: False)

    def unrelated_failure(command, **_kwargs):
        raise subprocess.CalledProcessError(
            1,
            command,
            output="Traceback: forbidden sentinel.txt could not be opened",
        )

    monkeypatch.setattr(subprocess, "check_output", unrelated_failure)

    with pytest.raises(RuntimeError, match="before all probes completed"):
        runner["_preflight_isolation"](Path("codex"), True)


def _receipt() -> dict[str, object]:
    return {
        "head": {"next_action": {"operation": "get_domain_context"}},
        "data": {
            "result": {"kind": "assessable"},
            "questions": [{"id": "q1", "options": [{"id": "opt1"}]}],
            "comparison_cards": [{"question_id": "q1", "passage_groups": []}],
            "evidence": [{"handle": "eh_0123456789abcdef"}],
            "evidence_workspace": {"recovery": {"operation": "read_pages"}},
            "reading_recovery": {"windows": []},
        },
    }


def test_structured_response_prefers_one_complete_structured_envelope() -> None:
    receipt = _receipt()
    item = {
        "result": {
            "structuredContent": receipt,
            "content": [{"type": "text", "text": json.dumps({"questions": []})}],
        }
    }

    assert _structured_response(item) == receipt


def test_structured_response_parses_one_json_text_fallback() -> None:
    receipt = _receipt()
    item = {"result": {"content": [{"type": "text", "text": json.dumps(receipt)}]}}

    assert _structured_response(item) == receipt


def test_preparation_accepts_complete_group_bound_result_scope(tmp_path: Path) -> None:
    expected = {
        "trial": "Trial-A",
        "comparison": [
            {"id": "A", "assignment": "treatment"},
            {"id": "B", "assignment": "control"},
        ],
        "endpoint_definition": "all-cause death",
        "population": "all randomized participants",
        "window": {"kind": "fixed", "description": "36 months"},
        "reported_scope": {
            "form": "group_bound_values",
            "analysis_population": "all randomized participants",
            "endpoint": {"definition": "all-cause death"},
            "group_values": [
                {"group_id": "A", "statistic": "risk", "value": "10", "unit": "%"},
                {"group_id": "B", "statistic": "risk", "value": "20", "unit": "%"},
            ],
        },
    }
    case_path = tmp_path / "case.json"
    case_path.write_text(
        json.dumps(
            {
                "schema": "rob2-kit.rsi-case.v1",
                "trial": "Trial-A",
                "requested_outcome": "Adverse Events",
                "sources": [{"path": "article.txt"}],
                "expected_result": expected,
            }
        ),
        encoding="utf-8",
    )

    loaded = _rsi_helpers["_load_case"](case_path)

    assert loaded["expected_result"] == expected

    expected["reported_scope"]["group_values"][1]["value"] = ""
    case_path.write_text(
        json.dumps(
            {
                "schema": "rob2-kit.rsi-case.v1",
                "trial": "Trial-A",
                "requested_outcome": "Adverse Events",
                "sources": [{"path": "article.txt"}],
                "expected_result": expected,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="reported_scope.group_values"):
        _rsi_helpers["_load_case"](case_path)


def test_scope_completeness_accepts_named_endpoint_with_null_definition() -> None:
    expected = {
        "trial": "Trial-A",
        "comparison": [
            {"id": "A", "assignment": "treatment"},
            {"id": "B", "assignment": "control"},
        ],
        "endpoint_definition": "death from any cause",
        "population": "all randomized participants",
        "window": "36 months",
        "reported_scope": {
            "form": "comparative_effect",
            "analysis_population": "all randomized participants",
            "endpoint": {"definition": None, "name": "Mortality"},
            "effect_measure": "hazard_ratio",
            "estimate": "HR 0.75",
            "precision": None,
        },
    }

    assert _missing_result_scope_dimensions(expected) == []


def test_preparation_rejects_complete_result_bound_to_another_trial(tmp_path: Path) -> None:
    case_path = tmp_path / "case.json"
    case_path.write_text(
        json.dumps(
            {
                "schema": "rob2-kit.rsi-case.v1",
                "trial": "Trial-A",
                "requested_outcome": "Overall Survival",
                "sources": [{"path": "article.txt"}],
                "expected_result": {
                    "trial": "Trial-B",
                    "comparison": [
                        {"id": "A", "assignment": "treatment"},
                        {"id": "B", "assignment": "control"},
                    ],
                    "endpoint_definition": "death from any cause",
                    "population": "all randomized participants",
                    "window": "36 months",
                    "reported_scope": {
                        "form": "comparative_effect",
                        "analysis_population": "all randomized participants",
                        "endpoint": {"definition": "death from any cause"},
                        "effect_measure": "hazard_ratio",
                        "estimate": "HR 0.75",
                        "precision": "95% CI 0.55 to 1.02",
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="trial must match case trial"):
        _rsi_helpers["_load_case"](case_path)


def test_preparation_rejects_top_level_fields_without_explicit_reported_scope(
    tmp_path: Path,
) -> None:
    case_path = tmp_path / "case.json"
    case_path.write_text(
        json.dumps(
            {
                "schema": "rob2-kit.rsi-case.v1",
                "trial": "Trial-A",
                "requested_outcome": "Overall Survival",
                "sources": [{"path": "article.txt"}],
                "expected_result": {
                    "trial": "Trial-A",
                    "comparison": [
                        {"id": "A", "assignment": "treatment"},
                        {"id": "B", "assignment": "control"},
                    ],
                    "endpoint_definition": "death from any cause",
                    "population": "all randomized participants",
                    "window": "36 months",
                    "estimate": "HR 0.75",
                    "effect_measure": "hazard_ratio",
                    "precision": "95% CI 0.55 to 1.02",
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="reported_scope"):
        _rsi_helpers["_load_case"](case_path)


def test_benchmark_manifest_preparation_rejects_scope_omission_trial_mismatch_and_duplicates(
    tmp_path: Path,
) -> None:
    required = (
        "outcome",
        "trial",
        "primary_status",
        "role",
        "definition",
        "effect_size",
        "source_locator",
        "reference_label_available",
        "expected_result",
    )
    expected = {
        "trial": "Trial-A",
        "comparison": [
            {"id": "A", "assignment": "treatment"},
            {"id": "B", "assignment": "control"},
        ],
        "endpoint_definition": "death from any cause",
        "population": "all randomized participants",
        "window": "36 months",
        "reported_scope": {
            "form": "comparative_effect",
            "analysis_population": "all randomized participants",
            "endpoint": {"definition": "death from any cause"},
            "effect_measure": "hazard_ratio",
            "estimate": "HR 0.75",
            "precision": "95% CI 0.55 to 1.02",
        },
    }
    rows_path = tmp_path / "metadata.tsv"

    def write_rows(payloads: list[dict[str, object]]) -> None:
        with rows_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=required, delimiter="\t")
            writer.writeheader()
            writer.writerows(payloads)

    row: dict[str, object] = {
        "outcome": "Overall Survival",
        "trial": "Trial-A",
        "primary_status": "primary",
        "role": "main_article",
        "definition": "death from any cause",
        "effect_size": "HR 0.75",
        "source_locator": "abstract",
        "reference_label_available": "yes",
        "expected_result": json.dumps(expected),
    }
    write_rows([row])
    assert _load_benchmark_rows(rows_path)[0]["trial"] == "Trial-A"

    incomplete = dict(expected)
    incomplete.pop("reported_scope")
    write_rows([{**row, "expected_result": json.dumps(incomplete)}])
    with pytest.raises(ValueError, match="reported_scope"):
        _load_benchmark_rows(rows_path)

    write_rows([{**row, "expected_result": json.dumps({**expected, "trial": "Trial-B"})}])
    with pytest.raises(ValueError, match="trial must match metadata"):
        _load_benchmark_rows(rows_path)

    contradictory = {**expected, "estimate": "HR 0.90"}
    write_rows([{**row, "expected_result": json.dumps(contradictory)}])
    with pytest.raises(ValueError, match="estimate conflicts with reported_scope.estimate"):
        _load_benchmark_rows(rows_path)

    write_rows([row, {**row, "outcome": " overall survival "}])
    with pytest.raises(ValueError, match="duplicate fresh benchmark case"):
        _load_benchmark_rows(rows_path)


def test_benchmark_manifest_rejects_source_case_for_different_trial(tmp_path: Path) -> None:
    source_case = tmp_path / "qualification-case.json"
    source_case.write_text(json.dumps({"trial": "Trial-B"}), encoding="utf-8")

    with pytest.raises(ValueError, match="source qualification case trial"):
        _load_source_case(source_case, "Trial-A")


def test_prepared_index_passes_typed_expected_result_to_proposal_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    metadata = tmp_path / "metadata.tsv"
    expected = {
        "trial": "CHAARTED",
        "comparison": [
            {"id": "A", "assignment": "docetaxel"},
            {"id": "B", "assignment": "control"},
        ],
        "endpoint_definition": "death from any cause",
        "population": "all randomized participants",
        "window": {"kind": "fixed", "description": "48 months"},
        "reported_scope": {
            "form": "comparative_effect",
            "analysis_population": "all randomized participants",
            "endpoint": {"definition": "death from any cause"},
            "effect_measure": "hazard_ratio",
            "estimate": "HR 0.68",
            "precision": "95% CI 0.57 to 0.82",
        },
    }
    with metadata.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "outcome",
                "trial",
                "primary_status",
                "role",
                "definition",
                "effect_size",
                "source_locator",
                "reference_label_available",
                "expected_result",
            ],
            delimiter="\t",
        )
        writer.writeheader()
        writer.writerow(
            {
                "outcome": "Overall Survival",
                "trial": "CHAARTED",
                "primary_status": "primary",
                "role": "main_article",
                "definition": "death from any cause",
                "effect_size": "HR 0.68",
                "source_locator": "abstract",
                "reference_label_available": "yes",
                "expected_result": json.dumps(expected),
            }
        )
    output = tmp_path / "fresh"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prepare_trial_specific_benchmark.py",
            "--metadata",
            str(metadata),
            "--output",
            str(output),
        ],
    )

    _prepare_index_helpers["main"]()

    index = json.loads((output / "index.json").read_text(encoding="utf-8"))
    item = index["cases"][0]
    assert item["expected_result"] == expected
    assert isinstance(item["expected_result"], dict)
    review_helpers = runpy.run_path(str(SCRIPTS / "review_benchmark_proposals.py"))
    review = {
        "candidate": {
            "proposal": {
                "results": [
                    {
                        "trial_id": "CHAARTED",
                        "requested_outcome": "Overall Survival",
                        "target": {
                            "comparison_groups": expected["comparison"],
                            "outcome_definition": expected["endpoint_definition"],
                            "intended_analysis_population": expected["population"],
                            "time_point_or_window": expected["window"],
                        },
                        "reported": expected["reported_scope"],
                    }
                ]
            }
        }
    }
    assert review_helpers["_scope_mismatches"](review, item) == []


def test_concurrent_workspace_preparation_has_one_atomic_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    source_bytes = b"the winning preparation owns these exact bytes\n"
    (case_dir / "article.txt").write_bytes(source_bytes)
    case_path = case_dir / "case.json"
    case_path.write_text(
        json.dumps(
            {
                "schema": "rob2-kit.rsi-case.v1",
                "trial": "Trial-A",
                "requested_outcome": "Overall Survival",
                "sources": [
                    {"path": "article.txt", "name": "article.txt", "role": "main_article"}
                ],
            }
        ),
        encoding="utf-8",
    )
    workspace = (tmp_path / "run" / "workspace").resolve()
    barrier = threading.Barrier(2)
    original_mkdir = Path.mkdir

    def synchronized_mkdir(
        path: Path,
        mode: int = 0o777,
        parents: bool = False,
        exist_ok: bool = False,
    ) -> None:
        if path == workspace:
            barrier.wait(timeout=5)
        original_mkdir(path, mode=mode, parents=parents, exist_ok=exist_ok)

    monkeypatch.setattr(Path, "mkdir", synchronized_mkdir)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(prepare_workspace, case_path, workspace) for _ in range(2)]
        results = []
        failures = []
        for future in futures:
            try:
                results.append(future.result(timeout=10))
            except ValueError as error:
                failures.append(str(error))

    assert len(results) == 1
    assert failures == ["refusing to overwrite an existing assessment workspace"]
    assert (workspace / "input" / "Trial-A" / "article.txt").read_bytes() == source_bytes
    assert (workspace / "input" / "Trial-A" / "sources.toml").is_file()


def test_failed_workspace_preparation_can_retry_after_launcher_records_failure(
    tmp_path: Path,
) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    case_path = case_dir / "case.json"
    case_path.write_text(
        json.dumps(
            {
                "schema": "rob2-kit.rsi-case.v1",
                "trial": "Trial-A",
                "requested_outcome": "Overall Survival",
                "sources": [
                    {"path": "article.txt", "name": "article.txt", "role": "main_article"}
                ],
            }
        ),
        encoding="utf-8",
    )
    run_dir = tmp_path / "run"
    workspace = run_dir / "workspace"

    with pytest.raises(FileNotFoundError):
        prepare_workspace(case_path, workspace)

    assert not run_dir.exists()
    # The phase launcher creates these records after run_rsi_case exits.
    run_dir.mkdir()
    (run_dir / "launcher-phase-1.stdout.txt").write_bytes(b"")
    (run_dir / "launcher-phase-1.stderr.txt").write_bytes(b"missing source\n")
    assert _phase1_run_dir_is_retryable(run_dir)

    (case_dir / "article.txt").write_bytes(b"source is now available\n")
    prepare_workspace(case_path, workspace)

    assert (workspace / "input" / "Trial-A" / "article.txt").read_bytes() == (
        b"source is now available\n"
    )

    assert not _phase1_run_dir_is_retryable(run_dir)


def test_prepared_assessment_tools_see_only_allowlisted_sources_and_scope(
    tmp_path: Path, monkeypatch
) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    source = b"captured source bytes, including its exact spacing.\n"
    registry = b'{"protocolSection":{"identificationModule":{"nctId":"NCT00000001"}}}\n'
    (case_dir / "article.txt").write_bytes(source)
    (case_dir / "registry-capture.json").write_bytes(registry)
    (case_dir / "prior-answer.json").write_text(
        '{"domain_1":"High","private_marker":"ANSWER_LABEL_MUST_NOT_LEAK"}',
        encoding="utf-8",
    )
    case = {
            "schema": "rob2-kit.rsi-case.v1",
            "trial": "Trial-A",
            "requested_outcome": "Progression-Free Survival",
            "campaign_id": "frozen-campaign-27f36d",
            "approved_scope": "progression-free survival at the reported timepoint",
        "sources": [{"path": "article.txt", "name": "main-article.txt", "role": "main_article"}],
        "registry_capture": {
            "path": "registry-capture.json",
            "captured_at": "2026-08-01T12:30:00Z",
            "sha256": hashlib.sha256(registry).hexdigest(),
            "provenance": "captured from the baseline ClinicalTrials.gov response",
        },
    }
    case_path = case_dir / "case.json"
    case_path.write_text(json.dumps(case), encoding="utf-8")
    workspace = tmp_path / "run" / "workspace"

    manifest = prepare_workspace(case_path, workspace)
    input_trial = workspace / "input" / "Trial-A"
    assert (input_trial / "main-article.txt").read_bytes() == source
    assert (input_trial / "registry.json").read_bytes() == registry
    assert not (input_trial / "prior-answer.json").exists()
    assert manifest["registry_capture"]["captured_at"] == "2026-08-01T12:30:00Z"
    assert manifest["registry_capture"]["sha256"] == hashlib.sha256(registry).hexdigest()
    assert manifest["campaign_id"] == "frozen-campaign-27f36d"
    assert (
        manifest["registry_capture"]["replayed_at"] != manifest["registry_capture"]["captured_at"]
    )

    async def inspect_assessment_tools() -> list[str]:
        monkeypatch.setenv("ROB2_WORKSPACE", str(workspace))
        async with Client(mcp) as client:
            await client.call_tool(
                "prepare_batch",
                {
                    "requested_outcome": case["requested_outcome"],
                    "expected_revision": 0,
                    "trial_labels": ["Trial-A"],
                },
            )
            sources = await client.call_tool("list_sources", {})
            search = await client.call_tool(
                "search_sources",
                {
                    "trial_id": "trial-a",
                    "query": "unlisted-answer-file-content-marker",
                    "mode": "phrase",
                },
            )
            assert search.structured_content["data"]["total_matches"] == 0
            status = await client.call_tool("get_status", {})
            return [
                json.dumps(sources.structured_content, sort_keys=True),
                json.dumps(search.structured_content, sort_keys=True),
                json.dumps(status.structured_content, sort_keys=True),
            ]

    outputs = asyncio.run(inspect_assessment_tools())
    tool_text = "\n".join(outputs)
    assert "main-article.txt" in tool_text
    assert "registry.json" in tool_text
    assert "ANSWER_LABEL_MUST_NOT_LEAK" not in tool_text
    assert "prior-answer.json" not in tool_text
    assert "High" not in tool_text


def test_prepare_workspace_allows_sources_elsewhere_under_eval_root(tmp_path: Path) -> None:
    eval_root = tmp_path / "eval"
    case_dir = eval_root / "runs" / "case-a"
    source_dir = eval_root / "reference" / "sources" / "Trial-A"
    case_dir.mkdir(parents=True)
    source_dir.mkdir(parents=True)
    source = b"shared evaluation corpus bytes\n"
    (source_dir / "article.txt").write_bytes(source)
    case = {
        "schema": "rob2-kit.rsi-case.v1",
        "trial": "Trial-A",
        "requested_outcome": "Progression-Free Survival",
        "sources": [
            {
                "path": "../../reference/sources/Trial-A/article.txt",
                "name": "main-article.txt",
                "role": "main_article",
            }
        ],
    }
    case_path = case_dir / "case.json"
    case_path.write_text(json.dumps(case), encoding="utf-8")

    manifest = prepare_workspace(case_path, tmp_path / "run" / "workspace")

    assert manifest["sources"][0]["name"] == "main-article.txt"
    assert (
        tmp_path / "run" / "workspace" / "input" / "Trial-A" / "main-article.txt"
    ).read_bytes() == source


def test_preparation_rejects_reference_label_as_trial_source(tmp_path: Path) -> None:
    eval_root = tmp_path / "eval"
    case_dir = eval_root / "runs" / "case-a"
    labels_dir = eval_root / "reference" / "catalog" / "provisional-labels"
    case_dir.mkdir(parents=True)
    labels_dir.mkdir(parents=True)
    (labels_dir / "overall-survival.csv").write_text("private label", encoding="utf-8")
    case_path = case_dir / "case.json"
    case_path.write_text(
        json.dumps(
            {
                "schema": "rob2-kit.rsi-case.v1",
                "trial": "Trial-A",
                "requested_outcome": "Overall Survival",
                "sources": [
                    {
                        "path": "../../reference/catalog/provisional-labels/overall-survival.csv",
                        "name": "article.txt",
                        "role": "main_article",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="declared trial source directory"):
        prepare_workspace(case_path, tmp_path / "run" / "workspace")


def test_reference_catalog_separates_completed_and_labeled_denominators() -> None:
    catalog = Path(__file__).parents[1] / "eval" / "reference" / "catalog"
    with (catalog / "outcomes.csv").open(encoding="utf-8", newline="") as stream:
        rows = {row["outcome"]: row for row in csv.DictReader(stream)}

    assert {
        outcome: (int(row["baseline_completed"]), int(row["reference_labeled"]))
        for outcome, row in rows.items()
    } == {
        "Progression-Free Survival": (8, 10),
        "Adverse Events": (10, 8),
        "Overall Survival": (9, 10),
    }
    with (catalog / "trials.csv").open(encoding="utf-8", newline="") as stream:
        trials = list(csv.DictReader(stream))
    assert len(trials) == 10
    assert all(
        row["source_directory"] == f"eval/reference/sources/{row['trial_slug']}" for row in trials
    )


def test_post_approval_record_fingerprints_actual_result_scope_outside_workspace(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    workspace = run_dir / "workspace"
    workspace.mkdir(parents=True)
    _workspace(workspace)
    evidence = _prepared_evidence(workspace)
    result = _result(evidence)
    saved = _call(workspace, "save_proposal", _proposal_args(workspace, [result]))
    assert saved["outcome"] == "review_required"
    assert approved_scope_record(workspace, "frozen requested scope") is None
    _review(workspace)

    state = _state(workspace)
    approved_result = state["proposal"]["payload"]["results"][0]
    record = approved_scope_record(workspace, "frozen requested scope")
    assert record is not None
    assert record["case_requested_scope"] == "frozen requested scope"
    assert record["proposal_identity"] == state["proposal"]["identity"]
    assert record["approval_identity"] == state["proposal_acknowledgment"]["identity"]
    assert record["results"] == [
        {
            "identity": _identity(approved_result),
            "trial_id": approved_result["trial_id"],
            "kind": approved_result["kind"],
            "target_scope_identity": _identity(approved_result["target"]),
            "reported_scope_identity": _identity(approved_result["reported"]),
        }
    ]
    assert "definition" not in json.dumps(record)

    record_path = run_dir / "approved-scope.json"
    record_path.write_text(json.dumps(record), encoding="utf-8")
    assert not (workspace / record_path.name).exists()
    visible = json.dumps(_call(workspace, "get_status", {}), sort_keys=True)
    assert record["proposal_identity"] not in visible
    assert record["results"][0]["identity"] not in visible
    assert record["approval_identity"] not in visible
    assert record["results"][0]["target_scope_identity"] not in visible
    assert record["results"][0]["reported_scope_identity"] not in visible

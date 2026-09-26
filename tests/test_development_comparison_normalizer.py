from __future__ import annotations

import hashlib
import json
import runpy
import shutil
import zipfile
from pathlib import Path
from typing import Any

import pytest
from support.rob2 import _assessment_workspace, _call, _domain_draft, _finalize_assessment

from rob2_kit.evaluation import run_comparison
from rob2_kit.packs import SCIENTIFIC_PACK

_NORMALIZER = runpy.run_path(
    str(Path(__file__).parents[1] / "scripts/normalize_development_comparison.py")
)


def _finalized_bundle(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    workspace, evidence, revision = _assessment_workspace(tmp_path / "assessment")
    for domain in SCIENTIFIC_PACK.domains:
        saved = _call(
            workspace,
            "save_domain_judgment",
            _domain_draft("trial", domain.id, revision, evidence),
        )
        assert saved["outcome"] == "success", saved
        revision = int(saved["head"]["state_revision"])
    finalized = _finalize_assessment(workspace, revision)
    artifact = workspace / finalized["data"]["artifact"]["path"]
    return artifact, finalized["data"]["artifact"]


def _expected_result(bundle: Path) -> dict[str, Any]:
    with zipfile.ZipFile(bundle) as archive:
        canonical = json.loads(archive.read("canonical.json"))
    result = canonical["proposal"]["payload"]["results"][0]
    return {
        "trial": result["trial_id"],
        "comparison": result["target"]["comparison_groups"],
        "endpoint_definition": result["reported"]["endpoint"]["definition"],
        "population": result["target"]["intended_analysis_population"],
        "window": result["target"]["time_point_or_window"],
        "reported_scope": result["reported"],
    }


def _result_identity(result: dict[str, Any]) -> str:
    encoded = json.dumps(result, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()


def test_normalizer_uses_only_independently_verified_bundle_and_retains_unknown_metrics(
    tmp_path: Path,
) -> None:
    source_bundle, artifact_record = _finalized_bundle(tmp_path)
    campaign = tmp_path / "campaign"
    run = campaign / "runs" / "facts" / "case" / "draw-1"
    (run / "workspace").mkdir(parents=True)
    bundle = run / "workspace" / "assessment.rob2.zip"
    shutil.copyfile(source_bundle, bundle)
    expected_result = _expected_result(bundle)
    materialized = run / "workspace" / "input" / "trial"
    materialized.mkdir(parents=True)
    source_bytes = b"materialized main source"
    fact_bytes = b"scope matched facts"
    case_metadata = {
        "trial": "trial",
        "requested_outcome": "requested outcome",
        "expected_result": expected_result,
        "approved_scope": None,
        "registry_capture": None,
        "campaign_id": "normalizer-test",
    }
    (materialized / "main.txt").write_bytes(source_bytes)
    (materialized / "scope-matched-facts.json").write_bytes(fact_bytes)
    (run / "run-inputs.json").write_text(
        json.dumps(
            {
                **case_metadata,
                "sources": [
                    {
                        "name": "main.txt",
                        "role": "main_article",
                        "sha256": hashlib.sha256(source_bytes).hexdigest(),
                    },
                    {
                        "name": "scope-matched-facts.json",
                        "role": "other",
                        "sha256": hashlib.sha256(fact_bytes).hexdigest(),
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    trace = run / "phase-1.jsonl"
    trace.write_text('{"type":"event_msg"}\n', encoding="utf-8")
    trace_hash = hashlib.sha256(trace.read_bytes()).hexdigest()
    bundle_hash = hashlib.sha256(bundle.read_bytes()).hexdigest()
    runner_id = "runner-attempt"
    (run / "execution.json").write_text(
        json.dumps(
            {
                "attempt_id": runner_id,
                "state": "succeeded",
                "codex_session_id": "codex-session-secret",
                "attempts": [
                    {
                        "attempt_id": runner_id,
                        "kind": "initial",
                        "state": "succeeded",
                        "expected_result_sha256": _result_identity(expected_result).removeprefix(
                            "sha256:"
                        ),
                    }
                ],
                "phases": [
                    {
                        "attempt_id": runner_id,
                        "phase": 1,
                        "started_at": "2026-09-25T10:00:00+00:00",
                        "finished_at": "2026-09-25T10:00:02+00:00",
                        "codex_session_id": "codex-session-secret",
                        "trace_sha256": trace_hash,
                    }
                ],
                "artifact": {
                    "attempt_id": runner_id,
                    "path": "workspace/assessment.rob2.zip",
                    "sha256": bundle_hash,
                    "identity": artifact_record["identity"],
                    "verified": True,
                },
            }
        ),
        encoding="utf-8",
    )
    launch = {
        "schema": "rob2-kit.development-comparison-launch.v1",
        "comparison_identity": "sha256:" + "a" * 64,
        "inputs_identity": "sha256:" + "b" * 64,
        "declared_environment": {
            "host": {"provider": "codex-cli", "prompt_identity": "sha256:" + "d" * 64},
            "model": {"family": "gpt-6-luna", "version": "6", "effort": "medium"},
            "artifacts": {"kit_identity": "sha256:" + "e" * 64},
        },
        "selected_factor": "fact_binding",
        "attempts": [
            {
                "attempt_id": "launch-draw-1",
                "arm_id": "facts",
                "cell_id": "ARASENS-pfs-D3",
                "draw_id": "draw-1",
                "trial_id": "trial",
                "outcome_id": "requested outcome",
                "expected_result": expected_result,
                "result_identity": _result_identity(expected_result),
                "source_identity": "sha256:" + "c" * 64,
                "frozen_case_metadata": case_metadata,
                "run_dir": "runs/facts/case/draw-1",
                "source_expectations": [
                    {
                        "name": "main.txt",
                        "role": "main_article",
                        "sha256": hashlib.sha256(source_bytes).hexdigest(),
                    },
                    {
                        "name": "scope-matched-facts.json",
                        "role": "other",
                        "sha256": hashlib.sha256(fact_bytes).hexdigest(),
                    },
                ],
                "source_materialization": {"status": "verified"},
            },
            {
                "attempt_id": "launch-draw-2",
                "arm_id": "facts",
                "cell_id": "ARASENS-pfs-D3",
                "draw_id": "draw-2",
                "trial_id": "trial",
                "outcome_id": "requested outcome",
                "expected_result": expected_result,
                "result_identity": _result_identity(expected_result),
                "source_identity": "sha256:" + "c" * 64,
                "run_dir": "runs/facts/case/draw-2",
                "source_expectations": [{"name": "scope-matched-facts.json"}],
                "source_materialization": {"status": "verified"},
                "launch_status": "runner_unavailable",
            },
        ],
    }
    outcomes, provenance = _NORMALIZER["normalize_launch"](launch, campaign)

    assessed, failed = outcomes
    assert assessed["status"] == "assessed"
    assert assessed["prediction"] in {"low", "some_concerns", "high"}
    assert assessed["completion"] is True
    assert assessed["latency_ms"] == 2000
    assert assessed["cost"] is None
    assert assessed["context_bytes"] is None
    assert assessed["tool_calls"] is None
    assert assessed["session_id"] == "sha256:" + hashlib.sha256(b"codex-session-secret").hexdigest()
    assert "codex-session-secret" not in json.dumps(outcomes)
    assert failed["status"] == "failed_infrastructure"
    assert failed["prediction"] == "unknown"
    assert failed["session_id"] is None
    assert provenance["attempts"][0]["artifact"]["status"] == "verified"
    assert provenance["attempts"][0]["artifact"]["approved_result_identity"]
    assert provenance["attempts"][0]["artifact"]["planned_result_identity"] == _result_identity(
        expected_result
    )
    assert provenance["attempts"][0]["host_session_observations"][0]["session_id"] == (
        "codex-session-secret"
    )
    assert provenance["attempts"][0]["phase_traces"][0]["status"] == "verified"
    assert provenance["attempts"][0]["source_materialization"]["status"] == "verified"
    assert (
        provenance["attempts"][0]["environment_identity_bindings"]["artifacts"]["kit_identity"][
            "status"
        ]
        == "declared_only"
    )
    assert provenance["attempts"][0]["fact_source_availability"] == "available"
    assert provenance["attempts"][0]["fact_uptake_or_correct_binding"] == "unknown"

    config_path = (
        Path(__file__).parents[1] / "docs/evaluation/development-comparison-v0.3.example.json"
    )
    config = json.loads(config_path.read_text(encoding="utf-8"))
    interventions = {
        arm["intervention_id"]: "sha256:" + f"{index:064x}"
        for index, arm in enumerate(config["arms"], 1)
    }
    receipt = run_comparison(config, interventions, outcomes)
    assert receipt["metrics"]["arms"]["facts"]["cost"] is None
    assert receipt["metrics"]["arms"]["facts"]["measurement_coverage"]["cost"] == {
        "observed": 0,
        "unknown": 2,
    }
    assert receipt["budget_measurements"]["cost"]["status"] == "unverified"

    trace.write_text('{"type":"tampered"}\n', encoding="utf-8")
    (materialized / "main.txt").write_bytes(b"changed after materialization")
    _, tampered_provenance = _NORMALIZER["normalize_launch"](launch, campaign)
    tampered = tampered_provenance["attempts"][0]
    assert tampered["phase_traces"][0]["status"] == "unverified"
    assert tampered["source_materialization"]["status"] == "unverified"
    assert tampered["fact_source_availability"] == "unverified"


def test_verified_bundle_for_wrong_endpoint_is_completed_but_unscored(tmp_path: Path) -> None:
    source_bundle, artifact_record = _finalized_bundle(tmp_path)
    campaign = tmp_path / "campaign"
    run = campaign / "runs" / "facts" / "case" / "draw-1"
    (run / "workspace").mkdir(parents=True)
    bundle = run / "workspace" / "assessment.rob2.zip"
    shutil.copyfile(source_bundle, bundle)
    expected_result = _expected_result(bundle)
    expected_result["endpoint_definition"] = "a different endpoint definition"
    runner_id = "wrong-result-attempt"
    (run / "phase-1.jsonl").write_text('{"type":"event_msg"}\n', encoding="utf-8")
    trace_hash = hashlib.sha256((run / "phase-1.jsonl").read_bytes()).hexdigest()
    (run / "execution.json").write_text(
        json.dumps(
            {
                "attempt_id": runner_id,
                "state": "succeeded",
                "codex_session_id": "unique-session",
                "attempts": [
                    {
                        "attempt_id": runner_id,
                        "kind": "initial",
                        "state": "succeeded",
                        "expected_result_sha256": _result_identity(expected_result).removeprefix(
                            "sha256:"
                        ),
                    }
                ],
                "phases": [
                    {
                        "attempt_id": runner_id,
                        "phase": 1,
                        "started_at": "2026-09-25T10:00:00+00:00",
                        "finished_at": "2026-09-25T10:00:02+00:00",
                        "codex_session_id": "unique-session",
                        "trace_sha256": trace_hash,
                    }
                ],
                "artifact": {
                    "attempt_id": runner_id,
                    "path": "workspace/assessment.rob2.zip",
                    "sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
                    "identity": artifact_record["identity"],
                    "verified": True,
                },
            }
        ),
        encoding="utf-8",
    )
    launch = {
        "schema": "rob2-kit.development-comparison-launch.v1",
        "comparison_identity": "sha256:" + "a" * 64,
        "inputs_identity": "sha256:" + "b" * 64,
        "selected_factor": "fact_binding",
        "attempts": [
            {
                "attempt_id": "draw",
                "arm_id": "facts",
                "cell_id": "ARASENS-pfs-D3",
                "draw_id": "draw-1",
                "trial_id": "trial",
                "outcome_id": "requested outcome",
                "expected_result": expected_result,
                "result_identity": _result_identity(expected_result),
                "source_identity": "sha256:" + "c" * 64,
                "run_dir": "runs/facts/case/draw-1",
                "source_expectations": [],
            }
        ],
    }

    outcomes, provenance = _NORMALIZER["normalize_launch"](launch, campaign)
    assert outcomes[0]["status"] == "scope_unverified"
    assert outcomes[0]["completion"] is True
    assert outcomes[0]["prediction"] in {"low", "some_concerns", "high"}
    assert provenance["attempts"][0]["artifact"]["status"] == "verified"
    assert provenance["attempts"][0]["artifact"]["disposition"] == "scope_unverified"
    assert "Result dimensions differ" in provenance["attempts"][0]["artifact"]["reason"]

    config_path = (
        Path(__file__).parents[1] / "docs/evaluation/development-comparison-v0.3.example.json"
    )
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["plan"]["cases"][0]["scope"] = "eligible"
    interventions = {
        arm["intervention_id"]: "sha256:" + f"{index:064x}"
        for index, arm in enumerate(config["arms"], 1)
    }
    receipt = run_comparison(
        config, interventions, outcomes, {outcomes[0]["cell_id"]: outcomes[0]["prediction"]}
    )
    assert receipt["metrics"]["pairs"]["fact-binding"]["assessed_pair_draws"] == 0
    assert (
        receipt["metrics"]["arms"]["facts"]["provisional_label_agreement"]["assessed_denominator"]
        == 0
    )


def test_normalizer_rejects_a_session_shared_by_baseline_and_fact_draws(tmp_path: Path) -> None:
    campaign = tmp_path / "campaign"
    attempts = []
    for arm_id, attempt_id, sessions in (
        ("baseline", "base", ["shared-session"]),
        ("facts", "facts", ["shared-session", "second-session"]),
    ):
        run = campaign / "runs" / arm_id / "draw-1"
        run.mkdir(parents=True)
        (run / "execution.json").write_text(
            json.dumps(
                {
                    "attempt_id": attempt_id,
                    "attempts": [
                        {
                            "attempt_id": attempt_id,
                            "kind": "initial",
                            "state": "failed_infrastructure",
                        }
                    ],
                    "phases": [
                        {
                            "attempt_id": attempt_id,
                            "phase": index,
                            "codex_session_id": session_id,
                        }
                        for index, session_id in enumerate(sessions, 1)
                    ],
                }
            ),
            encoding="utf-8",
        )
        attempts.append(
            {
                "attempt_id": attempt_id,
                "arm_id": arm_id,
                "cell_id": "case",
                "draw_id": "draw-1",
                "trial_id": "trial",
                "outcome_id": "outcome",
                "run_dir": f"runs/{arm_id}/draw-1",
                "source_expectations": [],
            }
        )
    launch = {
        "schema": "rob2-kit.development-comparison-launch.v1",
        "comparison_identity": "sha256:" + "a" * 64,
        "inputs_identity": "sha256:" + "b" * 64,
        "selected_factor": "fact_binding",
        "attempts": attempts,
    }

    with pytest.raises(ValueError, match="reused across development arms or draws"):
        _NORMALIZER["normalize_launch"](launch, campaign)

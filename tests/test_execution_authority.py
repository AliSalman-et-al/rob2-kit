from __future__ import annotations

import hashlib
import json
import runpy
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from rob2_kit.evaluation.adjudication import SCHEMA, write_sidecar

SCRIPTS = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _runner() -> dict[str, object]:
    return runpy.run_path(str(SCRIPTS / "run_rsi_case.py"))


def _collector() -> dict[str, object]:
    return runpy.run_path(str(SCRIPTS / "collect_rsi_benchmark.py"))


def test_execution_record_binds_campaign_and_rejects_duplicate_phase(tmp_path: Path) -> None:
    runner = _runner()
    run_dir = tmp_path / "campaign" / "outcome" / "Trial-A"
    prompt = tmp_path / "prompt.txt"
    case = tmp_path / "case.json"
    prompt.write_text("prompt", encoding="utf-8")
    case.write_text("{}", encoding="utf-8")
    inputs = {"trial": "Trial-A", "requested_outcome": "Overall Survival"}
    identity = runner["_execution_identity"](run_dir, inputs)
    assert identity == {
        "campaign_id": "campaign",
        "case_id": "campaign-overallsurvival-triala",
        "trial_id": "Trial-A",
        "outcome": "Overall Survival",
    }

    load = runner["_load_or_create_execution"]
    record = load(
        run_dir,
        identity,
        run_inputs=inputs,
        case_file=case,
        prompt_file=prompt,
        phase=1,
        session=None,
    )
    assert record["state"] == "running"
    assert record["phases"][0]["phase"] == 1

    (run_dir / "phase-1.jsonl").write_text(
        json.dumps({"thread_id": "session-1"}) + "\n", encoding="utf-8"
    )
    record["state"] = "resumable"
    runner["_atomic_json"](run_dir / "execution.json", record)
    runner["_release_execution_lock"](run_dir)
    resumed = load(
        run_dir,
        identity,
        run_inputs=inputs,
        case_file=case,
        prompt_file=prompt,
        phase=2,
        session="session-1",
    )
    assert resumed["phases"][-1]["phase"] == 2
    assert resumed["continuation"]["lineage"][-1] == {"phase": 2, "session": "session-1"}
    runner["_release_execution_lock"](run_dir)

    with pytest.raises(ValueError, match="already recorded"):
        load(
            run_dir,
            identity,
            run_inputs=inputs,
            case_file=case,
            prompt_file=prompt,
            phase=2,
            session="session-1",
        )


def test_success_requires_verified_bundle_and_preserves_phase_provenance(tmp_path: Path) -> None:
    runner = _runner()
    run_dir = tmp_path / "campaign" / "outcome" / "Trial-A"
    record = {
        "state": "running",
        "phases": [{"phase": 1, "session": None}],
        "attempts": [],
    }
    trace = run_dir / "phase-1.jsonl"
    artifact = run_dir / "workspace" / "result.rob2.zip"
    trace.parent.mkdir(parents=True)
    artifact.parent.mkdir(parents=True)
    trace.write_text("{}\n", encoding="utf-8")
    artifact.write_bytes(b"bundle")

    original = runner["_finish_execution"].__globals__["runpy"].run_path
    runner["_finish_execution"].__globals__["runpy"].run_path = lambda path: {
        "verify": lambda candidate: (True, "verified")
    }
    try:
        runner["_finish_execution"](
            run_dir,
            record,
            1,
            0,
            artifact={"path": "result.rob2.zip", "identity": "sha256:" + "0" * 64},
        )
    finally:
        runner["_finish_execution"].__globals__["runpy"].run_path = original

    assert record["state"] == "succeeded"
    assert record["artifact"]["verified"] is True
    assert record["artifact"]["sha256"] == hashlib.sha256(b"bundle").hexdigest()
    assert record["phases"][0]["trace_sha256"] == runner["_sha256_file"](trace)


def test_collector_binds_adjudication_to_checkpoint_domain_question_and_label(
    tmp_path: Path,
) -> None:
    collector = _collector()
    trial_dir = tmp_path / "campaign" / "outcome" / "Trial-A"
    sidecar_path = trial_dir / "adjudications" / "one.json"
    sidecar_path.parent.mkdir(parents=True)
    bundle = trial_dir / "workspace" / "result.rob2.zip"
    bundle.parent.mkdir(parents=True)
    result_identity = "sha256:" + "1" * 64
    checkpoint_identity = "sha256:" + "2" * 64
    source_id = "source_" + "a" * 64
    canonical = {
        "snapshots": {
            "Trial-A": {"checkpoints": [checkpoint_identity]},
        },
        "batch": {
            "trials": [{"id": "Trial-A", "sources": [{"id": source_id}]}],
        },
        "domain_records": {
            "Trial-A:domain:missing": {
                "identity": checkpoint_identity,
                "trial_id": "Trial-A",
                "domain_id": "domain:missing",
                "judgment": "low",
                "answers": [
                    {
                        "question_id": "sq:missing:data-available",
                        "answer": "yes",
                    }
                ],
            }
        },
    }
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("canonical.json", json.dumps(canonical))

    raw = {
        "schema": SCHEMA,
        "run_identity": "campaign",
        "case_identity": "campaign-case",
        "result_identity": result_identity,
        "domain_identity": "domain:missing",
        "question_identity": "sq:missing:data-available",
        "checkpoint_identity": checkpoint_identity,
        "source_identities": (source_id,),
        "reference_label": "low",
        "model_label": "Low",
        "provisional_label": "low",
        "classification": "agreement",
        "rationale": "The checkpoint and source support the reviewed label.",
        "reviewer_identity": "reviewer-1",
        "reviewer_role": "adjudicator",
        "adjudication_version": "2026-09-20",
        "reviewed_at": datetime(2026, 9, 20, 12, 0, tzinfo=UTC),
        "confidence": 1.0,
    }
    write_sidecar(sidecar_path, raw)
    accepted = collector["_case_adjudications"](
        trial_dir,
        case_id="campaign-case",
        trial_id="Trial-A",
        campaign_id="campaign",
        bundle=bundle,
        result_identity=result_identity,
    )
    assert accepted[0]["schema"] == SCHEMA

    for field, value, message in (
        ("domain_identity", "domain:measurement", "domain identity"),
        ("question_identity", "sq:missing:not-a-question", "question identity"),
        ("model_label", "high", "model label"),
    ):
        write_sidecar(sidecar_path, {**raw, field: value})
        with pytest.raises(ValueError, match=message):
            collector["_case_adjudications"](
                trial_dir,
                case_id="campaign-case",
                trial_id="Trial-A",
                campaign_id="campaign",
                bundle=bundle,
                result_identity=result_identity,
            )


def test_trace_artifact_recovery_finds_nested_finalize_receipt(tmp_path: Path) -> None:
    runner = _runner()
    trace = tmp_path / "phase-2.jsonl"
    trace.write_text(
        json.dumps(
            {
                "item": {
                    "result": {
                        "structured_content": {
                            "data": {
                                "artifact": {
                                    "path": ".rob2-kit/finalized/x.rob2.zip",
                                    "sha256": "sha256:" + "a" * 64,
                                }
                            }
                        }
                    }
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert runner["_trace_artifact"](tmp_path, 2) == {
        "path": ".rob2-kit/finalized/x.rob2.zip",
        "sha256": "sha256:" + "a" * 64,
    }


def test_collector_rejects_unclaimed_or_moved_bundles(tmp_path: Path) -> None:
    collector = _collector()
    bundle = tmp_path / "case" / "workspace" / "result.rob2.zip"
    bundle.parent.mkdir(parents=True)
    bundle.write_bytes(b"bundle")
    execution = {
        "state": "succeeded",
        "artifact": {
            "path": "workspace/result.rob2.zip",
            "sha256": hashlib.sha256(b"bundle").hexdigest(),
            "verified": True,
        },
    }
    assert collector["_bundle"](bundle.parents[1], execution) == bundle

    execution["artifact"]["path"] = "workspace/moved.rob2.zip"
    with pytest.raises(ValueError, match="stale or moved"):
        collector["_bundle"](bundle.parents[1], execution)

    execution["artifact"]["path"] = "workspace/result.rob2.zip"
    execution["state"] = "failed_infrastructure"
    with pytest.raises(ValueError, match="unclaimed bundle"):
        collector["_bundle"](bundle.parents[1], execution)


def test_no_hit_search_is_unresolved_not_scientific_absence() -> None:
    from rob2_kit.application.domains import _evidence_sufficiency

    summary = _evidence_sufficiency(
        [
            {
                "question_id": "sq:test",
                "bases": [
                    {
                        "kind": "absence",
                        "search_receipt": "receipt-1",
                    }
                ],
            }
        ],
        {
            "receipt-1": {
                "truncated": False,
                "total_matches": 0,
                "condition": "no_hits",
                "ranking_complete": True,
                "exhausted": True,
            }
        },
    )

    assert summary["claims"][0]["status"] == "unresolved"


def test_continuation_session_is_recovered_from_a_crashed_phase_trace(tmp_path: Path) -> None:
    runner = _runner()
    run_dir = tmp_path / "campaign" / "outcome" / "Trial-A"
    prompt = tmp_path / "prompt.txt"
    case = tmp_path / "case.json"
    prompt.write_text("prompt", encoding="utf-8")
    case.write_text("{}", encoding="utf-8")
    inputs = {"trial": "Trial-A", "requested_outcome": "Overall Survival"}
    identity = runner["_execution_identity"](run_dir, inputs)
    runner["_load_or_create_execution"](
        run_dir,
        identity,
        run_inputs=inputs,
        case_file=case,
        prompt_file=prompt,
        phase=1,
        session=None,
    )
    (run_dir / "phase-1.jsonl").write_text(
        json.dumps({"session_id": "authoritative-session"}) + "\n", encoding="utf-8"
    )
    record = json.loads((run_dir / "execution.json").read_text(encoding="utf-8"))
    record["state"] = "resumable"
    runner["_atomic_json"](run_dir / "execution.json", record)
    runner["_release_execution_lock"](run_dir)

    with pytest.raises(ValueError, match="does not match"):
        runner["_load_or_create_execution"](
            run_dir,
            identity,
            run_inputs=inputs,
            case_file=case,
            prompt_file=prompt,
            phase=2,
            session="wrong-session",
        )
    resumed = runner["_load_or_create_execution"](
        run_dir,
        identity,
        run_inputs=inputs,
        case_file=case,
        prompt_file=prompt,
        phase=2,
        session="authoritative-session",
    )
    assert resumed["codex_session_id"] == "authoritative-session"
    runner["_release_execution_lock"](run_dir)


def test_collector_binds_bundle_sources_to_frozen_run_inputs(tmp_path: Path) -> None:
    collector = _collector()
    trial_dir = tmp_path / "case"
    trial_dir.mkdir()
    source_hash = "a" * 64
    run_inputs = {
        "trial": "Trial-A",
        "requested_outcome": "Overall Survival",
        "sources": [{"role": "main_article", "sha256": source_hash, "name": "main.pdf"}],
    }
    (trial_dir / "run-inputs.json").write_text(
        json.dumps(run_inputs, sort_keys=True), encoding="utf-8"
    )
    execution = {
        "run_input_sha256": hashlib.sha256(
            json.dumps(run_inputs, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    }
    bundle = trial_dir / "bundle.rob2.zip"
    canonical = {
        "batch": {
            "trials": [
                {
                    "id": "trial-a",
                    "requested_outcome": "Any treatment-emergent adverse event",
                    "sources": [{"role": "main_article", "sha256": "sha256:" + source_hash}],
                }
            ]
        }
    }
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("canonical.json", json.dumps(canonical))
    collector["_validate_execution_inputs"](
        trial_dir,
        execution,
        trial="Trial-A",
        outcome="Overall Survival",
        manifest_row=None,
        bundle=bundle,
    )
    canonical["batch"]["trials"][0]["sources"][0]["sha256"] = "sha256:" + "b" * 64
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("canonical.json", json.dumps(canonical))
    with pytest.raises(ValueError, match="source inventory/content hashes"):
        collector["_validate_execution_inputs"](
            trial_dir,
            execution,
            trial="Trial-A",
            outcome="Overall Survival",
            manifest_row=None,
            bundle=bundle,
        )

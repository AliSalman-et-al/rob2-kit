"""Public synthetic dossier and normalized replay-trace contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import validate

from rob2_kit.evaluation import (
    GoldenAcceptanceRequired,
    load_public_dossier,
    normalize_trace,
    semantic_diff,
)

ROOT = Path(__file__).resolve().parents[1]


def test_public_dossier_is_complete_and_credential_free() -> None:
    dossier = load_public_dossier(ROOT)

    assert dossier.dossier_id == "dossier:synthetic-trial"
    assert {source.role for source in dossier.sources} >= {
        "full_text",
        "protocol",
        "sap",
        "supplement",
        "registry",
        "evidence",
    }
    assert set(dossier.domains) == {
        "randomization",
        "deviations",
        "missing",
        "measurement",
        "selection",
    }
    assert {
        "optional-source-absence",
        "chronology-conflict",
        "multiple-time-points",
        "duplicates",
        "another-trial-discussion",
        "bibliography-trap",
        "layout-dependent-table",
        "prompt-injection",
        "unreadable-content",
        "changed-input",
    } <= set(dossier.overlays)
    assert all(
        "credential" not in json.dumps(source.model_dump()).casefold() for source in dossier.sources
    )


def test_prompt_manifest_covers_positive_and_negative_families() -> None:
    dossier = load_public_dossier(ROOT)
    expected = {
        "direct",
        "indirect",
        "synonym",
        "multi-result",
        "resume",
        "start-new",
        "correction",
        "status",
        "explanation",
        "negative",
    }
    assert expected <= set(dossier.prompt_families)
    assert any(prompt.negative for prompt in dossier.prompts)


def test_trace_normalization_replaces_volatile_values_but_preserves_order() -> None:
    trace = normalize_trace(
        {
            "scenario": "direct",
            "prompt_family": "direct",
            "host": {"name": "codex", "adapter": "codex@1"},
            "model": "5.6-sol",
            "release": "0.1.0",
            "execution_contract": "contract:abc",
            "calls": [
                {
                    "name": "get_work_context",
                    "arguments": {
                        "run_id": "run:9e3f",
                        "work_token": "token:secret",
                        "cursor": "cursor:secret",
                        "project_root": "C:/private/project",
                        "requested_at": "2026-08-04T12:00:01Z",
                    },
                    "response_class": "success",
                    "run_state": "assessing",
                    "next_action": "submit_domain_evidence",
                    "workflow_events": ["operation:domain-started"],
                    "checkpoint": "checkpoint:randomization",
                },
                {
                    "name": "submit_domain_evidence",
                    "arguments": {"run_id": "run:9e3f", "work_token": "token:other"},
                    "response_class": "accepted",
                    "run_state": "assessing",
                    "next_action": "submit_domain_answers",
                    "workflow_events": [],
                    "checkpoint": "checkpoint:randomization",
                },
            ],
            "final": {"run_state": "complete", "identities": {"run_id": "run:9e3f"}},
            "signals": {"duration_ms": 1200, "input_tokens": 22, "output_tokens": 44},
        }
    )

    assert [call.name for call in trace.calls] == [
        "get_work_context",
        "submit_domain_evidence",
    ]
    first_args = trace.calls[0].arguments
    assert first_args["run_id"] == "<run-1>"
    assert first_args["work_token"] == "<work-token-1>"
    assert first_args["cursor"] == "<cursor-1>"
    assert first_args["project_root"] == "<path-1>"
    assert first_args["requested_at"] == "<timestamp-1>"
    assert trace.calls[1].arguments["run_id"] == "<run-1>"
    assert trace.calls[1].arguments["work_token"] == "<work-token-2>"
    assert trace.calls[0].sequence == 1
    assert trace.calls[1].sequence == 2


def test_semantic_diff_is_readable_and_golden_updates_are_explicit(tmp_path: Path) -> None:
    expected = {"run_state": "assessing", "calls": [{"name": "status"}]}
    actual = {"run_state": "complete", "calls": [{"name": "status"}]}
    diff = semantic_diff(expected, actual)
    assert "run_state" in diff[0]
    golden = tmp_path / "golden.json"
    golden.write_text(json.dumps(expected), encoding="utf-8")
    with pytest.raises(GoldenAcceptanceRequired):
        from rob2_kit.evaluation import accept_golden

        accept_golden(golden, actual)
    from rob2_kit.evaluation import accept_golden

    accept_golden(golden, actual, accept=True)
    assert json.loads(golden.read_text(encoding="utf-8")) == actual


def test_public_trace_fixture_matches_the_published_schema() -> None:
    trace_path = ROOT / "tests" / "public_fixtures" / "traces" / "direct-codex.json"
    schema_path = ROOT / "schemas" / "normalized-trace.schema.json"
    validate(
        instance=normalize_trace(json.loads(trace_path.read_text(encoding="utf-8"))).model_dump(
            mode="json"
        ),
        schema=json.loads(schema_path.read_text(encoding="utf-8")),
    )

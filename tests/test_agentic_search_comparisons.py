from __future__ import annotations

from copy import deepcopy

import pytest

from rob2_kit.evaluation import run_comparison, validate_comparison_config
from rob2_kit.evaluation.observations import ObservationImportError, import_observations
from rob2_kit.interfaces.mcp.contracts import SearchBatchRequest, SearchData


def _config() -> dict[str, object]:
    neutral = {
        "mode": "none",
        "passages": "not_supplied",
        "labels": "forbidden",
        "answers": "forbidden",
    }
    decisive = {
        "mode": "decisive",
        "passages": "complete_relevant",
        "labels": "forbidden",
        "answers": "forbidden",
    }
    return {
        "schema": "rob2-kit.evaluation-comparisons.v0.1",
        "arms": [
            {
                "id": "free",
                "intervention_id": "free",
                "retrieval": "free_search",
                "spelling": "porter_only",
                "context": "baseline",
                "guidance": "baseline",
                "evidence": neutral,
            },
            {
                "id": "oracle",
                "intervention_id": "oracle",
                "retrieval": "supplied_decisive_evidence",
                "spelling": "porter_only",
                "context": "baseline",
                "guidance": "baseline",
                "evidence": decisive,
            },
        ],
        "pairs": [{"id": "retrieval", "left": "free", "right": "oracle", "diagnostic": True}],
        "plan": {
            "cases": [
                {
                    "case_id": "case-1",
                    "trial_id": "trial-1",
                    "outcome_id": "outcome-1",
                    "domain_ids": ["domain:missing"],
                },
                {
                    "case_id": "case-2",
                    "trial_id": "trial-2",
                    "outcome_id": "outcome-2",
                    "domain_ids": ["domain:measurement"],
                },
            ],
            "host": {
                "provider": "codex-cli",
                "interface": "jsonl",
                "version": "1",
                "prompt_identity": "sha256:" + "c" * 64,
            },
            "model": {"family": "gpt-5.6-luna", "version": "medium", "effort": "medium"},
            "retry_policy": {"max_attempts": 2, "rule": "infrastructure_only"},
            "scoring": {
                "primary_metric": "scientific_accuracy",
                "metrics": ["support", "completion", "latency", "cost"],
                "class_recall": True,
            },
            "budget": {
                "max_attempts": 5,
                "max_cost": 1.0,
                "max_context_bytes": 500,
                "max_tool_calls": 20,
            },
        },
    }


def test_comparison_schema_predeclares_diagnostic_arms() -> None:
    validate_comparison_config(
        _config(), {"free": "sha256:" + "a" * 64, "oracle": "sha256:" + "b" * 64}
    )


@pytest.mark.parametrize(
    "change",
    [
        lambda config: config["arms"][1]["evidence"].update({"labels": "provided"}),
        lambda config: config["arms"][0].update({"retrieval": "supplied_decisive_evidence"}),
        lambda config: config["pairs"][0].update({"diagnostic": False}),
    ],
)
def test_comparison_schema_rejects_coaching_or_non_diagnostic_design(change) -> None:
    config = deepcopy(_config())
    change(config)
    with pytest.raises(ValueError):
        validate_comparison_config(
            config, {"free": "sha256:" + "a" * 64, "oracle": "sha256:" + "b" * 64}
        )


@pytest.mark.parametrize(
    "mutate",
    (
        lambda config: config["arms"][0].update({"id": []}),
        lambda config: config["arms"][0].update({"intervention_id": []}),
        lambda config: config["arms"][0].update({"retrieval": []}),
        lambda config: config["pairs"][0].update({"left": []}),
        lambda config: config["pairs"][0].update({"id": []}),
    ),
)
def test_comparison_schema_rejects_malformed_json_without_leaking_type_errors(mutate) -> None:
    config = deepcopy(_config())
    mutate(config)
    with pytest.raises(ValueError):
        validate_comparison_config(
            config, {"free": "sha256:" + "a" * 64, "oracle": "sha256:" + "b" * 64}
        )


def _outcome(
    attempt_id: str,
    arm_id: str,
    cell_id: str,
    session_id: str,
    prediction: str,
    *,
    status: str = "assessed",
) -> dict[str, object]:
    return {
        "attempt_id": attempt_id,
        "arm_id": arm_id,
        "cell_id": cell_id,
        "session_id": session_id,
        "status": status,
        "prediction": prediction,
        "support": "full",
        "completion": status == "assessed",
        "latency_ms": 10,
        "cost": 0.1,
        "context_bytes": 100,
        "tool_calls": 2,
    }


def test_comparison_runner_retains_failures_and_does_not_choose_a_retry() -> None:
    config = _config()
    interventions = {"free": "sha256:" + "a" * 64, "oracle": "sha256:" + "b" * 64}
    outcomes = [
        _outcome("free-1", "free", "case-1", "session-free", "low"),
        _outcome("free-2", "free", "case-1", "session-free", "high"),
        _outcome("free-failure", "free", "case-2", "session-free", "unknown", status="failed"),
        _outcome("oracle-1", "oracle", "case-1", "session-oracle", "low"),
        _outcome("oracle-2", "oracle", "case-2", "session-oracle", "high"),
    ]

    result = run_comparison(config, interventions, outcomes, {"case-1": "low", "case-2": "high"})

    assert result["retained_outcome_count"] == len(outcomes)
    assert result["metrics"]["arms"]["free"]["attempts"] == 3
    assert result["metrics"]["arms"]["free"]["statuses"]["failed"] == 1
    pair = result["metrics"]["pairs"]["retrieval"]
    assert pair["matched_cells"] == 2
    assert pair["ambiguous_cells"] == 1
    assert pair["same_prediction"] == 0
    assert result["metrics"]["arms"]["oracle"]["class_recall"]["high"]["rate"] == 1.0
    assert "labels" not in result
    assert result["plan_identity"].startswith("sha256:")


def test_search_purpose_models_require_a_domain_for_question_purpose() -> None:
    with pytest.raises(ValueError, match="question purpose requires a Domain"):
        SearchBatchRequest(
            trial_id="trial",
            query="allocation",
            mode="any",
            purpose_question_id="sq:randomization:sequence",
        )
    with pytest.raises(ValueError, match="question purpose requires a Domain"):
        SearchData.model_validate(
            {
                "hits": [],
                "query": "allocation",
                "mode": "any",
                "profile": "porter-unicode61-v1",
                "total_matches": 0,
                "truncated": False,
                "condition": "no_hits",
                "search_receipt": "sr_aaaaaaaaaaaaaaaa",
                "session_id": "sha256:" + "a" * 64,
                "session_handle": "ss_aaaaaaaaaaaaaaaa",
                "matching_page_count": 0,
                "candidate_count": 0,
                "ranking_complete": True,
                "returned_rank_start": None,
                "returned_rank_end": None,
                "next_cursor": None,
                "exhausted": True,
                "term_feedback": [],
                "term_feedback_truncated": False,
                "term_feedback_sources_truncated": False,
                "purpose_question_id": "sq:randomization:sequence",
            }
        )


def test_observation_comparison_arms_cannot_share_a_session() -> None:
    manifest = {
        "schema": "rob2-kit.observation-import-manifest.v1",
        "comparison_config": _config(),
        "attempts": [
            {
                "attempt_id": "a",
                "comparison_arm": "free",
                "session_id": "shared",
                "transcripts": ["a"],
            },
            {
                "attempt_id": "b",
                "comparison_arm": "oracle",
                "session_id": "shared",
                "transcripts": ["b"],
            },
        ],
        "transcripts": [],
    }
    with pytest.raises(ObservationImportError, match="independent sessions"):
        import_observations(manifest, {"a": b"", "b": b""})

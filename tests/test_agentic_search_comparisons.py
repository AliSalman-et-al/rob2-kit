from __future__ import annotations

from copy import deepcopy

import pytest

from rob2_kit.evaluation import validate_comparison_config
from rob2_kit.evaluation.observations import ObservationImportError, import_observations
from rob2_kit.interfaces.mcp.contracts import SearchBatchRequest, SearchData


def _config() -> dict[str, object]:
    neutral = {
        "mode": "none", "passages": "not_supplied",
        "labels": "forbidden", "answers": "forbidden",
    }
    decisive = {
        "mode": "decisive", "passages": "complete_relevant",
        "labels": "forbidden", "answers": "forbidden",
    }
    return {
        "schema": "rob2-kit.evaluation-comparisons.v0.1",
        "arms": [
            {
                "id": "free", "intervention_id": "free", "retrieval": "free_search",
                "spelling": "porter_only", "context": "baseline", "guidance": "baseline",
                "evidence": neutral,
            },
            {
                "id": "oracle", "intervention_id": "oracle",
                "retrieval": "supplied_decisive_evidence", "spelling": "porter_only",
                "context": "baseline", "guidance": "baseline", "evidence": decisive,
            },
        ],
        "pairs": [{"id": "retrieval", "left": "free", "right": "oracle", "diagnostic": True}],
    }


def test_comparison_schema_predeclares_diagnostic_arms() -> None:
    validate_comparison_config(
        _config(), {"free": "sha256:" + "a" * 64, "oracle": "sha256:" + "b" * 64}
    )


@pytest.mark.parametrize("change", [
    lambda config: config["arms"][1]["evidence"].update({"labels": "provided"}),
    lambda config: config["arms"][0].update({"retrieval": "supplied_decisive_evidence"}),
    lambda config: config["pairs"][0].update({"diagnostic": False}),
])
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
                "attempt_id": "a", "comparison_arm": "free", "session_id": "shared",
                "transcripts": ["a"],
            },
            {
                "attempt_id": "b", "comparison_arm": "oracle", "session_id": "shared",
                "transcripts": ["b"],
            },
        ],
        "transcripts": [],
    }
    with pytest.raises(ObservationImportError, match="independent sessions"):
        import_observations(manifest, {"a": b"", "b": b""})

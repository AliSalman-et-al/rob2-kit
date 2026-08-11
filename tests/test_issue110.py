"""Installed-replay normalization behavior (#110)."""

from rob2_kit.evaluation.installed_replay import (
    normalize_replay_trace,
    normalize_semantic_value,
    semantic_projection,
)


def test_installed_replay_normalizes_live_call_ids_and_projects_to_durable_semantics() -> None:
    trace = normalize_replay_trace(
        [
            {
                "name": "prepare_run",
                "arguments": {"project_root": "C:/temporary/a"},
                "response": {"run_id": "run:one", "run_state": "assessing"},
            },
            {
                "name": "continue_run",
                "arguments": {"run_id": "run:one", "work_token": "work-token:one"},
                "response": {"run_id": "run:one", "run_state": "complete"},
            },
        ],
        final={"run_id": "run:one", "run_state": "complete"},
    )

    assert trace["calls"][0]["arguments"]["project_root"] == "<path-1>"
    assert trace["calls"][1]["arguments"]["run_id"] == "<run-1>"
    assert trace["calls"][1]["arguments"]["work_token"] == "<work-token-1>"
    assert trace["final"]["run_id"] == "<run-1>"
    durable = normalize_semantic_value(
        {
            "ledger_cursor": "ledger:42",
            "trial_id": "trial:alpha",
            "result_id": "result:alpha-mortality",
        }
    )
    assert durable == {
        "ledger_cursor": "<ledger-cursor-1>",
        "trial_id": "trial:alpha",
        "result_id": "result:alpha-mortality",
    }
    assert semantic_projection(
        {"run_state": "complete", "events": ["one"], "volatile": "ignore"}
    ) == {"run_state": "complete", "events": ["one"]}
    assert normalize_semantic_value({"run_id": "run:one"}) == {"run_id": "<run-1>"}


def test_installed_replay_normalizes_ephemeral_location_handles_but_preserves_reuse() -> None:
    """Navigation-token bytes may change, but their call structure may not."""

    def trace(handles: tuple[str, str]) -> dict[str, object]:
        return normalize_replay_trace(
            [
                {
                    "name": "search_evidence",
                    "arguments": {},
                    "response": {
                        "page": {
                            "hits": [
                                {"location_handle": handles[0]},
                                {"location_handle": handles[1]},
                            ]
                        }
                    },
                }
            ],
            final={"run_state": "complete"},
        )

    assert trace(("loc:first", "loc:second")) == trace(("loc:renamed-a", "loc:renamed-b"))
    assert trace(("loc:reused", "loc:reused")) != trace(("loc:distinct-a", "loc:distinct-b"))

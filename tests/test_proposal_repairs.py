from __future__ import annotations

from pathlib import Path

from support.rob2 import (
    _call,
    _prepared_evidence,
    _proposal_args,
    _read_required_main_reports,
    _result,
    _result_for_trial,
    _workspace,
)

from rob2_kit.application import proposal
from rob2_kit.application._state import _state
from rob2_kit.workflow_models import ProposalDraft


def _multi_trial_workspace(tmp_path: Path) -> Path:
    text = (
        "The requested outcome was not reported; only an alternate endpoint was measured. "
        "death ascertainment; end of follow-up; assigned to intervention; assigned to control; "
        "randomized population; risk ratio; The requested outcome was measured in the analyzed "
        "population.; risk; 1; events; 2.\n"
    )
    for name in ("trial-a", "trial-b"):
        trial = tmp_path / "input" / name
        trial.mkdir(parents=True)
        (trial / "main.txt").write_text(text, encoding="utf-8")
        (trial / "sources.toml").write_text(
            'roles = { "main.txt" = "main_article" }\n', encoding="utf-8"
        )
        if name == "trial-a":
            (trial / "revised.txt").write_text(text + " corrected source.\n", encoding="utf-8")
    return tmp_path


def _multi_trial_evidence(workspace: Path) -> dict[str, dict[str, object]]:
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    _read_required_main_reports(workspace)
    evidence: dict[str, dict[str, object]] = {}
    for trial_id in ("trial-a", "trial-b"):
        source = next(
            item
            for item in _call(workspace, "list_sources", {"trial_id": trial_id})["data"]["sources"]
            if item["label"] == "main.txt"
        )
        evidence[trial_id] = _call(
            workspace,
            "select_text_evidence",
            {
                "trial_id": trial_id,
                "source_id": source["id"],
                "page": 1,
                "start_line": 1,
                "end_line": 1,
            },
        )["data"]["evidence"]
    return evidence


def test_application_aggregates_duplicate_result_and_group_repairs(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    evidence = _prepared_evidence(workspace)
    first = _result(evidence)
    second = _result(evidence)
    first["target"]["comparison_groups"] = [
        {"id": "a", "assignment": "assigned to intervention"},
        {"id": "a", "assignment": "assigned to intervention duplicate"},
    ]
    first["reported"]["group_values"] = [
        {"group_id": "a", "statistic": "risk", "value": "1", "unit": "events"},
        {"group_id": "a", "statistic": "risk", "value": "2", "unit": "events"},
    ]
    proposal_args = _proposal_args(workspace, [first, second])

    receipt = proposal.save_proposal(workspace, ProposalDraft.model_validate(proposal_args))
    assert receipt["outcome"] == "repair"
    assert all(repair["detail"] for repair in receipt["repairs"])
    codes = {repair["code"] for repair in receipt["repairs"]}
    assert {
        "duplicate_trial_result",
        "duplicate_target_group",
        "duplicate_reported_group",
    } <= codes


def test_fastmcp_aggregates_reported_group_set_mismatch(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    evidence = _prepared_evidence(workspace)
    result = _result(evidence)
    result["reported"]["group_values"][1]["group_id"] = "unexpected"
    receipt = _call(workspace, "save_proposal", _proposal_args(workspace, [result]))
    assert receipt["outcome"] == "repair"
    mismatch = next(
        item for item in receipt["repairs"] if item["code"] == "reported_group_set_mismatch"
    )
    assert mismatch["path"] == "/results/0/reported/group_values"
    assert "missing IDs: b" in mismatch["detail"]
    assert "unexpected IDs: unexpected" in mismatch["detail"]


def test_initial_partial_proposal_is_rejected(tmp_path: Path) -> None:
    workspace = _multi_trial_workspace(tmp_path)
    evidence = _multi_trial_evidence(workspace)

    repair = _call(
        workspace,
        "save_proposal",
        _proposal_args(workspace, [_result_for_trial(evidence["trial-a"], "trial-a")]),
    )

    assert repair["outcome"] == "repair"
    assert any(item["code"] == "one_result_per_trial_required" for item in repair["repairs"])
    assert _state(workspace).get("proposal") is None


def test_pending_partial_replacement_rejects_unknown_and_duplicate_trials(
    tmp_path: Path,
) -> None:
    workspace = _multi_trial_workspace(tmp_path)
    evidence = _multi_trial_evidence(workspace)
    first = _call(
        workspace,
        "save_proposal",
        _proposal_args(
            workspace,
            [
                _result_for_trial(evidence["trial-a"], "trial-a"),
                _result_for_trial(evidence["trial-b"], "trial-b"),
            ],
        ),
    )
    assert first["outcome"] == "review_required"
    duplicate = _result_for_trial(evidence["trial-a"], "trial-a")
    unknown = _result_for_trial(evidence["trial-a"], "not-captured")

    repair = _call(
        workspace,
        "save_proposal",
        _proposal_args(workspace, [duplicate, duplicate, unknown]),
    )

    assert repair["outcome"] == "repair"
    codes = {item["code"] for item in repair["repairs"]}
    assert {"duplicate_trial_result", "cross_trial_evidence"} <= codes


def test_pending_partial_replacement_is_revision_checked_and_retryable(tmp_path: Path) -> None:
    workspace = _multi_trial_workspace(tmp_path)
    evidence = _multi_trial_evidence(workspace)
    first = _call(
        workspace,
        "save_proposal",
        _proposal_args(
            workspace,
            [
                _result_for_trial(evidence["trial-a"], "trial-a"),
                _result_for_trial(evidence["trial-b"], "trial-b"),
            ],
        ),
    )
    replacement = _result_for_trial(evidence["trial-a"], "trial-a")
    replacement["target"]["time_point_or_window"]["description"] = "a corrected window"
    request = _proposal_args(workspace, [replacement])
    request["expected_revision"] = first["head"]["state_revision"] - 1

    stale = _call(workspace, "save_proposal", request)

    assert stale["outcome"] == "conflict"
    request["expected_revision"] = _call(workspace, "get_status", {})["head"]["state_revision"]
    saved = _call(workspace, "save_proposal", request)
    retry = _call(workspace, "save_proposal", request)
    assert saved["outcome"] == "review_required"
    assert retry["outcome"] == "success"
    assert retry["data"]["retry"] is True

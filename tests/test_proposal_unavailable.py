from __future__ import annotations

from pathlib import Path

from support.proposal import _state_proposal
from support.rob2 import _call, _prepared_evidence, _proposal_args, _unavailable_result, _workspace


def test_unavailable_result_uses_captured_requested_outcome(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    evidence = _prepared_evidence(workspace)
    unavailable = _unavailable_result(evidence, "Researcher must select the intended result.")
    repair = _call(workspace, "save_proposal", _proposal_args(workspace, [unavailable]))
    assert repair["outcome"] == "review_required"
    assert _state_proposal(workspace)["results"][0]["requested_outcome"] == "requested outcome"


def test_unavailable_missing_facts_are_deduplicated_and_source_is_derived(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    evidence = _prepared_evidence(workspace)
    missing_fact = "Researcher must select the intended result."
    unavailable = {
        **_unavailable_result(evidence, missing_fact),
        "missing_facts": [
            {
                "fact": missing_fact,
                "basis": {
                    "kind": "missing_reporting",
                    "evidence": evidence["handle"],
                },
            },
            {
                "fact": "different fact",
                "basis": {
                    "kind": "missing_reporting",
                    "evidence": evidence["handle"],
                },
            },
            {
                "fact": missing_fact,
                "basis": {
                    "kind": "missing_reporting",
                    "evidence": evidence["handle"],
                },
            },
        ],
    }

    repair = _call(workspace, "save_proposal", _proposal_args(workspace, [unavailable]))

    assert repair["outcome"] == "repair"
    codes = {item["code"] for item in repair["repairs"]}
    assert codes == {"duplicate_missing_fact"}


def test_unavailable_basis_is_not_limited_to_english_phrasing(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "input" / "trial" / "main.txt").write_text(
        "El desenlace solicitado no fue informado.", encoding="utf-8"
    )
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    source = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"][0]
    evidence = _call(
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
    unavailable = _unavailable_result(evidence, "The requested endpoint result is not reported.")

    saved = _call(workspace, "save_proposal", _proposal_args(workspace, [unavailable]))

    assert saved["outcome"] == "review_required"

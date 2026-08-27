from __future__ import annotations

from pathlib import Path

import pytest
from support.proposal import _state_proposal
from support.rob2 import _call, _prepared_evidence, _proposal_args, _unavailable_result, _workspace

from rob2_kit.workflow_models import has_missing_reporting_signal


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


def test_unavailable_basis_requires_a_missing_reporting_signal(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "input" / "trial" / "main.txt").write_text(
        "An alternate endpoint was measured.", encoding="utf-8"
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
    unavailable = _unavailable_result(evidence, "Select the requested endpoint.")

    repair = _call(workspace, "save_proposal", _proposal_args(workspace, [unavailable]))

    assert repair["outcome"] == "repair"
    assert any(
        item["code"] == "unavailable_source_lacks_missing_signal" for item in repair["repairs"]
    )


def test_unavailable_basis_accepts_not_routinely_documented(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "input" / "trial" / "main.txt").write_text(
        "Adverse events were not routinely documented.", encoding="utf-8"
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
    unavailable = _unavailable_result(evidence, "Select the adverse-event endpoint.")

    saved = _call(workspace, "save_proposal", _proposal_args(workspace, [unavailable]))

    assert saved["outcome"] == "review_required"


@pytest.mark.parametrize(
    ("source", "expected"),
    (
        ("not routinely documented", True),
        ("no outcome data", True),
        ("missing reporting data", True),
        ("data were unavailable", True),
        ("outcome data were missing", True),
        ("The result was not significant", False),
        ("No results were statistically significant", False),
        ("The result was not reported as significant", False),
        ("There was no difference", False),
        ("without adjustment", False),
        ("not reported", True),
        ("results were not reported", True),
    ),
)
def test_missing_reporting_signal_is_narrow_and_lexical(source: str, expected: bool) -> None:
    assert has_missing_reporting_signal(source) is expected

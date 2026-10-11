from __future__ import annotations

from pathlib import Path

from support.rob2 import (
    _call,
    _prepared_evidence,
    _proposal_args,
    _unavailable_result,
    _workspace,
)


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

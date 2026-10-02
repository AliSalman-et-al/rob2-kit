from __future__ import annotations

import json
from pathlib import Path

import pytest

from rob2_kit.evaluation.cohort import DOMAINS
from scripts.build_adjudication_cohort import _trace_receipt
from scripts.build_fresh_adjudication_cohort import _trace
from scripts.build_september_adjudication_cohorts import _review_from_trace


@pytest.mark.parametrize("mode", ["summary", "fragment"])
@pytest.mark.parametrize("importer", ["audit", "fresh", "september"])
def test_partial_review_cannot_become_complete_adjudication_evidence(
    tmp_path: Path, mode: str, importer: str
) -> None:
    receipt = {
        "outcome": "success",
        "data": {
            "review": {"disposition": "assessed", "trial_id": "trial"},
            "domain_findings": [{"domain_id": domain, "answers": []} for domain in DOMAINS],
            "review_page": {"mode": mode},
        },
    }
    path = tmp_path / "phase-1.jsonl"
    path.write_text(
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "mcp_tool_call",
                    "tool": "review_trial",
                    "result": {"structured_content": receipt},
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="no (complete )?assessed review receipt"):
        if importer == "audit":
            _trace_receipt(path)
        elif importer == "fresh":
            _trace(tmp_path)
        else:
            _review_from_trace((path,))

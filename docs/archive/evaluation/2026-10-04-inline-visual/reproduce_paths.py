"""Offline native MCP path comparison on a neutral raster allocation fixture."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest
from support import rob2 as support
from test_inline_visual_references import TRANSCRIPTIONS, _prepared

from rob2_kit.application._state import _canonical_evidence_records, _state
from rob2_kit.workflow_models import VisualEvidenceReference

root = Path(sys.argv[1])
assert not root.exists(), "Keep existing diagnostic artifacts; choose a fresh output directory."
root.mkdir(parents=True)
with pytest.MonkeyPatch.context() as patch:
    initial, text, revision, source = _prepared(root / "initial", patch)
    records = {}
    result = {}
    for name in ["selected_handle", "inline_visual"]:
        workspace = root / name
        shutil.copytree(initial, workspace)
        support._call(
            workspace, "get_domain_context", {"trial_id": "trial", "domain_id": "domain:selection"}
        )
        actions = []

        def invoke(operation: str, arguments: dict) -> dict:
            response = support._call(workspace, operation, arguments)
            actions.append({"operation": operation, "outcome": response["outcome"]})
            return response

        rendered = invoke(
            "render_page", {"trial_id": "trial", "source_id": source["id"], "page": 1}
        )
        assert len(rendered["_image_content"]) == 1
        reference = {
            "delivery_receipt": rendered["data"]["delivery_receipt"],
            "region": [0.0, 0.0, 1.0, 1.0],
            "transcription": TRANSCRIPTIONS[0],
            "uncertainty": "The graphic does not establish analysis timing.",
        }
        if name == "selected_handle":
            reference = invoke(
                "select_visual_evidence",
                {"trial_id": "trial", "source_id": source["id"], **reference},
            )["data"]["evidence"]["handle"]
        draft = support._domain_draft("trial", "domain:selection", revision, text)
        draft["answers"][0]["bases"].append({"evidence": reference, "role": "context"})
        draft["answers"][0]["unknowns"] = ["The graphic does not establish analysis timing."]
        draft["answers"][0]["counterevidence"] = [
            {
                "evidence": [reference],
                "implication": "Allocation counts do not date an analysis plan.",
            }
        ]
        saved = invoke("save_domain_judgment", draft)
        assert saved["outcome"] == "success", saved
        record = _state(workspace)["domain_records"]["trial:domain:selection"]
        ids = {basis["evidence"] for answer in record["answers"] for basis in answer["bases"]}
        catalog = _canonical_evidence_records(workspace, ids)
        records[name] = (record["result_identity"], record["answers"], catalog)
        result[name] = {"public_actions": actions, "action_count": len(actions)}
    assert records["selected_handle"] == records["inline_visual"]
    result.update(
        {
            "model_calls": 0,
            "comparison": "Both paths on current code; offline MCP transport, not model behavior.",
            "same_result_answers_citations_counterclaims_uncertainty": True,
            "inline_visual_required_values": VisualEvidenceReference.model_json_schema()[
                "required"
            ],
            "selected_visual_required_values": [
                "trial_id",
                "source_id",
                "delivery_receipt",
                "transcription",
                "region",
            ],
            "no_entailment_or_transcription_truth_claim": True,
            "frozen_paid_pair_unchanged": True,
        }
    )
    (root / "measurement.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))

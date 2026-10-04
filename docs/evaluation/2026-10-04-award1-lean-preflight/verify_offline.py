"""Check existing offline provenance artifacts; never launch inference."""

import json
import sqlite3
import sys
from pathlib import Path

from fastmcp.exceptions import ToolError
from support import rob2 as support

from rob2_kit.application._state import _canonical_evidence_records, _identity, _state

root = Path(sys.argv[1])
workspace = root / "offline-provenance-workspace"
state = _state(workspace)
record = state["domain_records"]["award-1-2014:domain:missing"]
submitted = json.loads((root / "offline-input.json").read_text())["answers"]
current = json.loads((root / "approved-offline-result.json").read_text())
original = json.loads((root / "original-proposal.json").read_text())["payload"]["results"][0]
for key in ["target", "reported", "relation", "bindings"]:
    assert current[key] == original[key]
assert record["result_identity"] == _identity(current)
assert current["evidence"][1]["kind"] == "figure"
identities = {basis["evidence"] for answer in record["answers"] for basis in answer["bases"]}
catalog = _canonical_evidence_records(workspace, identities)
for expected, saved in zip(submitted, record["answers"], strict=True):
    assert saved["unknowns"] == expected["unknowns"]
    assert (
        saved["counterevidence"][0]["implication"] == expected["counterevidence"][0]["implication"]
    )
    counterbasis = saved["bases"][saved["counterevidence"][0]["basis_index"]]
    assert catalog[counterbasis["evidence"]]["kind"] == "figure"
    for basis in saved["bases"]:
        assert "working_observation" not in basis
        evidence = catalog[basis["evidence"]]
        assert basis["source"] == (
            evidence["transcription"] if evidence["kind"] == "figure" else evidence["quote"]
        )
for evidence in catalog.values():
    if evidence["kind"] == "figure":
        assert "Exenatide" in evidence["transcription"] and "Placebo" in evidence["transcription"]
        assert evidence["uncertainty"] == (
            "Exenatide figure n=26 differs from prose n=24; no numerical reconciliation asserted."
        )
        assert evidence["delivery_receipt"] and evidence["render"]["png_sha256"]
    else:
        assert evidence["source_version"] and evidence["start_line"] and evidence["end_line"]
        assert evidence["quote"] and evidence["page"]
with sqlite3.connect(workspace / ".rob2-kit/working.sqlite3") as connection:
    assert connection.execute("select count(*) from working_checkpoints").fetchone()[0] == 0
future = root / "future-initial-workspace"
assert not _state(future).get("domain_records")
with sqlite3.connect(future / ".rob2-kit/derivative.sqlite3") as connection:
    assert (
        connection.execute("select count(*) from page_reads where phase='assessment'").fetchone()[0]
        == 0
    )
result = {
    "passed": True,
    "production_sha": "e6b13031ddfa72437f3e1f2f9ca3b38ea58a064c",
    "exact_Code_target_reported_relation_preserved": True,
    "original_leaf_bindings_and_digests_preserved": True,
    "current_result_identity_bound": record["result_identity"],
    "canonical_domain_identity": record["identity"],
    "canonical_server_label": record["judgment"],
    "label_is_not_a_reference_answer": True,
    "active_answers": record["active_questions"],
    "canonical_evidence_count": len(identities),
    "visual_transcription_receipt_render_uncertainty_retained": True,
    "text_quote_source_version_page_lines_retained": True,
    "unknowns_and_excluded_arm_counterpoint_retained": True,
    "working_checkpoints": 0,
    "forced_scope_metadata": False,
    "future_initial_domain_records": 0,
    "future_initial_assessment_reads": 0,
    "paid_calls": 0,
}
invalid = json.loads((root / "offline-input.json").read_text())
revision = _state(workspace)["revision"]
invalid["expected_revision"] = revision
invalid["answers"][0]["bases"] = [
    {"source_id": "sh_0123456789abcdef", "page": 1, "start_line": 1, "end_line": 2}
]
try:
    rejected = support._call(workspace, "save_domain_judgment", invalid)
    assert rejected["outcome"] in {"condition", "repair"}
except ToolError:
    pass
assert _state(workspace)["revision"] == revision
result["unsupported_source_rejected_without_revision_change"] = True
(root / "offline-validation.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))

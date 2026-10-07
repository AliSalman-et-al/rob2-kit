"""Exact quoted-text sharing retains scientific fields and source recovery."""

import copy
import json
from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError
from test_bounded_trial_review import _SELECTOR, _collect, _identity, _project, _review

from rob2_kit.interfaces.mcp import server
from rob2_kit.workflow_models import WorkingResultStep


def receipt() -> dict:
    original = _review(justification="Original qualified inference.", evidence_count=1)
    answer = original["data"]["domain_findings"][0]["answers"][0]
    answer.update(
        warrant="A distinct inferential bridge, not synonymous with the justification.",
        unknowns=["Outcome availability remains unknown.", "Attribution is unproven."],
        counterevidence=[{"basis_index": 0, "implication": "Opposes this particular inference."}],
        limitations=[
            {"unresolved_premise": "Actual measurement count", "stopping_rationale": "Unreported."}
        ],
        facts=[
            {
                "text": "原始 exact source quotation. " * 80,
                "role": role,
                "evidence": answer["evidence"][0],
            }
            for role in ("support", "counterevidence")
        ],
        bases=[
            {"kind": "inference", "assertion": "host_asserted", "evidence": answer["evidence"][0]}
        ],
        evidence_expansions=[
            {
                "operation": "read_pages",
                "trial_id": "synthetic-trial",
                "evidence": answer["evidence"][0]["handle"],
                "windows": [
                    {"source_id": "sh_0000000000000000", "page": 1, "start_line": 1, "end_line": 3}
                ],
            }
        ],
    )
    answer["missing_data"] = {
        "rows": [
            {
                "scope": {
                    "arm": "Alpha",
                    "population": "randomized",
                    "unit": "participants",
                    "time_point": "selected window",
                },
                "randomized": 20,
                "analyzed": 19,
                "observed": None,
                "unavailable": 2,
                "basis": [answer["evidence"][0]["identity"]],
            }
        ],
    }
    answer["bases"][0]["working_observation"] = {
        "observation": {
            "text": "Host interpretation remains source-bound and qualified.",
            "scope": {
                "relation": "partial_overlap",
                "meaning": "uncertain",
                "uncertainty": "Different window.",
            },
            "sources": [
                {"source_id": "sh_0000000000000000", "page": 1, "start_line": 1, "end_line": 3}
            ],
        },
        "transfer": "Explicit conditional inference across windows.",
    }
    snapshot = answer["bases"][0]["working_observation"]
    snapshot["result_step"] = WorkingResultStep.model_validate(
        {
            "id": "collection",
            "aspect": "outcome_ascertainment",
            "observation": snapshot["observation"],
            "inference": "Conditional connection to the selected Result.",
            "unknowns": ["Actual outcome availability remains unknown."],
            "counterevidence": [
                {
                    **snapshot["observation"],
                    "text": "An analysis count does not establish measurement availability.",
                }
            ],
            "counts": [
                {
                    "arm": "Alpha",
                    "population": "randomized",
                    "unit": "participants",
                    "time_point": "selected window",
                    "randomized": 20,
                    "analyzed": 19,
                    "basis": [answer["evidence"][0]["handle"]],
                }
            ],
        }
    ).model_dump(mode="json", exclude_none=True)
    snapshot["count_evidence"] = {
        answer["evidence"][0]["handle"]: answer["evidence"][0]["identity"]
    }
    second = copy.deepcopy(answer)
    second.update(
        question_id="sq:randomization:concealment",
        warrant="Different answer-specific interpretation.",
        unknowns=["Different unresolved premise."],
    )
    original["data"]["domain_findings"][0]["answers"].append(second)
    return server._validate_response("review_trial", original)


def expand(snapshot: dict) -> dict:
    original = copy.deepcopy(snapshot)
    bodies = original["data"].pop("evidence_bodies", {})
    for domain in original["data"]["domain_findings"]:
        for answer in domain["answers"]:
            for fact in answer["facts"]:
                identity = fact.pop("source_body", None)
                if identity:
                    assert fact["evidence"] == bodies[identity]["evidence"]
                    fact["text"] = bodies[identity]["text"]
    return original


def test_only_identical_source_text_changes_and_complete_receipt_roundtrips():
    original = receipt()
    unchanged = copy.deepcopy(original)
    projected = server._share_review_fact_text(original)
    assert expand(projected) == original == unchanged
    for before, after in zip(
        original["data"]["domain_findings"][0]["answers"],
        projected["data"]["domain_findings"][0]["answers"],
        strict=True,
    ):
        assert {k: v for k, v in before.items() if k != "facts"} == {
            k: v for k, v in after.items() if k != "facts"
        }
        assert after["facts"][1] == before["facts"][1]
        assert after["facts"][0]["role"] == before["facts"][0]["role"]
    assert server._review_transport_bytes(projected) < server._review_transport_bytes(original)
    assert server._share_review_fact_text(projected) == projected


def test_short_quotes_keep_inline_shape_when_sharing_would_increase_native_bytes():
    original = receipt()
    for answer in original["data"]["domain_findings"][0]["answers"]:
        for fact in answer["facts"]:
            fact["text"] = "Short exact quote."
    assert server._share_review_fact_text(original) == original


def test_sharing_can_deliver_complete_fidelity_within_the_same_native_limit(tmp_path, monkeypatch):
    original = receipt()
    shared = server._share_review_fact_text(original)
    limit = (server._review_transport_bytes(original) + server._review_transport_bytes(shared)) // 2
    monkeypatch.setattr(server, "_REVIEW_TRIAL_RESPONSE_BYTES", limit)
    delivered = _project(original, tmp_path)
    assert expand(delivered) == original
    assert "review_page" not in delivered["data"]
    assert server._review_transport_bytes(delivered) <= limit
    monkeypatch.setattr(server, "_share_review_fact_text", lambda snapshot: snapshot)
    legacy = _project(original, tmp_path)
    assert legacy["data"]["review_page"]["mode"] == "summary"
    assert legacy["data"]["review_page"]["complete"] is False


@pytest.mark.parametrize("defect", ["different_text", "different_handle", "different_identity"])
def test_conflicting_or_unique_source_binding_stays_inline(defect):
    original = receipt()
    for fact in original["data"]["domain_findings"][0]["answers"][1]["facts"]:
        if defect == "different_text":
            fact["text"] += " Different tail."
        else:
            fact["evidence"]["identity" if defect == "different_identity" else "handle"] = (
                _identity("other-region")
                if defect == "different_identity"
                else "eh_0000000000000001"
            )
    assert server._share_review_fact_text(original) == original


@pytest.mark.parametrize("defect", ["missing_body", "identity", "handle", "quote"])
def test_unbound_body_cannot_pass_public_output_contract(defect):
    projected = server._share_review_fact_text(receipt())
    bodies = projected["data"]["evidence_bodies"]
    identity = next(iter(bodies))
    if defect == "missing_body":
        bodies.clear()
    elif defect == "identity":
        bodies[_identity("different")] = bodies.pop(identity)
    elif defect == "quote":
        bodies[identity]["text"] += " Altered quote."
    else:
        bodies[identity]["evidence"]["handle"] = "eh_0000000000000001"
    with pytest.raises(ToolError, match="internal_output_contract_error"):
        server._validate_response("review_trial", projected)


def test_selected_views_are_self_contained_and_visual_routes_remain_exact(tmp_path):
    original = receipt()
    for answer in original["data"]["domain_findings"][0]["answers"]:
        answer["evidence_expansions"] = [
            {
                "operation": "render_page",
                "trial_id": "synthetic-trial",
                "evidence": answer["evidence"][0]["handle"],
                "source_id": "sh_0000000000000000",
                "page": 7,
            }
        ]
    original = server._validate_response("review_trial", original)
    projected = _project(original, tmp_path)
    assert expand(projected) == original
    selected = _project(original, tmp_path, selector=_SELECTOR)
    answer = selected["data"]["domain_findings"][0]["answers"][0]
    assert answer == original["data"]["domain_findings"][0]["answers"][0]
    assert "evidence_bodies" not in selected["data"]


def test_raw_unicode_overflow_recovers_exact_shared_snapshot_and_rejects_stale_cursor(
    tmp_path: Path, monkeypatch
):
    (tmp_path / ".rob2-kit").mkdir()
    original = receipt()
    original["data"]["domain_findings"][0]["answers"][0]["unknowns"] = [
        "未知 scientific uncertainty. " * 500
    ]
    monkeypatch.setattr(server, "_REVIEW_TRIAL_RESPONSE_BYTES", 6_000)
    delivered = _project(original, tmp_path, persist=True)
    page = delivered["data"]["review_page"]
    cursor = page["stable_recovery"]["cursor"]
    recovered = json.loads(_collect(original, tmp_path, cursor=cursor))
    assert expand(recovered) == original
    assert recovered == server._share_review_fact_text(original)
    stale = copy.deepcopy(original)
    stale["data"]["review"]["identity"] = _identity("changed-review")
    with pytest.raises(ValueError, match="review_cursor_stale"):
        _project(stale, tmp_path, cursor=cursor)

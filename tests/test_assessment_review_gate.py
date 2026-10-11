from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from support.rob2 import (
    _answer_value,
    _assessment_workspace,
    _call,
    _domain_draft,
    _finalize_assessment,
)

from rob2_kit.application._state import _state
from rob2_kit.packs import SCIENTIFIC_PACK


def _complete_assessment(tmp_path: Path) -> tuple[Path, dict[str, Any], int]:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    for domain in SCIENTIFIC_PACK.domains:
        saved = _call(
            workspace,
            "save_domain_judgment",
            _domain_draft("trial", domain.id, revision, evidence),
        )
        assert saved["outcome"] == "success", saved
        revision = int(saved["head"]["state_revision"])
    return workspace, evidence, revision


def _recover_full_review(workspace: Path, reviewed: dict[str, Any]) -> dict[str, Any]:
    page = reviewed["data"].get("review_page")
    if page is None or page["mode"] == "complete":
        return reviewed

    assert page["mode"] == "summary"
    assert page["complete"] is False
    assert "result" in page["deferred_fields"]
    assert reviewed["data"].get("result") is None

    cursor = page["stable_recovery"]["cursor"]
    fragments: list[str] = []
    offset = 0
    total: int | None = None
    for _ in range(64):
        continued = _call(
            workspace,
            "review_trial",
            {
                "trial_id": reviewed["data"]["review"]["trial_id"],
                "expected_revision": reviewed["head"]["state_revision"],
                "cursor": cursor,
            },
        )
        assert continued["outcome"] == "success", continued
        assert continued["head"] == reviewed["head"]
        fragment_page = continued["data"]["review_page"]
        assert fragment_page["mode"] == "fragment"
        assert fragment_page["complete"] is False
        assert fragment_page["offset_unit"] == "unicode_codepoints"
        assert fragment_page["offset"] == offset
        total = fragment_page["total"] if total is None else total
        assert fragment_page["total"] == total
        fragment = fragment_page["fragment"]
        assert fragment
        fragments.append(fragment)
        offset += len(fragment)
        cursor = fragment_page["next_cursor"]
        if cursor is None:
            assert offset == total
            recovered = json.loads("".join(fragments))
            assert recovered["head"] == reviewed["head"]
            assert recovered["data"]["review"]["identity"] == reviewed["data"]["review"]["identity"]
            return recovered
        assert offset < total
    pytest.fail("full review receipt did not terminate within 64 fragments")


def test_trial_requires_review_and_explicit_closure_before_finalization(tmp_path: Path) -> None:
    workspace, evidence, revision = _complete_assessment(tmp_path)
    premature = _call(workspace, "finalize_batch", {"expected_revision": revision})
    assert premature["outcome"] == "condition"
    assert _state(workspace)["trial_dispositions"] == {"trial": "reviewable"}

    reviewed = _call(
        workspace,
        "review_trial",
        {"trial_id": "trial", "expected_revision": revision},
    )
    assert reviewed["outcome"] == "success", reviewed
    assert reviewed["data"]["review"]["disposition"] == "assessed"
    assert len(reviewed["data"]["review"]["checkpoint_ids"]) == 5
    full_review = _recover_full_review(workspace, reviewed)
    assert full_review["data"]["result"]["trial_id"] == "trial"
    assert all(
        basis["assertion"] == "host_asserted"
        for finding in full_review["data"]["domain_findings"]
        for answer in finding["answers"]
        for basis in answer["bases"]
    )
    old_review_reference = reviewed["data"]["review"]["identity"]

    searched = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": "risk ratio", "mode": "any"},
    )
    assert searched["outcome"] == "success"
    refreshed = _call(
        workspace,
        "get_domain_context",
        {"trial_id": "trial", "domain_id": SCIENTIFIC_PACK.domains[0].id},
    )
    assert refreshed["outcome"] == "success", refreshed
    checkpoint = _state(workspace)["domain_records"]["trial:domain:randomization"]
    correction = _domain_draft(
        "trial",
        SCIENTIFIC_PACK.domains[0].id,
        int(reviewed["head"]["state_revision"]),
        evidence,
    )
    correction["answers"][0]["answer"] = _answer_value(
        correction["answers"][0]["question_id"], "probably_yes"
    )
    correction["supersedes"] = checkpoint["identity"]
    correction["revision_basis"] = {
        "kind": "self_correction",
        "rationale": "The revised answer changes the reviewed Domain checkpoint.",
    }
    corrected = _call(workspace, "save_domain_judgment", correction)
    assert corrected["outcome"] == "success", corrected
    assert _state(workspace).get("trial_reviews", {}).get("trial") is None

    stale_close = _call(
        workspace,
        "close_trial",
        {
            "trial_id": "trial",
            "expected_revision": corrected["head"]["state_revision"],
            "review_reference": old_review_reference,
        },
    )
    assert stale_close["outcome"] == "condition"
    assert stale_close["condition"]["code"] == "trial_review_stale"
    reviewed = _call(
        workspace,
        "review_trial",
        {"trial_id": "trial", "expected_revision": corrected["head"]["state_revision"]},
    )
    assert reviewed["outcome"] == "success", reviewed
    assert reviewed["data"]["review"]["identity"] != old_review_reference
    revision = int(reviewed["head"]["state_revision"])
    closed = _call(
        workspace,
        "close_trial",
        {
            "trial_id": "trial",
            "expected_revision": revision,
            "review_reference": reviewed["data"]["review"]["identity"],
        },
    )
    assert closed["outcome"] == "success", closed

    finalized = _call(
        workspace,
        "finalize_batch",
        {"expected_revision": int(closed["head"]["state_revision"])},
    )
    assert finalized["outcome"] == "success", finalized
    assert finalized["data"]["artifact"]["identity"]
    state = _state(workspace)
    assert state["review"] is None
    assert state["phase"] == "finalized"
    assert state["trial_closures"]["trial"]["identity"] == closed["data"]["closure"]["identity"]
    assert not any(item.get("purpose") == "assessment" for item in state.get("acknowledgments", []))


def test_domain_revision_requires_lineage_and_preserves_history(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    first = _call(
        workspace,
        "save_domain_judgment",
        _domain_draft("trial", SCIENTIFIC_PACK.domains[0].id, revision, evidence),
    )
    assert first["outcome"] == "success", first
    revision = int(first["head"]["state_revision"])
    key = "trial:domain:randomization"
    prior = _state(workspace)["domain_records"][key]
    refreshed = _call(
        workspace,
        "get_domain_context",
        {"trial_id": "trial", "domain_id": SCIENTIFIC_PACK.domains[0].id},
    )
    assert refreshed["outcome"] == "success", refreshed

    changed = _domain_draft("trial", SCIENTIFIC_PACK.domains[0].id, revision, evidence)
    changed["answers"][0]["answer"] = _answer_value(
        changed["answers"][0]["question_id"], "probably_yes"
    )
    refused = _call(workspace, "save_domain_judgment", changed)
    assert refused["outcome"] == "condition"
    assert refused["condition"]["code"] == "domain_revision_basis_required"
    assert _state(workspace)["domain_history"][key] == [prior["identity"]]

    changed["supersedes"] = prior["identity"]
    changed["revision_basis"] = {
        "kind": "self_correction",
        "rationale": "The prior answer was inconsistent with the active question evidence.",
    }
    revised = _call(workspace, "save_domain_judgment", changed)
    assert revised["outcome"] == "success", revised
    state = _state(workspace)
    assert state["domain_history"][key] == [
        prior["identity"],
        revised["data"]["checkpoint"]["identity"],
    ]

    retry = _call(workspace, "save_domain_judgment", changed)
    assert retry["outcome"] == "success"
    assert retry["data"]["retry"] is True
    assert _state(workspace)["domain_history"][key] == state["domain_history"][key]

    revision = int(revised["head"]["state_revision"])
    for domain in SCIENTIFIC_PACK.domains[1:]:
        saved = _call(
            workspace,
            "save_domain_judgment",
            _domain_draft("trial", domain.id, revision, evidence),
        )
        assert saved["outcome"] == "success", saved
        revision = int(saved["head"]["state_revision"])

    finalized = _finalize_assessment(workspace, revision)
    assert finalized["outcome"] == "success", finalized


def test_new_evidence_revision_must_use_novel_evidence(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "trial"
    trial.mkdir(parents=True)
    (trial / "novel.txt").write_text(
        "A newly selected complete premise changes the evidence audit.", encoding="utf-8"
    )
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    first = _call(
        workspace,
        "save_domain_judgment",
        _domain_draft("trial", SCIENTIFIC_PACK.domains[0].id, revision, evidence),
    )
    assert first["outcome"] == "success", first
    revision = int(first["head"]["state_revision"])
    key = "trial:domain:randomization"
    prior = _state(workspace)["domain_records"][key]
    source = next(
        item
        for item in _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
        if item["label"] == "novel.txt"
    )
    novel = _call(
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
    refreshed = _call(
        workspace,
        "get_domain_context",
        {"trial_id": "trial", "domain_id": SCIENTIFIC_PACK.domains[0].id},
    )
    assert refreshed["outcome"] == "success", refreshed
    changed = _domain_draft("trial", SCIENTIFIC_PACK.domains[0].id, revision, evidence)
    changed["supersedes"] = prior["identity"]
    changed["revision_basis"] = {
        "kind": "new_evidence",
        "evidence": novel["handle"],
        "rationale": "A newly selected complete premise changes the evidence audit.",
    }

    refused = _call(workspace, "save_domain_judgment", changed)
    assert refused["outcome"] == "condition"
    assert refused["condition"]["code"] == "domain_revision_basis_invalid"

    changed["answers"][0]["bases"] = [
        {
            "kind": "direct_support",
            "evidence": novel["handle"],
        }
    ]
    revised = _call(workspace, "save_domain_judgment", changed)
    assert revised["outcome"] == "success", revised
    assert (
        _state(workspace)["domain_records"][key]["revision_basis"]["evidence"] == novel["identity"]
    )

    retry = _call(workspace, "save_domain_judgment", changed)
    assert retry["outcome"] == "success"
    assert retry["data"]["retry"] is True

    revision = int(revised["head"]["state_revision"])
    for domain in SCIENTIFIC_PACK.domains[1:]:
        saved = _call(
            workspace,
            "save_domain_judgment",
            _domain_draft("trial", domain.id, revision, evidence),
        )
        assert saved["outcome"] == "success", saved
        revision = int(saved["head"]["state_revision"])

    finalized = _finalize_assessment(workspace, revision)
    assert finalized["outcome"] == "success", finalized
    artifact = workspace / finalized["data"]["artifact"]["path"]
    standalone = subprocess.run(
        [sys.executable, "scripts/verify_bundle.py", str(artifact)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert standalone.returncode == 0, standalone.stderr or standalone.stdout


def test_discard_is_not_a_public_mcp_tool() -> None:
    from rob2_kit.interfaces.mcp.server import PUBLIC_TOOL_NAMES

    assert "discard" not in PUBLIC_TOOL_NAMES

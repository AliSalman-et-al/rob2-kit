"""A source-bound interpretation belongs in the Evidence basis already submitted."""

from pathlib import Path

import pytest
from support.rob2 import (
    _assessment_workspace,
    _call,
    _domain_draft,
    _finalize_assessment,
    _read_required_main_reports,
    _standalone_verify,
)

from rob2_kit.application._state import _canonical_evidence_records, _state
from rob2_kit.application.finalization import verify_bundle
from rob2_kit.packs.scientific import SCIENTIFIC_PACK


@pytest.mark.parametrize(
    "scope",
    [
        {"relation": "mismatch", "groups": ["third arm"], "stage": "initial treatment"},
        {"relation": "partial_overlap", "window": "early and later follow-up"},
        {
            "relation": "matched",
            "population": "sampled participants",
            "method": "group-based analysis",
            "meaning": "inferred",
        },
        {"relation": "shared_trial_context", "groups": ["all trial groups"]},
        {"relation": "unknown", "uncertainty": "Sampling mechanism not established"},
        None,
    ],
)
def test_basis_captures_interpretation_without_working_checkpoint_or_scope_inference(
    tmp_path: Path, scope: dict | None
) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    _read_required_main_reports(workspace)
    assert _call(workspace, "get_status", {})["data"]["working_checkpoint"]["status"] == "absent"
    draft = _domain_draft("trial", SCIENTIFIC_PACK.domains[0].id, revision, evidence)
    observation = {"text": "A host interpretation of the cited material."}
    if scope is not None:
        observation["scope"] = scope
    draft["answers"][0]["bases"][0]["working_observation"] = observation
    answer_before = draft["answers"][0]["answer"]
    saved = _call(workspace, "save_domain_judgment", draft)
    assert saved["outcome"] == "success", saved
    record = _state(workspace)["domain_records"]["trial:domain:randomization"]
    basis = record["answers"][0]["bases"][0]
    assert record["answers"][0]["answer"] == answer_before
    link = basis["working_observation"]
    assert set(link) == {"observation"}
    note = link["observation"]
    assert note["text"] == observation["text"] and note["text"] != basis["source"]
    assert "domain_id" not in note and "question_id" not in note
    canonical = _canonical_evidence_records(workspace, {basis["evidence"]})[basis["evidence"]]
    assert canonical["quote"] == basis["source"]
    assert note["sources"] == [
        {
            "source_id": evidence["source_id"],
            "page": canonical["page"],
            "start_line": canonical["start_line"],
            "end_line": canonical["end_line"],
        }
    ]
    if scope is None:
        assert "scope" not in note
    else:
        assert all(note["scope"][key] == value for key, value in scope.items())
        assert "result_identity" not in note["scope"]
        assert "population" not in note["scope"] or "population" in scope
    context = _call(
        workspace,
        "get_domain_context",
        {"trial_id": "trial", "domain_id": SCIENTIFIC_PACK.domains[0].id},
    )
    public = context["data"]["answers"][0]["bases"][0]["working_observation"]
    assert public["observation"]["text"] == observation["text"]
    assert _call(workspace, "get_status", {})["data"]["working_checkpoint"]["status"] == "absent"
    if scope is None:
        revision = int(saved["head"]["state_revision"])
        for domain in SCIENTIFIC_PACK.domains[1:]:
            saved = _call(
                workspace,
                "save_domain_judgment",
                _domain_draft("trial", domain.id, revision, evidence),
            )
            assert saved["outcome"] == "success", saved
            revision = int(saved["head"]["state_revision"])
        finalized = _finalize_assessment(workspace, revision)
        artifact = workspace / finalized["data"]["artifact"]["path"]
        assert verify_bundle(artifact)
        assert _standalone_verify(artifact).returncode == 0

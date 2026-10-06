"""Scope is a visible host interpretation, not a scientific answer gate."""

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

from rob2_kit.application._state import _identity, _state
from rob2_kit.application.finalization import verify_bundle
from rob2_kit.packs.scientific import SCIENTIFIC_PACK
from rob2_kit.workflow_models import WorkingNote


@pytest.mark.parametrize(
    "scope",
    [
        {"relation": "mismatch", "groups": ["CBD200"], "stage": "stage 2", "meaning": "reported"},
        {"relation": "partial_overlap", "groups": ["CBD400", "placebo"], "window": "weeks 1–12"},
        {
            "relation": "matched",
            "population": "randomized",
            "method": "Cox censoring",
            "meaning": "inferred",
        },
        {
            "relation": "shared_trial_context",
            "groups": ["all randomized arms"],
            "stage": "treatment completion",
        },
        {"relation": "unknown", "uncertainty": "Outcome-specific observed counts not reported"},
    ],
)
def test_scope_survives_native_warrant_roundtrip_without_changing_answer(
    tmp_path: Path, scope: dict
) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    _read_required_main_reports(workspace)
    scope = {
        **scope,
        "result_identity": _identity(_state(workspace)["proposal"]["payload"]["results"][0]),
    }
    note = {
        "text": "Source-located observation; scope remains a host interpretation.",
        "sources": [
            {"source_id": evidence["source_id"], "page": 1, "start_line": 1, "end_line": 1}
        ],
        "scope": scope,
    }
    saved = _call(
        workspace,
        "save_working_checkpoint",
        {"checkpoint": {"trial_id": "trial", "observations": [note]}},
    )
    assert saved["outcome"] == "success", saved
    checkpoint = _call(workspace, "get_status", {})["data"]["working_checkpoint"]["checkpoint"]
    note = WorkingNote.model_validate(checkpoint["observations"][0]).model_dump(
        mode="json", exclude_none=True
    )
    draft = _domain_draft("trial", SCIENTIFIC_PACK.domains[0].id, revision, evidence)
    original_answer = draft["answers"][0]["answer"]
    link = {"checkpoint_identity": checkpoint["identity"], "observation": note}
    draft["answers"][0]["bases"][0]["working_observation"] = link
    accepted = _call(workspace, "save_domain_judgment", draft)
    assert accepted["outcome"] == "success", accepted
    record = _state(workspace)["domain_records"]["trial:domain:randomization"]
    assert record["answers"][0]["answer"] == original_answer
    assert record["answers"][0]["bases"][0]["working_observation"] == link
    context = _call(
        workspace,
        "get_domain_context",
        {"trial_id": "trial", "domain_id": SCIENTIFIC_PACK.domains[0].id},
    )
    projected = context["data"]["answers"][0]["bases"][0]["working_observation"]
    assert projected["observation"]["scope"]["relation"] == scope["relation"]
    assert projected["observation"]["scope"]["result_identity"] == scope["result_identity"]
    # Replacement does not erase the canonical warrant's provenance snapshot.
    _call(workspace, "save_working_checkpoint", {"checkpoint": {"trial_id": "trial"}})
    assert _state(workspace)["domain_records"]["trial:domain:randomization"] == record
    if scope["relation"] == "shared_trial_context":
        revision = int(accepted["head"]["state_revision"])
        for domain in SCIENTIFIC_PACK.domains[1:]:
            accepted = _call(
                workspace,
                "save_domain_judgment",
                _domain_draft("trial", domain.id, revision, evidence),
            )
            assert accepted["outcome"] == "success", accepted
            revision = int(accepted["head"]["state_revision"])
        finalized = _finalize_assessment(workspace, revision)
        artifact = workspace / finalized["data"]["artifact"]["path"]
        assert verify_bundle(artifact)
        assert _standalone_verify(artifact).returncode == 0


def test_warrant_cannot_claim_an_unsaved_working_observation(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    _read_required_main_reports(workspace)
    draft = _domain_draft("trial", SCIENTIFIC_PACK.domains[0].id, revision, evidence)
    draft["answers"][0]["bases"][0]["working_observation"] = {
        "checkpoint_identity": "sha256:" + "a" * 64,
        "observation": {
            "text": "Not saved",
            "sources": [
                {"source_id": evidence["source_id"], "page": 1, "start_line": 1, "end_line": 1}
            ],
        },
    }
    response = _call(workspace, "save_domain_judgment", draft)
    assert response["outcome"] == "repair", response
    assert any(item["code"] == "working_observation_link_invalid" for item in response["repairs"])

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from support.rob2 import _assessment_workspace, _call, _domain_draft

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


def test_finalization_auto_freezes_without_assessment_review(tmp_path: Path) -> None:
    workspace, _evidence, revision = _complete_assessment(tmp_path)
    finalized = _call(workspace, "finalize_batch", {"expected_revision": revision})
    assert finalized["outcome"] == "success", finalized
    assert finalized["data"]["artifact"]["identity"]
    state = _state(workspace)
    assert state["review"] is None
    assert state["phase"] == "finalized"
    assert not any(item.get("purpose") == "assessment" for item in state.get("acknowledgments", []))


def test_domain_revision_requires_lineage_and_preserves_history(tmp_path: Path) -> None:
    workspace, evidence, revision = _complete_assessment(tmp_path)
    key = "trial:domain:randomization"
    prior = _state(workspace)["domain_records"][key]

    changed = _domain_draft("trial", SCIENTIFIC_PACK.domains[0].id, revision, evidence)
    changed["answers"][0]["answer"] = "probably_yes"
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

    finalized = _call(
        workspace,
        "finalize_batch",
        {"expected_revision": int(revised["head"]["state_revision"])},
    )
    assert finalized["outcome"] == "success", finalized


def test_domain_continuation_names_only_current_checkpoint(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    domain_id = SCIENTIFIC_PACK.domains[0].id
    initial = _call(
        workspace,
        "get_domain_context",
        {"trial_id": "trial", "domain_id": domain_id},
    )
    assert initial["data"].get("current_checkpoint") is None
    assert "prior_digests" not in initial["data"]
    saved = _call(
        workspace,
        "save_domain_judgment",
        _domain_draft("trial", domain_id, revision, evidence),
    )
    assert saved["outcome"] == "success", saved
    context = _call(
        workspace,
        "get_domain_context",
        {"trial_id": "trial", "domain_id": domain_id},
    )
    checkpoint = saved["data"]["checkpoint"]["identity"]
    assert context["data"]["current_checkpoint"] == checkpoint
    action = context["head"]["next_action"]
    assert action["supersedes"] == checkpoint
    assert action["caller_inputs"] == ["answers", "multiple_concerns", "revision_basis"]


def test_new_evidence_revision_must_use_novel_evidence(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "trial"
    trial.mkdir(parents=True)
    (trial / "novel.txt").write_text(
        "A newly selected complete premise changes the evidence audit.", encoding="utf-8"
    )
    workspace, evidence, revision = _complete_assessment(tmp_path)
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
    assert revised["data"]["checkpoint"]["revision_basis"]["evidence"] == novel["identity"]

    retry = _call(workspace, "save_domain_judgment", changed)
    assert retry["outcome"] == "success"
    assert retry["data"]["retry"] is True

    finalized = _call(
        workspace,
        "finalize_batch",
        {"expected_revision": int(revised["head"]["state_revision"])},
    )
    assert finalized["outcome"] == "success", finalized
    artifact = workspace / finalized["data"]["artifact"]["path"]
    standalone = subprocess.run(
        [sys.executable, "scripts/verify_bundle.py", str(artifact)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert standalone.returncode == 0, standalone.stderr or standalone.stdout


def test_researcher_cli_discard_is_idempotent_and_restartable(tmp_path: Path) -> None:
    workspace, _evidence, revision = _complete_assessment(tmp_path)
    finalized = _call(workspace, "finalize_batch", {"expected_revision": revision})
    artifact = workspace / finalized["data"]["artifact"]["path"]
    assert artifact.is_file()

    command = [
        sys.executable,
        "-m",
        "rob2_kit.interfaces.cli.app",
        "discard",
        "--workspace",
        str(workspace),
    ]
    first = subprocess.run(command, text=True, capture_output=True, check=True)
    receipt = json.loads(first.stdout)
    assert receipt["outcome"] == "success"
    assert receipt["discard"]["artifact"] == finalized["data"]["artifact"]
    assert _state(workspace)["phase"] == "empty"
    assert artifact.is_file()

    retry = subprocess.run(command, text=True, capture_output=True, check=True)
    retry_receipt = json.loads(retry.stdout)
    assert retry_receipt["retry"] is True
    assert retry_receipt["discard"]["identity"] == receipt["discard"]["identity"]

    restarted = _call(
        workspace,
        "prepare_batch",
        {
            "requested_outcome": "requested outcome",
            "expected_revision": int(_state(workspace)["revision"]),
        },
    )
    assert restarted["outcome"] == "success"


def test_discard_is_not_a_public_mcp_tool() -> None:
    from rob2_kit.interfaces.mcp.server import PUBLIC_TOOL_NAMES

    assert "discard" not in PUBLIC_TOOL_NAMES

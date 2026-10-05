"""Reasoned domain adoption is representational, not evidence of scientific accuracy."""

from __future__ import annotations

import copy
import json
import runpy
import zipfile
from pathlib import Path

import pytest
from support.rob2 import (
    _assessment_workspace,
    _call,
    _domain_draft,
    _finalize_assessment,
    _rehashed_full_tamper,
    _standalone_verify,
)

from rob2_kit.application import domains
from rob2_kit.application._state import _state
from rob2_kit.application.domains import _domain_identity
from rob2_kit.application.finalization import verify_bundle
from rob2_kit.logic.adjudication import valid_domain_decision
from rob2_kit.packs import SCIENTIFIC_PACK

_STANDALONE = runpy.run_path("scripts/verify_bundle.py")


def _adjudication(parent: dict, handle: str, judgment: str = "high") -> dict:
    return {
        "result_identity": parent["result_identity"],
        "domain_id": parent["domain_id"],
        "checkpoint_identity": parent["identity"],
        "pack_identity": SCIENTIFIC_PACK.content_hash,
        "judgment": judgment,
        "rationale": (
            "The cited source establishes a material concern inadequately represented "
            "by the default; this synthetic fixture tests representation only."
        ),
        "assessor": "test host assessor",
        "evidence": [handle],
        "counterevidence": [
            {
                "evidence": handle,
                "implication": (
                    "The same passage also contains a limiting fact; "
                    "it does not remove the stated material concern."
                ),
            }
        ],
    }


def test_domain_adjudication_lifecycle_binding_review_export_and_tampering(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    original = _domain_draft("trial", "domain:randomization", revision, evidence)
    saved = _call(workspace, "save_domain_judgment", original)
    assert saved["outcome"] == "success", saved
    parent = copy.deepcopy(_state(workspace)["domain_records"]["trial:domain:randomization"])
    assert parent["judgment"] == parent["decision"]["proposed"] == "some_concerns"
    revision = saved["head"]["state_revision"]
    _call(
        workspace,
        "get_domain_context",
        {"trial_id": "trial", "domain_id": "domain:randomization", "max_response_bytes": 131072},
    )
    draft = {
        **original,
        "expected_revision": revision,
        "supersedes": parent["identity"],
        "revision_basis": {
            "kind": "self_correction",
            "rationale": "Adjudicate material bias while preserving signaling answers.",
        },
        "adjudication": _adjudication(parent, evidence["handle"]),
    }
    for field, value in (
        ("result_identity", "sha256:" + "0" * 64),
        ("domain_id", "domain:selection"),
        ("checkpoint_identity", "sha256:" + "0" * 64),
        ("pack_identity", "sha256:" + "0" * 64),
        ("evidence", ["eh_0000000000000000"]),
        ("judgment", "some_concerns"),
        ("counterevidence", [{"evidence": "eh_0000000000000000", "implication": "foreign"}]),
    ):
        invalid = copy.deepcopy(draft)
        invalid["adjudication"][field] = value
        rejected = _call(workspace, "save_domain_judgment", invalid)
        assert rejected["outcome"] == "repair", rejected
        assert _state(workspace)["revision"] == revision
    changed = copy.deepcopy(draft)
    changed["answers"][0]["unknowns"] = ["New answer premise"]
    assert _call(workspace, "save_domain_judgment", changed)["outcome"] == "repair"
    changed_basis = copy.deepcopy(draft)
    changed_basis["answers"][0]["bases"][0]["kind"] = "context"
    assert _call(workspace, "save_domain_judgment", changed_basis)["outcome"] == "repair"

    adopted = _call(workspace, "save_domain_judgment", draft)
    assert adopted["outcome"] == "success", adopted
    current = _state(workspace)["domain_records"]["trial:domain:randomization"]
    assert current["answers"] == parent["answers"]
    assert current["trace"] == parent["trace"]
    assert current["driver_questions"] == parent["driver_questions"]
    assert current["decision"]["trace_authority"] == "proposed_algorithm"
    assert current["decision"]["proposed"] == "some_concerns"
    assert current["decision"]["adopted"] == current["judgment"] == "high"
    assert adopted["data"]["checkpoint"]["decision"] == current["decision"]
    assert _call(workspace, "save_domain_judgment", draft)["data"]["retry"] is True

    recovered = _call(
        workspace,
        "get_domain_context",
        {"trial_id": "trial", "domain_id": "domain:randomization"},
    )
    assert recovered["outcome"] == "success", recovered
    assert recovered["data"]["decision"] == current["decision"]

    # Complete the other domains with Low defaults so the adopted High alone drives overall.
    revision = adopted["head"]["state_revision"]
    paths = {
        "domain:deviations": {
            "sq:deviations:participants-aware": "no",
            "sq:deviations:personnel-aware": "no",
            "sq:deviations:appropriate-analysis": "yes",
        },
        "domain:missing": {"sq:missing:data-available": "yes"},
        "domain:measurement": {
            "sq:measurement:method-inappropriate": "no",
            "sq:measurement:differential": "no",
            "sq:measurement:assessor-aware": "no",
        },
        "domain:selection": {
            "sq:selection:prespecified-analysis": "yes",
            "sq:selection:multiple-measurements": "no",
            "sq:selection:multiple-analyses": "no",
        },
    }
    for domain_id, answers in paths.items():
        item = _domain_draft("trial", domain_id, revision, evidence)
        item["answers"] = [
            {**answer, "answer": answers[answer["question_id"]]}
            for answer in item["answers"]
            if answer["question_id"] in answers
        ]
        response = _call(workspace, "save_domain_judgment", item)
        assert response["outcome"] == "success", response
        revision = response["head"]["state_revision"]
    foreign = copy.deepcopy(draft)
    foreign_parent = _state(workspace)["domain_records"]["trial:domain:deviations"]["identity"]
    foreign.update(expected_revision=revision, supersedes=foreign_parent)
    foreign["adjudication"]["checkpoint_identity"] = foreign_parent
    assert _call(workspace, "save_domain_judgment", foreign)["outcome"] == "repair"
    snapshot = _state(workspace)["snapshots"]["trial"]
    assert snapshot["overall"] == "high"
    assert snapshot["overall_driver_domains"] == ["domain:randomization"]
    assert snapshot["overall_receipt"]["drivers"][0]["decision"] == current["decision"]
    # Diagnostic counterfactuals recompute defaults; they cannot inherit the adjudication.
    assert any(
        item["hypothetical_domain_judgment"] == "some_concerns"
        for item in snapshot["overall_receipt"]["alternatives"]
        if item["domain_id"] == "domain:randomization"
    )
    reviewed = _call(
        workspace, "review_trial", {"trial_id": "trial", "expected_revision": revision}
    )
    assert reviewed["outcome"] == "success", reviewed
    findings = reviewed["data"]["domain_findings"]
    assert findings[0]["decision"] == current["decision"]
    finalized = _finalize_assessment(workspace, reviewed["head"]["state_revision"])
    artifact = workspace / finalized["data"]["artifact"]["path"]
    assert verify_bundle(artifact)
    assert _standalone_verify(artifact).returncode == 0
    with zipfile.ZipFile(artifact) as archive:
        canonical = json.loads(archive.read("canonical.json"))
    exported = canonical["domain_records"]["trial:domain:randomization"]
    assert exported["decision"] == current["decision"]
    assert (
        finalized["data"]["assessment_summary"]["trial"]["domain_decisions"]["domain:randomization"]
        == current["decision"]
    )
    history = {
        item["identity"]: item
        for items in canonical["domain_history_records"].values()
        for item in items
    }
    catalog = canonical["proposal"]["evidence"]
    assert valid_domain_decision(
        exported, "some_concerns", history, catalog, SCIENTIFIC_PACK.content_hash
    )
    assert _STANDALONE["_valid_domain_decision"](
        exported, "some_concerns", history, catalog, SCIENTIFIC_PACK.content_hash
    )

    # Rehash the checkpoint itself: semantic rejection must not depend on its original digest.
    for field, value in (
        ("pack_identity", "sha256:" + "0" * 64),
        ("rationale", " "),
        ("checkpoint_identity", "sha256:" + "0" * 64),
        ("evidence", ["sha256:" + "0" * 64]),
    ):
        invalid = copy.deepcopy(exported)
        invalid["decision"]["adjudication"][field] = value
        invalid["identity"] = _domain_identity(invalid)
        assert not valid_domain_decision(
            invalid, "some_concerns", history, catalog, SCIENTIFIC_PACK.content_hash
        )
        assert not _STANDALONE["_valid_domain_decision"](
            invalid, "some_concerns", history, catalog, SCIENTIFIC_PACK.content_hash
        )
    for index, mutation in enumerate(
        (
            lambda value: value["domain_records"]["trial:domain:randomization"]["decision"].update(
                {"adopted": "low"}
            ),
            lambda value: value["domain_records"]["trial:domain:randomization"].pop("decision"),
            lambda value: value["legacy_domain_checkpoints"].update(
                {"identities": [exported["identity"]]}
            ),
        )
    ):
        target = tmp_path / f"adjudication-tamper-{index}.rob2.zip"
        _rehashed_full_tamper(artifact, target, mutation)
        assert not verify_bundle(target)
        assert _standalone_verify(target).returncode == 1


def test_answer_revision_drops_adjudication_and_rejects_stale_parent(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    initial = _domain_draft("trial", "domain:randomization", revision, evidence)
    saved = _call(workspace, "save_domain_judgment", initial)
    parent = copy.deepcopy(_state(workspace)["domain_records"]["trial:domain:randomization"])
    _call(
        workspace, "get_domain_context", {"trial_id": "trial", "domain_id": "domain:randomization"}
    )
    override = {
        **initial,
        "expected_revision": saved["head"]["state_revision"],
        "supersedes": parent["identity"],
        "revision_basis": {"kind": "self_correction", "rationale": "Reassess material bias."},
        "adjudication": _adjudication(parent, evidence["handle"], "low"),
    }
    override["adjudication"]["rationale"] = "A source-bound material-bias explanation. " * 2000
    adopted = _call(workspace, "save_domain_judgment", override)
    assert adopted["outcome"] == "success", adopted
    current = _state(workspace)["domain_records"]["trial:domain:randomization"]
    assert current["judgment"] == "low"
    context = _call(
        workspace,
        "get_domain_context",
        {"trial_id": "trial", "domain_id": "domain:randomization", "max_response_bytes": 131072},
    )
    assert context["outcome"] == "success", context
    assert context["data"]["decision"] == current["decision"]
    revision = adopted["head"]["state_revision"]
    for domain in SCIENTIFIC_PACK.domains[1:]:
        saved_domain = _call(
            workspace, "save_domain_judgment", _domain_draft("trial", domain.id, revision, evidence)
        )
        assert saved_domain["outcome"] == "success", saved_domain
        revision = saved_domain["head"]["state_revision"]
    reviewed = _call(
        workspace, "review_trial", {"trial_id": "trial", "expected_revision": revision}
    )
    assert reviewed["outcome"] == "success", reviewed
    assert "domain_adjudication" in reviewed["data"]["review_page"]["deferred_fields"]
    detail = _call(
        workspace,
        "review_trial",
        {
            "trial_id": "trial",
            "expected_revision": reviewed["head"]["state_revision"],
            "domain_id": "domain:randomization",
        },
    )
    fragments = []
    while True:
        page = detail["data"]["review_page"]
        fragments.append(page["fragment"])
        if page["next_cursor"] is None:
            break
        detail = _call(
            workspace,
            "review_trial",
            {
                "trial_id": "trial",
                "expected_revision": reviewed["head"]["state_revision"],
                "cursor": page["next_cursor"],
            },
        )
    reconstructed = json.loads("".join(fragments))
    assert (
        reconstructed["decision"]["adjudication"]["rationale"]
        == override["adjudication"]["rationale"]
    )
    old_review = _state(workspace)["trial_reviews"]["trial"]["identity"]
    revised = copy.deepcopy(initial)
    revised.update(
        expected_revision=reviewed["head"]["state_revision"],
        supersedes=current["identity"],
        revision_basis={
            "kind": "self_correction",
            "rationale": "A new interpretation changes the answer snapshot.",
        },
    )
    revised["answers"][0]["answer"] = "probably_yes"
    changed = _call(workspace, "save_domain_judgment", revised)
    assert changed["outcome"] == "success", changed
    latest = _state(workspace)["domain_records"]["trial:domain:randomization"]
    assert "trial" not in _state(workspace)["trial_reviews"]
    stale_closure = _call(
        workspace,
        "close_trial",
        {
            "trial_id": "trial",
            "expected_revision": changed["head"]["state_revision"],
            "review_reference": old_review,
        },
    )
    assert stale_closure["outcome"] == "condition", stale_closure
    assert latest["decision"]["adjudication"] is None
    assert latest["decision"]["authority"] == "algorithm"
    assert latest["judgment"] == latest["decision"]["proposed"] == "some_concerns"
    override["expected_revision"] = changed["head"]["state_revision"]
    stale = _call(workspace, "save_domain_judgment", override)
    assert stale["outcome"] == "condition", stale
    assert _state(workspace)["domain_records"]["trial:domain:randomization"] == latest


def test_identical_unmarked_checkpoint_retry_preserves_historical_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    draft = _domain_draft("trial", "domain:randomization", revision, evidence)
    original_identity = domains._domain_identity

    def legacy_identity(record: dict) -> str:
        record.pop("decision", None)
        return original_identity(record)

    # Create an authentic unmarked fixture through the ledger, not a rewritten
    # real artifact. Restore the current writer before the identical retry.
    with monkeypatch.context() as context:
        context.setattr(domains, "_domain_identity", legacy_identity)
        saved = _call(workspace, "save_domain_judgment", draft)
    assert saved["outcome"] == "success", saved
    before = copy.deepcopy(_state(workspace))
    assert "decision" not in before["domain_records"]["trial:domain:randomization"]
    retried = _call(workspace, "save_domain_judgment", draft)
    assert retried["outcome"] == "success", retried
    assert retried["data"]["retry"] is True
    assert _state(workspace) == before


def test_prior_pack_adjudication_workspace_fails_explicitly_without_history_rewrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from rob2_kit.application import finalization

    workspace, evidence, revision = _assessment_workspace(tmp_path)
    draft = _domain_draft("trial", "domain:randomization", revision, evidence)
    saved = _call(workspace, "save_domain_judgment", draft)
    parent = _state(workspace)["domain_records"]["trial:domain:randomization"]
    _call(workspace, "get_domain_context", {"domain_id": "domain:randomization"})
    draft.update(
        expected_revision=saved["head"]["state_revision"],
        supersedes=parent["identity"],
        revision_basis={"kind": "self_correction", "rationale": "Source-bound host adoption"},
        adjudication=_adjudication(parent, evidence["handle"]),
    )
    adopted = _call(workspace, "save_domain_judgment", draft)
    assert adopted["outcome"] == "success", adopted
    before = _state(workspace)
    # Simulate installing a later pack, not editing a historical checkpoint.
    later = SimpleNamespace(content_hash="sha256:" + "f" * 64)
    monkeypatch.setattr(domains, "SCIENTIFIC_PACK", later)
    monkeypatch.setattr(finalization, "SCIENTIFIC_PACK", later)
    for operation in (
        lambda: domains.get_domain_context(workspace, domain_id="domain:randomization"),
        lambda: domains.save_domain_judgment(workspace, draft),
        lambda: finalization.finalize_batch(workspace, before["revision"]),
    ):
        with pytest.raises(ValueError, match="adjudication_pack_migration_unsupported"):
            operation()
        assert _state(workspace) == before

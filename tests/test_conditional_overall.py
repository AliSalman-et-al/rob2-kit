"""Cochrane proposal, result-specific host escalation and independent replay."""

import runpy
from copy import deepcopy
from itertools import product
from pathlib import Path

import pytest
from pydantic import ValidationError
from support.rob2 import _assessment_workspace, _call, _domain_draft, _standalone_verify
from test_finalization_bundle_integrity import _rewrite_rehashed

from rob2_kit.application._state import _identity, _state
from rob2_kit.application.finalization import verify_bundle
from rob2_kit.logic.aggregation import aggregation_record, snapshot_evaluation
from rob2_kit.logic.evaluator import evaluate_overall
from rob2_kit.packs import SCIENTIFIC_PACK
from rob2_kit.workflow_models import CumulativeConcernsAssessment

_STANDALONE = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/verify_bundle.py"))
_DOMAINS = tuple(domain.id for domain in SCIENTIFIC_PACK.domains)
_ID = "sha256:" + "1" * 64
_OTHER = "sha256:" + "2" * 64


def _snapshot(values: tuple[str, ...]) -> dict:
    return {
        "result_identity": _ID,
        "checkpoints": [_ID] * 5,
        "domain_judgments": dict(zip(_DOMAINS, values, strict=True)),
    }


def _assessment(snapshot: dict, conclusion: str = "substantially_lowers_confidence"):
    return CumulativeConcernsAssessment.model_validate(
        {
            "result_identity": snapshot["result_identity"],
            "checkpoints": snapshot["checkpoints"],
            "conclusion": conclusion,
            "rationale": "The combined concerns materially compromise this result.",
        }
    )


def test_all_243_proposals_and_independent_replay():
    for values in product(("low", "some_concerns", "high"), repeat=5):
        expected = (
            "high" if "high" in values else "some_concerns" if "some_concerns" in values else "low"
        )
        snapshot = _snapshot(values)
        record, result = aggregation_record(snapshot)
        snapshot["aggregation"] = record
        assert result.judgment.value == expected
        assert record["proposed"] == record["adopted"] == expected
        assert record["assessment_status"] == "omitted"
        assert snapshot_evaluation(snapshot) == result
        assert _STANDALONE["_snapshot_evaluation"](snapshot) == (
            expected,
            result.trace[0],
            list(result.driver_domains),
        )


def test_all_26_multiple_concern_vectors_and_three_host_conclusions():
    count = 0
    for values in product(("low", "some_concerns"), repeat=5):
        if values.count("some_concerns") < 2:
            continue
        count += 1
        snapshot = _snapshot(values)
        assert snapshot_evaluation(snapshot).judgment.value == "high"
        assert _STANDALONE["_snapshot_evaluation"](snapshot)[0] == "high"
        for conclusion in ("substantially_lowers_confidence", "no_escalation", "unresolved"):
            record, result = aggregation_record(snapshot, _assessment(snapshot, conclusion))
            snapshot["aggregation"] = record
            assert result.judgment.value == (
                "high" if conclusion == "substantially_lowers_confidence" else "some_concerns"
            )
            assert record["proposed"] == "some_concerns"
            assert record["authority"] == "host"
            assert record["assessment_status"] == conclusion
            assert snapshot_evaluation(snapshot) == result
            assert _STANDALONE["_snapshot_evaluation"](snapshot)[0] == result.judgment.value
    assert count == 26


@pytest.mark.parametrize("values", [("low",) * 5, ("high",) * 5, ("some_concerns",) + ("low",) * 4])
def test_host_assessment_cannot_override_low_high_or_single_concern(values):
    snapshot = _snapshot(values)
    with pytest.raises(ValueError):
        aggregation_record(snapshot, _assessment(snapshot))


def test_invalid_inputs_and_stale_basis_fail():
    snapshot = _snapshot(("some_concerns",) * 5)
    for change in ({"rationale": "  "}, {"conclusion": "count_policy"}, {"policy": "legacy"}):
        with pytest.raises(ValidationError):
            CumulativeConcernsAssessment.model_validate(
                {**_assessment(snapshot).model_dump(), **change}
            )
    for key, value in (("result_identity", _OTHER), ("checkpoints", [_OTHER] * 5)):
        stale = CumulativeConcernsAssessment.model_validate(
            {**_assessment(snapshot).model_dump(), key: value}
        )
        with pytest.raises(ValueError):
            aggregation_record(snapshot, stale)
    for judgments in ({}, {**snapshot["domain_judgments"], _DOMAINS[0]: "invalid"}):
        with pytest.raises(ValueError):
            evaluate_overall(judgments)
    record, _ = aggregation_record(snapshot, _assessment(snapshot))
    snapshot["aggregation"] = record
    null_marker = {**snapshot, "aggregation": None}
    with pytest.raises(ValueError):
        snapshot_evaluation(null_marker)
    with pytest.raises(ValueError):
        _STANDALONE["_snapshot_evaluation"](null_marker)
    for key, value in (
        ("contract", "count_policy"),
        ("authority", "algorithm"),
        ("proposed", "high"),
    ):
        tampered = deepcopy(snapshot)
        tampered["aggregation"][key] = value
        with pytest.raises(ValueError):
            snapshot_evaluation(tampered)
        with pytest.raises(ValueError):
            _STANDALONE["_snapshot_evaluation"](tampered)


def _multiple_concerns_workspace(tmp_path):
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    low = {
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
    }
    for domain in SCIENTIFIC_PACK.domains:
        draft = _domain_draft("trial", domain.id, revision, evidence)
        if domain.id in low:
            template = draft["answers"][0]
            draft["answers"] = [
                {**template, "question_id": q, "answer": a} for q, a in low[domain.id].items()
            ]
        saved = _call(workspace, "save_domain_judgment", draft)
        assert saved["outcome"] == "success", saved
        revision = saved["head"]["state_revision"]
    return workspace, evidence, revision


def test_optional_review_escalation_changes_identity_and_invalidates_old_review(tmp_path):
    workspace, evidence, revision = _multiple_concerns_workspace(tmp_path)
    before = deepcopy(_state(workspace)["snapshots"]["trial"])
    assert before["overall"] == "some_concerns"
    first = _call(workspace, "review_trial", {"trial_id": "trial", "expected_revision": revision})
    assert first["outcome"] == "success", first
    revision = first["head"]["state_revision"]
    old_reference = first["data"]["review"]["identity"]
    for conclusion in ("unresolved", "no_escalation", "substantially_lowers_confidence"):
        reviewed = _call(
            workspace,
            "review_trial",
            {
                "trial_id": "trial",
                "expected_revision": revision,
                "cumulative_concerns": _assessment(before, conclusion).model_dump(mode="json"),
            },
        )
        assert reviewed["outcome"] == "success", reviewed
        revision = reviewed["head"]["state_revision"]
        assert reviewed["data"]["review"]["aggregation"]["assessment_status"] == conclusion
    retry = _call(
        workspace,
        "review_trial",
        {
            "trial_id": "trial",
            "expected_revision": revision - 1,
            "cumulative_concerns": _assessment(before).model_dump(mode="json"),
        },
    )
    assert retry["outcome"] == "success", retry
    assert retry["data"]["retry"] is True
    assert retry["head"]["state_revision"] == revision
    state = _state(workspace)
    current = state["snapshots"]["trial"]
    assert current["overall"] == "high"
    assert current["identity"] != before["identity"]
    assert state["snapshot_history_records"]["trial"][0] == before
    assert len(state["snapshot_history_records"]["trial"]) == 4
    stale = _call(
        workspace,
        "close_trial",
        {"trial_id": "trial", "expected_revision": revision, "review_reference": old_reference},
    )
    assert stale["outcome"] == "condition"
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
        workspace, "finalize_batch", {"expected_revision": closed["head"]["state_revision"]}
    )
    assert finalized["outcome"] == "success", finalized
    artifact = workspace / finalized["data"]["artifact"]["path"]
    assert verify_bundle(artifact)
    assert _standalone_verify(artifact).returncode == 0

    # Diagnostics use a new proposal, never a host conclusion bound to other checkpoints.
    for alternative in current["overall_receipt"]["alternatives"]:
        if alternative["status"] != "evaluated":
            continue
        judgments = {
            **current["domain_judgments"],
            alternative["domain_id"]: alternative["hypothetical_domain_judgment"],
        }
        assert alternative["hypothetical_overall"] == evaluate_overall(judgments).judgment.value

    def corrupt(canonical, kind):
        snapshot = canonical["snapshots"]["trial"]
        old_identity = snapshot["identity"]
        if kind == "delete_marker":
            snapshot.pop("aggregation")
        elif kind == "policy":
            snapshot["aggregation"]["contract"] = "rob2-kit.overall.count-policy.v1"
        elif kind == "rationale":
            snapshot["aggregation"]["assessment"]["rationale"] = " "
        elif kind == "basis":
            snapshot["aggregation"]["assessment"]["result_identity"] = _OTHER
        elif kind == "descriptor":
            canonical["scientific_pack"].pop("aggregation_contract")
        else:
            canonical["legacy_aggregation_snapshots"] = [old_identity]
        snapshot["identity"] = _identity({k: v for k, v in snapshot.items() if k != "identity"})
        canonical["snapshot_history"]["trial"][-1] = snapshot["identity"]
        canonical["snapshot_history_records"]["trial"][-1] = deepcopy(snapshot)
        review = canonical["trial_reviews"]["trial"]
        review["snapshot_identity"] = snapshot["identity"]
        if "aggregation" in snapshot:
            review["aggregation"] = snapshot["aggregation"]
        else:
            review.pop("aggregation", None)
        review["identity"] = _identity({k: v for k, v in review.items() if k != "identity"})
        closure = canonical["trial_closures"]["trial"]
        closure["review_identity"] = review["identity"]
        closure["identity"] = _identity({k: v for k, v in closure.items() if k != "identity"})

    for kind in ("delete_marker", "policy", "rationale", "basis", "descriptor", "legacy_ledger"):
        tampered = tmp_path / f"{kind}.rob2.zip"
        _rewrite_rehashed(artifact, tampered, lambda c, kind=kind: corrupt(c, kind))
        assert not verify_bundle(tampered), kind
        assert _standalone_verify(tampered).returncode != 0, kind


def test_domain_revision_drops_bound_cumulative_assessment(tmp_path):
    workspace, evidence, revision = _multiple_concerns_workspace(tmp_path)
    before = deepcopy(_state(workspace)["snapshots"]["trial"])
    reviewed = _call(
        workspace,
        "review_trial",
        {
            "trial_id": "trial",
            "expected_revision": revision,
            "cumulative_concerns": _assessment(before).model_dump(mode="json"),
        },
    )
    assert reviewed["outcome"] == "success", reviewed
    state = _state(workspace)
    adopted = deepcopy(state["snapshots"]["trial"])
    revision = reviewed["head"]["state_revision"]
    domain_id = "domain:randomization"
    _call(workspace, "get_domain_context", {"trial_id": "trial", "domain_id": domain_id})
    correction = _domain_draft("trial", domain_id, revision, evidence)
    correction["supersedes"] = state["domain_records"][f"trial:{domain_id}"]["identity"]
    correction["revision_basis"] = {
        "kind": "self_correction",
        "rationale": "Reconsider the supporting rationale.",
    }
    correction["answers"][0]["justification"] = "Revised rationale for the same scientific answer."
    saved = _call(workspace, "save_domain_judgment", correction)
    assert saved["outcome"] == "success", saved
    state = _state(workspace)
    assert state["snapshots"]["trial"]["overall"] == "some_concerns"
    assert state["snapshots"]["trial"]["aggregation"]["assessment_status"] == "omitted"
    assert state["snapshot_history_records"]["trial"][-2] == adopted
    assert "trial" not in state["trial_reviews"]
    stale = _call(
        workspace,
        "review_trial",
        {
            "trial_id": "trial",
            "expected_revision": saved["head"]["state_revision"],
            "cumulative_concerns": _assessment(before).model_dump(mode="json"),
        },
    )
    assert stale["outcome"] == "condition"

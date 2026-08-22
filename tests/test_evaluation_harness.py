from pathlib import Path

import pytest

from rob2_kit.evaluation.harness import (
    EXPECTED_RESOURCES,
    EXPECTED_TOOLS,
    AttemptLedger,
    IsolatedRun,
    ZeroSourceAttestation,
    verify_run_matrix,
)


def _run(outcome: str) -> IsolatedRun:
    return IsolatedRun.create(
        outcome,
        ("sha256:source",),
        {"candidate": "a"},
        restart_dossier={
            "preflight.json": "sha256:preflight",
            "intake_plan.json": "sha256:plan",
            "captured_batch.json": "sha256:captured",
            "proposal_review.json": "sha256:proposal",
        },
        proposal_review="sha256:proposal",
        review_authority_required="researcher",
        transition="sha256:transition",
        continuation="approve_batch",
    )


def test_zero_source_attestation_and_restart_identity_are_strict():
    attestation = ZeroSourceAttestation(
        wheel_hash="sha256:" + "a" * 64,
        mcp_identity="rob2-nonce",
        tool_names=EXPECTED_TOOLS,
        resource_uris=EXPECTED_RESOURCES,
        skill_names=("rob2-workflow", "rob2-signalling"),
        state_empty=True,
        observed_model="Claude Haiku",
    )
    assert not attestation.verify()
    run = _run("pfs")
    reference = run.restart_reference()
    assert not run.verify_restart(reference)
    reference["mcp_identity"] = "other"
    assert run.verify_restart(reference) == (
        "restart mcp_identity does not rehydrate the exact run",
    )


def test_attempt_lock_only_allows_documented_pre_behaviour_interruption(tmp_path: Path):
    ledger = AttemptLedger(tmp_path / "attempts.json")
    first = ledger.start("pfs")
    ledger.record_external_interruption(first, before_behavior=True)
    ledger.start("pfs")
    with pytest.raises(ValueError, match="one clean attempt"):
        ledger.start("pfs")
    later = AttemptLedger(tmp_path / "later.json")
    attempt = later.start("pfs")
    with pytest.raises(ValueError, match="after behavior"):
        later.record_external_interruption(attempt, before_behavior=False)
    with pytest.raises(ValueError, match="one clean attempt"):
        later.start("pfs")


def test_restart_reference_binds_the_review_dossier():
    run = _run("pfs")
    reference = run.restart_reference()
    assert not run.verify_restart(reference)
    reference["continuation"] = "save_proposal"
    assert run.verify_restart(reference) == (
        "restart continuation does not rehydrate the exact run",
    )


def test_matrix_requires_unique_identities_and_equal_source_hashes():
    runs = tuple(
        _run(outcome)
        for outcome in ("pfs", "overall_survival", "adverse_events")
    )
    assert not verify_run_matrix(runs)
    duplicate = (runs[0], runs[0], runs[2])
    assert any("unique workspace_id" in failure for failure in verify_run_matrix(duplicate))

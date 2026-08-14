from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_judgments import approved_workspace

from rob2_kit.batch_summary import (
    ArtifactReceipt,
    BatchCondition,
    BatchSaved,
    Problem,
    finalize_batch,
    terminalize_problem,
)
from rob2_kit.storage import transaction

NOW = datetime(2026, 8, 14, tzinfo=UTC)
HASH = "sha256:" + "a" * 64


def test_artifact_receipt_requires_canonical_relative_path_and_hashes() -> None:
    valid_path = ".rob2-kit/batches/" + "a" * 64

    def receipt(path: str = valid_path, bundle_hash: str = HASH) -> ArtifactReceipt:
        return ArtifactReceipt(
            bundle_path=path,
            bundle_hash=bundle_hash,
            file_count=1,
            summary_hash=HASH,
            index_hash=HASH,
        )

    assert receipt().bundle_path == valid_path
    for path in (".", "a//b", "a/./b", "a/", "C:foo", "/a", "../a", "a\\b"):
        with pytest.raises(ValueError):
            receipt(path=path)
    for value in ("", "sha256:" + "A" * 64, "sha256:abc", "a" * 64):
        with pytest.raises(ValueError):
            receipt(bundle_hash=value)


def test_problem_terminal_and_batch_summary_are_atomic_and_idempotent(tmp_path: Path) -> None:
    workspace, _ = approved_workspace(tmp_path)
    assert isinstance(finalize_batch(workspace, "actor", NOW), BatchCondition)
    problem = Problem(
        code="missing",
        category="needs_input",
        detail="need source",
        trial_id="t",
        result_id="r",
        actor="actor",
        observed_at=NOW,
    )
    saved = terminalize_problem(workspace, "t", "needs_input", (problem,))
    assert saved.status == "saved"
    summary = finalize_batch(workspace, "actor", NOW)
    assert isinstance(summary, BatchSaved)
    assert summary.summary.counts.model_dump() == {
        "assessed": 0,
        "needs_input": 1,
        "failed": 0,
    }
    retry = finalize_batch(workspace, "actor", NOW)
    assert isinstance(retry, BatchSaved)
    assert retry.summary.summary_hash == summary.summary.summary_hash


def test_tampered_problem_terminal_is_never_summarized(tmp_path: Path) -> None:
    workspace, _ = approved_workspace(tmp_path)
    terminalize_problem(
        workspace,
        "t",
        "failed",
        (
            Problem(
                code="bad",
                category="failed",
                detail="bad",
                trial_id="t",
                result_id="r",
                actor="actor",
                observed_at=NOW,
            ),
        ),
    )
    with transaction(workspace) as connection:
        row = connection.execute(
            "SELECT name,payload FROM records WHERE name LIKE 'terminal_trial:%'"
        ).fetchone()
        assert row is not None
        connection.execute(
            "UPDATE records SET payload=? WHERE name=?",
            (bytes(row[1]).replace(b'"detail":"bad"', b'"detail":"evil"'), row[0]),
        )
    with pytest.raises(ValueError, match="invalid Trial terminal"):
        finalize_batch(workspace, "actor", NOW)

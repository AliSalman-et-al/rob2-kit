import hashlib
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_judgments import approved_workspace

from rob2_kit.batch_summary import Problem, finalize_batch, terminalize_problem
from rob2_kit.reports import _bundle_hash, batch_artifact_receipt, export_batch
from rob2_kit.storage import transaction


def test_problem_only_batch_index_is_stable_and_escaped(tmp_path: Path) -> None:
    workspace, _ = approved_workspace(tmp_path)
    now = datetime(2026, 8, 14, tzinfo=UTC)
    terminalize_problem(
        workspace,
        "t",
        "failed",
        (
            Problem(
                code="source",
                category="failed",
                detail="<unsafe>",
                trial_id="t",
                result_id="r",
                actor="a",
                observed_at=now,
            ),
        ),
    )
    summary = finalize_batch(workspace, "a", now).summary
    first = export_batch(workspace, summary.approved_batch_hash)
    contents = {
        item.relative_to(first): item.read_bytes() for item in first.rglob("*") if item.is_file()
    }
    second = export_batch(workspace, summary.approved_batch_hash)
    assert contents == {
        item.relative_to(second): item.read_bytes() for item in second.rglob("*") if item.is_file()
    }
    assert b"&lt;unsafe&gt;" in contents[Path("index.html")]
    assert contents[Path("batch-summary.json")]


def test_batch_export_rejects_tampered_committed_summary(tmp_path: Path) -> None:
    workspace, _ = approved_workspace(tmp_path)
    now = datetime(2026, 8, 14, tzinfo=UTC)
    terminalize_problem(
        workspace,
        "t",
        "failed",
        (
            Problem(
                code="source",
                category="failed",
                detail="x",
                trial_id="t",
                result_id="r",
                actor="a",
                observed_at=now,
            ),
        ),
    )
    summary = finalize_batch(workspace, "a", now).summary
    with transaction(workspace) as connection:
        connection.execute(
            "UPDATE records SET payload=replace(payload,?,?) WHERE name=?",
            (b'"detail":"x"', b'"detail":"evil"', f"batch_summary:{summary.approved_batch_hash}"),
        )
    with pytest.raises(ValueError, match="integrity"):
        export_batch(workspace, summary.approved_batch_hash)


def test_batch_artifact_receipt_fails_closed_for_tamper_or_escaped_path(tmp_path: Path) -> None:
    workspace, _ = approved_workspace(tmp_path)
    now = datetime(2026, 8, 14, tzinfo=UTC)
    terminalize_problem(
        workspace,
        "t",
        "failed",
        (
            Problem(
                code="source",
                category="failed",
                detail="x",
                trial_id="t",
                result_id="r",
                actor="a",
                observed_at=now,
            ),
        ),
    )
    summary = finalize_batch(workspace, "a", now).summary
    target = export_batch(workspace, summary.approved_batch_hash)
    assert batch_artifact_receipt(workspace, target, summary).file_count == 2

    index = target / "index.html"
    original = index.read_bytes()
    index.write_bytes(original + b"tampered")
    with pytest.raises(ValueError, match="cannot be verified"):
        batch_artifact_receipt(workspace, target, summary)
    index.write_bytes(original)
    redirected = target / "redirect"
    try:
        redirected.symlink_to(index)
    except OSError:
        pytest.skip("symlink creation is unavailable on this Windows runner")
    with pytest.raises(ValueError, match="cannot be verified"):
        batch_artifact_receipt(workspace, target, summary)
    with pytest.raises(ValueError, match="escapes workspace"):
        batch_artifact_receipt(workspace, tmp_path.parent, summary)


def test_bundle_hash_sorts_mixed_case_posix_names(tmp_path: Path) -> None:
    upper, lower = tmp_path / "Z", tmp_path / "a"
    upper.write_bytes(b"upper")
    lower.write_bytes(b"lower")
    expected = hashlib.sha256(b"Z\0upper\0a\0lower\0").hexdigest()
    assert (
        _bundle_hash([("a", lower.read_bytes()), ("Z", upper.read_bytes())]) == f"sha256:{expected}"
    )


def test_batch_artifact_receipt_rejects_windows_junction(tmp_path: Path) -> None:
    if os.name != "nt":
        pytest.skip("junctions are unavailable on this platform")
    workspace, _ = approved_workspace(tmp_path)
    now = datetime(2026, 8, 14, tzinfo=UTC)
    terminalize_problem(
        workspace,
        "t",
        "failed",
        (
            Problem(
                code="source",
                category="failed",
                detail="x",
                trial_id="t",
                result_id="r",
                actor="a",
                observed_at=now,
            ),
        ),
    )
    summary = finalize_batch(workspace, "a", now).summary
    target = export_batch(workspace, summary.approved_batch_hash)
    outside = tmp_path / "outside"
    outside.mkdir()
    junction = target / "redirect"
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
        capture_output=True,
        check=False,
    )
    if created.returncode:
        pytest.skip("junction creation is unavailable on this Windows runner")
    with pytest.raises(ValueError, match="cannot be verified"):
        batch_artifact_receipt(workspace, target, summary)

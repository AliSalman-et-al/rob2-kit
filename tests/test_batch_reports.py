from datetime import UTC, datetime
from pathlib import Path

from test_judgments import approved_workspace

from rob2_kit.batch_summary import Problem, finalize_batch, terminalize_problem
from rob2_kit.reports import export_batch
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
    import pytest

    with pytest.raises(ValueError, match="integrity"):
        export_batch(workspace, summary.approved_batch_hash)

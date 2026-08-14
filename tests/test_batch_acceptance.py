import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pymupdf
import pytest
from test_judgments import _save

from rob2_kit.assessment import (
    Arm,
    BatchRequest,
    Comparison,
    OutcomeTarget,
    Proposal,
    Randomization,
    ResultAnchor,
    ResultSpec,
    Trial,
)
from rob2_kit.batch import approve_batch, save_proposal
from rob2_kit.batch_summary import (
    BatchCondition,
    BatchSaved,
    Problem,
    TerminalConflict,
    finalize_batch,
)
from rob2_kit.finish import FinishConflict, finish_trial
from rob2_kit.ingestion import ingest_batch
from rob2_kit.packs import SCIENTIFIC_PACK
from rob2_kit.reports import batch_artifact_receipt, export_batch
from rob2_kit.server import (
    FailedFinishRequest,
    NeedsInputFinishRequest,
    finish_trial_request,
)
from rob2_kit.sources import Source, SourceInput, SourceRole, TrialInput
from rob2_kit.storage import transaction

NOW = datetime(2026, 8, 14, tzinfo=UTC)


def _three_trial_workspace(tmp_path: Path) -> tuple[Path, tuple[Source, ...]]:
    inputs = []
    for trial_id, marker in (("A", "marker-A"), ("B", "marker-B"), ("C", "marker-C")):
        document = pymupdf.open()
        document.new_page().insert_text((72, 72), f"random concealed balanced {marker}")
        document.save(tmp_path / f"{trial_id}.pdf")
        document.close()
        inputs.append(
            TrialInput(
                id=trial_id,
                label=f"Trial {trial_id}",
                sources=(
                    SourceInput(
                        role=SourceRole.MAIN_ARTICLE,
                        path=f"{trial_id}.pdf",
                        label=f"Main {trial_id}",
                    ),
                ),
            )
        )
    ingested = ingest_batch(tmp_path, tuple(inputs))
    sources = tuple(item.sources[0] for item in ingested.trials)
    trials = tuple(Trial(id=item.id, label=item.label) for item in inputs)
    specs = tuple(
        ResultSpec(
            id=f"result-{trial.id}",
            trial=trial,
            randomization=Randomization(id=f"random-{trial.id}", description="Random"),
            arms=(Arm(id="a", label="A"), Arm(id="b", label="B")),
            comparison=Comparison(intervention_arm_id="a", comparator_arm_id="b"),
            effect_of_interest="assignment",
            outcome_definition="outcome",
            measurement="measure",
            time_point="time",
            population="all",
            analysis_method="method",
            analysis_choices=("choice",),
            effect_measure="RR",
            anchor=ResultAnchor(
                source_id=source.id,
                source_sha256=source.sha256,
                page_number=1,
                start=26,
                end=34,
                quote=f"marker-{trial.id}",
            ),
        )
        for trial, source in zip(trials, sources, strict=True)
    )
    proposal = Proposal(
        request=BatchRequest(
            outcome_target=OutcomeTarget(id="outcome", label="Outcome", description="Description"),
            trial_inputs=tuple(inputs),
        ),
        trials=trials,
        result_specs=specs,
        sources=sources,
    )
    assert save_proposal(tmp_path, proposal).state.status == "proposal"
    assert approve_batch(tmp_path).state.status == "approved"
    return tmp_path, sources


def _problem(trial_id: str, category: Literal["needs_input", "failed"]) -> Problem:
    return Problem(
        code=f"code-{trial_id}",
        category=category,
        detail=f"detail-{trial_id}",
        trial_id=trial_id,
        result_id=f"result-{trial_id}",
        actor="terminal",
        observed_at=NOW,
    )


def test_three_trial_terminal_summary_and_internal_export_acceptance(tmp_path: Path) -> None:
    workspace, sources = _three_trial_workspace(tmp_path)
    for domain in SCIENTIFIC_PACK.domains:
        _save(workspace, sources[0], domain.id, trial_id="A", result_id="result-A")
    assert finish_trial(workspace, "A", None, None, None, (), "finisher", NOW).status == "saved"
    b = finish_trial_request(
        str(workspace),
        NeedsInputFinishRequest(
            mode="needs_input",
            trial_id="B",
            problems=(_problem("B", "needs_input"),),
            actor="terminal",
            observed_at=NOW,
        ),
    )
    assert b.status == "saved"
    incomplete = finalize_batch(workspace, "finalizer", NOW)
    assert isinstance(incomplete, BatchCondition)
    assert incomplete.code == "trials_incomplete" and incomplete.detail == "C"
    c = finish_trial_request(
        str(workspace),
        FailedFinishRequest(
            mode="failed",
            trial_id="C",
            problems=(_problem("C", "failed"),),
            actor="terminal",
            observed_at=NOW,
        ),
    )
    assert c.status == "saved"
    summary_result = finalize_batch(workspace, "finalizer", NOW)
    assert isinstance(summary_result, BatchSaved)
    summary = summary_result.summary
    assert [entry.trial.id for entry in summary.entries] == ["A", "B", "C"]
    assert summary.counts.model_dump() == {"assessed": 1, "needs_input": 1, "failed": 1}
    assert summary.entries[1].problems == (_problem("B", "needs_input"),)
    assert summary.entries[2].problems == (_problem("C", "failed"),)
    with transaction(workspace) as connection:
        snapshots = connection.execute(
            "SELECT name,payload FROM records WHERE name LIKE 'assessment_snapshot:%'"
        ).fetchall()
    assert len(snapshots) == 1 and ":A" in snapshots[0][0]
    assert sources[0].id.encode() in bytes(snapshots[0][1])
    assert sources[1].id.encode() not in bytes(snapshots[0][1])
    assert sources[2].id.encode() not in bytes(snapshots[0][1])
    assert isinstance(
        finish_trial_request(
            str(workspace),
            FailedFinishRequest(
                mode="failed",
                trial_id="A",
                problems=(_problem("A", "failed"),),
                actor="terminal",
                observed_at=NOW,
            ),
        ),
        TerminalConflict,
    )
    assessment_conflict = finish_trial(workspace, "B", None, None, None, (), "finisher", NOW)
    assert isinstance(assessment_conflict, FinishConflict) and assessment_conflict.snapshot is None
    bundle = export_batch(workspace, summary.approved_batch_hash)
    assert (bundle / "trials" / "A" / "assessment.json").is_file()
    assert (bundle / "trials" / "A" / "report.html").is_file()
    assert (bundle / "trials" / "A" / "sources").is_dir()
    assert not (bundle / "trials" / "B").exists() and not (bundle / "trials" / "C").exists()
    index = (bundle / "index.html").read_text(encoding="utf-8")
    assert 'href="trials/A/report.html"' in index and "needs_input" in index and "failed" in index
    a_bytes = b"".join(
        item.read_bytes() for item in (bundle / "trials" / "A").rglob("*") if item.is_file()
    )
    assert b"marker-B" not in a_bytes and b"marker-C" not in a_bytes
    first = {
        item.relative_to(bundle): item.read_bytes() for item in bundle.rglob("*") if item.is_file()
    }
    restarted = export_batch(workspace, summary.approved_batch_hash)
    assert first == {
        item.relative_to(restarted): item.read_bytes()
        for item in restarted.rglob("*")
        if item.is_file()
    }


def test_public_finalize_materializes_a_deterministic_artifact_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The public finalizer, not a separate export call, completes handoff."""
    import rob2_kit.server as server

    workspace, sources = _three_trial_workspace(tmp_path)
    for domain in SCIENTIFIC_PACK.domains:
        _save(workspace, sources[0], domain.id, trial_id="A", result_id="result-A")
    assert finish_trial(workspace, "A", None, None, None, (), "finisher", NOW).status == "saved"
    for trial_id, category in (("B", "needs_input"), ("C", "failed")):
        result = finish_trial_request(
            str(workspace),
            NeedsInputFinishRequest(
                mode="needs_input",
                trial_id=trial_id,
                problems=(_problem(trial_id, category),),
                actor="terminal",
                observed_at=NOW,
            )
            if category == "needs_input"
            else FailedFinishRequest(
                mode="failed",
                trial_id=trial_id,
                problems=(_problem(trial_id, category),),
                actor="terminal",
                observed_at=NOW,
            ),
        )
        assert result.status == "saved"
    monkeypatch.setenv("ROB2_WORKSPACE", str(workspace))

    first = server.finalize_one_batch("finalizer", NOW)
    assert first.status == "saved"
    assert first.receipt.bundle_path.startswith(".rob2-kit/batches/")
    assert not Path(first.receipt.bundle_path).is_absolute()
    target = workspace / first.receipt.bundle_path
    assert (target / "batch-summary.json").is_file()
    assert (target / "trials" / "A" / "assessment.json").is_file()
    assert first.receipt.file_count == len([item for item in target.rglob("*") if item.is_file()])
    assert first.receipt.summary_hash == first.summary.summary_hash
    assert first.receipt.index_hash

    second = server.finalize_one_batch("finalizer", NOW)
    assert second == first
    report = target / "trials" / "A" / "report.html"
    report.write_bytes(report.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="cannot be verified"):
        batch_artifact_receipt(workspace, target, first.summary)


def test_public_finalize_recovers_export_after_summary_is_committed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import rob2_kit.server as server

    workspace, _sources = _three_trial_workspace(tmp_path)
    for trial_id in ("A", "B", "C"):
        assert (
            finish_trial_request(
                str(workspace),
                NeedsInputFinishRequest(
                    mode="needs_input",
                    trial_id=trial_id,
                    problems=(_problem(trial_id, "needs_input"),),
                    actor="terminal",
                    observed_at=NOW,
                ),
            ).status
            == "saved"
        )
    monkeypatch.setenv("ROB2_WORKSPACE", str(workspace))
    original_export = server.export_batch

    def fail_after_commit(*_args, **_kwargs):
        raise OSError("injected export failure")

    monkeypatch.setattr(server, "export_batch", fail_after_commit)
    with pytest.raises(OSError, match="injected export failure"):
        server.finalize_one_batch("finalizer", NOW)
    assert isinstance(finalize_batch(workspace, "finalizer", NOW), BatchSaved)

    monkeypatch.setattr(server, "export_batch", original_export)
    recovered = server.finalize_one_batch("finalizer", NOW)
    assert recovered.status == "saved"
    assert (workspace / recovered.receipt.bundle_path / "batch-summary.json").is_file()


def test_batch_export_promotion_failure_restores_previous_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, sources = _three_trial_workspace(tmp_path)
    for domain in SCIENTIFIC_PACK.domains:
        _save(workspace, sources[0], domain.id, trial_id="A", result_id="result-A")
    assert finish_trial(workspace, "A", None, None, None, (), "finisher", NOW).status == "saved"
    assert (
        finish_trial_request(
            str(workspace),
            NeedsInputFinishRequest(
                mode="needs_input",
                trial_id="B",
                problems=(_problem("B", "needs_input"),),
                actor="terminal",
                observed_at=NOW,
            ),
        ).status
        == "saved"
    )
    assert (
        finish_trial_request(
            str(workspace),
            FailedFinishRequest(
                mode="failed",
                trial_id="C",
                problems=(_problem("C", "failed"),),
                actor="terminal",
                observed_at=NOW,
            ),
        ).status
        == "saved"
    )
    summary = finalize_batch(workspace, "finalizer", NOW).summary
    target = export_batch(workspace, summary.approved_batch_hash)
    original = {
        item.relative_to(target): item.read_bytes() for item in target.rglob("*") if item.is_file()
    }
    with transaction(workspace) as connection:
        row = connection.execute(
            "SELECT payload FROM records WHERE name=?",
            (f"batch_summary:{summary.approved_batch_hash}",),
        ).fetchone()
    assert row is not None
    summary_bytes = bytes(row[0])
    replace = Path.replace

    def interrupted(path: Path, destination: Path) -> Path:
        if (
            path.parent == target.parent
            and path.name.startswith(f".{target.name}-stage-")
            and destination == target
        ):
            raise OSError("injected promotion failure")
        return replace(path, destination)

    monkeypatch.setattr(Path, "replace", interrupted)
    with pytest.raises(OSError, match="injected promotion failure"):
        export_batch(workspace, summary.approved_batch_hash)
    assert original == {
        item.relative_to(target): item.read_bytes() for item in target.rglob("*") if item.is_file()
    }
    assert not list(target.parent.glob(f".{target.name}-stage-*"))
    assert not (target.parent / f".{target.name}-backup").exists()
    with transaction(workspace) as connection:
        unchanged = connection.execute(
            "SELECT payload FROM records WHERE name=?",
            (f"batch_summary:{summary.approved_batch_hash}",),
        ).fetchone()
    assert unchanged is not None and bytes(unchanged[0]) == summary_bytes
    monkeypatch.undo()
    assert original == {
        item.relative_to(export_batch(workspace, summary.approved_batch_hash)): item.read_bytes()
        for item in target.rglob("*")
        if item.is_file()
    }
    backup = target.parent / f".{target.name}-backup"
    shutil.copytree(target, backup)
    assert export_batch(workspace, summary.approved_batch_hash) == target
    assert not backup.exists()

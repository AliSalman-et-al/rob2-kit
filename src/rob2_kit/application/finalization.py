"""Finalization of the new application Batch and portable verification bundle."""
# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from rob2_kit.reports import application_finalization_report
from rob2_kit.storage import read_only_transaction, workspace_mutation_lock

from ._state import identity, read_json, record_uri, write_jsons
from .contracts import (
    AuthoritativePresentation,
    Continuation,
    RecordKind,
    RecordReference,
    TrialDisposition,
)


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FinalizationCounts(_Closed):
    total: int = Field(ge=0)
    pending: int = Field(ge=0)
    assessed: int = Field(ge=0)
    needs_input: int = Field(ge=0)
    failed: int = Field(ge=0)


class FinalizedTrial(_Closed):
    trial_id: str
    disposition: TrialDisposition
    outcome: RecordReference
    snapshot: RecordReference | None = None


class FinalizationSummary(_Closed):
    # The portable bundle verifier's canonical summary record uses this stable wire kind.
    kind: Literal["finalization"] = "finalization"
    identity: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    approved_batch: RecordReference
    counts: FinalizationCounts
    trials: tuple[FinalizedTrial, ...]
    presentation: AuthoritativePresentation
    observed_at: datetime


class FinalizationArtifact(_Closed):
    bundle_path: str
    bundle_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    manifest_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    file_count: int = Field(ge=1)
    summary_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class FinalizationResult(_Closed):
    outcome: Literal["success"] = "success"
    summary: RecordReference
    counts: FinalizationCounts
    presentation: AuthoritativePresentation
    artifact: FinalizationArtifact
    next_action: Literal["complete"] = "complete"


class FinalizationCondition(_Closed):
    outcome: Literal["condition"] = "condition"
    code: str
    detail: str
    next_action: Continuation | None = None


def presentation_for_counts(counts: FinalizationCounts) -> AuthoritativePresentation:
    assessed = counts.assessed
    assessed_word = "assessment" if assessed == 1 else "assessments"
    trial_word = "Trial" if assessed == 1 else "Trials"
    if assessed == counts.total and assessed > 0:
        return AuthoritativePresentation(
            code="finalized_all_assessed",
            headline=f"{assessed} RoB 2 {assessed_word} completed",
            summary=f"Batch finalized. RoB 2 {assessed_word} completed for {assessed} {trial_word}.",
        )
    if assessed == 0:
        facts: list[str] = []
        if counts.needs_input:
            word = "Trial needs" if counts.needs_input == 1 else "Trials need"
            facts.append(f"{counts.needs_input} {word} researcher input.")
        if counts.failed:
            word = "Trial failed" if counts.failed == 1 else "Trials failed"
            facts.append(f"{counts.failed} {word}.")
        suffix = " " + " ".join(facts) if facts else ""
        return AuthoritativePresentation(
            code="finalized_zero_assessed",
            headline="Batch finalized",
            summary=f"Batch finalized. No RoB 2 assessments were completed.{suffix}",
        )
    return AuthoritativePresentation(
        code="finalized_mixed",
        headline=f"{assessed} RoB 2 {assessed_word} completed",
        summary=(
            f"Batch finalized. RoB 2 {assessed_word} completed for {assessed} {trial_word}; "
            f"{counts.needs_input} {'Trial needs' if counts.needs_input == 1 else 'Trials need'} "
            f"researcher input and {counts.failed} {'Trial failed' if counts.failed == 1 else 'Trials failed'}."
        ),
    )


def _bundle_hash(files: list[tuple[str, bytes]]) -> str:
    digest = hashlib.sha256()
    for path, data in sorted(files):
        digest.update(path.encode())
        digest.update(b"\0")
        digest.update(data)
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def _regular_files(root: Path) -> list[tuple[str, bytes]]:
    files: list[tuple[str, bytes]] = []
    for path in root.rglob("*"):
        if path.is_symlink() or (not path.is_file() and not path.is_dir()):
            raise ValueError("finalization artifact contains a redirected or special entry")
        if path.is_file():
            files.append((path.relative_to(root).as_posix(), path.read_bytes()))
    return files


def _copy_app_records(workspace: Path, target: Path, names: list[str]) -> None:
    with read_only_transaction(workspace) as connection:
        if connection is None:
            raise ValueError("application ledger is unavailable")
        rows = connection.execute(
            "SELECT name,payload FROM records WHERE name LIKE 'application:%'"
        ).fetchall()
    parsed_rows: list[tuple[str, bytes, dict[str, object]]] = []
    active_checkpoint_ids: set[str] = set()
    for name, payload in rows:
        try:
            parsed = json.loads(bytes(payload).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("application ledger record is corrupt") from None
        if not isinstance(parsed, dict):
            raise ValueError("application ledger record is corrupt")
        logical = str(name).removeprefix("application:")
        if logical.startswith("domain-observation-") and isinstance(parsed.get("identity"), str):
            active_checkpoint_ids.add(parsed["identity"])
        parsed_rows.append((logical, bytes(payload), parsed))

    identities: set[str] = set()
    for logical, payload, parsed in parsed_rows:
        record_identity = parsed.get("identity")
        if logical.startswith("domain-candidate-") and record_identity in active_checkpoint_ids:
            continue
        if isinstance(record_identity, str):
            if record_identity in identities:
                continue
            identities.add(record_identity)
        destination = target / "records" / logical
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(bytes(payload))


def _materialize_bundle(workspace: Path, summary: FinalizationSummary) -> FinalizationArtifact:
    root = workspace.resolve(strict=True)
    parent = root / ".rob2-kit" / "finalized"
    parent.mkdir(parents=True, exist_ok=True)
    if parent.is_symlink():
        raise ValueError("finalization output directory is redirected")
    name = summary.approved_batch.identity.removeprefix("sha256:")
    target = parent / name
    if target.exists() and not target.is_dir():
        raise ValueError("finalization artifact target is invalid")
    if target.is_dir():
        existing = _verify_bundle(target, summary)
        if existing is not None:
            return existing
        raise ValueError("existing finalization artifact cannot be verified")
    stage = parent / f".{name}-stage"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir()
    (stage / "summary.json").write_text(summary.model_dump_json(), encoding="utf-8")
    captured = read_json(workspace, "captured_batch.json")
    captured_identity = None if captured is None else captured.get("identity")
    if not isinstance(captured, dict) or not isinstance(captured_identity, str):
        raise ValueError("captured Batch is unavailable")
    captured_dir = root / ".rob2-kit" / "sources-v3" / captured_identity.removeprefix("sha256:")
    sources = captured.get("sources", [])
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("captured source record is corrupt")
        trial = str(source["trial_id"])
        candidate = str(source["candidate_identity"])
        source_path = captured_dir / trial / candidate
        if source_path.is_symlink() or not source_path.is_file():
            raise ValueError("captured Source bytes are unavailable")
        if "sha256:" + hashlib.sha256(source_path.read_bytes()).hexdigest() != source.get("sha256"):
            raise ValueError("captured Source bytes are corrupt")
        destination = stage / "sources" / trial / candidate
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, destination)
    _copy_app_records(
        workspace, stage, ["approved_batch.json", "state.json", "captured_batch.json"]
    )
    report_records: list[dict[str, object]] = []
    for record_path in (stage / "records").rglob("*.json"):
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("application bundle record is corrupt") from error
        if not isinstance(record, dict):
            raise ValueError("application bundle record is corrupt")
        report_records.append(record)
    (stage / "report.html").write_text(
        application_finalization_report(summary.model_dump(mode="json"), report_records),
        encoding="utf-8",
    )
    render_root = root / ".rob2-kit" / "renders"
    if render_root.exists():
        for render in render_root.iterdir():
            if render.is_symlink() or not render.is_file():
                raise ValueError("render artifact is redirected or special")
            destination = stage / "renders" / render.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(render, destination)
    files = _regular_files(stage)
    file_rows = [
        {"path": path, "sha256": "sha256:" + hashlib.sha256(data).hexdigest()}
        for path, data in files
    ]
    manifest_base = {"summary_hash": summary.identity, "files": file_rows}
    manifest_hash = identity(manifest_base)
    (stage / "manifest.json").write_text(
        json.dumps(
            {**manifest_base, "manifest_hash": manifest_hash}, sort_keys=True, separators=(",", ":")
        ),
        encoding="utf-8",
    )
    final_files = _regular_files(stage)
    bundle_hash = _bundle_hash(final_files)
    stage.replace(target)
    return FinalizationArtifact(
        bundle_path=target.relative_to(root).as_posix(),
        bundle_hash=bundle_hash,
        manifest_hash=manifest_hash,
        file_count=len(final_files),
        summary_hash=summary.identity,
    )


def _verify_bundle(target: Path, summary: FinalizationSummary) -> FinalizationArtifact | None:
    try:
        raw_summary = json.loads((target / "summary.json").read_text(encoding="utf-8"))
        parsed_summary = FinalizationSummary.model_validate(raw_summary)
        summary_payload = {
            "approved_batch": parsed_summary.approved_batch.model_dump(mode="json"),
            "counts": parsed_summary.counts.model_dump(mode="json"),
            "trials": [item.model_dump(mode="json") for item in parsed_summary.trials],
            "presentation": parsed_summary.presentation.model_dump(mode="json"),
        }
        if (
            parsed_summary.identity != summary.identity
            or identity(summary_payload) != parsed_summary.identity
        ):
            return None
        manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
        base = {"summary_hash": manifest["summary_hash"], "files": manifest["files"]}
        if (
            identity(base) != manifest["manifest_hash"]
            or manifest["summary_hash"] != summary.identity
        ):
            return None
        for row in manifest["files"]:
            data = (target / row["path"]).read_bytes()
            if "sha256:" + hashlib.sha256(data).hexdigest() != row["sha256"]:
                return None
        files = _regular_files(target)
        expected_paths = {str(row["path"]) for row in manifest["files"]} | {"manifest.json"}
        if {path for path, _data in files} != expected_paths:
            return None
        return FinalizationArtifact(
            bundle_path=target.as_posix(),
            bundle_hash=_bundle_hash(files),
            manifest_hash=manifest["manifest_hash"],
            file_count=len(files),
            summary_hash=summary.identity,
        )
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def finalize_batch(workspace: str | Path) -> FinalizationResult | FinalizationCondition:
    with workspace_mutation_lock(workspace):
        state = read_json(workspace, "state.json") or {}
        approved_identity = state.get("approved_batch_identity")
        if not isinstance(approved_identity, str):
            return FinalizationCondition(
                code="batch_not_approved",
                detail="finalization did not occur: an approved Batch is required",
            )
        approved = RecordReference(
            kind=RecordKind.APPROVED_BATCH,
            identity=approved_identity,
            uri=record_uri("approved_batch", approved_identity),
        )
        dispositions_raw = state.get("trial_dispositions", {})
        if not isinstance(dispositions_raw, dict):
            return FinalizationCondition(
                code="trial_state_corrupt",
                detail="finalization did not occur: Trial dispositions are corrupt",
            )
        rows = tuple(
            sorted(
                (str(trial), TrialDisposition(value)) for trial, value in dispositions_raw.items()
            )
        )
        counts = FinalizationCounts(
            total=len(rows),
            pending=sum(value is TrialDisposition.PENDING for _, value in rows),
            assessed=sum(value is TrialDisposition.ASSESSED for _, value in rows),
            needs_input=sum(value is TrialDisposition.NEEDS_INPUT for _, value in rows),
            failed=sum(value is TrialDisposition.FAILED for _, value in rows),
        )
        if counts.total == 0 or counts.pending:
            pending = ",".join(trial for trial, value in rows if value is TrialDisposition.PENDING)
            return FinalizationCondition(
                code="trials_incomplete",
                detail=f"finalization did not occur: pending Trials {pending or 'none'}",
            )
        existing_identity = state.get("finalization_identity")
        if isinstance(existing_identity, str):
            raw = read_json(
                workspace, f"finalization-{existing_identity.removeprefix('sha256:')}.json"
            )
            if raw is None:
                return FinalizationCondition(
                    code="finalization_corrupt",
                    detail="finalization did not occur: saved receipt is corrupt",
                )
            try:
                saved = FinalizationResult.model_validate(raw)
            except ValueError:
                return FinalizationCondition(
                    code="finalization_corrupt",
                    detail="finalization did not occur: saved receipt is corrupt",
                )
            if verify_finalization_result(workspace, saved) is None:
                return FinalizationCondition(
                    code="finalization_corrupt",
                    detail="finalization did not occur: saved artifact failed verification",
                )
            return saved
        final_trials: list[FinalizedTrial] = []
        for trial_id, disposition in rows:
            raw_outcome = read_json(workspace, f"trial-outcome-{trial_id}.json")
            if raw_outcome is None or raw_outcome.get("disposition") != disposition.value:
                return FinalizationCondition(
                    code="terminal_unavailable",
                    detail=f"finalization did not occur: terminal outcome for Trial {trial_id} is unavailable",
                )
            outcome_identity = str(raw_outcome.get("identity"))
            outcome_ref = RecordReference(
                kind=RecordKind.TRIAL_OUTCOME,
                identity=outcome_identity,
                uri=record_uri("trial_terminal", outcome_identity),
            )
            snapshot_ref = None
            if disposition is TrialDisposition.ASSESSED:
                snapshot = raw_outcome.get("snapshot")
                if not isinstance(snapshot, dict):
                    return FinalizationCondition(
                        code="assessment_snapshot_unavailable",
                        detail=f"finalization did not occur: verified AssessmentSnapshot for Trial {trial_id} is unavailable",
                    )
                snapshot_ref = RecordReference.model_validate(snapshot)
                if (
                    read_json(
                        workspace,
                        f"assessment-snapshot-{snapshot_ref.identity.removeprefix('sha256:')}.json",
                    )
                    is None
                ):
                    return FinalizationCondition(
                        code="assessment_snapshot_unavailable",
                        detail=f"finalization did not occur: verified AssessmentSnapshot for Trial {trial_id} is unavailable",
                    )
            final_trials.append(
                FinalizedTrial(
                    trial_id=trial_id,
                    disposition=disposition,
                    outcome=outcome_ref,
                    snapshot=snapshot_ref,
                )
            )
        presentation = presentation_for_counts(counts)
        observed = datetime.now(UTC)
        summary_payload = {
            "approved_batch": approved.model_dump(mode="json"),
            "counts": counts.model_dump(mode="json"),
            "trials": [item.model_dump(mode="json") for item in final_trials],
            "presentation": presentation.model_dump(mode="json"),
        }
        summary_identity = identity(summary_payload)
        summary = FinalizationSummary(
            identity=summary_identity,
            approved_batch=approved,
            counts=counts,
            trials=tuple(final_trials),
            presentation=presentation,
            observed_at=observed,
        )
        # This receipt deliberately precedes bundle materialization: its identity
        # binds the finalized scientific state, not the self-referential manifest.
        write_jsons(
            workspace,
            {
                "finalization-receipt.json": {
                    "kind": "finalization_receipt",
                    "identity": identity({"summary": summary_identity, "outcome": "committed"}),
                    "summary": summary_identity,
                    "outcome": "committed",
                }
            },
        )
        artifact = _materialize_bundle(Path(workspace), summary)
        summary_ref = RecordReference(
            kind=RecordKind.FINALIZATION,
            identity=summary_identity,
            uri=record_uri("batch_summary", summary_identity),
        )
        result = FinalizationResult(
            summary=summary_ref, counts=counts, presentation=presentation, artifact=artifact
        )
        write_jsons(
            workspace,
            {
                f"finalization-{summary_identity.removeprefix('sha256:')}.json": result.model_dump(
                    mode="json"
                ),
                "finalization-summary.json": summary.model_dump(mode="json"),
                "state.json": {
                    **state,
                    "phase": "finalized",
                    "finalization_identity": summary_identity,
                },
            },
        )
        if verify_finalization_result(workspace, result) is None:
            return FinalizationCondition(
                code="finalization_postflight_failed",
                detail="finalization did not occur: produced artifact failed verification",
            )
        return result


def verify_finalization(workspace: str | Path, artifact: FinalizationArtifact) -> bool:
    root = Path(workspace).resolve(strict=True)
    target = root / artifact.bundle_path
    if target.is_symlink() or not target.is_dir():
        return False
    summary_raw = read_json(workspace, "finalization-summary.json")
    if summary_raw is None:
        return False
    summary = FinalizationSummary.model_validate(summary_raw)
    state = read_json(workspace, "state.json")
    if (
        state is None
        or state.get("phase") != "finalized"
        or state.get("approved_batch_identity") != summary.approved_batch.identity
    ):
        return False
    for trial in summary.trials:
        outcome = read_json(workspace, f"trial-outcome-{trial.trial_id}.json")
        if (
            outcome is None
            or outcome.get("identity") != trial.outcome.identity
            or outcome.get("disposition") != trial.disposition.value
        ):
            return False
        if trial.snapshot is not None:
            snapshot = read_json(
                workspace,
                f"assessment-snapshot-{trial.snapshot.identity.removeprefix('sha256:')}.json",
            )
            if snapshot is None or snapshot.get("identity") != trial.snapshot.identity:
                return False
    verified = _verify_bundle(target, summary)
    return (
        verified is not None
        and verified.bundle_hash == artifact.bundle_hash
        and verified.manifest_hash == artifact.manifest_hash
    )


def verify_finalization_result(
    workspace: str | Path, saved: FinalizationResult
) -> FinalizationResult | None:
    """Rebuild a finalization receipt from the verified ledger and bundle."""
    try:
        root = Path(workspace).resolve(strict=True)
        final_root = root / ".rob2-kit" / "finalized"
        relative = Path(saved.artifact.bundle_path)
        target = (root / relative).resolve(strict=True)
        if (
            relative.is_absolute()
            or final_root.is_symlink()
            or not target.is_relative_to(final_root.resolve(strict=True))
            or target.is_symlink()
        ):
            return None
        raw_summary = read_json(workspace, "finalization-summary.json")
        if raw_summary is None:
            return None
        summary = FinalizationSummary.model_validate(raw_summary)
        summary_payload = {
            "approved_batch": summary.approved_batch.model_dump(mode="json"),
            "counts": summary.counts.model_dump(mode="json"),
            "trials": [item.model_dump(mode="json") for item in summary.trials],
            "presentation": summary.presentation.model_dump(mode="json"),
        }
        if identity(summary_payload) != summary.identity:
            return None
        counts = FinalizationCounts(
            total=len(summary.trials),
            pending=sum(item.disposition is TrialDisposition.PENDING for item in summary.trials),
            assessed=sum(item.disposition is TrialDisposition.ASSESSED for item in summary.trials),
            needs_input=sum(
                item.disposition is TrialDisposition.NEEDS_INPUT for item in summary.trials
            ),
            failed=sum(item.disposition is TrialDisposition.FAILED for item in summary.trials),
        )
        if (
            counts != summary.counts
            or counts.pending
            or summary.presentation != presentation_for_counts(counts)
        ):
            return None
        verified = _verify_bundle(target, summary)
        if verified is None:
            return None
        artifact = FinalizationArtifact(
            bundle_path=relative.as_posix(),
            bundle_hash=verified.bundle_hash,
            manifest_hash=verified.manifest_hash,
            file_count=verified.file_count,
            summary_hash=verified.summary_hash,
        )
        trusted = FinalizationResult(
            summary=RecordReference(
                kind=RecordKind.FINALIZATION,
                identity=summary.identity,
                uri=record_uri("batch_summary", summary.identity),
            ),
            counts=counts,
            presentation=summary.presentation,
            artifact=artifact,
        )
        state = read_json(workspace, "state.json")
        if (
            state is None
            or state.get("phase") != "finalized"
            or state.get("finalization_identity") != summary.identity
            or state.get("trial_dispositions")
            != {item.trial_id: item.disposition.value for item in summary.trials}
            or saved != trusted
            or not verify_finalization(workspace, artifact)
        ):
            return None
        return trusted
    except (OSError, ValueError, TypeError):
        return None

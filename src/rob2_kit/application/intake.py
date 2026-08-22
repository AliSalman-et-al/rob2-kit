"""Immutable Intake plans, review authority, and exact atomic capture."""
# ruff: noqa: E501

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rob2_kit.sources import SourceRole
from rob2_kit.storage import workspace_mutation_lock

from ._state import delete_json, identity, read_json, record_uri, write_jsons
from .acknowledgments import verify_acknowledgment
from .contracts import (
    CaptureBatchContinuation,
    Continuation,
    OperationOutcome,
    PreflightSourcesContinuation,
    RecordKind,
    RecordReference,
    ReviewAcknowledgmentReference,
    ReviewAuthority,
    SaveProposalContinuation,
)
from .preflight import (
    AuthorizedSourceRoot,
    CandidateSource,
    PreflightRequest,
    SourcePreflight,
    preflight_sources,
    verify_source_preflight,
)


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceDisposition(StrEnum):
    INCLUDE = "include"
    OMIT = "omit"


class SourceCriticality(StrEnum):
    REQUIRED = "required"
    EXPECTED = "expected"
    OPTIONAL = "optional"


class IntakePlanEntry(_Closed):
    candidate_identity: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    role: SourceRole
    disposition: SourceDisposition
    criticality: SourceCriticality
    omission_reason: str | None = None

    @model_validator(mode="after")
    def omission_is_explained(self) -> IntakePlanEntry:
        if self.disposition is SourceDisposition.OMIT and not self.omission_reason:
            raise ValueError("omitted candidates require an omission reason")
        if self.disposition is SourceDisposition.INCLUDE and self.omission_reason is not None:
            raise ValueError("included candidates cannot have an omission reason")
        return self


class IntakePlan(_Closed):
    kind: Literal["intake_plan"] = "intake_plan"
    identity: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    preflight: RecordReference
    entries: tuple[IntakePlanEntry, ...] = Field(min_length=1)
    blockers: tuple[str, ...] = ()
    conditions: tuple[str, ...] = ()

    @property
    def reference(self) -> RecordReference:
        return RecordReference(
            kind=RecordKind.INTAKE_PLAN,
            identity=self.identity,
            uri=record_uri("intake_plan", self.identity),
        )


def _plan_payload(plan: IntakePlan) -> dict[str, object]:
    return {
        "preflight": plan.preflight.model_dump(mode="json"),
        "entries": [item.model_dump(mode="json") for item in plan.entries],
        "blockers": list(plan.blockers),
        "conditions": list(plan.conditions),
    }


def verify_intake_plan(raw: object) -> IntakePlan:
    """Validate the closed stored shape and its content-addressed identity."""
    if not isinstance(raw, dict) or set(raw) != {
        "kind",
        "identity",
        "preflight",
        "entries",
        "blockers",
        "conditions",
    }:
        raise ValueError("stored Intake plan has an invalid shape")
    plan = IntakePlan.model_validate(raw)
    if identity(_plan_payload(plan)) != plan.identity:
        raise ValueError("stored Intake plan identity mismatch")
    return plan


class IntakePlanReceipt(_Closed):
    outcome: OperationOutcome
    plan: RecordReference
    blockers: tuple[str, ...] = ()
    conditions: tuple[str, ...] = ()
    acknowledgment: ReviewAcknowledgmentReference | None = None
    next_action: Continuation | None = None


class CaptureRequest(_Closed):
    plan: RecordReference
    acknowledgment: ReviewAcknowledgmentReference


class CaptureReceipt(_Closed):
    outcome: OperationOutcome
    captured_batch: RecordReference | None = None
    plan: RecordReference
    acknowledgment: ReviewAcknowledgmentReference
    conditions: tuple[str, ...] = ()
    next_action: Continuation | None = None


def intake_required_authority(plan: IntakePlan) -> ReviewAuthority:
    return ReviewAuthority.RESEARCHER if plan.conditions else ReviewAuthority.HOST


def _preflight_record(workspace: str | Path) -> SourcePreflight:
    raw = read_json(workspace, "preflight.json")
    if raw is None:
        raise ValueError("source preflight does not exist")
    return verify_source_preflight(raw)


def _entry_candidates(preflight: SourcePreflight) -> dict[str, CandidateSource]:
    return {item.identity: item for item in preflight.candidates}


def save_intake_plan(
    workspace: str | Path,
    preflight: RecordReference,
    entries: tuple[IntakePlanEntry, ...],
    *,
    host_caller: str | None = None,
) -> IntakePlanReceipt:
    current = _preflight_record(workspace)
    if preflight.kind is not RecordKind.SOURCE_PREFLIGHT or preflight.identity != current.identity:
        raise ValueError("plan must reference the current source preflight")
    candidates = _entry_candidates(current)
    provided = {entry.candidate_identity for entry in entries}
    blockers: list[str] = []
    if provided != set(candidates):
        missing = sorted(set(candidates) - provided)
        extra = sorted(provided - set(candidates))
        blockers.extend([f"undecided_candidate:{item}" for item in missing])
        blockers.extend([f"unknown_candidate:{item}" for item in extra])
    if len(provided) != len(entries):
        blockers.append("duplicate_candidate_decision")
    for entry in entries:
        candidate = candidates.get(entry.candidate_identity)
        if candidate is None:
            continue
        if candidate.condition and entry.disposition is SourceDisposition.INCLUDE:
            blockers.append(f"unreadable_inclusion:{candidate.relative_path}")
    included = [entry for entry in entries if entry.disposition is SourceDisposition.INCLUDE]
    main_count = sum(entry.role is SourceRole.MAIN_ARTICLE for entry in included)
    if main_count != 1:
        blockers.append("main_article_cardinality")
    for entry in entries:
        if (
            entry.disposition is SourceDisposition.OMIT
            and entry.criticality is SourceCriticality.REQUIRED
        ):
            blockers.append(f"required_omission:{entry.candidate_identity}")
    conditions = sorted(set(current.conditions))
    for entry in entries:
        if (
            entry.disposition is SourceDisposition.OMIT
            and entry.criticality is not SourceCriticality.REQUIRED
        ):
            conditions.append(f"omission:{entry.candidate_identity}")
    ordered_entries = tuple(sorted(entries, key=lambda item: item.candidate_identity))
    payload = {
        "preflight": preflight.model_dump(mode="json"),
        "entries": [item.model_dump(mode="json") for item in ordered_entries],
        "blockers": sorted(set(blockers)),
        "conditions": sorted(set(conditions)),
    }
    plan = IntakePlan(
        identity=identity(payload),
        preflight=preflight,
        entries=ordered_entries,
        blockers=tuple(sorted(set(blockers))),
        conditions=tuple(sorted(set(conditions))),
    )
    state = read_json(workspace, "state.json") or {}
    acknowledgment: ReviewAcknowledgmentReference | None = None
    records = {"intake_plan.json": plan.model_dump(mode="json")}
    state.update(
        {
            "phase": "intake",
            "plan_identity": plan.identity,
            "review_authority": "none",
            "review_satisfied": False,
        }
    )
    if not plan.blockers and not plan.conditions and host_caller is not None:
        caller = host_caller.strip()
        if not caller.startswith("host:"):
            raise ValueError("host caller attribution is required")
        observed_at = datetime.now(UTC).isoformat()
        ack_payload = {
            "record": plan.reference.model_dump(mode="json"),
            "authority": ReviewAuthority.HOST.value,
            "purpose": "intake",
            "caller": caller,
            "observed_at": observed_at,
        }
        ack_identity = identity(ack_payload)
        acknowledgment = ReviewAcknowledgmentReference(
            kind="review_ack", identity=ack_identity, uri=record_uri("review_ack", ack_identity)
        )
        records["review_ack.json"] = {**acknowledgment.model_dump(mode="json"), **ack_payload}
        state.update(
            {"review_authority": "host", "review_satisfied": True, "ack_identity": ack_identity}
        )
    records["state.json"] = state
    write_jsons(
        workspace,
        records,
    )
    return IntakePlanReceipt(
        outcome=OperationOutcome.CONDITION if plan.blockers else OperationOutcome.SUCCESS,
        plan=plan.reference,
        blockers=plan.blockers,
        conditions=plan.conditions,
        acknowledgment=acknowledgment,
        next_action=(
            CaptureBatchContinuation(plan=plan.reference, acknowledgment=acknowledgment)
            if acknowledgment is not None
            else None
        ),
    )


def acknowledge_intake(
    workspace: str | Path,
    plan: RecordReference,
    authority: ReviewAuthority,
    *,
    caller: str = "host:internal",
    observed_at: datetime | None = None,
) -> ReviewAcknowledgmentReference:
    raw = read_json(workspace, "intake_plan.json")
    if raw is None:
        raise ValueError("intake plan does not exist")
    current = verify_intake_plan(raw)
    if plan.kind is not RecordKind.INTAKE_PLAN or plan.identity != current.identity:
        raise ValueError("acknowledgment does not identify the current Intake plan")
    if current.blockers:
        raise ValueError("blocking Intake defects cannot be acknowledged")
    required = intake_required_authority(current)
    if authority is not required:
        raise PermissionError("researcher acknowledgment is required")
    if authority not in {ReviewAuthority.HOST, ReviewAuthority.RESEARCHER}:
        raise PermissionError("a caller acknowledgment is required")
    caller = caller.strip()
    if not caller:
        raise ValueError("caller attribution is required")
    if authority is ReviewAuthority.RESEARCHER and not caller.startswith(("cli:", "server:")):
        raise PermissionError("researcher authority must come from an interactive adapter")
    if authority is ReviewAuthority.HOST and not caller.startswith("host:"):
        raise PermissionError("host authority must come from a host adapter")
    observation = observed_at or datetime.now(UTC)
    if observation.tzinfo is None or observation.utcoffset() is None:
        raise ValueError("observation time must be timezone-aware")
    observation = observation.astimezone(UTC)
    ack_payload = {
        "record": plan.model_dump(mode="json"),
        "authority": authority.value,
        "purpose": "intake",
        "caller": caller,
        "observed_at": observation.isoformat(),
    }
    ack_identity = identity(ack_payload)
    ack = ReviewAcknowledgmentReference(
        kind="review_ack", identity=ack_identity, uri=record_uri("review_ack", ack_identity)
    )
    state = read_json(workspace, "state.json") or {}
    state.update(
        {
            "review_authority": authority.value,
            "review_satisfied": True,
            "ack_identity": ack.identity,
        }
    )
    write_jsons(
        workspace,
        {
            "review_ack.json": {**ack.model_dump(mode="json"), **ack_payload},
            "state.json": state,
        },
    )
    return ack


def _roots(workspace: str | Path) -> tuple[AuthorizedSourceRoot, ...]:
    raw = read_json(workspace, "roots.json")
    if raw is None:
        raise ValueError("authorized roots are unavailable after restart")
    return tuple(AuthorizedSourceRoot.model_validate(item) for item in raw.get("roots", ()))


def _drift_details(original: SourcePreflight, current: SourcePreflight) -> tuple[str, ...]:
    old = {
        (item.trial_id, item.root_alias, item.relative_path): item for item in original.candidates
    }
    new = {
        (item.trial_id, item.root_alias, item.relative_path): item for item in current.candidates
    }
    details: list[str] = []
    removed = set(old) - set(new)
    added = set(new) - set(old)
    # A same-byte path move is a rename; classify it separately from additions
    # and removals while retaining only safe logical aliases in the receipt.
    for old_key in sorted(removed):
        matches = [key for key in added if old[old_key].sha256 == new[key].sha256]
        if matches:
            new_key = sorted(matches)[0]
            details.append(f"renamed:{old_key[1]}:{old_key[2]}->{new_key[2]}")
            added.remove(new_key)
        else:
            details.append(f"removed:{old_key[1]}:{old_key[2]}")
    details.extend(f"added:{key[1]}:{key[2]}" for key in sorted(added))
    for key in sorted(set(old) & set(new)):
        if old[key].sha256 != new[key].sha256:
            details.append(f"changed_bytes:{key[1]}:{key[2]}")
    return tuple(details)


def _recover_pending_capture(workspace: str | Path) -> None:
    marker = read_json(workspace, "capture_pending.json")
    if marker is None:
        return
    root = Path(workspace).resolve(strict=True)
    final = root / Path(str(marker.get("final_relative", "")))
    if not final.is_relative_to(root) or not final.is_dir() or final.is_symlink():
        staging_name = marker.get("staging_name")
        if isinstance(staging_name, str):
            staging = root / ".rob2-kit" / "capture-staging" / staging_name
            if staging.is_dir() and not staging.is_symlink():
                shutil.rmtree(staging)
        delete_json(workspace, "capture_pending.json")
        return
    sources = marker.get("sources")
    if not isinstance(sources, list):
        raise ValueError("capture recovery marker is corrupt")
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("capture recovery marker is corrupt")
        trial_id = source.get("trial_id")
        candidate_id = source.get("candidate_identity")
        digest = source.get("sha256")
        if not all(isinstance(value, str) for value in (trial_id, candidate_id, digest)):
            raise ValueError("capture recovery marker is corrupt")
        path = final / trial_id / candidate_id
        if not path.is_file() or path.is_symlink():
            raise ValueError("capture recovery bytes are incomplete")
        actual = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != digest:
            raise ValueError("capture recovery bytes are corrupt")
    batch_payload = {
        "plan": marker["plan"],
        "acknowledgment": marker["acknowledgment"],
        "sources": sources,
    }
    captured_identity = str(marker["captured_identity"])
    state = read_json(workspace, "state.json") or {}
    state.update(
        {
            "phase": "proposal",
            "captured_identity": captured_identity,
            "plan_identity": marker["plan"],
            "capture_pending": False,
        }
    )
    write_jsons(
        workspace,
        {
            "captured_batch.json": {
                "kind": "captured_batch",
                "identity": captured_identity,
                **batch_payload,
            },
            "state.json": state,
        },
    )
    delete_json(workspace, "capture_pending.json")


def _captured_replay_is_exact(workspace: str | Path, captured_identity: object) -> bool:
    if not isinstance(captured_identity, str):
        return False
    raw = read_json(workspace, "captured_batch.json")
    if not isinstance(raw, dict) or set(raw) != {
        "kind",
        "identity",
        "plan",
        "acknowledgment",
        "sources",
    }:
        return False
    if raw.get("kind") != "captured_batch" or raw.get("identity") != captured_identity:
        return False
    payload = {key: raw[key] for key in ("plan", "acknowledgment", "sources")}
    if identity(payload) != captured_identity or not isinstance(raw["sources"], list):
        return False
    root = (
        Path(workspace).resolve(strict=True)
        / ".rob2-kit"
        / "sources-v3"
        / captured_identity.removeprefix("sha256:")
    )
    for source in raw["sources"]:
        if not isinstance(source, dict) or set(source) != {
            "candidate_identity",
            "trial_id",
            "sha256",
            "role",
        }:
            return False
        if not all(isinstance(source[key], str) for key in source):
            return False
        path = root / source["trial_id"] / source["candidate_identity"]
        if not path.is_file() or path.is_symlink():
            return False
        if "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
            return False
    return True


def capture_batch(workspace: str | Path, request: CaptureRequest) -> CaptureReceipt:
    with workspace_mutation_lock(workspace):
        return _capture_batch_locked(workspace, request)


def _capture_batch_locked(workspace: str | Path, request: CaptureRequest) -> CaptureReceipt:
    _recover_pending_capture(workspace)
    state = read_json(workspace, "state.json") or {}
    plan = verify_intake_plan(read_json(workspace, "intake_plan.json"))
    if request.plan.identity != plan.identity:
        raise ValueError("capture plan is stale")
    if (
        state.get("ack_identity") != request.acknowledgment.identity
        or verify_acknowledgment(
            workspace,
            "review_ack.json",
            request.acknowledgment,
            record=plan.reference,
            purpose="intake",
            authority=intake_required_authority(plan),
        )
        is None
    ):
        raise ValueError("capture acknowledgment is stale")
    if state.get("captured_identity") and state.get("plan_identity") == plan.identity:
        if not _captured_replay_is_exact(workspace, state.get("captured_identity")):
            return CaptureReceipt(
                outcome=OperationOutcome.CONDITION,
                plan=request.plan,
                acknowledgment=request.acknowledgment,
                conditions=("captured_integrity_failure",),
            )
        reference = RecordReference(
            kind=RecordKind.CAPTURED_BATCH,
            identity=state["captured_identity"],
            uri=record_uri("captured_batch", state["captured_identity"]),
        )
        return CaptureReceipt(
            outcome=OperationOutcome.SUCCESS,
            captured_batch=reference,
            plan=request.plan,
            acknowledgment=request.acknowledgment,
            next_action=SaveProposalContinuation(captured_batch=reference),
        )
    if state.get("ack_identity") != request.acknowledgment.identity or not state.get(
        "review_satisfied"
    ):
        raise PermissionError("capture requires the exact stored Intake acknowledgment")
    roots = _roots(workspace)
    original = _preflight_record(workspace)
    expected = {item.identity for item in original.candidates}
    rescanned = preflight_sources(
        workspace,
        PreflightRequest(roots=roots, expected_head=plan.preflight.identity),
        persist=False,
    )
    actual = {item.identity for item in rescanned.candidates}
    if expected != actual:
        return CaptureReceipt(
            outcome=OperationOutcome.CONFLICT,
            plan=request.plan,
            acknowledgment=request.acknowledgment,
            conditions=("inventory_drift", *_drift_details(original, rescanned)),
            next_action=PreflightSourcesContinuation(),
        )
    candidates = _entry_candidates(rescanned)
    included = [entry for entry in plan.entries if entry.disposition is SourceDisposition.INCLUDE]
    workspace_path = Path(workspace).resolve(strict=True)
    root_map = {root.alias: workspace_path / root.path for root in roots}
    stage_root = Path(workspace).resolve(strict=True) / ".rob2-kit" / "capture-staging"
    stage_root.mkdir(parents=True, exist_ok=True)
    staging: Path | None = Path(tempfile.mkdtemp(prefix="batch-", dir=stage_root))
    final: Path | None = None
    published = False
    try:
        staged_sources: list[dict[str, object]] = []
        for entry in included:
            candidate = candidates[entry.candidate_identity]
            source_path = root_map[candidate.root_alias] / Path(candidate.relative_path)
            if not source_path.is_file() or source_path.is_symlink():
                raise ValueError("source changed or redirected during capture")
            destination = staging / candidate.trial_id / candidate.identity
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, destination)
            copied_digest = "sha256:" + hashlib.sha256(destination.read_bytes()).hexdigest()
            if copied_digest != candidate.sha256:
                raise ValueError("source changed during capture")
            staged_sources.append(
                {
                    "candidate_identity": candidate.identity,
                    "trial_id": candidate.trial_id,
                    "sha256": candidate.sha256,
                    "role": entry.role,
                }
            )
        batch_payload = {
            "plan": plan.identity,
            "acknowledgment": request.acknowledgment.identity,
            "sources": sorted(
                staged_sources,
                key=lambda item: (str(item["trial_id"]), str(item["candidate_identity"])),
            ),
        }
        captured_identity = identity(batch_payload)
        final = (
            Path(workspace).resolve(strict=True)
            / ".rob2-kit"
            / "sources-v3"
            / captured_identity.removeprefix("sha256:")
        )
        final.parent.mkdir(parents=True, exist_ok=True)
        if final.exists():
            # A failed transaction can leave only staged bytes.  It has no
            # ledger record and is deliberately never an observable capture.
            shutil.rmtree(final)
        write_jsons(
            workspace,
            {
                "capture_pending.json": {
                    "plan": plan.identity,
                    "acknowledgment": request.acknowledgment.identity,
                    "captured_identity": captured_identity,
                    "final_relative": final.relative_to(
                        Path(workspace).resolve(strict=True)
                    ).as_posix(),
                    "staging_name": staging.name,
                    "sources": staged_sources,
                },
                "state.json": {**state, "capture_pending": True},
            },
        )
        os.replace(staging, final)
        staging = None
        record = RecordReference(
            kind=RecordKind.CAPTURED_BATCH,
            identity=captured_identity,
            uri=record_uri("captured_batch", captured_identity),
        )
        state.update(
            {
                "phase": "proposal",
                "captured_identity": captured_identity,
                "plan_identity": plan.identity,
                "capture_pending": False,
            }
        )
        write_jsons(
            workspace,
            {
                "captured_batch.json": {
                    "kind": "captured_batch",
                    "identity": captured_identity,
                    **batch_payload,
                },
                "state.json": state,
            },
        )
        delete_json(workspace, "capture_pending.json")
        published = True
        return CaptureReceipt(
            outcome=OperationOutcome.SUCCESS,
            captured_batch=record,
            plan=request.plan,
            acknowledgment=request.acknowledgment,
            next_action=SaveProposalContinuation(captured_batch=record),
        )
    finally:
        if staging is not None and staging.exists():
            shutil.rmtree(staging)
        if final is not None and final.exists() and not published:
            shutil.rmtree(final)

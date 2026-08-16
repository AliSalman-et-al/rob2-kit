"""Workspace-bound proposal and approval trust boundary."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Annotated, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from rob2_kit.assessment import (
    ApprovedTrialResult,
    CapturedBatch,
    Proposal,
    ProposalApprovalCondition,
    ProposalApprovalReceipt,
    ProposalApproved,
    ProposalDraft,
    ProposalDraftRepair,
    ProposalInvalid,
    ProposalReceipt,
    ProposalRepair,
    ProposalSaveCondition,
    ProposalSaved,
    ProposalValid,
    ProposalValidation,
    ProposalValidationCondition,
    ResultSpec,
    Trial,
)
from rob2_kit.detail import detail_reference
from rob2_kit.ingestion.service import (
    local_source_records,
    local_sources,
    read_captured_batch,
    registry_source,
)
from rob2_kit.models import canonical_json_bytes, sha256
from rob2_kit.packs import MAINTAINER_POLICY_PACK, SCIENTIFIC_PACK
from rob2_kit.storage import load_state, read_only_transaction, transaction
from rob2_kit.text_projection import VerifiedProjection, canonical_projection_identity


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Problem(_Strict):
    code: str
    detail: str


class PackIdentity(_Strict):
    id: str
    version: str
    content_hash: str


class NoActiveBatch(_Strict):
    status: Literal["no_active"] = "no_active"


class ApprovedBatch(_Strict):
    status: Literal["approved"] = "approved"
    proposal: Proposal
    pack_identities: tuple[PackIdentity, ...]
    frozen_hash: str


class StaleBatch(_Strict):
    status: Literal["stale"] = "stale"
    approved: ApprovedBatch
    problems: tuple[Problem, ...]


BatchState = Annotated[
    NoActiveBatch | ApprovedBatch | StaleBatch,
    Field(discriminator="status"),
]


class ProposalVersion(_Strict):
    """Immutable, content-addressed v2 proposal version."""

    schema_id: Literal["rob2.proposal_version"] = "rob2.proposal_version"
    schema_version: Literal[1] = 1
    draft: ProposalDraft
    proposal: Proposal
    draft_hash: str
    proposal_hash: str
    captured_batch_hash: str
    version_hash: str


def _draft_hash(draft: ProposalDraft) -> str:
    return sha256(draft)


def _proposal_hash(proposal: Proposal) -> str:
    return sha256(proposal)


def _draft_repair(
    pointer: str,
    invariant: str,
    actual: str,
    action: str,
    *,
    subject: str | None = None,
    count: int | None = None,
) -> ProposalRepair:
    return ProposalRepair(
        pointer=pointer,
        subject=subject,
        invariant=cast(
            Literal[
                "captured_batch",
                "trial_set",
                "result_set",
                "result_anchor",
                "anchor_scope",
                "anchor_stale",
                "anchor_integrity",
                "outcome_target",
            ],
            invariant,
        ),
        actual=cast(
            Literal["missing", "duplicate", "out_of_scope", "invalid", "stale", "mismatch"],
            actual,
        ),
        action=cast(
            Literal["add_result", "remove_result", "replace_anchor", "refresh_capture", "retry"],
            action,
        ),
        count=count,
    )


def _canonical_proposal_from_draft(
    workspace: str | Path, draft: ProposalDraft, captured: CapturedBatch
) -> tuple[Proposal | None, tuple[ProposalRepair, ...]]:
    """Resolve handles against one frozen capture and build the complete Proposal."""

    repairs: list[ProposalRepair] = []
    expected = tuple(item.trial_input.id for item in captured.trials)
    if len(draft.results) < len(expected):
        repairs.append(
            _draft_repair(
                "/results",
                "result_set",
                "missing",
                "add_result",
                count=len(expected) - len(draft.results),
            )
        )
    if len(draft.results) > len(expected):
        repairs.append(
            _draft_repair(
                "/results",
                "result_set",
                "out_of_scope",
                "remove_result",
                count=len(draft.results) - len(expected),
            )
        )
    if len(draft.results) != len(expected):
        repairs.append(
            _draft_repair("/results", "trial_set", "mismatch", "retry", count=len(draft.results))
        )
    if repairs:
        return None, tuple(sorted(repairs, key=lambda item: (item.pointer, item.invariant)))

    from rob2_kit.retrieval import (
        RetrievalBasisError,
        build_retrieval_snapshot,
        handle_from_id,
        resolve_evidence_handle,
    )

    proposals: list[ResultSpec] = []
    for index, result_draft in enumerate(draft.results):
        captured_trial = captured.trials[index]
        trial_id = captured_trial.trial_input.id
        pointer = f"/results/{index}/anchor"
        if not captured_trial.sources:
            repairs.append(
                _draft_repair(
                    f"/results/{index}",
                    "captured_batch",
                    "missing",
                    "refresh_capture",
                    subject=trial_id,
                )
            )
            continue
        try:
            context = build_retrieval_snapshot(
                workspace,
                trial_id,
                captured_trial.sources,
            )
            if context.snapshot.scope_kind != "captured_batch":
                raise RetrievalBasisError("Proposal anchors require Captured Batch scope")
            handle = handle_from_id(result_draft.anchor.handle_id)
            anchor = resolve_evidence_handle(context, handle)
            if getattr(anchor, "kind", None) != "text":
                raise ValueError("anchor must resolve to text")
            from rob2_kit.judgment_models import TextEvidenceRef

            text_anchor = cast(TextEvidenceRef, anchor)
        except RetrievalBasisError:
            raise
        except (OSError, ValueError, IndexError, KeyError):
            repairs.append(
                _draft_repair(
                    pointer,
                    "anchor_integrity",
                    "stale",
                    "replace_anchor",
                    subject=trial_id,
                )
            )
            continue
        trial = Trial(id=captured_trial.trial_input.id, label=captured_trial.trial_input.label)
        proposals.append(
            ResultSpec(
                id=result_draft.result_id,
                trial=trial,
                randomization=result_draft.randomization,
                arms=result_draft.arms,
                comparison=result_draft.comparison,
                effect_of_interest=result_draft.effect_of_interest,
                outcome_definition=result_draft.outcome_definition,
                measurement=result_draft.measurement,
                time_point=result_draft.time_point,
                population=result_draft.population,
                analysis_method=result_draft.analysis_method,
                analysis_choices=result_draft.analysis_choices,
                effect_measure=result_draft.effect_measure,
                numerical_values=result_draft.numerical_values,
                denominators=result_draft.denominators,
                anchor={
                    "source_id": text_anchor.source_id,
                    "source_sha256": text_anchor.source_sha256,
                    "page_number": text_anchor.page_number,
                    "start": text_anchor.start,
                    "end": text_anchor.end,
                    "quote": text_anchor.quote,
                },
            )
        )
    if repairs:
        return None, tuple(sorted(repairs, key=lambda item: (item.pointer, item.invariant)))
    trials = tuple(
        Trial(id=item.trial_input.id, label=item.trial_input.label) for item in captured.trials
    )
    proposal = Proposal(
        request={"outcome_target": draft.outcome_target, "trial_inputs": captured.trial_inputs},
        trials=trials,
        result_specs=tuple(proposals),
        sources=tuple(source for item in captured.trials for source in item.sources),
    )
    return proposal, ()


def validate_proposal_draft(
    workspace: str | Path, draft: ProposalDraft
) -> tuple[ProposalValidation, Proposal | None]:
    """Validate a minimal draft without writing anything."""

    draft_hash = _draft_hash(draft)
    from rob2_kit.retrieval import RetrievalBasisError

    captured = read_captured_batch(workspace)
    if captured is None:
        validation = ProposalValidationCondition(
            draft_hash=draft_hash,
        )
        return validation, None
    try:
        proposal, repairs = _canonical_proposal_from_draft(workspace, draft, captured)
    except RetrievalBasisError:
        return ProposalValidationCondition(draft_hash=draft_hash), None
    if repairs:
        return (
            ProposalInvalid(
                draft_hash=draft_hash,
                repairs=repairs,
            ),
            None,
        )
    assert proposal is not None
    return (
        ProposalValid(
            draft_hash=draft_hash,
            captured_batch_hash=captured.content_hash,
            proposal_hash=_proposal_hash(proposal),
        ),
        proposal,
    )


def _stored_state(data: bytes) -> ApprovedBatch:
    return ApprovedBatch.model_validate_json(data)


def _problems(
    workspace: str | Path,
    proposal: Proposal,
    projection: VerifiedProjection | None = None,
) -> tuple[Problem, ...]:
    problems = []
    root = Path(workspace).resolve(strict=True)
    projection = projection or VerifiedProjection(root)
    pages_by_source: dict[str, tuple[str, ...]] = {}
    requested = {item.id for item in proposal.request.trial_inputs}
    for trial_id in requested:
        inventory = tuple(source for source in proposal.sources if source.trial_id == trial_id)
        try:
            records = local_source_records(workspace, trial_id)
            actual = local_sources(workspace, trial_id)
            registry = registry_source(workspace, trial_id)
            actual = actual + (() if registry is None else (registry,))
        except ValueError as error:
            problems.append(Problem(code="source_inventory_invalid", detail=f"{trial_id}: {error}"))
            continue
        if tuple(sorted(inventory, key=lambda source: source.id)) != tuple(
            sorted(actual, key=lambda source: source.id)
        ):
            problems.append(Problem(code="source_inventory_mismatch", detail=trial_id))
        declarations = next(item for item in proposal.request.trial_inputs if item.id == trial_id)
        declared_counts: dict[tuple[str, str, str], int] = {}
        expected_declarations = []
        for item in declarations.sources:
            key = (item.role.value, Path(item.path).as_posix(), item.label)
            occurrence = declared_counts.get(key, 0)
            declared_counts[key] = occurrence + 1
            expected_declarations.append((*key, occurrence))
        actual_declarations = sorted(
            (
                record.source.role.value,
                Path(record.input_path).as_posix(),
                record.source.label,
                record.occurrence,
            )
            for record in records
        )
        if sorted(expected_declarations) != actual_declarations:
            problems.append(Problem(code="source_declarations_mismatch", detail=trial_id))
        if not inventory:
            problems.append(Problem(code="source_inventory_missing", detail=trial_id))
        elif sum(source.role.value == "main_article" for source in inventory) != 1:
            problems.append(Problem(code="main_article_invalid", detail=trial_id))
    for source in proposal.sources:
        try:
            pages_by_source[source.id] = projection.pages(
                source, canonical_projection_identity(workspace, source)
            )
        except (OSError, ValueError) as error:
            problems.append(Problem(code="source_stale", detail=f"{source.id}: {error}"))
            pages_by_source.pop(source.id, None)
    for spec in proposal.result_specs:
        source = next((s for s in proposal.sources if s.id == spec.anchor.source_id), None)
        if source is None:
            continue
        try:
            pages = pages_by_source.get(source.id)
            if pages is None:
                raise ValueError("source projection is unavailable")
            page = pages[spec.anchor.page_number - 1]
            if (
                spec.anchor.end > len(page)
                or spec.anchor.end - spec.anchor.start != len(spec.anchor.quote)
                or page[spec.anchor.start : spec.anchor.end] != spec.anchor.quote
            ):
                problems.append(Problem(code="anchor_invalid", detail=spec.id))
        except (IndexError, OSError, ValueError):
            problems.append(Problem(code="anchor_invalid", detail=spec.id))
    return tuple(problems)


def _packs() -> tuple[PackIdentity, ...]:
    return (
        PackIdentity(
            id=SCIENTIFIC_PACK.id,
            version=SCIENTIFIC_PACK.version,
            content_hash=SCIENTIFIC_PACK.content_hash,
        ),
        PackIdentity(
            id=MAINTAINER_POLICY_PACK.id,
            version=MAINTAINER_POLICY_PACK.version,
            content_hash=MAINTAINER_POLICY_PACK.content_hash,
        ),
    )


def frozen_batch_hash(proposal: Proposal, packs: tuple[PackIdentity, ...]) -> str:
    """The one identity binding an approved proposal to its exact pack identities."""
    return sha256({"proposal": proposal, "packs": packs})


def _approved_problems(
    workspace: str | Path,
    state: ApprovedBatch,
    pack_identities: tuple[PackIdentity, ...] | None,
    projection: VerifiedProjection | None = None,
) -> tuple[Problem, ...]:
    problems = _problems(workspace, state.proposal, projection)
    current = _packs() if pack_identities is None else pack_identities
    if current != state.pack_identities:
        problems += (Problem(code="pack_stale", detail="pack identity changed"),)
    if state.frozen_hash != frozen_batch_hash(state.proposal, state.pack_identities):
        problems += (
            Problem(code="frozen_identity_corrupt", detail="approved batch hash mismatch"),
        )
    return tuple(dict.fromkeys(problems))


def _validated_approved_state(
    workspace: str | Path,
    state: ApprovedBatch,
    pack_identities: tuple[PackIdentity, ...] | None = None,
    projection: VerifiedProjection | None = None,
) -> ApprovedBatch | StaleBatch:
    problems = _approved_problems(workspace, state, pack_identities, projection)
    return state if not problems else StaleBatch(approved=state, problems=problems)


def current_batch(
    workspace: str | Path, *, pack_identities: tuple[PackIdentity, ...] | None = None
) -> BatchState:
    data = load_state(workspace)
    if data is None:
        return NoActiveBatch()
    state = _stored_state(data)
    if isinstance(state, ApprovedBatch):
        return _validated_approved_state(workspace, state, pack_identities)
    return state


def current_batch_in_transaction(
    workspace: str | Path,
    connection: sqlite3.Connection,
    *,
    pack_identities: tuple[PackIdentity, ...] | None = None,
    projection: VerifiedProjection | None = None,
) -> BatchState:
    """Read and validate the active batch using the caller's locked snapshot."""
    row = connection.execute("SELECT payload FROM records WHERE name='active_batch'").fetchone()
    if row is None:
        return NoActiveBatch()
    state = _stored_state(bytes(row[0]))
    if isinstance(state, ApprovedBatch):
        return _validated_approved_state(workspace, state, pack_identities, projection)
    return state


def _version_key(version_hash: str) -> str:
    return f"proposal_version:{version_hash}"


def _version_identity(version: ProposalVersion) -> str:
    return sha256(version.model_dump(exclude={"schema_id", "schema_version", "version_hash"}))


def _active_version(connection: sqlite3.Connection) -> ProposalVersion | None:
    row = connection.execute(
        "SELECT payload FROM runtime_meta WHERE name='active_proposal_version'"
    ).fetchone()
    if row is None:
        return None
    version_hash = bytes(row[0]).decode()
    stored = connection.execute(
        "SELECT payload FROM records WHERE name=?", (_version_key(version_hash),)
    ).fetchone()
    if stored is None:
        raise ValueError("proposal version is unavailable")
    version = ProposalVersion.model_validate_json(bytes(stored[0]))
    if version.version_hash != version_hash:
        raise ValueError("proposal version identity is corrupt")
    expected = _version_identity(version)
    if expected != version_hash:
        raise ValueError("proposal version identity is corrupt")
    return version


def save_proposal_draft(workspace: str | Path, draft: ProposalDraft) -> ProposalReceipt:
    """Validate and durably save one immutable v2 proposal version."""

    with read_only_transaction(workspace) as connection:
        if connection is not None and (
            connection.execute(
                "SELECT 1 FROM records WHERE name='active_batch' OR "
                "name LIKE 'batch_summary:%' LIMIT 1"
            ).fetchone()
        ):
            return ProposalSaveCondition(draft_hash=sha256(draft))
    validation, proposal = validate_proposal_draft(workspace, draft)
    if isinstance(validation, ProposalInvalid):
        return ProposalDraftRepair(draft_hash=validation.draft_hash, repairs=validation.repairs)
    if isinstance(validation, ProposalValidationCondition):
        return ProposalSaveCondition(draft_hash=validation.draft_hash)
    assert proposal is not None
    version_without_identity = {
        "draft": draft,
        "proposal": proposal,
        "draft_hash": validation.draft_hash,
        "proposal_hash": validation.proposal_hash,
        "captured_batch_hash": validation.captured_batch_hash,
    }
    version_hash = sha256(version_without_identity)
    version = ProposalVersion(
        draft=draft,
        proposal=proposal,
        draft_hash=validation.draft_hash,
        proposal_hash=validation.proposal_hash,
        captured_batch_hash=validation.captured_batch_hash,
        version_hash=version_hash,
    )
    payload = canonical_json_bytes(version)
    with transaction(workspace) as connection:
        active = connection.execute(
            "SELECT payload FROM records WHERE name='active_batch'"
        ).fetchone()
        if active is not None and isinstance(_stored_state(bytes(active[0])), ApprovedBatch):
            return ProposalSaveCondition(draft_hash=validation.draft_hash)
        if connection.execute(
            "SELECT 1 FROM records WHERE name LIKE 'batch_summary:%' LIMIT 1"
        ).fetchone():
            return ProposalSaveCondition(draft_hash=validation.draft_hash)
        captured_head = connection.execute(
            "SELECT payload FROM runtime_meta WHERE name='captured_batch_hash'"
        ).fetchone()
        if (
            captured_head is None
            or bytes(captured_head[0]).decode() != validation.captured_batch_hash
        ):
            return ProposalSaveCondition(draft_hash=validation.draft_hash)
        key = _version_key(version_hash)
        existing = connection.execute("SELECT payload FROM records WHERE name=?", (key,)).fetchone()
        if existing is not None and bytes(existing[0]) != payload:
            raise ValueError("proposal version identity conflicts with stored bytes")
        if existing is None:
            connection.execute("INSERT INTO records(name,payload) VALUES(?,?)", (key, payload))
        connection.execute(
            "INSERT INTO runtime_meta(name,payload) VALUES('active_proposal_version',?) "
            "ON CONFLICT(name) DO UPDATE SET payload=excluded.payload",
            (version_hash.encode(),),
        )
    return ProposalSaved(
        proposal_ref=detail_reference("proposal", version_hash),
        draft_hash=version.draft_hash,
        captured_batch_hash=version.captured_batch_hash,
        version_hash=version.version_hash,
    )


def save_proposal_mapping(workspace: str | Path, raw_draft: object) -> ProposalReceipt:
    """Aggregate malformed nested Proposal fields before any durable write."""

    draft_hash = sha256(raw_draft)
    try:
        draft = ProposalDraft.model_validate(raw_draft)
    except ValidationError as error:
        repairs: list[ProposalRepair] = []
        for item in error.errors(include_url=False, include_context=False, include_input=False):
            location = tuple(str(part) for part in item["loc"])
            pointer = (
                ""
                if not location
                else "/" + "/".join(part.replace("~", "~0").replace("/", "~1") for part in location)
            )
            error_type = str(item["type"])
            if error_type == "missing":
                actual = "missing"
                action = "correct_field"
            elif error_type == "extra_forbidden":
                actual = "extra"
                action = "remove_field"
            elif "type" in error_type or "parsing" in error_type:
                actual = "wrong_type"
                action = "correct_field"
            else:
                actual = "invalid"
                action = "correct_field"
            repairs.append(
                ProposalRepair(
                    pointer=pointer or "/",
                    invariant="draft_schema",
                    actual=actual,
                    action=action,
                )
            )

        def repair_key(item: ProposalRepair) -> tuple[str, str, str, str]:
            return (item.pointer, item.invariant, item.actual, item.action)

        return ProposalDraftRepair(
            draft_hash=draft_hash,
            repairs=tuple(sorted(repairs, key=repair_key)),
        )
    return save_proposal_draft(workspace, draft)


def read_proposal_version(
    workspace: str | Path, version_hash: str | None = None
) -> ProposalVersion | None:
    """Read one immutable proposal version, verifying its content identity."""

    with read_only_transaction(workspace) as connection:
        if connection is None:
            return None
        version = _active_version(connection) if version_hash is None else None
        if version_hash is not None:
            row = connection.execute(
                "SELECT payload FROM records WHERE name=?", (_version_key(version_hash),)
            ).fetchone()
            if row is None:
                return None
            version = ProposalVersion.model_validate_json(bytes(row[0]))
        if version is None:
            return None
        expected = _version_identity(version)
        if version.version_hash != expected:
            raise ValueError("proposal version identity is corrupt")
        return version


def read_proposal_detail(workspace: str | Path, proposal_ref: str) -> Proposal:
    """Return the complete immutable Proposal for researcher review."""

    version = read_proposal_version(workspace, proposal_ref)
    if version is None:
        raise ValueError("proposal detail is unavailable")
    return version.proposal


def approve_proposal(workspace: str | Path, reviewed_proposal_hash: str) -> ProposalApprovalReceipt:
    """Approve only the exact immutable Proposal reviewed by the researcher."""

    with transaction(workspace) as connection:
        version = _active_version(connection)
        captured = read_captured_batch(workspace)
        if version is None or captured is None:
            return ProposalApprovalCondition(
                proposal_hash=reviewed_proposal_hash,
            )
        if reviewed_proposal_hash != version.proposal_hash:
            return ProposalApprovalCondition(
                proposal_hash=version.proposal_hash,
            )
        if captured.content_hash != version.captured_batch_hash:
            return ProposalApprovalCondition(
                proposal_hash=version.proposal_hash,
            )
        problems = _problems(workspace, version.proposal)
        if problems:
            return ProposalApprovalCondition(
                proposal_hash=version.proposal_hash,
            )
        packs = _packs()
        approved = ApprovedBatch(
            proposal=version.proposal,
            pack_identities=packs,
            frozen_hash=frozen_batch_hash(version.proposal, packs),
        )
        existing = connection.execute(
            "SELECT payload FROM records WHERE name='active_batch'"
        ).fetchone()
        if existing is not None:
            current = _stored_state(bytes(existing[0]))
            if (
                not isinstance(current, ApprovedBatch)
                or current.frozen_hash != approved.frozen_hash
            ):
                return ProposalApprovalCondition(proposal_hash=version.proposal_hash)
        from rob2_kit.packets import VerifiedDomainPacketBasis, build_approved_work_packet

        first_trial = version.proposal.trials[0]
        first_result = next(
            item for item in version.proposal.result_specs if item.trial.id == first_trial.id
        )
        first_domain = SCIENTIFIC_PACK.domains[0].id
        packet = build_approved_work_packet(
            VerifiedDomainPacketBasis(
                approved_batch=approved,
                trial_id=first_trial.id,
                result_id=first_result.id,
                domain_id=first_domain,
            )
        )
        packet_key = f"detail:domain:{packet.packet_hash}"
        packet_payload = canonical_json_bytes(packet)
        packet_row = connection.execute(
            "SELECT payload FROM records WHERE name=?", (packet_key,)
        ).fetchone()
        if packet_row is not None and bytes(packet_row[0]) != packet_payload:
            raise ValueError("approved work packet record is corrupt")
        if packet_row is None:
            connection.execute(
                "INSERT INTO records(name,payload) VALUES(?,?)",
                (packet_key, packet_payload),
            )
        packet_ref = detail_reference("domain", packet.packet_hash)
        approved_key = f"detail:batch:{approved.frozen_hash}"
        approved_payload = canonical_json_bytes(approved)
        approved_row = connection.execute(
            "SELECT payload FROM records WHERE name=?", (approved_key,)
        ).fetchone()
        if approved_row is not None and bytes(approved_row[0]) != approved_payload:
            raise ValueError("Approved Batch Detail record is corrupt")
        if approved_row is None:
            connection.execute(
                "INSERT INTO records(name,payload) VALUES(?,?)",
                (approved_key, approved_payload),
            )
        if existing is not None:
            current = _stored_state(bytes(existing[0]))
            if isinstance(current, ApprovedBatch) and current.frozen_hash == approved.frozen_hash:
                return ProposalApproved(
                    approved_batch_hash=current.frozen_hash,
                    proposal_hash=version.proposal_hash,
                    captured_batch_hash=version.captured_batch_hash,
                    first_packet_ref=packet_ref,
                    trial_results=tuple(
                        ApprovedTrialResult(trial_id=trial.id, result_id=result.id)
                        for trial in version.proposal.trials
                        for result in version.proposal.result_specs
                        if result.trial.id == trial.id
                    ),
                    next_action=packet.next_action,
                )
        connection.execute(
            "INSERT INTO records(name,payload) VALUES('active_batch',?) "
            "ON CONFLICT(name) DO UPDATE SET payload=excluded.payload",
            (canonical_json_bytes(approved),),
        )
        return ProposalApproved(
            approved_batch_hash=approved.frozen_hash,
            proposal_hash=version.proposal_hash,
            captured_batch_hash=version.captured_batch_hash,
            first_packet_ref=packet_ref,
            trial_results=tuple(
                ApprovedTrialResult(trial_id=trial.id, result_id=result.id)
                for trial in version.proposal.trials
                for result in version.proposal.result_specs
                if result.trial.id == trial.id
            ),
            next_action=packet.next_action,
        )

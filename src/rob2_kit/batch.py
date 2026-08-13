"""Workspace-bound proposal and approval trust boundary."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from rob2_kit.assessment import Proposal
from rob2_kit.ingestion.service import local_source_records, local_sources, registry_source
from rob2_kit.models import canonical_json_bytes, sha256
from rob2_kit.packs import MAINTAINER_POLICY_PACK, SCIENTIFIC_PACK
from rob2_kit.search import _source_bytes
from rob2_kit.sources import _extract_pages
from rob2_kit.storage import load_state, transaction


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


class ProposedBatch(_Strict):
    status: Literal["proposal"] = "proposal"
    draft: Proposal
    problems: tuple[Problem, ...]


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
    NoActiveBatch | ProposedBatch | ApprovedBatch | StaleBatch,
    Field(discriminator="status"),
]


class SaveProposalResult(_Strict):
    state: NoActiveBatch | ProposedBatch | ApprovedBatch | StaleBatch = Field(
        discriminator="status"
    )


class ApproveBatchResult(_Strict):
    state: NoActiveBatch | ProposedBatch | ApprovedBatch | StaleBatch = Field(
        discriminator="status"
    )


def _stored_state(data: bytes) -> ProposedBatch | ApprovedBatch:
    status = json.loads(data)["status"]
    return {"proposal": ProposedBatch, "approved": ApprovedBatch}[status].model_validate_json(data)


def _problems(workspace: str | Path, proposal: Proposal) -> tuple[Problem, ...]:
    problems = []
    root = Path(workspace).resolve(strict=True)
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
            _source_bytes(root, source)
        except (OSError, ValueError) as error:
            problems.append(Problem(code="source_stale", detail=f"{source.id}: {error}"))
            continue
    for spec in proposal.result_specs:
        source = next((s for s in proposal.sources if s.id == spec.anchor.source_id), None)
        if source is None:
            continue
        try:
            page = _extract_pages(_source_bytes(root, source), source.media_type)[
                spec.anchor.page_number - 1
            ]
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


def current_batch(
    workspace: str | Path, *, pack_identities: tuple[PackIdentity, ...] | None = None
) -> BatchState:
    data = load_state(workspace)
    if data is None:
        return NoActiveBatch()
    state = _stored_state(data)
    if isinstance(state, ApprovedBatch):
        problems = _problems(workspace, state.proposal)
        current = _packs() if pack_identities is None else pack_identities
        if current != state.pack_identities:
            problems = problems + (Problem(code="pack_stale", detail="pack identity changed"),)
        if problems:
            return StaleBatch(
                approved=state,
                problems=tuple(dict.fromkeys(problems)),
            )
    return state


def current_batch_in_transaction(
    workspace: str | Path,
    connection: sqlite3.Connection,
    *,
    pack_identities: tuple[PackIdentity, ...] | None = None,
) -> BatchState:
    """Read and validate the active batch using the caller's locked snapshot."""
    row = connection.execute("SELECT payload FROM records WHERE name='active_batch'").fetchone()
    if row is None:
        return NoActiveBatch()
    state = _stored_state(bytes(row[0]))
    if isinstance(state, ApprovedBatch):
        problems = _problems(workspace, state.proposal)
        current = _packs() if pack_identities is None else pack_identities
        if current != state.pack_identities:
            problems = problems + (Problem(code="pack_stale", detail="pack identity changed"),)
        if problems:
            return StaleBatch(approved=state, problems=tuple(dict.fromkeys(problems)))
    return state


def save_proposal(workspace: str | Path, proposal: Proposal) -> SaveProposalResult:
    with transaction(workspace) as connection:
        row = connection.execute("SELECT payload FROM records WHERE name='active_batch'").fetchone()
        stored = None if row is None else _stored_state(bytes(row[0]))
        if isinstance(stored, ApprovedBatch):
            return SaveProposalResult(
                state=StaleBatch(
                    approved=stored,
                    problems=(Problem(code="batch_already_approved", detail="proposal is frozen"),),
                )
            )
        result = ProposedBatch(draft=proposal, problems=_problems(workspace, proposal))
        connection.execute(
            "INSERT INTO records(name,payload) VALUES('active_batch',?) "
            "ON CONFLICT(name) DO UPDATE SET payload=excluded.payload",
            (canonical_json_bytes(result),),
        )
        return SaveProposalResult(state=result)


def approve_batch(workspace: str | Path) -> ApproveBatchResult:
    with transaction(workspace) as connection:
        row = connection.execute("SELECT payload FROM records WHERE name='active_batch'").fetchone()
        if row is None:
            return ApproveBatchResult(state=NoActiveBatch())
        state = _stored_state(bytes(row[0]))
        if not isinstance(state, ProposedBatch):
            return ApproveBatchResult(state=state)
        problems = _problems(workspace, state.draft)
        if problems:
            result = ProposedBatch(draft=state.draft, problems=problems)
            connection.execute(
                "UPDATE records SET payload=? WHERE name='active_batch'",
                (canonical_json_bytes(result),),
            )
            return ApproveBatchResult(state=result)
        packs = _packs()
        approved = ApprovedBatch(
            proposal=state.draft,
            pack_identities=packs,
            frozen_hash=sha256({"proposal": state.draft, "packs": packs}),
        )
        connection.execute(
            "UPDATE records SET payload=? WHERE name='active_batch'",
            (canonical_json_bytes(approved),),
        )
        return ApproveBatchResult(state=approved)

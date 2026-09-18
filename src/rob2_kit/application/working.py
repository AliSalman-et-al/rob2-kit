"""Source-bound working notes kept outside canonical assessment state."""

from pathlib import Path
from typing import Any

from ..models import canonical_json_bytes
from ..workflow_models import (
    WorkingCheckpoint,
    WorkingCheckpointDraft,
    WorkingSourceBinding,
    WorkingSourceRange,
)
from ..workflow_models import (
    _identity as _with_identity,
)
from ._state import _db, _decode_object, _ensure, _result, _root, _state
from ._state import _identity as _digest
from .evidence import read_pages as _read_pages
from .source_handles import source_handle, source_handle_map

_MAX_WORKING_CHECKPOINT_BYTES = 24_576


def _active_trial_sources(state: dict[str, Any], trial_id: str) -> tuple[dict[str, Any], ...]:
    batch = state.get("batch")
    trials = batch.get("trials") if isinstance(batch, dict) else None
    if not isinstance(trials, list):
        return ()
    trial = next(
        (item for item in trials if isinstance(item, dict) and item.get("id") == trial_id),
        None,
    )
    sources = trial.get("sources") if isinstance(trial, dict) else None
    if not isinstance(sources, list):
        return ()
    return tuple(source for source in sources if isinstance(source, dict))


def _source_scope(state: dict[str, Any], trial_id: str) -> tuple[WorkingSourceBinding, ...]:
    bindings = tuple(
        sorted(
            (
                WorkingSourceBinding(
                    source_id=str(source["id"]),
                    projection_hash=str(source["projection_hash"]),
                )
                for source in _active_trial_sources(state, trial_id)
                if isinstance(source.get("id"), str)
                and isinstance(source.get("projection_hash"), str)
            ),
            key=lambda item: item.source_id,
        )
    )
    handles = [source_handle(item.source_id) for item in bindings]
    if len(handles) != len(set(handles)):
        raise ValueError("working_checkpoint_source_ambiguous")
    return bindings


def _result_identity(state: dict[str, Any], trial_id: str) -> str | None:
    proposal = state.get("proposal")
    if not isinstance(proposal, dict):
        review = state.get("review")
        candidate = review.get("candidate") if isinstance(review, dict) else None
        proposal = candidate.get("proposal") if isinstance(candidate, dict) else None
    payload = proposal.get("payload", proposal) if isinstance(proposal, dict) else None
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return None
    result = next(
        (item for item in results if isinstance(item, dict) and item.get("trial_id") == trial_id),
        None,
    )
    return _digest(result) if isinstance(result, dict) else None


def _domain_checkpoint_identities(state: dict[str, Any], trial_id: str) -> tuple[str, ...]:
    """Snapshot current Domain heads so stale notes cannot outrank a commit."""

    records = state.get("domain_records")
    if not isinstance(records, dict):
        return ()
    return tuple(
        sorted(
            str(record["identity"])
            for key, record in records.items()
            if isinstance(key, str)
            and key.startswith(f"{trial_id}:")
            and isinstance(record, dict)
            and isinstance(record.get("identity"), str)
        )
    )


def _ranges(draft: WorkingCheckpointDraft) -> tuple[WorkingSourceRange, ...]:
    values: list[WorkingSourceRange] = list(draft.unread_ranges)
    for group in (draft.observations, draft.interpretations, draft.open_questions, draft.drafts):
        for item in group:
            values.extend(item.sources)
    for item in draft.terminology:
        values.extend(item.sources)
    return tuple(values)


def _validate_ranges(
    root: Path,
    draft: WorkingCheckpointDraft,
    sources: tuple[dict[str, Any], ...],
    batch: object,
) -> None:
    by_id = {str(source["id"]): source for source in sources if isinstance(source.get("id"), str)}
    handle_index = source_handle_map(batch)
    read_pages: dict[tuple[str, int], str] = {}
    for item in _ranges(draft):
        matches = tuple(
            source_id
            for owner_trial, source_id in handle_index.get(item.source_id, ())
            if owner_trial == draft.trial_id
        )
        if not matches:
            raise ValueError("working_checkpoint_source_unknown")
        if len(matches) != 1:
            raise ValueError("working_checkpoint_source_ambiguous")
        source_id = matches[0]
        source = by_id.get(source_id)
        if source is None:
            raise ValueError("working_checkpoint_source_outside_trial")
        page_count = source.get("page_count")
        if not isinstance(page_count, int) or isinstance(page_count, bool):
            raise ValueError("working_checkpoint_source_invalid")
        if item.page > page_count:
            raise ValueError("working_checkpoint_locator_outside_source")
        if item.start_line == 0:
            continue
        page_key = (source_id, item.page)
        if page_key not in read_pages:
            page = _read_pages(root, draft.trial_id, source_id, [item.page])["pages"][0]
            read_pages[page_key] = str(page["text"])
        line_count = len(read_pages[page_key].splitlines())
        if item.end_line > line_count:
            raise ValueError("working_checkpoint_locator_outside_source")


def save_working_checkpoint(workspace: str | Path, draft: WorkingCheckpointDraft) -> dict[str, Any]:
    """Replace this Trial's bounded working notes without changing workflow state."""
    root = _root(workspace)
    _ensure(root)
    state = _state(root)
    batch = state.get("batch")
    trial_id = draft.trial_id
    batch_id = batch.get("identity") if isinstance(batch, dict) else None
    dispositions = state.get("trial_dispositions", {})
    disposition = dispositions.get(trial_id) if isinstance(dispositions, dict) else None
    if not isinstance(batch_id, str) or disposition not in {"pending", "reviewable"}:
        return _result(
            "condition",
            state,
            condition={
                "code": "working_checkpoint_trial_unavailable",
                "detail": "Save notes only for a current, unclosed Trial in the active Batch.",
            },
        )
    trials_in_batch = batch.get("trials", []) if isinstance(batch, dict) else []
    active_trial = next(
        (
            item.get("id")
            for item in trials_in_batch
            if isinstance(item, dict)
            and dispositions.get(item.get("id")) in {"pending", "reviewable"}
        ),
        None,
    )
    if trial_id != active_trial:
        return _result(
            "condition",
            state,
            condition={
                "code": "working_checkpoint_trial_not_current",
                "detail": "Save notes only for the current Trial reported by get_status.",
            },
        )
    sources = _active_trial_sources(state, trial_id)
    # Trial existence is authoritative even when intake captured no Sources.
    trials = batch.get("trials", []) if isinstance(batch, dict) else []
    if not any(isinstance(item, dict) and item.get("id") == trial_id for item in trials):
        return _result(
            "condition",
            state,
            condition={
                "code": "working_checkpoint_trial_unknown",
                "detail": "The Trial is not part of the active Batch.",
            },
        )
    _validate_ranges(root, draft, sources, batch)
    value = {
        "batch_id": batch_id,
        "trial_id": trial_id,
        "result_identity": _result_identity(state, trial_id),
        "domain_checkpoint_identities": _domain_checkpoint_identities(state, trial_id),
        "source_scope": [item.model_dump(mode="json") for item in _source_scope(state, trial_id)],
        **draft.model_dump(mode="json", exclude={"trial_id"}),
    }
    checkpoint = _with_identity(WorkingCheckpoint.model_validate(value), None)
    payload = canonical_json_bytes(checkpoint.model_dump(mode="json", exclude_none=True))
    if len(payload) > _MAX_WORKING_CHECKPOINT_BYTES:
        return _result(
            "condition",
            state,
            condition={
                "code": "working_checkpoint_too_large",
                "detail": (
                    "Working notes exceed the 24 KiB checkpoint limit. Keep only the exact "
                    "observations and locators needed to resume."
                ),
            },
        )

    current = _state(root)
    if (
        current.get("batch", {}).get("identity") != batch_id
        or _result_identity(current, trial_id) != checkpoint.result_identity
        or _source_scope(current, trial_id) != checkpoint.source_scope
    ):
        return _result(
            "condition",
            current,
            condition={
                "code": "working_checkpoint_basis_changed",
                "detail": "The Trial source or Result changed while notes were being saved.",
            },
        )
    with _db(root, "working.sqlite3") as connection:
        connection.execute(
            "INSERT OR REPLACE INTO working_checkpoints(batch_id,trial_id,identity,payload) "
            "VALUES (?,?,?,?)",
            (batch_id, trial_id, checkpoint.identity, payload),
        )
    current = _state(root)
    return _result(
        "success",
        current,
        checkpoint_identity=checkpoint.identity,
        trial_id=trial_id,
        result_identity=checkpoint.result_identity,
        source_count=len(checkpoint.source_scope),
        authoritative=False,
        next_action=(
            "Resume from these source-linked notes. Recover cited text with read_pages only when "
            "it is missing or uncertain; use render_page for a whole-page visual locator. These "
            "notes are not Evidence or saved Domain answers."
        ),
    )


def working_checkpoint_status(
    root: Path, state: dict[str, Any], trial_id: str | None
) -> dict[str, Any]:
    """Return current notes or a no-content stale/absent marker for the active Trial."""
    if trial_id is None:
        return {
            "status": "absent",
            "reason": "no_active_trial",
            "trial_id": None,
            "checkpoint_identity": None,
            "checkpoint": None,
            "recovery": "reorient_from_sources",
        }
    batch = state.get("batch")
    batch_id = batch.get("identity") if isinstance(batch, dict) else None
    if not isinstance(batch_id, str):
        return {
            "status": "absent",
            "reason": "no_active_batch",
            "trial_id": trial_id,
            "checkpoint_identity": None,
            "checkpoint": None,
            "recovery": "reorient_from_sources",
        }
    with _db(root, "working.sqlite3") as connection:
        row = connection.execute(
            "SELECT identity,payload FROM working_checkpoints WHERE batch_id=? AND trial_id=?",
            (batch_id, trial_id),
        ).fetchone()
    if row is None:
        return {
            "status": "absent",
            "reason": "not_saved",
            "trial_id": trial_id,
            "checkpoint_identity": None,
            "checkpoint": None,
            "recovery": "reorient_from_sources",
        }
    payload_bytes = bytes(row["payload"])
    payload = _decode_object(payload_bytes, "working checkpoint")
    checkpoint = WorkingCheckpoint.model_validate(payload)
    if (
        row["identity"] != checkpoint.identity
        or canonical_json_bytes(checkpoint.model_dump(mode="json", exclude_none=True))
        != payload_bytes
        or checkpoint.batch_id != batch_id
        or checkpoint.trial_id != trial_id
    ):
        raise ValueError("working checkpoint integrity check failed")
    reason = None
    if checkpoint.result_identity != _result_identity(state, trial_id):
        reason = "result_changed"
    elif checkpoint.source_scope != _source_scope(state, trial_id):
        reason = "source_changed"
    elif (
        checkpoint.domain_checkpoint_identities is not None
        and checkpoint.domain_checkpoint_identities
        != _domain_checkpoint_identities(state, trial_id)
    ):
        return {
            "status": "stale",
            "reason": "canonical_newer",
            "trial_id": trial_id,
            "checkpoint_identity": checkpoint.identity,
            "checkpoint": None,
            "recovery": "resume_from_canonical_checkpoint",
        }
    if reason is not None:
        return {
            "status": "stale",
            "reason": reason,
            "trial_id": trial_id,
            "checkpoint_identity": checkpoint.identity,
            "checkpoint": None,
            "recovery": "reorient_from_sources",
        }
    return {
        "status": "current",
        "reason": None,
        "trial_id": trial_id,
        "checkpoint_identity": checkpoint.identity,
        "checkpoint": checkpoint.model_dump(mode="json", exclude_none=True),
        "recovery": "resume_from_checkpoint",
    }

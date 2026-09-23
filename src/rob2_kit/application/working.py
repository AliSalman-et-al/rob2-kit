"""Source-bound working notes kept outside canonical assessment state."""

from pathlib import Path
from typing import Any

from ..models import canonical_json_bytes
from ..workflow_models import (
    WorkingCheckpoint,
    WorkingCheckpointDraft,
    WorkingDomainBinding,
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


def _domain_checkpoint_bindings(
    state: dict[str, Any], trial_id: str
) -> tuple[WorkingDomainBinding, ...]:
    records = state.get("domain_records")
    if not isinstance(records, dict):
        return ()
    return tuple(
        sorted(
            (
                WorkingDomainBinding(
                    domain_id=key.removeprefix(f"{trial_id}:"),
                    checkpoint_identity=record["identity"],
                )
                for key, record in records.items()
                if isinstance(key, str)
                and key.startswith(f"{trial_id}:")
                and isinstance(record, dict)
                and isinstance(record.get("identity"), str)
                and key.removeprefix(f"{trial_id}:")
                in {
                    "domain:randomization",
                    "domain:deviations",
                    "domain:missing",
                    "domain:measurement",
                    "domain:selection",
                }
            ),
            key=lambda item: item.domain_id,
        )
    )


def _ranges(draft: WorkingCheckpointDraft) -> tuple[WorkingSourceRange, ...]:
    values: list[WorkingSourceRange] = list(draft.unread_ranges)
    for group in (draft.observations, draft.interpretations, draft.open_questions, draft.drafts):
        for item in group:
            values.extend(item.sources)
    for item in draft.terminology:
        values.extend(item.sources)
    for premise in draft.premise_records:
        for item in (*premise.observations, *premise.counterevidence):
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
        "domain_checkpoint_bindings": [
            item.model_dump(mode="json") for item in _domain_checkpoint_bindings(state, trial_id)
        ],
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


def _stored_checkpoint(
    root: Path, state: dict[str, Any], trial_id: str
) -> WorkingCheckpoint | None:
    batch = state.get("batch")
    batch_id = batch.get("identity") if isinstance(batch, dict) else None
    if not isinstance(batch_id, str):
        return None
    with _db(root, "working.sqlite3") as connection:
        row = connection.execute(
            "SELECT identity,payload FROM working_checkpoints WHERE batch_id=? AND trial_id=?",
            (batch_id, trial_id),
        ).fetchone()
    if row is None:
        return None
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
    return checkpoint


def _note_source_ids(items: tuple[dict[str, Any], ...]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                source_id
                for item in items
                if isinstance(item, dict)
                for source in item.get("sources", ())
                if isinstance(source, dict)
                and isinstance((source_id := source.get("source_id")), str)
            }
        )
    )


def _investigation_status(premise: dict[str, Any] | None) -> tuple[str, str]:
    if not isinstance(premise, dict):
        return "not_established", "not_established"
    status = premise.get("status")
    if status == "support":
        return "supported", "host_asserted"
    if status == "contradiction":
        return "contradicted", "host_asserted"
    if status == "bounded":
        return "bounded", "host_asserted"
    if status == "unresolved":
        return (
            "bounded" if isinstance(premise.get("stopping_rationale"), str) else "unresolved",
            "host_asserted",
        )
    return "not_established", "not_established"


def investigation_projection(
    root: Path,
    state: dict[str, Any],
    trial_id: str | None,
    domain_id: str | None = None,
    *,
    workflow_permission: dict[str, Any] | None = None,
    sufficiency: tuple[str, str] | None = None,
) -> dict[str, Any] | None:
    """Project the existing working checkpoint into a host-facing investigation view.

    This is deliberately a read projection. It never creates a record, upgrades a
    host assertion into Evidence, or decides whether a Domain answer is correct.
    """

    if trial_id is None:
        return None
    checkpoint = _stored_checkpoint(root, state, trial_id)
    if checkpoint is None:
        from ..packs import SCIENTIFIC_PACK

        permission = workflow_permission or {
            "permitted": True,
            "operation": "save_working_checkpoint",
            "authority": "host",
            "detail": (
                "Working notes are optional and may be saved without changing canonical "
                "assessment state."
            ),
        }
        question = next(
            (
                item
                for item in SCIENTIFIC_PACK.questions
                if domain_id is not None and item.domain_id == domain_id
            ),
            None,
        )
        proposition = (
            question.wording
            if question is not None
            else "No source-grounded premise has been recorded yet."
        )
        source_scope = tuple(
            source_handle(item.source_id) for item in _source_scope(state, trial_id)
        )
        choices = [
            {
                "operation": "save_working_checkpoint",
                "available": True,
                "rationale": "Save source-linked observations without committing an answer.",
            },
            {
                "operation": "search_sources",
                "available": True,
                "rationale": "Search captured Sources for Evidence that discriminates the premise.",
            },
            {
                "operation": "read_pages",
                "available": True,
                "rationale": "Read exact Source pages before relying on a passage as Evidence.",
            },
            {
                "operation": "accept_limitation",
                "available": domain_id is not None,
                "rationale": (
                    "Record an honest limitation through Domain validation when accessible "
                    "investigation cannot resolve the premise."
                ),
            },
        ]
        legal_operation = permission.get("operation")
        if domain_id is not None and legal_operation != "validate_domain_assessment":
            choices.append(
                {
                    "operation": "validate_domain_assessment",
                    "available": True,
                    "rationale": (
                        "Revise the current Domain draft and validate its structure and "
                        "references without treating validation as semantic approval."
                    ),
                }
            )
        if permission.get("permitted") and legal_operation in {
            "validate_domain_assessment",
            "save_domain_judgment",
        }:
            choices.append(
                {
                    "operation": legal_operation,
                    "available": True,
                    "rationale": (
                        "Revise or continue the current Domain through the exact permitted "
                        "workflow operation; permission is not scientific sufficiency."
                    ),
                }
            )
        return {
            "proposition": proposition,
            "status": "not_established",
            "sufficiency": {"status": "not_established", "attribution": "not_established"},
            "workflow_permission": permission,
            "coverage": {
                "source_scope": source_scope,
                "observed_sources": (),
                "unread_sources": source_scope,
                "observed_note_count": 0,
                "state": "unobserved",
            },
            "observations": (),
            "support": (),
            "counterevidence": (),
            "unresolved": proposition,
            "recovery_choices": choices,
            "stopping_rationale": None,
            "stale": (),
            "checkpoint_identity": None,
            "legacy": "supported",
        }
    records = tuple(
        item.model_dump(mode="json", exclude_none=True)
        for item in (checkpoint.premise_records or ())
        if domain_id is None or item.domain_id in {None, domain_id}
    )
    premise = records[0] if records else None
    if premise is None:
        # A legacy/general checkpoint may still contain useful observations even
        # before a Domain-specific proposition has been written.
        proposition = "No Domain-specific premise has been recorded yet."
    else:
        proposition = str(premise["proposition"])
    current_sources = _source_scope(state, trial_id)
    source_scope = tuple(source_handle(item.source_id) for item in current_sources)
    source_changed = checkpoint.source_scope != current_sources
    result_changed = checkpoint.result_identity != _result_identity(state, trial_id)
    current_bindings = {
        item.domain_id: item.checkpoint_identity
        for item in _domain_checkpoint_bindings(state, trial_id)
    }
    saved_bindings = {
        item.domain_id: item.checkpoint_identity
        for item in (checkpoint.domain_checkpoint_bindings or ())
    }
    legacy = checkpoint.domain_checkpoint_bindings is None
    changed_domains = {
        key
        for key in set(current_bindings) | set(saved_bindings)
        if current_bindings.get(key) != saved_bindings.get(key)
    }
    related_domain_changed = (
        bool(changed_domains) if domain_id is None else domain_id in changed_domains
    )
    invalid_reason = (
        "result_changed" if result_changed else "source_changed" if source_changed else None
    )
    stale: list[dict[str, str]] = []
    if invalid_reason is not None:
        stale.extend(
            {"material": material, "reason": invalid_reason}
            for material in (
                "observations",
                "interpretations",
                "counterevidence",
                "premise_inference",
                "drafts",
                "stopping_rationale",
            )
        )
    elif legacy and related_domain_changed:
        stale.extend(
            {"material": material, "reason": "legacy_checkpoint"}
            for material in (
                "interpretations",
                "counterevidence",
                "premise_inference",
                "drafts",
                "stopping_rationale",
            )
        )
    elif related_domain_changed:
        stale.extend(
            {"material": material, "reason": "domain_revision"}
            for material in (
                "interpretations",
                "premise_inference",
                "drafts",
                "stopping_rationale",
            )
        )

    observations = tuple(
        item.model_dump(mode="json", exclude_none=True) for item in checkpoint.observations
    )
    premise_observations = tuple(premise.get("observations", ())) if premise else ()
    support = premise_observations if premise and premise.get("status") == "support" else ()
    counterevidence = tuple(premise.get("counterevidence", ())) if premise else ()
    observed = set(_note_source_ids(tuple(observations) + tuple(premise_observations)))
    unread = tuple(sorted({item.source_id for item in checkpoint.unread_ranges}))
    coverage_state = (
        "invalidated"
        if invalid_reason
        else "legacy"
        if legacy
        else "partial"
        if checkpoint.unread_ranges
        else "complete"
        if source_scope and set(source_scope) <= observed
        else "partial"
        if observed
        else "unobserved"
    )
    status, attribution = sufficiency or _investigation_status(premise)
    if invalid_reason is not None or related_domain_changed:
        status, attribution = "unresolved", "not_established"
    permission = workflow_permission or {
        "permitted": True,
        "operation": "save_working_checkpoint",
        "authority": "host",
        "detail": (
            "The working checkpoint is advisory and may be replaced without changing "
            "assessment state."
        ),
    }
    choices = [
        {
            "operation": "save_working_checkpoint",
            "available": True,
            "rationale": (
                "Replace source-linked working notes without changing canonical assessment state."
            ),
        },
        {
            "operation": "search_sources",
            "available": True,
            "rationale": (
                "Search captured Sources for a discriminating passage when the premise remains "
                "open."
            ),
        },
        {
            "operation": "read_pages",
            "available": True,
            "rationale": (
                "Read the exact cited or unread Source range before relying on it as Evidence."
            ),
        },
        {
            "operation": "accept_limitation",
            "available": domain_id is not None,
            "rationale": (
                "Record the unresolved premise and stopping rationale through Domain "
                "validation when further accessible investigation is not discriminating."
            ),
        },
    ]
    legal_operation = permission.get("operation")
    if domain_id is not None and legal_operation != "validate_domain_assessment":
        choices.append(
            {
                "operation": "validate_domain_assessment",
                "available": True,
                "rationale": (
                    "Revise the current Domain draft and validate its structure and references "
                    "without treating validation as semantic approval."
                ),
            }
        )
    if permission.get("permitted") and legal_operation in {
        "validate_domain_assessment",
        "save_domain_judgment",
    }:
        choices.append(
            {
                "operation": legal_operation,
                "available": True,
                "rationale": (
                    "Follow the current workflow permission; structural permission does not "
                    "establish scientific sufficiency."
                ),
            }
        )
    unresolved = premise.get("unresolved_component") if premise else None
    # Source-located observations remain useful for reorientation.  A changed
    # Domain or Source/Result makes the dependent interpretation stale, but it
    # must not erase the facts that tell the host what to revisit.
    stopping_rationale = (
        None
        if invalid_reason is not None or related_domain_changed
        else premise.get("stopping_rationale")
        if premise
        else None
    )
    return {
        "proposition": proposition,
        "status": status,
        "sufficiency": {"status": status, "attribution": attribution},
        "workflow_permission": permission,
        "coverage": {
            "source_scope": source_scope,
            "observed_sources": tuple(sorted(observed)),
            "unread_sources": unread,
            "observed_note_count": len(observations) + len(premise_observations),
            "state": coverage_state,
        },
        "observations": observations,
        "support": support,
        "counterevidence": counterevidence,
        "unresolved": unresolved,
        "recovery_choices": choices,
        "stopping_rationale": stopping_rationale,
        "stale": stale,
        "checkpoint_identity": checkpoint.identity,
        "legacy": "reorientation_required" if legacy else "supported",
    }


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

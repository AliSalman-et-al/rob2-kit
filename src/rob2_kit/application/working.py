"""Source-bound working notes kept outside canonical assessment state."""

from pathlib import Path
from typing import Any

from ..models import canonical_json_bytes
from ..workflow_models import (
    WorkingAccountNote,
    WorkingCheckpoint,
    WorkingCheckpointDraft,
    WorkingDomainBinding,
    WorkingNote,
    WorkingResultStep,
    WorkingSourceBinding,
    WorkingSourceRange,
)
from ..workflow_models import (
    _identity as _with_identity,
)
from ._state import (
    _db,
    _decode_object,
    _ensure,
    _reading_batch_basis,
    _result,
    _root,
    _state,
    _trial_inventory_basis,
)
from ._state import _identity as _digest
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
    for step in draft.result_account or ():
        for note in (step.observation, *step.counterevidence):
            for source in note.sources:
                if not isinstance(source, WorkingSourceRange):
                    raise ValueError("working_checkpoint_reference_not_resolved")
                values.append(source)
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
    page_text: dict[tuple[str, int], str] = {}
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
        if page_key not in page_text:
            with _db(root, "derivative.sqlite3") as connection:
                row = connection.execute(
                    "SELECT text FROM pages WHERE source_id=? AND page=?",
                    page_key,
                ).fetchone()
            if row is None:
                raise ValueError("working_checkpoint_locator_outside_source")
            page_text[page_key] = str(row["text"])
        line_count = len(page_text[page_key].splitlines())
        if item.end_line > line_count:
            raise ValueError("working_checkpoint_locator_outside_source")


def save_working_checkpoint(workspace: str | Path, draft: WorkingCheckpointDraft) -> dict[str, Any]:
    """Replace this Trial's bounded working notes without changing workflow state."""
    root = _root(workspace)
    _ensure(root)
    state = _state(root)
    batch = state.get("batch")
    trial_id = draft.trial_id
    batch_id = _trial_inventory_basis(state, trial_id)
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
    if draft.result_account is not None:
        from .evidence import _evidence_for_handles, source_reference_resolver

        resolve = source_reference_resolver(root, trial_id)

        def note_locations(note: WorkingAccountNote) -> WorkingNote:
            references = tuple(
                reference
                if isinstance(reference, WorkingSourceRange) and reference.start_line == 0
                else resolve(reference)
                for reference in note.sources
            )
            selected = _evidence_for_handles(
                root,
                {reference for reference in references if isinstance(reference, str)},
                trial_id,
            )
            by_handle = {item["handle"]: item for item in selected.values()}
            locations = []
            for reference in references:
                if isinstance(reference, WorkingSourceRange):
                    locations.append(reference)
                    continue
                item = by_handle[reference]
                locations.append(
                    WorkingSourceRange(
                        source_id=source_handle(item["source_id"]),
                        page=item["render"]["page"] if item["kind"] == "figure" else item["page"],
                        start_line=item.get("start_line", 0),
                        end_line=item.get("end_line", 0),
                    )
                )
            return WorkingNote.model_validate({**note.model_dump(), "sources": locations})

        normalized = tuple(
            WorkingResultStep.model_validate(
                {
                    **step.model_dump(),
                    "observation": note_locations(step.observation),
                    "counterevidence": tuple(note_locations(note) for note in step.counterevidence),
                }
            )
            for step in draft.result_account
        )
        draft = draft.model_copy(update={"result_account": normalized})
    source_scope = _source_scope(state, trial_id)
    if draft.result_account is not None:
        result_identity = _result_identity(state, trial_id)
        if result_identity is None:
            raise ValueError("Result account requires a selected Result")
        from .evidence import _evidence_for_handles

        steps = []
        for step in draft.result_account:
            counts = []
            for row in step.counts:
                if not row.basis:
                    raise ValueError("Account count rows require explicit current-Trial Evidence")
                _evidence_for_handles(root, set(row.basis), trial_id)
                if row.result_identity not in {None, result_identity}:
                    raise ValueError("Account count row belongs to a different Result")
                counts.append(row.model_copy(update={"result_identity": result_identity}))
            # Changes receive a new content identity; a host step name stays stable.
            updated = step.model_copy(update={"counts": tuple(counts), "identity": None})
            steps.append(_with_identity(updated, None))
        draft = draft.model_copy(update={"result_account": tuple(steps)})
        if "main_report_source_id" not in draft.model_fields_set:
            previous = _stored_checkpoint(root, state, trial_id)
            if previous is not None and previous.source_scope == source_scope:
                draft = draft.model_copy(
                    update={"main_report_source_id": previous.main_report_source_id}
                )
    if draft.result_account is None and "main_report_source_id" not in draft.model_fields_set:
        previous = _stored_checkpoint(root, state, trial_id)
        if previous is not None and previous.source_scope == source_scope:
            selected = previous.main_report_source_id
            if selected is not None:
                prior_observations = tuple(
                    note
                    for note in previous.observations
                    if selected == "missing"
                    or any(source.source_id == selected for source in note.sources)
                )
                observations = list(draft.observations)
                if not (
                    selected != "missing"
                    and any(
                        source.source_id == selected
                        for note in observations
                        for source in note.sources
                    )
                ):
                    for note in prior_observations:
                        if note in observations:
                            continue
                        if len(observations) >= 16:
                            raise ValueError(
                                "working_checkpoint_main_report_context_limit: keep the "
                                "source-backed report identity observation when replacing notes"
                            )
                        observations.insert(0, note)
                draft = draft.model_copy(
                    update={
                        "main_report_source_id": selected,
                        "observations": tuple(observations),
                    }
                )
    account_observations = tuple(step.observation for step in draft.result_account or ())
    observations = (*draft.observations, *account_observations)
    if draft.main_report_source_id == "missing" and not observations and sources:
        raise ValueError("working_checkpoint_main_report_missing_requires_observation")
    if isinstance(draft.main_report_source_id, str) and draft.main_report_source_id != "missing":
        if not any(
            isinstance(note_range, WorkingSourceRange)
            and note_range.source_id == draft.main_report_source_id
            for observation in observations
            for note_range in observation.sources
        ):
            raise ValueError("working_checkpoint_main_report_source_requires_observation")
    _validate_ranges(root, draft, sources, batch)
    value = {
        "batch_id": batch_id,
        "trial_id": trial_id,
        "result_identity": _result_identity(state, trial_id),
        "domain_checkpoint_identities": _domain_checkpoint_identities(state, trial_id),
        "domain_checkpoint_bindings": [
            item.model_dump(mode="json") for item in _domain_checkpoint_bindings(state, trial_id)
        ],
        "source_scope": [item.model_dump(mode="json") for item in source_scope],
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
        _trial_inventory_basis(current, trial_id) != batch_id
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


def main_report_identity(root: Path, state: dict[str, Any], trial_id: str) -> dict[str, Any]:
    """Resolve report identity from explicit intake roles or current source notes."""
    sources = _active_trial_sources(state, trial_id)
    declared = [
        source
        for source in sources
        if source.get("declared_role") == "main_article" and isinstance(source.get("id"), str)
    ]
    if declared:
        return {
            "identity_status": "identified",
            "identity_basis": "declared_role",
            "identity_sources": tuple(sorted(str(source["id"]) for source in declared)),
            "identity_observations": (),
        }

    checkpoint = _stored_checkpoint(root, state, trial_id)
    # Report identity is based on the captured source set, not on a Proposal
    # Result. Preserve this one source-backed observation when Results change.
    if checkpoint is None or checkpoint.source_scope != _source_scope(state, trial_id):
        return {
            "identity_status": "unresolved",
            "identity_basis": None,
            "identity_sources": (),
            "identity_observations": (),
        }

    observations = tuple(
        {
            "text": note.text,
            "sources": tuple(source.model_dump(mode="json") for source in note.sources),
        }
        for note in (
            *checkpoint.observations,
            *(step.observation for step in checkpoint.result_account or ()),
        )
    )
    selected = checkpoint.main_report_source_id
    if selected == "missing" and (observations or not sources):
        return {
            "identity_status": "missing",
            "identity_basis": "working_checkpoint",
            "identity_sources": (),
            "identity_observations": observations[:8],
        }
    if isinstance(selected, str):
        matches = tuple(
            source_id
            for owner_trial, source_id in source_handle_map(state.get("batch")).get(selected, ())
            if owner_trial == trial_id
        )
        if len(matches) == 1:
            basis = tuple(
                note
                for note in observations
                if any(
                    isinstance(source, dict) and source.get("source_id") == selected
                    for source in note["sources"]
                )
            )
            if basis:
                return {
                    "identity_status": "identified",
                    "identity_basis": "working_checkpoint",
                    "identity_sources": matches,
                    "identity_observations": basis[:8],
                }
    return {
        "identity_status": "unresolved",
        "identity_basis": None,
        "identity_sources": (),
        "identity_observations": observations[:8],
    }


def _stored_checkpoint(
    root: Path, state: dict[str, Any], trial_id: str
) -> WorkingCheckpoint | None:
    batch_id = _trial_inventory_basis(state, trial_id)
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


def _delivery_projection(
    root: Path,
    state: dict[str, Any],
    trial_id: str,
    sources: tuple[WorkingSourceBinding, ...],
    *,
    range_limit: int | None = 128,
) -> dict[str, Any]:
    """Report text ranges returned by read_pages separately from host note references."""

    batch_id = _reading_batch_basis(state)
    source_ids = tuple(item.source_id for item in sources)
    handles = {item.source_id: source_handle(item.source_id) for item in sources}
    if not isinstance(batch_id, str) or not source_ids:
        return {
            "state": "unobserved",
            "ranges": (),
            "delivered_sources": (),
            "sources_without_delivery": tuple(sorted(handles.values())),
        }

    placeholders = ",".join("?" for _ in source_ids)
    with _db(root, "derivative.sqlite3") as connection:
        rows = connection.execute(
            "SELECT phase,source_id,page,start_line,end_line FROM page_reads "
            f"WHERE batch_id=? AND trial_id=? AND source_id IN ({placeholders}) "
            "ORDER BY source_id,page,phase,start_line,end_line",
            (batch_id, trial_id, *source_ids),
        ).fetchall()
        pages = connection.execute(
            "SELECT source_id,page,text FROM pages "
            f"WHERE source_id IN ({placeholders}) ORDER BY source_id,page",
            source_ids,
        ).fetchall()

    ranges: list[dict[str, Any]] = []
    # Coverage is a union of delivered lines, not a history of read attempts.
    # Keep phases separate and retain gaps and the empty-page sentinel. The
    # original receipts remain in page_reads; compact before the preview limit.
    for row in rows:
        if str(row["source_id"]) not in handles:
            continue
        current = {
            "source_id": handles[str(row["source_id"])],
            "page": int(row["page"]),
            "start_line": int(row["start_line"]),
            "end_line": int(row["end_line"]),
            "phase": str(row["phase"]),
        }
        previous = ranges[-1] if ranges else None
        if (
            previous is not None
            and all(previous[key] == current[key] for key in ("source_id", "page", "phase"))
            and previous["start_line"] > 0
            and current["start_line"] > 0
            and current["start_line"] <= previous["end_line"] + 1
        ):
            previous["end_line"] = max(previous["end_line"], current["end_line"])
        else:
            ranges.append(current)
    ranges_by_page: dict[tuple[str, int], list[tuple[int, int]]] = {}
    for row in rows:
        source_id = str(row["source_id"])
        ranges_by_page.setdefault((source_id, int(row["page"])), []).append(
            (int(row["start_line"]), int(row["end_line"]))
        )
    pages_by_source: dict[str, list[Any]] = {}
    for row in pages:
        pages_by_source.setdefault(str(row["source_id"]), []).append(row)

    delivered = {str(row["source_id"]) for row in rows if str(row["source_id"]) in handles}
    fully_delivered: set[str] = set()
    for source_id, page_rows in pages_by_source.items():
        for page in page_rows:
            page_number = int(page["page"])
            line_count = len(str(page["text"]).splitlines())
            intervals = ranges_by_page.get((source_id, page_number), ())
            if line_count == 0:
                if not any(start == end == 0 for start, end in intervals):
                    break
                continue
            cursor = 1
            for start, end in sorted(intervals):
                if end < cursor:
                    continue
                if start > cursor:
                    break
                cursor = max(cursor, end + 1)
            if cursor <= line_count:
                break
        else:
            if page_rows:
                fully_delivered.add(source_id)

    all_delivered = all(
        source_id in fully_delivered for source_id in source_ids if source_id in pages_by_source
    ) and all(source_id in pages_by_source for source_id in source_ids)
    return {
        "state": ("delivered" if all_delivered else "partial" if delivered else "unobserved"),
        "ranges": tuple(ranges if range_limit is None else ranges[:range_limit]),
        "range_count": len(ranges),
        "delivered_sources": tuple(sorted(handles[item] for item in delivered)),
        "sources_without_delivery": tuple(
            sorted(handles[item] for item in set(source_ids) - delivered)
        ),
        "ranges_truncated": range_limit is not None and len(ranges) > range_limit,
    }


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
    active_question_ids: tuple[str, ...] | None = None,
) -> dict[str, Any] | None:
    """Project the existing working checkpoint into a host-facing investigation view.

    This is deliberately a read projection. It never creates a record, upgrades a
    host assertion into Evidence, or decides whether a Domain answer is correct.
    """

    if trial_id is None:
        return None
    checkpoint = _stored_checkpoint(root, state, trial_id)
    if checkpoint is None:
        permission = workflow_permission or {
            "permitted": True,
            "operation": "save_working_checkpoint",
            "authority": "host",
            "detail": (
                "Working notes are optional and may be saved without changing canonical "
                "assessment state."
            ),
        }
        proposition = (
            "Reconstruct selected-Result production: assignment, outcome collection, "
            "analysis and reporting."
        )
        source_bindings = _source_scope(state, trial_id)
        source_scope = tuple(source_handle(item.source_id) for item in source_bindings)
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
                    "Record an honest limitation in the Domain draft when accessible "
                    "investigation cannot resolve the premise."
                ),
            },
        ]
        legal_operation = permission.get("operation")
        if permission.get("permitted") and legal_operation == "save_domain_judgment":
            choices.append(
                {
                    "operation": legal_operation,
                    "available": True,
                    "rationale": (
                        "Submit the complete Domain draft; workflow permission does not "
                        "establish scientific sufficiency."
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
                **_delivery_projection(root, state, trial_id, source_bindings),
            },
            "host_notes": {
                "referenced_sources": (),
                "unread_ranges": (),
                "observation_count": 0,
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
            "premises": (),
        }
    records = tuple(
        item.model_dump(mode="json", exclude_none=True)
        for item in (checkpoint.premise_records or ())
        if domain_id is None or item.domain_id in {None, domain_id}
    )
    records = tuple(
        sorted(records, key=lambda item: (str(item.get("question_id") or ""), item["proposition"]))
    )
    active_order = {
        question_id: index for index, question_id in enumerate(active_question_ids or ())
    }
    unresolved_status = {"unresolved": 0, "bounded": 1, "contradiction": 2}
    premise = min(
        records,
        key=lambda item: (
            0 if item.get("question_id") in active_order else 1,
            unresolved_status.get(item.get("status"), 3),
            active_order.get(item.get("question_id"), len(active_order)),
            str(item.get("question_id") or ""),
            str(item["proposition"]),
        ),
        default=None,
    )
    if premise is None:
        # A legacy/general checkpoint may still contain useful observations even
        # before a Domain-specific proposition has been written.
        proposition = (
            "Apply the selected-Result reconstruction to this Domain's independent official "
            "propositions. Recover the complete account from working_checkpoint."
            if checkpoint.result_account is not None
            else "No Domain-specific premise has been recorded yet."
        )
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
        item.model_dump(mode="json", exclude_none=True)
        for item in (
            *checkpoint.observations,
            *(step.observation for step in checkpoint.result_account or ()),
        )
    )
    premise_observations = tuple(premise.get("observations", ())) if premise else ()
    all_premise_observations = tuple(
        note
        for record in records
        for note in record.get("observations", ())
        if isinstance(note, dict)
    )
    support = premise_observations if premise and premise.get("status") == "support" else ()
    counterevidence = tuple(premise.get("counterevidence", ())) if premise else ()
    noted_sources = tuple(sorted(_note_source_ids(tuple(observations) + all_premise_observations)))
    declared_unread_ranges = tuple(
        item.model_dump(mode="json") for item in checkpoint.unread_ranges
    )
    delivery = _delivery_projection(root, state, trial_id, current_sources)
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
                "submission when further accessible investigation is not discriminating."
            ),
        },
    ]
    legal_operation = permission.get("operation")
    if permission.get("permitted") and legal_operation == "save_domain_judgment":
        choices.append(
            {
                "operation": legal_operation,
                "available": True,
                "rationale": (
                    "Submit the complete Domain draft; workflow permission does not establish "
                    "scientific sufficiency."
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
            **delivery,
        },
        "host_notes": {
            "referenced_sources": noted_sources,
            "unread_ranges": declared_unread_ranges,
            "observation_count": len(observations) + len(all_premise_observations),
        },
        "observations": () if checkpoint.result_account is not None else observations,
        "support": support,
        "counterevidence": counterevidence,
        "unresolved": unresolved,
        "recovery_choices": choices,
        "stopping_rationale": stopping_rationale,
        "stale": stale,
        "checkpoint_identity": checkpoint.identity,
        "legacy": "reorientation_required" if legacy else "supported",
        "premises": records,
    }


def account_reconsideration(
    checkpoint: WorkingCheckpoint, state: dict[str, Any]
) -> list[dict[str, str]]:
    current = {step.id: step.identity for step in checkpoint.result_account or ()}
    affected = []
    for key, record in (state.get("domain_records") or {}).items():
        if not key.startswith(checkpoint.trial_id + ":"):
            continue
        for answer in record.get("answers", ()):
            for basis in answer.get("bases", ()):
                step = (basis.get("working_observation") or {}).get("result_step")
                if isinstance(step, dict) and current.get(step["id"]) != step["identity"]:
                    item = {
                        "domain_id": record["domain_id"],
                        "question_id": answer["question_id"],
                        "step_id": step["id"],
                        "step_identity": step["identity"],
                        "reason": "changed" if step["id"] in current else "removed",
                    }
                    if item not in affected:
                        affected.append(item)
    return affected


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
    batch_id = _trial_inventory_basis(state, trial_id)
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
    current_bindings = {
        item.domain_id: item.checkpoint_identity
        for item in _domain_checkpoint_bindings(state, trial_id)
    }
    saved_bindings = {
        item.domain_id: item.checkpoint_identity
        for item in (checkpoint.domain_checkpoint_bindings or ())
    }
    stale_domains = tuple(
        sorted(
            key
            for key in set(current_bindings) | set(saved_bindings)
            if current_bindings.get(key) != saved_bindings.get(key)
        )
    )
    canonical_changed = (
        bool(stale_domains)
        if checkpoint.domain_checkpoint_bindings is not None
        else (
            checkpoint.domain_checkpoint_identities is not None
            and checkpoint.domain_checkpoint_identities
            != _domain_checkpoint_identities(state, trial_id)
        )
    )
    if reason is None and canonical_changed:
        return {
            "status": "stale",
            "reason": "canonical_newer",
            "trial_id": trial_id,
            "checkpoint_identity": checkpoint.identity,
            "checkpoint": checkpoint.model_dump(mode="json", exclude_none=True),
            "stale_domains": stale_domains,
            "reconsideration": account_reconsideration(checkpoint, state),
            "recovery": "resume_from_checkpoint",
        }
    if reason is not None:
        return {
            "status": "stale",
            "reason": reason,
            "trial_id": trial_id,
            "checkpoint_identity": checkpoint.identity,
            "checkpoint": None,
            "stale_domains": (),
            "recovery": "reorient_from_sources",
        }
    return {
        "status": "current",
        "reason": None,
        "trial_id": trial_id,
        "checkpoint_identity": checkpoint.identity,
        "checkpoint": checkpoint.model_dump(mode="json", exclude_none=True),
        "stale_domains": (),
        "reconsideration": account_reconsideration(checkpoint, state),
        "recovery": "resume_from_checkpoint",
    }

from pathlib import Path
from typing import Any

from ..packs import SCIENTIFIC_PACK
from ._state import _ensure, _result, _root, _state
from .contracts import COUNTERS
from .evidence import _evidence_catalog, main_report_reading_status

_STATUS_RECOVERABLE_NARRATIVE_TEXT_BUDGET = 12_288


def _selected_evidence(workspace: Path) -> list[dict[str, Any]]:
    """Expose only the selected-material records needed to resume a proposal."""
    selected: list[dict[str, Any]] = []
    remaining = _STATUS_RECOVERABLE_NARRATIVE_TEXT_BUDGET
    for item in _evidence_catalog(workspace).values():
        if item.get("kind") == "narrative":
            keys = (
                "handle",
                "identity",
                "kind",
                "trial_id",
                "source_id",
                "page",
                "start_line",
                "end_line",
                "quote",
            )
            value = {key: item[key] for key in keys if key in item}
            has_exact_recovery = all(
                isinstance(item.get(key), int) for key in ("page", "start_line", "end_line")
            ) and all(isinstance(item.get(key), str) for key in ("trial_id", "source_id"))
            quote = item.get("quote")
            if has_exact_recovery and isinstance(quote, str):
                size = len(quote.encode("utf-8"))
                if size <= remaining:
                    remaining -= size
                    value["text_status"] = "complete"
                else:
                    value.pop("quote", None)
                    value["text_status"] = "omitted"
                    value["recovery"] = {
                        "operation": "read_pages",
                        "trial_id": item["trial_id"],
                        "windows": [
                            {
                                "source_id": item["source_id"],
                                "page": item["page"],
                                "start_line": item["start_line"],
                                "end_line": item["end_line"],
                            }
                        ],
                    }
            else:
                value["text_status"] = "complete"
            selected.append(value)
            continue
        elif item.get("kind") == "figure":
            keys = (
                "handle",
                "identity",
                "kind",
                "trial_id",
                "source_id",
                "transcription",
                "region",
                "render",
                "provenance",
            )
        else:
            continue
        selected.append({key: item[key] for key in keys if key in item})
    return sorted(selected, key=lambda value: str(value["handle"]))


def presentation(state: dict[str, Any]) -> dict[str, Any]:
    """Derive the one public status projection from durable workflow state."""
    dispositions = dict(state.get("trial_dispositions", {}))
    counts = {
        disposition: sum(value == disposition for value in dispositions.values())
        for disposition in ("assessed", "needs_input", "failed", "pending")
    }
    phase = str(state.get("phase", "empty"))
    total = len(dispositions)
    if phase == "finalized":
        wording = (
            "Batch finalized. No RoB 2 assessments were completed."
            if not counts["assessed"]
            else "Batch finalized. "
            f"RoB 2 assessments completed for {counts['assessed']}/{total} Trials. "
            f"{counts['needs_input']} Trials need input; {counts['failed']} Trials failed."
        )
    elif phase == "ready_to_finalize":
        wording = (
            "Batch incomplete. Continue now with head.next_action to finalize the Batch. Never "
            "stop, summarize, or ask whether to continue before finalization."
        )
    elif phase == "assessment":
        wording = (
            f"Batch incomplete: {counts['assessed']}/{total} Trials completed; "
            f"{counts['pending']} pending. Continue now with head.next_action. Never stop at a "
            "Trial boundary, ask whether to continue, infer pending Trial judgments, or reduce "
            "rigor for token or context limits."
        )
    elif counts["needs_input"] or counts["failed"]:
        wording = (
            "Batch incomplete. Continue now with head.next_action. Never stop, summarize, ask "
            "whether to continue, or infer pending Trial judgments."
        )
    elif phase == "proposal":
        if isinstance(state.get("review"), dict):
            wording = (
                "Proposal Review pending: the researcher may accept this source-reported "
                "candidate or ask the model to choose another candidate; no Trial is "
                "assessable until approval."
            )
        else:
            wording = "Proposal is being prepared or submitted; no Trial is assessable yet."
    else:
        wording = "No active Batch assessment exists."
    return {"counts": counts, "wording": wording}


def get_status(workspace: str | Path) -> dict[str, Any]:
    root = _root(workspace)
    _ensure(root)
    state = _state(root)
    dispositions = dict(state.get("trial_dispositions", {}))
    public = presentation(state)
    batch_value = state.get("batch")
    batch = batch_value if isinstance(batch_value, dict) else {}
    reading_trials = batch.get("trials", [])
    if state.get("phase") == "assessment":
        active_trial, _active_domain = _active_trial_and_domain(state)
        reading_trials = [
            trial
            for trial in reading_trials
            if isinstance(trial, dict) and trial.get("id") == active_trial
        ]
    raw_reading = (
        main_report_reading_status(
            root,
            reading_trials,
            phase=str(state.get("phase")),
        )
        if state.get("phase") in {"proposal", "assessment"}
        else {}
    )

    def public_windows(windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                key: value
                for key, value in item.items()
                if key in {"source_id", "page", "start_line", "end_line"}
            }
            for item in windows
        ]

    main_report_reading = {
        trial_id: {
            "status": item["status"],
            "budget_bytes": item["budget_bytes"],
            "covered_prefix_bytes": item["covered_prefix_bytes"],
            "required_ranges": public_windows(item["required_ranges"][:20]),
            "required_range_count": len(item["required_ranges"]),
            "unread_ranges": public_windows(item["unread_ranges"][:20]),
            "unread_range_count": len(item["unread_ranges"]),
        }
        for trial_id, item in raw_reading.items()
    }
    return _result(
        "success",
        state,
        trial_dispositions=dispositions,
        terminal_counts=public["counts"],
        continuation=_continuation(state),
        selected_evidence=_selected_evidence(root) if state.get("phase") == "proposal" else [],
        main_report_reading=main_report_reading,
        authoritative_wording=public["wording"],
        counters=dict(COUNTERS),
    )


def get_status_head(workspace: str | Path) -> dict[str, Any]:
    """Return continuation metadata without reading optional derivative Evidence."""
    root = _root(workspace)
    _ensure(root)
    state = _state(root)
    return _result(
        "success",
        state,
        continuation=_continuation(state),
        authoritative_wording=presentation(state)["wording"],
    )


def _active_trial_and_domain(state: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return the one pending Trial and Domain that may advance."""
    records = state.get("domain_records") or {}
    for trial_id, disposition in state.get("trial_dispositions", {}).items():
        if disposition != "pending":
            continue
        for domain in SCIENTIFIC_PACK.domains:
            if f"{trial_id}:{domain.id}" not in records:
                return trial_id, domain.id
    return None, None


def _continuation(state: dict[str, Any]) -> dict[str, Any] | None:
    phase = state.get("phase")
    if isinstance(state.get("review"), dict):
        review = state["review"]
        return {
            "operation": "researcher_review",
            "authority": "researcher",
            "review_reference": review["identity"],
            "purpose": review["purpose"],
        }
    if phase == "empty":
        return {
            "operation": "prepare_batch",
            "authority": "host",
            "expected_revision": int(state.get("revision", 0)),
            "caller_inputs": ["requested_outcome", "trial_labels"],
        }
    if phase == "proposal":
        return {
            "operation": "save_proposal",
            "authority": "host",
            "expected_revision": int(state.get("revision", 0)),
            "caller_inputs": ["results"],
        }
    if phase == "assessment":
        trial_id, domain_id = _active_trial_and_domain(state)
        if trial_id is not None and domain_id is not None:
            return {
                "operation": "get_domain_context",
                "authority": "host",
                "trial_id": trial_id,
                "domain_id": domain_id,
            }
        return None
    if phase == "ready_to_finalize":
        return {
            "operation": "finalize_batch",
            "authority": "host",
            "expected_revision": int(state.get("revision", 0)),
        }
    return None

"""Import the documented Codex MCP stream into a small privacy-safe artifact.

The importer intentionally observes structure only.  It does not preserve model
messages, tool arguments, returned text, or scientific explanations.  A manifest
is required to attach an explicit workflow identity to a transcript; no identity
is derived from a file name.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA = "rob2-kit.mcp-observations.v1"
MANIFEST_SCHEMA = "rob2-kit.observation-import-manifest.v1"
SUPPORTED_SERVERS = frozenset({"rob2"})
DOCUMENTED_TOOLS = frozenset(
    {
        "finalize_batch",
        "close_trial",
        "get_domain_context",
        "get_status",
        "list_sources",
        "prepare_batch",
        "read_pages",
        "render_page",
        "review_trial",
        "reason_domain_assessment",
        "reason_proposal",
        "request_proposal_approval",
        "request_trial_terminal",
        "save_domain_judgment",
        "save_working_checkpoint",
        "save_proposal",
        "search_sources",
        "search_sources_batch",
        "select_text_evidence",
        "select_visual_evidence",
        "validate_domain_assessment",
        "validate_proposal",
    }
)
SEARCH_MODES = frozenset({"all", "phrase", "any", "prefix", "literal"})
_PHASES = frozenset({"proposal", "assessment", "correction"})
_ACCEPTED_OUTCOMES = frozenset({"success", "review_required"})
_RESPONSE_OUTCOMES = frozenset(
    {"success", "review_required", "repair", "condition", "conflict", "error"}
)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_OPAQUE = re.compile(
    r"^(?:sha256:[0-9a-fA-F]{64}|(?:eh|sr|opt|source|passage|call|op|sh|ss)_[A-Za-z0-9_.:-]{1,127}|sc_[0-9a-f]{16}_[0-9]+|dcp2\.[A-Za-z0-9_.:-]{1,127})$"
)
_TERMINAL = {"assessed", "needs_input", "failed", "unknown"}


class ObservationImportError(ValueError):
    """A malformed manifest or transcript record with a safe location."""


def _fail(location: str, detail: str) -> ObservationImportError:
    return ObservationImportError(f"{location}: {detail}")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _id(value: Any) -> str | None:
    if not isinstance(value, str) or not value or not _SAFE_ID.fullmatch(value):
        return None
    return value


def _opaque(value: Any) -> str | None:
    return value if isinstance(value, str) and _OPAQUE.fullmatch(value) else None


def _obj(value: Any, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _fail(location, "expected an object")
    return value


def _string(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value:
        raise _fail(location, "expected a non-empty string")
    return value


def _manifest_attempts(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ObservationImportError("manifest: invalid schema")
    attempts = manifest.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        raise ObservationImportError("manifest: attempts must be a non-empty list")
    seen: set[str] = set()
    comparison = manifest.get("comparison_config")
    arm_ids: set[str] = (
        {
            arm["id"]
            for arm in comparison.get("arms", [])
            if isinstance(arm, dict) and isinstance(arm.get("id"), str)
        }
        if isinstance(comparison, dict)
        else set()
    )
    sessions_by_arm: dict[str, set[str]] = {}
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(attempts, 1):
        row = _obj(raw, f"manifest.attempts[{index}]")
        attempt_id = _string(row.get("attempt_id"), f"manifest.attempts[{index}].attempt_id")
        if not _SAFE_ID.fullmatch(attempt_id):
            raise _fail(f"manifest.attempts[{index}].attempt_id", "invalid opaque identity")
        if attempt_id in seen:
            raise _fail(f"manifest.attempts[{index}].attempt_id", "duplicate identity")
        if comparison is not None:
            arm = row.get("comparison_arm")
            session = row.get("session_id")
            if (
                not isinstance(arm, str)
                or arm not in arm_ids
                or not isinstance(session, str)
                or not session
            ):
                raise _fail(
                    f"manifest.attempts[{index}]", "comparison arm and session are required"
                )
            for other_arm, sessions in sessions_by_arm.items():
                if other_arm != arm and session in sessions:
                    raise _fail(
                        f"manifest.attempts[{index}].session_id",
                        "comparison arms require independent sessions",
                    )
            sessions_by_arm.setdefault(arm, set()).add(session)
        seen.add(attempt_id)
        result.append(row)
    return result


def _transcript_specs(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    specs: dict[str, dict[str, Any]] = {}
    attempts = _manifest_attempts(manifest)
    declared_attempts = {attempt["attempt_id"] for attempt in attempts}
    top = manifest.get("transcripts", [])
    if not isinstance(top, list):
        raise ObservationImportError("manifest.transcripts: expected a list")
    for index, raw in enumerate(top, 1):
        row = _obj(raw, f"manifest.transcripts[{index}]")
        transcript_id = _string(
            row.get("transcript_id"), f"manifest.transcripts[{index}].transcript_id"
        )
        attempt_id = row.get("attempt_id")
        if not isinstance(attempt_id, str) or attempt_id not in declared_attempts:
            raise _fail(f"manifest.transcripts[{index}]", "transcript has no declared attempt")
        if not _SAFE_ID.fullmatch(transcript_id):
            raise _fail(f"manifest.transcripts[{index}].transcript_id", "invalid opaque identity")
        if transcript_id in specs:
            raise _fail(f"manifest.transcripts[{index}].transcript_id", "duplicate identity")
        specs[transcript_id] = row
    for index, attempt in enumerate(attempts, 1):
        entries = attempt.get("transcripts", attempt.get("transcript_ids", []))
        if not isinstance(entries, list) or not entries:
            raise _fail(f"manifest.attempts[{index}].transcripts", "must be a non-empty list")
        for entry in entries:
            if isinstance(entry, str):
                transcript_id = entry
                row = {"transcript_id": entry, "attempt_id": attempt["attempt_id"]}
            else:
                row = _obj(entry, f"manifest.attempts[{index}].transcripts")
                transcript_id = _string(
                    row.get("transcript_id"), "transcript mapping.transcript_id"
                )
                row = {**row, "attempt_id": attempt["attempt_id"]}
            if transcript_id in specs and specs[transcript_id].get("attempt_id") not in (
                None,
                attempt["attempt_id"],
            ):
                raise _fail(
                    "manifest transcript mapping", "transcript belongs to multiple attempts"
                )
            specs[transcript_id] = {**specs.get(transcript_id, {}), **row}
    for transcript_id, spec in specs.items():
        if "phase" in spec and spec["phase"] not in _PHASES:
            raise _fail(f"manifest transcript {transcript_id}", "invalid transcript phase")
    phases = [spec.get("phase") for spec in specs.values()]
    if any(phase is not None for phase in phases) and any(phase is None for phase in phases):
        raise ObservationImportError("manifest transcripts: phase must be declared for all or none")
    if manifest.get("comparison_config") is not None:
        arm_by_attempt = {attempt["attempt_id"]: attempt["comparison_arm"] for attempt in attempts}
        sessions_by_arm: dict[str, set[str]] = {}
        for transcript_id, spec in specs.items():
            session_id = spec.get("session_id", transcript_id)
            if not isinstance(session_id, str) or not session_id:
                raise _fail(f"manifest transcript {transcript_id}", "session_id is required")
            arm = arm_by_attempt[spec["attempt_id"]]
            for other_arm, sessions in sessions_by_arm.items():
                if other_arm != arm and session_id in sessions:
                    raise _fail(
                        f"manifest transcript {transcript_id}.session_id",
                        "comparison arms require independent sessions",
                    )
            sessions_by_arm.setdefault(arm, set()).add(session_id)
    return specs


def load_manifest(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        data = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise ObservationImportError("manifest: unable to read JSON") from error
    _obj(data, "manifest")
    _manifest_attempts(data)
    _transcript_specs(data)
    return data


def _jsonl_records(raw: bytes, label: str) -> list[tuple[int, dict[str, Any]]]:
    records: list[tuple[int, dict[str, Any]]] = []
    try:
        lines = raw.decode("utf-8-sig").splitlines()
    except UnicodeDecodeError as error:
        raise _fail(f"{label}:1", "malformed JSONL record") from error
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise _fail(f"{label}:{number}", "malformed JSONL record") from error
        records.append((number, _obj(value, f"{label}:{number}")))
    return records


def _item(record: Mapping[str, Any], location: str) -> dict[str, Any] | None:
    if record.get("type") not in {"item.started", "item.completed"}:
        return None
    item = record.get("item")
    if not isinstance(item, dict) or item.get("type") != "mcp_tool_call":
        return None
    if (
        not isinstance(item.get("id"), str)
        or not item["id"]
        or not isinstance(item.get("tool"), str)
    ):
        raise _fail(location, "MCP call requires id and tool")
    if item["tool"] not in DOCUMENTED_TOOLS:
        raise _fail(location, "unsupported MCP tool")
    server = item.get("server")
    if not isinstance(server, str) or server not in SUPPORTED_SERVERS:
        raise _fail(location, "unsupported MCP server")
    arguments = item.get("arguments")
    if arguments is not None and not isinstance(arguments, dict):
        raise _fail(location, "MCP call arguments must be an object")
    if isinstance(arguments, dict) and "mode" in arguments:
        mode = arguments.get("mode")
        if not isinstance(mode, str) or mode not in SEARCH_MODES:
            raise _fail(location, "unsupported search mode")
    return item


def _structural_response(item: Mapping[str, Any]) -> dict[str, Any] | None:
    result = item.get("result")
    if not isinstance(result, dict):
        return None
    for key in ("structured_content", "structuredContent"):
        structured = result.get(key)
        if isinstance(structured, dict):
            return structured
    # Codex JSONL also stores the server response as one JSON object in content.
    content = result.get("content")
    if isinstance(content, list):
        for part in content:
            if (
                isinstance(part, dict)
                and part.get("type") == "text"
                and isinstance(part.get("text"), str)
            ):
                try:
                    parsed = json.loads(part["text"])
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    return parsed
    return None


def _response_encoding(item: Mapping[str, Any]) -> str:
    result = item.get("result")
    if not isinstance(result, dict):
        return "unavailable"
    if isinstance(result.get("structured_content"), dict) or isinstance(
        result.get("structuredContent"), dict
    ):
        return "structured_content"
    content = result.get("content")
    if isinstance(content, list) and any(
        isinstance(part, dict) and part.get("type") == "text" for part in content
    ):
        return "text_fallback"
    return "unavailable"


def _scope(
    arguments: Mapping[str, Any], response: Mapping[str, Any] | None
) -> dict[str, str | None]:
    data = response.get("data") if isinstance(response, dict) else None
    data = data if isinstance(data, dict) else {}
    values: dict[str, str | None] = {}
    for name in ("trial_id", "result_id", "domain_id", "question_id", "source_id"):
        candidate = arguments.get(name)
        if not isinstance(candidate, str):
            candidate = data.get(name)
        if not isinstance(candidate, str) and name == "domain_id":
            candidate = arguments.get("purpose_domain_id") or data.get("purpose_domain_id")
        if not isinstance(candidate, str) and name == "question_id":
            candidate = arguments.get("purpose_question_id") or data.get("purpose_question_id")
        values[name] = _id(candidate)
    return values


def _purpose(value: Mapping[str, Any] | None) -> dict[str, str | None]:
    value = value if isinstance(value, Mapping) else {}
    return {
        "domain_id": _id(value.get("purpose_domain_id")),
        "question_id": _id(value.get("purpose_question_id")),
    }


def _identity_values(value: Any, key: str = "") -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for name, child in value.items():
            if name.casefold() in {
                "identity",
                "handle",
                "id",
                "source_id",
                "passage_id",
                "evidence_id",
                "evidence_handle",
                "selected_evidence",
            }:
                opaque = _opaque(child)
                if opaque:
                    found.add(opaque)
            found.update(_identity_values(child, name))
    elif isinstance(value, list):
        for child in value:
            found.update(_identity_values(child, key))
    elif key.casefold() in {
        "evidence",
        "evidence_id",
        "evidence_handle",
        "evidence_refs",
        "selected_evidence",
        "passage_refs",
        "source_id",
        "passage_id",
        "source_handle",
        "cursor",
        "next_cursor",
        "session_handle",
    }:
        opaque = _opaque(value)
        if opaque:
            found.add(opaque)
    return found


def _answer_options(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if (
                key in {"id", "option_id", "answer_option_id"}
                and isinstance(child, str)
                and child.startswith("opt_")
            ):
                opaque = _opaque(child)
                if opaque:
                    found.add(opaque)
            found.update(_answer_options(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_answer_options(child))
    return found


def _evidence_refs(value: Any) -> list[str]:
    refs = sorted(item for item in _identity_values(value) if item.startswith("eh_"))
    return refs


def _committed_evidence(response: Mapping[str, Any] | None) -> list[str] | None:
    if not isinstance(response, dict) or response.get("outcome") not in _ACCEPTED_OUTCOMES:
        return None
    data = response.get("data")
    checkpoint = data.get("checkpoint") if isinstance(data, dict) else None
    if not isinstance(checkpoint, dict):
        return None
    refs = _evidence_refs(checkpoint)
    return refs or None


def _committed_options(response: Mapping[str, Any] | None) -> list[str] | None:
    if not isinstance(response, dict) or response.get("outcome") not in _ACCEPTED_OUTCOMES:
        return None
    data = response.get("data")
    checkpoint = data.get("checkpoint") if isinstance(data, dict) else None
    if not isinstance(checkpoint, dict):
        return None
    options = sorted(_answer_options(checkpoint))
    return options or None


def _committed_answers(response: Mapping[str, Any] | None) -> list[dict[str, str]] | None:
    if not isinstance(response, dict) or response.get("outcome") not in _ACCEPTED_OUTCOMES:
        return None
    data = response.get("data")
    checkpoint = data.get("checkpoint") if isinstance(data, dict) else None
    answers = checkpoint.get("answers") if isinstance(checkpoint, dict) else None
    if not isinstance(answers, list):
        return None
    rows = [
        {"question_id": answer["question_id"], "answer": answer["answer"]}
        for answer in answers
        if isinstance(answer, dict)
        and isinstance(answer.get("question_id"), str)
        and isinstance(answer.get("answer"), str)
    ]
    return rows or None


def _logical_searches(
    tool: str, arguments: Mapping[str, Any], response: Mapping[str, Any] | None
) -> list[dict[str, Any]]:
    """Project a transport search and any independent child queries."""
    data = response.get("data") if isinstance(response, Mapping) else None
    if tool == "search_sources_batch":
        requests = arguments.get("requests")
        results = data.get("results") if isinstance(data, dict) else None
        requests = requests if isinstance(requests, list) else []
        results_by_index = (
            {
                row.get("index"): row
                for row in results
                if isinstance(row, dict) and isinstance(row.get("index"), int)
            }
            if isinstance(results, list)
            else {}
        )
        children = []
        for index, request in enumerate(requests):
            if not isinstance(request, dict):
                continue
            result = results_by_index.get(index)
            nested = result.get("result") if isinstance(result, dict) else None
            nested_data = nested.get("data") if isinstance(nested, dict) else None
            children.append(
                {
                    "index": index,
                    "scope": _scope(request, None),
                    "purpose": _purpose(request),
                    "mode": request.get("mode")
                    if isinstance(request.get("mode"), str) and request["mode"] in SEARCH_MODES
                    else None,
                    "has_cursor": isinstance(request.get("cursor"), str),
                    "outcome": nested.get("outcome") if isinstance(nested, dict) else None,
                    "hit_count": len(nested_data["hits"])
                    if isinstance(nested_data, dict) and isinstance(nested_data.get("hits"), list)
                    else None,
                    "has_next_cursor": isinstance(nested_data, dict)
                    and isinstance(nested_data.get("next_cursor"), str),
                }
            )
        return children
    if tool != "search_sources":
        return []
    return [
        {
            "index": 0,
            "scope": _scope(arguments, response),
            "purpose": _purpose(arguments),
            "mode": arguments.get("mode")
            if isinstance(arguments.get("mode"), str) and arguments["mode"] in SEARCH_MODES
            else None,
            "has_cursor": isinstance(arguments.get("cursor"), str),
            "outcome": response.get("outcome") if isinstance(response, Mapping) else None,
            "hit_count": len(data["hits"])
            if isinstance(data, dict) and isinstance(data.get("hits"), list)
            else None,
            "has_next_cursor": isinstance(data, dict) and isinstance(data.get("next_cursor"), str),
        }
    ]


def _answer_observations(checkpoint: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Project revision-relevant facts without retaining scientific prose."""
    if not isinstance(checkpoint, Mapping):
        return []
    observations: list[dict[str, Any]] = []
    for answer in checkpoint.get("answers", []):
        if not isinstance(answer, Mapping) or not isinstance(answer.get("question_id"), str):
            continue
        locators: list[dict[str, Any]] = []
        bases = answer.get("bases", [])
        for basis in bases if isinstance(bases, list) else []:
            if not isinstance(basis, Mapping):
                continue
            locator = {
                key: basis[key]
                for key in ("evidence", "source_id", "page", "start_line", "end_line")
                if key in basis
            }
            if locator:
                locators.append(locator)
        justification = answer.get("justification")
        unknowns = answer.get("unknowns")
        unknowns = unknowns if isinstance(unknowns, list) else []
        counterevidence = answer.get("counterevidence")
        counterevidence = counterevidence if isinstance(counterevidence, list) else []
        observations.append(
            {
                "question_id": answer["question_id"],
                "answer": answer.get("answer"),
                "justification_digest": (
                    _digest(justification) if isinstance(justification, str) else None
                ),
                "justification_bytes": len(justification.encode("utf-8"))
                if isinstance(justification, str)
                else 0,
                "unknown_count": len(unknowns),
                "unknowns_digest": _digest(unknowns),
                "counterevidence_count": len(counterevidence),
                "counterevidence_digest": _digest(counterevidence),
                "evidence_locators": locators,
            }
        )
    return observations


def _operation(
    item: Mapping[str, Any],
    transcript_id: str,
    session_id: str,
    observed_options: set[str],
    observed_evidence: set[str],
    committed_checkpoints: dict[str, Mapping[str, Any]],
) -> dict[str, Any]:
    arguments = item.get("arguments")
    arguments = arguments if isinstance(arguments, dict) else {}
    response = _structural_response(item)
    data = response.get("data") if isinstance(response, dict) else None
    response_options = _answer_options(response)
    response_evidence = set(_evidence_refs(response))
    outcome = response.get("outcome") if response else None
    status = (
        "accepted"
        if outcome in _ACCEPTED_OUTCOMES
        else "rejected"
        if response or item.get("error")
        else "unmatched"
    )
    tool = item["tool"]
    event_records = item.get("_event_records")
    event_records = event_records if isinstance(event_records, list) else []
    thread_identity = item.get("_thread_identity")
    thread_instance = item.get("_thread_instance")
    op_key = _canonical([transcript_id, thread_instance, thread_identity, item["id"]])
    event_positions = [
        {
            "type": event["type"],
            "event_ordinal": event["event_ordinal"],
            "line": event["line"],
        }
        for event in event_records
        if isinstance(event, dict)
    ]
    started_events = [event for event in event_positions if event["type"] == "item.started"]
    completed_events = [event for event in event_positions if event["type"] == "item.completed"]
    operation: dict[str, Any] = {
        "operation_id": "op_" + hashlib.sha256(op_key).hexdigest(),
        "session_id": _id(session_id),
        "call_id": _id(item["id"]),
        "transcript_id": _id(transcript_id),
        "thread_identity": _opaque(thread_identity),
        "event_order": {
            "started": started_events[0] if started_events else None,
            "completed": completed_events[0] if completed_events else None,
            "start_events": started_events,
            "completion_events": completed_events,
        },
        "tool": tool,
        "status": status,
        "scope": _scope(arguments, response),
        "purpose": _purpose(arguments),
        "request_identities": sorted(_identity_values(arguments)),
        "request_shape": {
            "has_search_term": isinstance(arguments.get("query"), str),
            "mode": arguments.get("mode") if isinstance(arguments.get("mode"), str) else None,
            "limit": arguments.get("limit")
            if isinstance(arguments.get("limit"), int)
            and not isinstance(arguments.get("limit"), bool)
            else None,
            "has_cursor": isinstance(arguments.get("cursor"), str),
            "argument_count": len(arguments),
        },
        "response": {
            "present": response is not None or isinstance(item.get("result"), dict),
            "outcome": outcome if outcome in _RESPONSE_OUTCOMES else None,
            "response_bytes": len(_canonical(item.get("result")))
            if isinstance(item.get("result"), dict)
            else None,
            "identities": sorted(_identity_values(response)) if response else [],
            "hit_count": None,
            "truncated": None,
            "zero_hits": None,
            "terminal_dispositions": [],
            "encoding": _response_encoding(item),
            "logical_searches": _logical_searches(tool, arguments, response),
            "continuation": {
                "requested": isinstance(arguments.get("cursor"), str),
                "returned": isinstance(data, dict) and isinstance(data.get("next_cursor"), str),
            },
        },
        "metrics": {
            "cost": None,
            "tokens": None,
            "context_bytes": None,
            "latency_ms": None,
        },
    }
    if response:
        data = response.get("data")
        if isinstance(data, dict):
            hits = data.get("hits")
            operation["response"]["hit_count"] = (
                len(hits)
                if isinstance(hits, list)
                else data.get("candidate_count")
                if isinstance(data.get("candidate_count"), int)
                else None
            )
            operation["response"]["truncated"] = (
                data.get("truncated") if isinstance(data.get("truncated"), bool) else None
            )
            operation["response"]["zero_hits"] = (
                True
                if data.get("condition") == "no_hits"
                else data.get("total_matches") == 0
                if isinstance(data.get("total_matches"), int)
                else None
            )
            dispositions = data.get("trial_dispositions")
            if isinstance(dispositions, dict):
                operation["response"]["terminal_dispositions"] = sorted(
                    value for value in dispositions.values() if value in _TERMINAL
                )
            terminal = data.get("terminal")
            if (
                tool == "request_trial_terminal"
                and outcome in _ACCEPTED_OUTCOMES
                and isinstance(terminal, dict)
                and terminal.get("disposition") in {"needs_input", "failed"}
            ):
                operation["response"]["terminal_dispositions"] = [terminal["disposition"]]
    if tool in {"select_text_evidence", "select_visual_evidence"}:
        refs = _evidence_refs(response) if status == "accepted" else []
        operation["selection"] = refs or None
    if outcome == "repair":
        data = response.get("data") if isinstance(response, dict) else None
        raw_repairs = response.get("repairs") if isinstance(response, dict) else None
        if not isinstance(raw_repairs, list) and isinstance(data, dict):
            raw_repairs = data.get("repairs")
        repair_rows = raw_repairs if isinstance(raw_repairs, list) else []
        codes = sorted(
            {
                item["code"]
                for item in repair_rows
                if isinstance(item, Mapping) and isinstance(item.get("code"), str) and item["code"]
            }
        )
        paths = sorted(
            {
                item["path"]
                for item in repair_rows
                if isinstance(item, Mapping)
                and isinstance(item.get("path"), str)
                and item["path"].startswith("/")
            }
        )
        repair_observations = []
        for item in repair_rows:
            if not isinstance(item, Mapping):
                continue
            row = {
                key: item[key]
                for key in ("code", "path")
                if isinstance(item.get(key), str) and item[key]
            }
            if row:
                repair_observations.append(row)
        operation["repair"] = {
            "kind": "mechanical_validation",
            "count": len(repair_rows),
            "codes": codes,
            "paths": paths,
            "rows": repair_observations,
        }
    if tool.startswith("save_") or tool in {
        "request_proposal_approval",
        "request_trial_terminal",
    }:
        checkpoint = (
            response.get("data", {}).get("checkpoint")
            if isinstance(response, dict) and isinstance(response.get("data"), dict)
            else None
        )
        checkpoint = checkpoint if isinstance(checkpoint, dict) else {}
        identity = _opaque(checkpoint.get("identity"))
        supersedes = _opaque(checkpoint.get("supersedes"))
        mutation: dict[str, Any] = {
            "accepted": status == "accepted",
            "checkpoint_identity": identity,
            "supersedes": supersedes,
            "submitted_evidence_ids": sorted(set(_evidence_refs(arguments)) & observed_evidence)
            or None,
            "committed_evidence_ids": _committed_evidence(response),
            "submitted_option_ids": sorted(_answer_options(arguments) & observed_options) or None,
            "committed_option_ids": _committed_options(response),
            "committed_answers": _committed_answers(response),
        }
        operation["mutation"] = mutation
        checkpoint = (
            response.get("data", {}).get("checkpoint") if isinstance(response, dict) else None
        )
        if isinstance(checkpoint, dict) and isinstance(checkpoint.get("supersedes"), str):
            basis = checkpoint.get("revision_basis")
            revision_basis = dict(basis) if isinstance(basis, dict) else None
            if revision_basis is not None:
                rationale = revision_basis.pop("rationale", None)
                if isinstance(rationale, str):
                    revision_basis["rationale_digest"] = _digest(rationale)
                    revision_basis["rationale_bytes"] = len(rationale.encode("utf-8"))
            mutation["revision"] = {
                "before_identity": checkpoint["supersedes"],
                "after_identity": checkpoint.get("identity"),
                "before": _answer_observations(committed_checkpoints.get(checkpoint["supersedes"])),
                "after": _answer_observations(checkpoint),
                "revision_reason": revision_basis,
            }
        if (
            status == "accepted"
            and isinstance(checkpoint, dict)
            and isinstance(checkpoint.get("identity"), str)
        ):
            committed_checkpoints[checkpoint["identity"]] = checkpoint
    observed_options.update(response_options)
    observed_evidence.update(response_evidence)
    return operation


def _merge_call(previous: dict[str, Any], item: dict[str, Any], location: str) -> dict[str, Any]:
    left = {
        key: value for key, value in previous.items() if key not in {"result", "error", "status"}
    }
    right = {key: value for key, value in item.items() if key not in {"result", "error", "status"}}
    if _canonical(left) != _canonical(right):
        raise _fail(location, "ambiguous duplicate MCP operation identity")
    merged = dict(previous)
    for key in ("result", "error"):
        if key in item and item.get(key) is not None:
            if (
                key in merged
                and merged[key] is not None
                and _canonical(merged[key]) != _canonical(item[key])
            ):
                raise _fail(location, "ambiguous duplicate MCP operation identity")
            merged[key] = item[key]
    if item.get("status") is not None:
        merged["status"] = item["status"]
    return merged


def _relative_path(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or (path.parts and path.parts[0].endswith(":")):
        return None
    return path.as_posix()


def _read_transcript(
    raw: bytes, transcript_id: str, path: Any = None
) -> tuple[list[dict[str, Any]], int, int, dict[str, Any], list[dict[str, Any]]]:
    records = _jsonl_records(raw, transcript_id)
    calls: dict[tuple[int, str], dict[str, Any]] = {}
    call_events: dict[tuple[int, str], list[dict[str, Any]]] = {}
    call_threads: dict[tuple[int, str], str | None] = {}
    order: list[tuple[int, str]] = []
    stream: list[dict[str, Any]] = []
    thread_identities: list[str] = []
    active_thread: str | None = None
    thread_instance = 0
    imported_records = 0
    for event_ordinal, (number, record) in enumerate(records, 1):
        record_type = record.get("type")
        if record_type == "thread.started":
            thread_instance += 1
            thread_id = record.get("thread_id")
            active_thread = _digest(thread_id) if isinstance(thread_id, str) else None
            if active_thread is not None:
                thread_identities.append(active_thread)
            stream.append(
                {
                    "type": "thread.started",
                    "event_ordinal": event_ordinal,
                    "line": number,
                    "thread_identity": active_thread,
                }
            )
        elif record_type in {"turn.started", "turn.completed"}:
            stream.append(
                {
                    "type": record_type,
                    "event_ordinal": event_ordinal,
                    "line": number,
                    "thread_identity": active_thread,
                }
            )
        item = _item(record, f"{transcript_id}:{number}")
        if item is None:
            continue
        imported_records += 1
        call_id = item["id"]
        existing_keys = [key for key in order if key[1] == call_id]
        pending = next(
            (
                key
                for key in reversed(existing_keys)
                if not any(event["type"] == "item.completed" for event in call_events[key])
            ),
            None,
        )
        if record_type == "item.started" or pending is None and not existing_keys:
            key = (thread_instance, call_id)
        elif pending is not None:
            key = pending
        else:
            key = existing_keys[-1]
        event = {
            "type": record_type,
            "event_ordinal": event_ordinal,
            "line": number,
            "thread_identity": active_thread,
            "thread_instance": thread_instance,
        }
        call_events.setdefault(key, []).append(event)
        if key not in calls:
            calls[key] = item
            call_threads[key] = active_thread
            order.append(key)
        else:
            calls[key] = _merge_call(calls[key], item, f"{transcript_id}:{number}")
        thread_identity = call_threads[key]
        operation_id = (
            "op_"
            + hashlib.sha256(
                _canonical([transcript_id, key[0], thread_identity, call_id])
            ).hexdigest()
        )
        stream.append(
            {
                **event,
                "operation_id": operation_id,
                "call_id": _id(call_id),
                "tool": item["tool"],
                "thread_identity": thread_identity,
                "thread_instance": key[0],
            }
        )
    merged_calls = []
    for key in order:
        item = dict(calls[key])
        item["_event_records"] = call_events[key]
        item["_thread_identity"] = call_threads[key]
        item["_thread_instance"] = key[0]
        merged_calls.append(item)
    metadata = {
        "transcript_id": _id(transcript_id),
        "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "path": _relative_path(path),
        "records": len(records),
        "event_count": len(stream),
        "thread_identities": list(dict.fromkeys(thread_identities)),
    }
    return merged_calls, len(records), imported_records, metadata, stream


def _manifest_transcript_bytes(
    spec: Mapping[str, Any], supplied: Mapping[str, bytes] | None
) -> bytes:
    transcript_id = _string(spec.get("transcript_id"), "transcript mapping.transcript_id")
    if supplied and transcript_id in supplied:
        return supplied[transcript_id]
    path = spec.get("path")
    if not isinstance(path, str) or not path:
        raise ObservationImportError(
            f"transcript {transcript_id}: no supplied bytes or manifest path"
        )
    try:
        return Path(path).read_bytes()
    except OSError as error:
        raise ObservationImportError(f"transcript {transcript_id}: unable to read JSONL") from error


def import_observations(
    manifest: Mapping[str, Any], transcripts: Mapping[str, bytes] | None = None
) -> dict[str, Any]:
    """Return a deterministic observation artifact from a frozen manifest and JSONL bytes."""
    attempts = _manifest_attempts(manifest)
    specs = _transcript_specs(manifest)
    attempt_by_id = {attempt["attempt_id"]: attempt for attempt in attempts}
    grouped: dict[str, list[dict[str, Any]]] = {attempt["attempt_id"]: [] for attempt in attempts}
    for transcript_id, spec in specs.items():
        attempt_id = spec.get("attempt_id")
        if attempt_id is None:
            continue
        if attempt_id not in attempt_by_id:
            raise ObservationImportError(f"manifest transcript {transcript_id}: unknown attempt")
        grouped[attempt_id].append(spec)
    if transcripts is not None:
        unknown = set(transcripts) - set(specs)
        if unknown:
            raise ObservationImportError("supplied transcript: identity is absent from manifest")
    output_attempts: list[dict[str, Any]] = []
    total_records = imported_records = 0
    all_operations = 0
    all_searches = 0
    phase_searches = 0
    for attempt in attempts:
        attempt_id = attempt["attempt_id"]
        observed_options: set[str] = set()
        observed_evidence: set[str] = set()
        committed_checkpoints: dict[str, Mapping[str, Any]] = {}
        search_count = 0
        assessment_search_count = 0
        operations: list[dict[str, Any]] = []
        imported_transcripts: list[dict[str, Any]] = []
        event_stream: list[dict[str, Any]] = []
        for spec in grouped[attempt_id]:
            transcript_id = _string(spec.get("transcript_id"), "transcript mapping.transcript_id")
            session_id = _string(
                spec.get("session_id", transcript_id), f"transcript {transcript_id}.session_id"
            )
            raw = _manifest_transcript_bytes(spec, transcripts)
            calls, records, imported, transcript_receipt, events = _read_transcript(
                raw, transcript_id, spec.get("path")
            )
            total_records += records
            imported_records += imported
            transcript_receipt["phase"] = spec.get("phase")
            imported_transcripts.append(transcript_receipt)
            event_stream.extend(
                {
                    **event,
                    "transcript_id": transcript_receipt["transcript_id"],
                    "transcript_digest": transcript_receipt["digest"],
                }
                for event in events
            )
            for item in calls:
                operation = _operation(
                    item,
                    transcript_id,
                    session_id,
                    observed_options,
                    observed_evidence,
                    committed_checkpoints,
                )
                operations.append(operation)
                logical_search_count = len(operation["response"]["logical_searches"])
                if logical_search_count:
                    search_count += logical_search_count
                    if spec.get("phase") in {"assessment", "correction"}:
                        assessment_search_count += logical_search_count
        all_operations += len(operations)
        all_searches += search_count
        phase_searches += assessment_search_count
        terminal = attempt.get("terminal_disposition")
        if terminal not in _TERMINAL:
            terminal = "unknown"
        observed_terminal_values = {
            value
            for row in operations
            for value in row["response"].get("terminal_dispositions", [])
        }
        if len(observed_terminal_values) == 1:
            terminal = next(iter(observed_terminal_values))
        finalized = any(
            row["tool"] == "finalize_batch" and row["status"] == "accepted" for row in operations
        )
        capture_status = "complete" if finalized else "incomplete"
        attempted_mutations = [
            {
                "operation_id": row["operation_id"],
                "tool": row["tool"],
                "accepted": row["mutation"]["accepted"],
                "checkpoint_identity": row["mutation"]["checkpoint_identity"],
                "supersedes": row["mutation"]["supersedes"],
                "submitted_evidence_ids": row["mutation"]["submitted_evidence_ids"],
                "committed_evidence_ids": row["mutation"]["committed_evidence_ids"],
                "submitted_option_ids": row["mutation"]["submitted_option_ids"],
                "committed_option_ids": row["mutation"]["committed_option_ids"],
                "revision": row["mutation"].get("revision"),
            }
            for row in operations
            if "mutation" in row
        ]
        accepted_commits = [row for row in attempted_mutations if row["accepted"]]
        output_attempt = {
            "attempt_id": attempt_id,
            "trial_id": _id(attempt.get("trial_id")),
            "result_id": _opaque(
                attempt.get("result_id") or attempt.get("approved_result_identity")
            ),
            "intervention_id": _id(attempt.get("intervention_id")),
            "model": {
                "family": _id((attempt.get("model") or {}).get("family"))
                if isinstance(attempt.get("model"), dict)
                else None,
                "version": _id((attempt.get("model") or {}).get("version"))
                if isinstance(attempt.get("model"), dict)
                else None,
            },
            "kit_revision": _id(attempt.get("kit_revision")),
            "capture_status": capture_status,
            "terminal_disposition": terminal,
            "transcripts": imported_transcripts,
            "event_stream": event_stream,
            "reconciliation": {
                "operations": len(operations),
                "searches": search_count,
                "assessment_searches": assessment_search_count
                if all(spec.get("phase") is not None for spec in grouped[attempt_id])
                else None,
            },
            "attempted_mutations": attempted_mutations,
            "accepted_commits": accepted_commits,
            "operations": operations,
        }
        if manifest.get("comparison_config") is not None:
            output_attempt["comparison_arm"] = _id(attempt.get("comparison_arm"))
            output_attempt["session_id"] = _id(attempt.get("session_id"))
        output_attempts.append(output_attempt)
    # The assessment search count is the issue's diagnostic count when phases are
    # declared; otherwise all observed search calls are the only available count.
    phases_known = all(spec.get("phase") is not None for spec in specs.values())
    searches = phase_searches if phases_known else all_searches
    artifact = {
        "schema": SCHEMA,
        "manifest_identity": _digest(manifest),
        "attempts": output_attempts,
        "reconciliation": {
            "workflow_attempts": len(output_attempts),
            "records": total_records,
            "imported_mcp_records": imported_records,
            "ignored_host_records": total_records - imported_records,
            "mcp_calls": all_operations,
            "searches": searches,
            "assessment_searches": phase_searches if phases_known else None,
        },
    }
    return artifact


def dump_observations(artifact: Mapping[str, Any], path: str | Path) -> None:
    """Write canonical JSON without timestamps or other nondeterministic fields."""
    Path(path).write_bytes(_canonical(artifact) + b"\n")


__all__ = [
    "MANIFEST_SCHEMA",
    "SCHEMA",
    "DOCUMENTED_TOOLS",
    "ObservationImportError",
    "SEARCH_MODES",
    "SUPPORTED_SERVERS",
    "dump_observations",
    "import_observations",
    "load_manifest",
]

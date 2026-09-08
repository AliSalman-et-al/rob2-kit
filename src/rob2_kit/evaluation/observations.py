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
from pathlib import Path
from typing import Any

SCHEMA = "rob2-kit.mcp-observations.v1"
MANIFEST_SCHEMA = "rob2-kit.observation-import-manifest.v1"
SUPPORTED_SERVERS = frozenset({"rob2"})
DOCUMENTED_TOOLS = frozenset(
    {
        "finalize_batch",
        "get_domain_context",
        "get_status",
        "list_sources",
        "prepare_batch",
        "read_pages",
        "render_page",
        "request_proposal_approval",
        "request_trial_terminal",
        "save_domain_judgment",
        "save_proposal",
        "search_sources",
        "select_text_evidence",
        "select_visual_evidence",
    }
)
SEARCH_MODES = frozenset({"all", "phrase", "any", "prefix"})
_PHASES = frozenset({"proposal", "assessment", "correction"})
_ACCEPTED_OUTCOMES = frozenset({"success", "review_required"})
_RESPONSE_OUTCOMES = frozenset(
    {"success", "review_required", "repair", "condition", "conflict", "error"}
)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_OPAQUE = re.compile(
    r"^(?:sha256:[0-9a-fA-F]{64}|(?:eh|sr|opt|source|passage|call|op)_[A-Za-z0-9_.:-]{1,127})$"
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
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(attempts, 1):
        row = _obj(raw, f"manifest.attempts[{index}]")
        attempt_id = _string(row.get("attempt_id"), f"manifest.attempts[{index}].attempt_id")
        if not _SAFE_ID.fullmatch(attempt_id):
            raise _fail(f"manifest.attempts[{index}].attempt_id", "invalid opaque identity")
        if attempt_id in seen:
            raise _fail(f"manifest.attempts[{index}].attempt_id", "duplicate identity")
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


def _scope(
    arguments: Mapping[str, Any], response: Mapping[str, Any] | None
) -> dict[str, str | None]:
    data = response.get("data") if isinstance(response, dict) else None
    data = data if isinstance(data, dict) else {}
    values: dict[str, str | None] = {}
    for name in ("trial_id", "result_id", "domain_id", "question_id"):
        candidate = arguments.get(name)
        if not isinstance(candidate, str):
            candidate = data.get(name)
        values[name] = _id(candidate)
    return values


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


def _operation(
    item: Mapping[str, Any],
    transcript_id: str,
    session_id: str,
    observed_options: set[str],
    observed_evidence: set[str],
) -> dict[str, Any]:
    arguments = item.get("arguments")
    arguments = arguments if isinstance(arguments, dict) else {}
    response = _structural_response(item)
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
    op_key = _canonical([transcript_id, item["id"]])
    operation: dict[str, Any] = {
        "operation_id": "op_" + hashlib.sha256(op_key).hexdigest(),
        "session_id": _id(session_id),
        "call_id": _id(item["id"]),
        "transcript_id": _id(transcript_id),
        "tool": tool,
        "status": status,
        "scope": _scope(arguments, response),
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
        operation["mutation"] = {
            "accepted": status == "accepted",
            "checkpoint_identity": identity,
            "supersedes": supersedes,
            "submitted_evidence_ids": sorted(set(_evidence_refs(arguments)) & observed_evidence)
            or None,
            "committed_evidence_ids": _committed_evidence(response),
            "submitted_option_ids": sorted(_answer_options(arguments) & observed_options) or None,
            "committed_option_ids": _committed_options(response),
        }
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


def _read_transcript(raw: bytes, transcript_id: str) -> tuple[list[dict[str, Any]], int, int]:
    records = _jsonl_records(raw, transcript_id)
    calls: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    imported_records = 0
    for number, record in records:
        item = _item(record, f"{transcript_id}:{number}")
        if item is None:
            continue
        imported_records += 1
        call_id = item["id"]
        if call_id not in calls:
            calls[call_id] = item
            order.append(call_id)
        else:
            calls[call_id] = _merge_call(calls[call_id], item, f"{transcript_id}:{number}")
    return [calls[call_id] for call_id in order], len(records), imported_records


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
        search_count = 0
        assessment_search_count = 0
        operations: list[dict[str, Any]] = []
        for spec in grouped[attempt_id]:
            transcript_id = _string(spec.get("transcript_id"), "transcript mapping.transcript_id")
            session_id = _string(
                spec.get("session_id", transcript_id), f"transcript {transcript_id}.session_id"
            )
            calls, records, imported = _read_transcript(
                _manifest_transcript_bytes(spec, transcripts), transcript_id
            )
            total_records += records
            imported_records += imported
            for item in calls:
                operation = _operation(
                    item,
                    transcript_id,
                    session_id,
                    observed_options,
                    observed_evidence,
                )
                operations.append(operation)
                if operation["tool"] == "search_sources":
                    search_count += 1
                    if spec.get("phase") in {"assessment", "correction"}:
                        assessment_search_count += 1
        operations.sort(key=lambda row: row["operation_id"])
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
            }
            for row in operations
            if "mutation" in row
        ]
        accepted_commits = [row for row in attempted_mutations if row["accepted"]]
        output_attempts.append(
            {
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
                "reconciliation": {
                    "operations": len(operations),
                    "searches": search_count,
                    "assessment_searches": assessment_search_count,
                },
                "attempted_mutations": attempted_mutations,
                "accepted_commits": accepted_commits,
                "operations": operations,
            }
        )
    # The assessment search count is the issue's diagnostic count when phases are
    # declared; otherwise all observed search calls are the only available count.
    searches = phase_searches if any(spec.get("phase") for spec in specs.values()) else all_searches
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
            "assessment_searches": phase_searches,
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

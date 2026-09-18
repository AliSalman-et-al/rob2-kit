"""Validate a privacy-safe integrated qualification report.

The report is deliberately a receipt, not a scorer.  It records what was
checked and what the host exposed; an inaccessible host observation can never
be converted into a passing observation by this module.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

SCHEMA = "rob2-kit.integrated-qualification.v1"
PROMOTIONS = frozenset({"promote", "hold"})
STATUSES = frozenset(
    {
        "gain",
        "regression",
        "unsupported_reassurance",
        "concern",
        "scope_correction",
        "completion",
        "failure",
        "context",
        "latency",
        "cost",
    }
)
MECHANICAL_KINDS = frozenset({"build", "pack", "skill", "source", "config", "integrity"})
OBSERVATION_KINDS = frozenset({"text", "image", "guidance", "schema", "continuation"})
ATTEMPT_STATUSES = STATUSES
_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_PRIVATE = frozenset(
    {
        "path",
        "paths",
        "source",
        "sources",
        "content",
        "prompt",
        "prompts",
        "trace",
        "traces",
        "credential",
        "credentials",
        "rationale",
        "transcript",
        "transcripts",
    }
)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def identity(value: Any) -> str:
    """Return the canonical identity for a JSON-serializable frozen value."""
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _private(value: Any, location: str = "$") -> list[str]:
    if isinstance(value, dict):
        errors = [
            f"{location}: private field {key!r}"
            for key in value
            if isinstance(key, str)
            and key.casefold() in _PRIVATE
            and not (location == "$.identity" and key == "source")
        ]
        return errors + [
            error for key, child in value.items() for error in _private(child, f"{location}.{key}")
        ]
    if isinstance(value, list):
        return [
            error
            for index, child in enumerate(value)
            for error in _private(child, f"{location}[{index}]")
        ]
    if isinstance(value, str) and ("/" in value or "\\" in value):
        return [f"{location}: paths are forbidden"]
    return []


def _closed(row: object, fields: set[str], location: str, errors: list[str]) -> bool:
    if not isinstance(row, dict) or set(row) != fields:
        errors.append(f"{location} has an unclosed field set")
        return False
    return True


def _valid_id(value: object) -> bool:
    return isinstance(value, str) and _ID.fullmatch(value) is not None


def _valid_status(value: object) -> bool:
    return isinstance(value, str) and value in STATUSES


def validate(report: object) -> list[str]:
    """Return structural/privacy errors, without echoing private payloads."""
    if not isinstance(report, dict):
        return ["report must be an object"]
    errors = _private(report)
    fields = {"schema", "identity", "mechanical", "observations", "attempts", "promotion"}
    if not _closed(report, fields, "report", errors):
        return errors
    if report["schema"] != SCHEMA:
        errors.append("report schema is invalid")
    frozen = report["identity"]
    identity_fields = {"build", "pack", "skill", "source", "config"}
    if _closed(frozen, identity_fields, "identity", errors):
        if any(
            not isinstance(frozen[key], str) or not _HASH.fullmatch(frozen[key]) for key in frozen
        ):
            errors.append("frozen identities are invalid")

    mechanical = report["mechanical"]
    mechanical_ids: set[str] = set()
    if not isinstance(mechanical, list) or not mechanical:
        errors.append("mechanical checks must be a non-empty list")
    else:
        for index, check in enumerate(mechanical):
            location = f"mechanical[{index}]"
            if not _closed(check, {"check_id", "kind", "status", "observed"}, location, errors):
                continue
            check_id = check["check_id"]
            if not _valid_id(check_id) or (
                isinstance(check_id, str) and check_id in mechanical_ids
            ):
                errors.append(f"{location}.check_id is invalid or duplicated")
            if isinstance(check_id, str) and _valid_id(check_id):
                mechanical_ids.add(check_id)
            if (
                not isinstance(check["kind"], str)
                or check["kind"] not in MECHANICAL_KINDS
                or not _valid_status(check["status"])
            ):
                errors.append(f"{location} kind or status is invalid")
            if not isinstance(check["observed"], bool):
                errors.append(f"{location}.observed is invalid")

    observations = report["observations"]
    observation_ids: set[str] = set()
    observation_rows: list[dict[str, Any]] = []
    if not isinstance(observations, list) or not observations:
        errors.append("host observations must be a non-empty list")
    else:
        for index, observation in enumerate(observations):
            location = f"observations[{index}]"
            if not _closed(
                observation,
                {"observation_id", "attempt_id", "host", "kind", "status", "observable"},
                location,
                errors,
            ):
                continue
            observation_rows.append(observation)
            observation_id = observation["observation_id"]
            if not _valid_id(observation_id) or (
                isinstance(observation_id, str) and observation_id in observation_ids
            ):
                errors.append(f"{location}.observation_id is invalid or duplicated")
            if isinstance(observation_id, str) and _valid_id(observation_id):
                observation_ids.add(observation_id)
            if not _valid_id(observation["attempt_id"]) or not _valid_id(observation["host"]):
                errors.append(f"{location} identity is invalid")
            if (
                not isinstance(observation["kind"], str)
                or observation["kind"] not in OBSERVATION_KINDS
                or not _valid_status(observation["status"])
            ):
                errors.append(f"{location} kind or status is invalid")
            if (
                observation["observable"] is not True
                and observation["observable"] is not False
                and observation["observable"] is not None
            ):
                errors.append(f"{location}.observable is invalid")

    attempts = report["attempts"]
    attempt_ids: set[str] = set()
    attempt_hosts: dict[str, str] = {}
    if not isinstance(attempts, list) or not attempts:
        errors.append("attempts must be a non-empty list")
    else:
        for index, attempt in enumerate(attempts):
            location = f"attempts[{index}]"
            if not _closed(attempt, {"attempt_id", "host", "status"}, location, errors):
                continue
            attempt_id = attempt["attempt_id"]
            if not _valid_id(attempt_id) or (
                isinstance(attempt_id, str) and attempt_id in attempt_ids
            ):
                errors.append(f"{location}.attempt_id is invalid or duplicated")
            if isinstance(attempt_id, str) and _valid_id(attempt_id):
                attempt_ids.add(attempt_id)
                if _valid_id(attempt["host"]):
                    attempt_hosts[attempt_id] = attempt["host"]
            if not _valid_id(attempt["host"]) or not _valid_status(attempt["status"]):
                errors.append(f"{location} host or status is invalid")

    if observation_rows and attempt_ids:
        observation_attempt_ids = {
            row["attempt_id"]
            for row in observation_rows
            if isinstance(row["attempt_id"], str) and _valid_id(row["attempt_id"])
        }
        if observation_attempt_ids - attempt_ids:
            errors.append("host observation references an undeclared attempt")
        for index, observation in enumerate(observation_rows):
            attempt_host = attempt_hosts.get(str(observation["attempt_id"]))
            if attempt_host is not None and observation["host"] != attempt_host:
                errors.append(f"observations[{index}] host does not match its attempt")

    if attempt_hosts:
        observed_hosts = {
            row["host"] for row in observation_rows if row.get("host") in attempt_hosts.values()
        }
        observed_by_host = {
            host: {
                row["kind"]
                for row in observation_rows
                if row.get("host") == host
                and isinstance(row.get("kind"), str)
                and row["kind"] in OBSERVATION_KINDS
            }
            for host in observed_hosts
        }
        for host, observed_kinds in sorted(observed_by_host.items()):
            missing = OBSERVATION_KINDS - observed_kinds
            if missing:
                errors.append(
                    f"required host observations are missing for {host}: "
                    + ", ".join(sorted(missing))
                )
    expected_promotion = "promote"
    if errors:
        expected_promotion = "hold"
    elif (
        any(
            not check["observed"] or check["status"] in {"failure", "regression", "concern"}
            for check in mechanical
        )
        or any(
            row["observable"] is not True
            or row["status"] in {"failure", "regression", "concern", "scope_correction"}
            for row in observation_rows
        )
        or any(attempt["status"] in {"failure", "regression", "concern"} for attempt in attempts)
    ):
        expected_promotion = "hold"
    promotion = report["promotion"]
    if not isinstance(promotion, str) or promotion not in PROMOTIONS:
        errors.append("promotion is invalid")
    elif promotion != expected_promotion:
        errors.append("promotion does not match recorded evidence")
    return errors


def promotion_decision(report: object) -> str:
    """Return the conservative decision; malformed reports are held."""
    return report["promotion"] if isinstance(report, dict) and not validate(report) else "hold"

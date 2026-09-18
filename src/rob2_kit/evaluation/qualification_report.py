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
_DELIVERIES = frozenset({"success", "repairable_error", "unobservable"})


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
            and not (location in {"$.identity", "$.qualification"} and key == "source")
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
    if set(report) not in (fields, fields | {"qualification"}):
        errors.append("report has an unclosed field set")
        return errors
    if report["schema"] != SCHEMA:
        errors.append("report schema is invalid")
    frozen = report["identity"]
    identity_fields = {"build", "pack", "skill", "source", "config"}
    extended_identity_fields = identity_fields | {
        "executable",
        "tools",
        "schemas",
        "protocol",
        "runtime",
    }
    if not isinstance(frozen, dict) or set(frozen) not in (
        identity_fields,
        extended_identity_fields,
    ):
        errors.append("identity has an unclosed field set")
    elif isinstance(frozen, dict):
        if any(
            not isinstance(frozen[key], str) or not _HASH.fullmatch(frozen[key]) for key in frozen
        ):
            errors.append("frozen identities are invalid")
    qualification = report.get("qualification")
    if qualification is not None:
        qualification_fields = extended_identity_fields
        if not isinstance(frozen, dict) or set(frozen) != extended_identity_fields:
            errors.append("qualification requires the extended frozen identity set")
        if _closed(qualification, qualification_fields, "qualification", errors):
            if any(
                not isinstance(qualification[key], str) or not _HASH.fullmatch(qualification[key])
                for key in qualification
            ):
                errors.append("qualification identities are invalid")
            elif isinstance(frozen, dict) and set(frozen) == extended_identity_fields:
                if any(qualification[key] != frozen[key] for key in qualification_fields):
                    errors.append("qualification identities do not match frozen identities")

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
            observation_fields = {
                "observation_id",
                "attempt_id",
                "host",
                "kind",
                "status",
                "observable",
            }
            extended_observation_fields = observation_fields | {
                "delivery",
                "payload_digest",
                "error_code",
            }
            if not isinstance(observation, dict) or set(observation) not in (
                observation_fields,
                extended_observation_fields,
            ):
                errors.append(f"{location} has an unclosed field set")
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
            if "delivery" in observation and observation["delivery"] not in _DELIVERIES:
                errors.append(f"{location}.delivery is invalid")
            if "payload_digest" in observation and (
                observation["payload_digest"] is not None
                and (
                    not isinstance(observation["payload_digest"], str)
                    or not _HASH.fullmatch(observation["payload_digest"])
                )
            ):
                errors.append(f"{location}.payload_digest is invalid")
            if "error_code" in observation and (
                observation["error_code"] is not None
                and (
                    not isinstance(observation["error_code"], str)
                    or not _valid_id(observation["error_code"])
                )
            ):
                errors.append(f"{location}.error_code is invalid")
            delivery = observation.get("delivery")
            if delivery == "success" and (
                observation.get("observable") is not True
                or not isinstance(observation.get("payload_digest"), str)
                or observation.get("error_code") is not None
            ):
                errors.append(f"{location}.successful delivery is incomplete")
            if delivery == "repairable_error" and (
                observation.get("observable") is not True
                or not isinstance(observation.get("payload_digest"), str)
                or not isinstance(observation.get("error_code"), str)
            ):
                errors.append(f"{location}.repairable delivery is incomplete")
            if delivery == "unobservable" and observation.get("observable") is True:
                errors.append(f"{location}.unobservable delivery is contradictory")

    attempts = report["attempts"]
    attempt_ids: set[str] = set()
    attempt_hosts: dict[str, str] = {}
    attempt_statuses: dict[str, str] = {}
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
                if isinstance(attempt.get("status"), str):
                    attempt_statuses[attempt_id] = attempt["status"]
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
        rows_by_attempt = {
            (attempt_id, host): [
                row
                for row in observation_rows
                if row.get("attempt_id") == attempt_id and row.get("host") == host
            ]
            for attempt_id, host in attempt_hosts.items()
        }
        extended_delivery = any("delivery" in row for row in observation_rows)
        for (attempt_id, host), attempt_rows in sorted(rows_by_attempt.items()):
            if attempt_statuses.get(attempt_id) == "failure":
                continue
            observed_kinds = {
                row["kind"]
                for row in attempt_rows
                if isinstance(row.get("kind"), str) and row["kind"] in OBSERVATION_KINDS
            }
            missing = OBSERVATION_KINDS - observed_kinds
            if missing:
                errors.append(
                    f"required host observations are missing for {host} ({attempt_id}): "
                    + ", ".join(sorted(missing))
                )
            if extended_delivery:
                for kind in sorted(OBSERVATION_KINDS):
                    deliveries = {
                        row.get("delivery") for row in attempt_rows if row.get("kind") == kind
                    }
                    if "success" not in deliveries:
                        errors.append(
                            "successful host observation is missing for "
                            f"{host} ({attempt_id}): {kind}"
                        )
                    if "repairable_error" not in deliveries:
                        errors.append(
                            "repairable-error host observation is missing for "
                            f"{host} ({attempt_id}): {kind}"
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

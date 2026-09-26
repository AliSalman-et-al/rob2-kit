"""Bind source-backed benchmark scope decisions to immutable identities."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA = "rob2-kit.benchmark-scope-adjudications.v2"
RELATIONS = {"exact", "broader", "narrower", "component", "related"}
DECISIONS = {"equivalent", "accepted_with_scope_difference"}


def expected_result_sha256(expected_result: dict[str, Any]) -> str:
    payload = json.dumps(expected_result, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(payload).hexdigest()


def load_scope_adjudications(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise ValueError(f"scope adjudication file has an unsupported schema: {path}")
    rows = payload.get("adjudications")
    if not isinstance(rows, list):
        raise ValueError(f"scope adjudication rows are missing: {path}")
    seen: set[tuple[str, str, str, str, str]] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f"scope adjudication row is malformed: {path}")
        required = (
            "outcome",
            "trial",
            "expected_result_sha256",
            "review_identity",
            "result_identity",
            "observed_relation",
            "decision",
            "rationale",
            "source_citation",
        )
        if any(not isinstance(row.get(key), str) or not row[key].strip() for key in required):
            raise ValueError(f"scope adjudication row is incomplete: {path}")
        digest = row["expected_result_sha256"]
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError(f"scope adjudication expected-result hash is malformed: {path}")
        if row["decision"] not in DECISIONS:
            raise ValueError(
                f"unsupported scope adjudication decision: {row['decision']!r}"
            )
        if row["observed_relation"] not in RELATIONS:
            raise ValueError(
                f"unsupported scope adjudication relation: {row['observed_relation']!r}"
            )
        if (
            row["decision"] == "accepted_with_scope_difference"
            and row["observed_relation"] not in {"broader", "related"}
        ):
            raise ValueError(
                "accepted_with_scope_difference requires a broader or related observed_relation"
            )
        key = (
            row["outcome"],
            row["trial"],
            digest,
            row["review_identity"],
            row["result_identity"],
            row["observed_relation"],
        )
        if key in seen:
            raise ValueError(f"duplicate scope adjudication identity: {path}")
        seen.add(key)
    return rows


def matching_scope_adjudication(
    adjudications: list[dict[str, Any]],
    *,
    outcome: str,
    trial: str,
    expected_result: dict[str, Any],
    review_identity: object,
    result_identity: object,
    relation: object,
) -> dict[str, Any] | None:
    if (
        not isinstance(review_identity, str)
        or not isinstance(result_identity, str)
        or not isinstance(relation, str)
    ):
        return None
    expected_hash = expected_result_sha256(expected_result)
    matches = [
        row
        for row in adjudications
        if row["outcome"] == outcome
        and row["trial"] == trial
        and row["expected_result_sha256"] == expected_hash
        and row["review_identity"] == review_identity
        and row["result_identity"] == result_identity
        and row["observed_relation"] == relation
    ]
    return matches[0] if len(matches) == 1 else None

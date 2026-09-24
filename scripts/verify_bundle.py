#!/usr/bin/env python3
"""Verify a .rob2.zip without importing the rob2_kit package.

This deliberately stays a small, dependency-free boundary check.  The bundle
manifest and canonical identity are producer-independent; all checks here are
recomputed from bytes read from the archive.
"""

from __future__ import annotations

import hashlib
import json
import math
import posixpath
import re
import sys
import unicodedata
import zipfile
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, cast

_EXPECTED_DOMAIN_IDS = frozenset(
    {
        "domain:randomization",
        "domain:deviations",
        "domain:missing",
        "domain:measurement",
        "domain:selection",
    }
)
_EXPECTED_DOMAIN_ORDER = (
    "domain:randomization",
    "domain:deviations",
    "domain:missing",
    "domain:measurement",
    "domain:selection",
)
_SOURCE_ROLE_ORDER = {
    "main_article": 0,
    "registry": 1,
    "supplement": 2,
    "sap": 3,
    "protocol": 4,
}


def _source_order_key(source: dict[str, Any]) -> tuple[int, str, str]:
    return (
        _SOURCE_ROLE_ORDER.get(str(source.get("role")), 5),
        str(source.get("logical_path", "")).casefold(),
        str(source.get("id", "")),
    )


def _ordered_sources(sources: Any) -> list[dict[str, Any]]:
    return sorted(
        (source for source in sources if isinstance(source, dict)),
        key=_source_order_key,
    )


_DOMAIN_QUESTION_IDS = {
    "domain:randomization": {
        "sq:randomization:sequence",
        "sq:randomization:concealment",
        "sq:randomization:baseline-imbalance",
    },
    "domain:deviations": {
        "sq:deviations:participants-aware",
        "sq:deviations:personnel-aware",
        "sq:deviations:context-deviations",
        "sq:deviations:affected-outcome",
        "sq:deviations:balanced",
        "sq:deviations:appropriate-analysis",
        "sq:deviations:substantial-impact",
    },
    "domain:missing": {
        "sq:missing:data-available",
        "sq:missing:evidence-unbiased",
        "sq:missing:true-value-dependent",
        "sq:missing:likely-dependent",
    },
    "domain:measurement": {
        "sq:measurement:method-inappropriate",
        "sq:measurement:differential",
        "sq:measurement:assessor-aware",
        "sq:measurement:influence-possible",
        "sq:measurement:influence-likely",
    },
    "domain:selection": {
        "sq:selection:prespecified-analysis",
        "sq:selection:multiple-measurements",
        "sq:selection:multiple-analyses",
    },
}
_DOMAIN_QUESTION_ORDER = {
    domain_id: tuple(question_ids)
    for domain_id, question_ids in (
        (
            "domain:randomization",
            (
                "sq:randomization:sequence",
                "sq:randomization:concealment",
                "sq:randomization:baseline-imbalance",
            ),
        ),
        (
            "domain:deviations",
            (
                "sq:deviations:participants-aware",
                "sq:deviations:personnel-aware",
                "sq:deviations:context-deviations",
                "sq:deviations:affected-outcome",
                "sq:deviations:balanced",
                "sq:deviations:appropriate-analysis",
                "sq:deviations:substantial-impact",
            ),
        ),
        (
            "domain:missing",
            (
                "sq:missing:data-available",
                "sq:missing:evidence-unbiased",
                "sq:missing:true-value-dependent",
                "sq:missing:likely-dependent",
            ),
        ),
        (
            "domain:measurement",
            (
                "sq:measurement:method-inappropriate",
                "sq:measurement:differential",
                "sq:measurement:assessor-aware",
                "sq:measurement:influence-possible",
                "sq:measurement:influence-likely",
            ),
        ),
        (
            "domain:selection",
            (
                "sq:selection:prespecified-analysis",
                "sq:selection:multiple-measurements",
                "sq:selection:multiple-analyses",
            ),
        ),
    )
}
_ANSWER_VALUES = frozenset({"yes", "probably_yes", "probably_no", "no", "no_information"})
_QUESTION_ALLOWED_ANSWERS = {
    "sq:missing:evidence-unbiased": frozenset({"yes", "probably_yes", "probably_no", "no"})
}
_SCIENTIFIC_PACK = {
    "id": "rob2.parallel.assignment",
    "version": "2019.1",
    "result_semantics_version": "rob2-kit.result-semantics.v0.8",
    "content_hash": "sha256:1a2fde94dbfe7b8f1e696a98921c050943166136646efe7cc50d7883bef95a33",
    "official_source": {
        "version": "22 August 2019",
        "source_sha256": "A9E9C4FDC4BE2D29B5C0A1A6B828E09F2014A34F6D5C302A532F6153EA0FD670",
    },
}
_CURRENT_PACK_PRE_SEMANTIC_GUIDANCE = {
    "id": "rob2.parallel.assignment",
    "version": "2019.1",
    "result_semantics_version": "rob2-kit.result-semantics.v0.8",
    "content_hash": "sha256:bb4f07a86662df2decaad739013e1178a6767aceb9b63e6b438c7f98074d5d84",
    "official_source": {
        "version": "22 August 2019",
        "source_sha256": "A9E9C4FDC4BE2D29B5C0A1A6B828E09F2014A34F6D5C302A532F6153EA0FD670",
    },
}
_CURRENT_PACK_PRE_INFERENCE_GATES = {
    "id": "rob2.parallel.assignment",
    "version": "2019.1",
    "result_semantics_version": "rob2-kit.result-semantics.v0.8",
    "content_hash": "sha256:aeeb5c8aa3fa8f9fd46f4429ae93a4b8ea3f6d89cc292640305f1aa702a449ea",
    "official_source": {
        "version": "22 August 2019",
        "source_sha256": "A9E9C4FDC4BE2D29B5C0A1A6B828E09F2014A34F6D5C302A532F6153EA0FD670",
    },
}
_CURRENT_PACK_PRE_DEVIATIONS_GUIDANCE = {
    "id": "rob2.parallel.assignment",
    "version": "2019.1",
    "result_semantics_version": "rob2-kit.result-semantics.v0.8",
    "content_hash": "sha256:7cd97694107582be8fe6cd1091b8a851b631fed0e90aa5b453ffa8d4d9f50d17",
    "official_source": {
        "version": "22 August 2019",
        "source_sha256": "A9E9C4FDC4BE2D29B5C0A1A6B828E09F2014A34F6D5C302A532F6153EA0FD670",
    },
}
_CURRENT_PACK_LEGACY_PROOF = {
    "id": "rob2.parallel.assignment",
    "version": "2019.1",
    "result_semantics_version": "rob2-kit.result-semantics.v0.8",
    "content_hash": "sha256:86ad209ba3504bbe353049245b44cebf3b7d83862b2b3e475c431c6fec0a581f",
    "official_source": {
        "version": "22 August 2019",
        "source_sha256": "A9E9C4FDC4BE2D29B5C0A1A6B828E09F2014A34F6D5C302A532F6153EA0FD670",
    },
}
_CURRENT_PACK_PRIOR_GUIDANCE = {
    "id": "rob2.parallel.assignment",
    "version": "2019.1",
    "result_semantics_version": "rob2-kit.result-semantics.v0.8",
    "content_hash": "sha256:5c49411aedccf4cae2e3e97a955760ed83bd00283ff5a0ae5041272d13439b60",
    "official_source": {
        "version": "22 August 2019",
        "source_sha256": "A9E9C4FDC4BE2D29B5C0A1A6B828E09F2014A34F6D5C302A532F6153EA0FD670",
    },
}
_CURRENT_PACK_PREVIOUS_PROOF = {
    "id": "rob2.parallel.assignment",
    "version": "2019.1",
    "result_semantics_version": "rob2-kit.result-semantics.v0.7",
    "content_hash": "sha256:6d15307ced2cede1044b19507871c3b334c783868093f2015d372fb7b89f5a31",
    "official_source": {
        "version": "22 August 2019",
        "source_sha256": "A9E9C4FDC4BE2D29B5C0A1A6B828E09F2014A34F6D5C302A532F6153EA0FD670",
    },
}
_FORMER_CURRENT_PACK_PREVIOUS_PROOF = {
    "id": "rob2.parallel.assignment",
    "version": "2019.1",
    "result_semantics_version": "rob2-kit.result-semantics.v0.7",
    "content_hash": "sha256:f1cc5e7e0c06a26b351e455797d8936256b01388fdb446c1ef7cc926ab29613b",
    "official_source": {
        "version": "22 August 2019",
        "source_sha256": "A9E9C4FDC4BE2D29B5C0A1A6B828E09F2014A34F6D5C302A532F6153EA0FD670",
    },
}
_PREVIOUS_SCIENTIFIC_PACK = {
    "id": "rob2.parallel.assignment",
    "version": "2019.1",
    "result_semantics_version": "rob2-kit.result-semantics.v0.7",
    "content_hash": "sha256:9c293fbfaf1b10b82682a90d2e90986c3283fa1412f2c8b62a4d82a14a795dc8",
    "official_source": {
        "version": "22 August 2019",
        "source_sha256": "A9E9C4FDC4BE2D29B5C0A1A6B828E09F2014A34F6D5C302A532F6153EA0FD670",
    },
}
_LEGACY_SCIENTIFIC_PACK = {
    "id": "rob2.parallel.assignment",
    "version": "2019.1",
    "result_semantics_version": "rob2-kit.result-semantics.v0.6",
    "content_hash": "sha256:3ef492b34a81c19e3f75d72fea2b92c40aebde80c06e24e44c36cd76dc4cf3d4",
    "official_source": {
        "version": "22 August 2019",
        "source_sha256": "A9E9C4FDC4BE2D29B5C0A1A6B828E09F2014A34F6D5C302A532F6153EA0FD670",
    },
}
_HISTORICAL_SCIENTIFIC_PACK = {
    "id": "rob2.parallel.assignment",
    "version": "2019.1",
    "content_hash": "sha256:4bfd30a3d997e9eab0354ef7148726c5b112004a64b59dd57f02ac1493b61597",
    "official_source": {
        "version": "22 August 2019",
        "source_sha256": "A9E9C4FDC4BE2D29B5C0A1A6B828E09F2014A34F6D5C302A532F6153EA0FD670",
    },
}
_OLDER_SCIENTIFIC_PACK = {
    "id": "rob2.parallel.assignment",
    "version": "2019.1",
    "result_semantics_version": "rob2-kit.result-semantics.v0.7",
    "content_hash": "sha256:3ef492b34a81c19e3f75d72fea2b92c40aebde80c06e24e44c36cd76dc4cf3d4",
    "official_source": {
        "version": "22 August 2019",
        "source_sha256": "A9E9C4FDC4BE2D29B5C0A1A6B828E09F2014A34F6D5C302A532F6153EA0FD670",
    },
}


def identity(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _valid_batch(batch: object) -> bool:
    if not isinstance(batch, dict) or set(batch) != {"identity", "trials", "conditions"}:
        return False
    if (
        not isinstance(batch.get("trials"), list)
        or not batch["trials"]
        or not isinstance(batch.get("conditions"), list)
    ):
        return False
    if batch.get("identity") != identity(
        {"trials": batch["trials"], "conditions": batch["conditions"]}
    ):
        return False
    trial_ids: set[str] = set()
    for trial in batch["trials"]:
        if (
            not isinstance(trial, dict)
            or not isinstance(trial.get("id"), str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", trial["id"])
            or not isinstance(trial.get("label"), str)
            or not trial["label"].strip()
            or not isinstance(trial.get("requested_outcome"), str)
            or not trial["requested_outcome"].strip()
            or trial["id"] in trial_ids
            or not isinstance(trial.get("sources"), list)
            or set(trial)
            != {"id", "label", "requested_outcome", "sources", "registry", "omissions", "identity"}
        ):
            return False
        if trial["identity"] != identity(
            {key: value for key, value in trial.items() if key != "identity"}
        ):
            return False
        if not _valid_registry(trial.get("registry")):
            return False
        omissions = trial.get("omissions")
        if not isinstance(omissions, list) or any(not _valid_omission(item) for item in omissions):
            return False
        if len({item["path"] for item in omissions}) != len(omissions):
            return False
        trial_ids.add(trial["id"])
        source_ids: set[str] = set()
        for source in trial["sources"]:
            if not _valid_source(source, trial["id"]):
                return False
            if source["id"] in source_ids:
                return False
            source_ids.add(source["id"])
    return _valid_conditions(batch["conditions"], trial_ids)


def _valid_main_report_scopes(
    value: object, batch: dict[str, object], evidence: dict[str, object]
) -> bool:
    if not isinstance(value, list):
        return False
    sources: dict[tuple[object, object], dict[str, object]] = {}
    priority = {"protocol": 0, "sap": 1, "supplement": 2, "other": 3, "registry": 4}
    raw_trials = batch.get("trials", [])
    trials = raw_trials if isinstance(raw_trials, list) else []
    for trial in trials:
        if not isinstance(trial, dict):
            continue
        candidates = [
            item
            for item in trial.get("sources", [])
            if isinstance(item, dict) and item.get("role") == "main_article"
        ]
        if not candidates:
            candidates = sorted(
                (item for item in trial.get("sources", []) if isinstance(item, dict)),
                key=lambda item: (priority.get(str(item.get("role")), 5), str(item.get("id"))),
            )[:1]
        for item in candidates:
            sources[(trial.get("id"), item.get("id"))] = item
    if not sources:
        return not value
    seen: set[tuple[object, object]] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {
            "trial_id",
            "source_id",
            "source_sha256",
            "projection_hash",
            "end_page",
            "boundary_evidence",
            "excluded_ranges",
        }:
            return False
        key = (item.get("trial_id"), item.get("source_id"))
        source = sources.get(key)
        if key in seen or not isinstance(source, dict):
            return False
        seen.add(key)
        end_page = item.get("end_page")
        page_count = source.get("page_count")
        if item.get("source_sha256") != source.get("sha256") or item.get(
            "projection_hash"
        ) != source.get("projection_hash"):
            return False
        if (
            not isinstance(end_page, int)
            or isinstance(end_page, bool)
            or not isinstance(page_count, int)
            or not 1 <= end_page <= page_count
        ):
            return False
        boundary = item.get("boundary_evidence")
        ranges = item.get("excluded_ranges")
        if not isinstance(boundary, list) or not isinstance(ranges, list):
            return False
        for handle in boundary:
            selected = next(
                (
                    entry
                    for entry in evidence.values()
                    if isinstance(entry, dict) and entry.get("handle") == handle
                ),
                None,
            )
            if (
                not isinstance(selected, dict)
                or selected.get("kind") != "narrative"
                or selected.get("trial_id") != key[0]
                or selected.get("source_id") != key[1]
                or selected.get("page") not in {end_page, end_page + 1}
            ):
                return False
        if end_page == page_count:
            if ranges:
                return False
        elif len(ranges) != 1:
            return False
        else:
            excluded = ranges[0]
            if (
                not isinstance(excluded, dict)
                or set(excluded) != {"start_page", "end_page", "reason"}
                or excluded.get("start_page") != end_page + 1
                or excluded.get("end_page") != page_count
                or not isinstance(excluded.get("reason"), str)
                or not excluded["reason"].strip()
                or not boundary
            ):
                return False
    return seen == set(sources)


def _valid_omission(value: object) -> bool:
    base = {"path", "reason", "rationale"}
    optional = {"role", "declared_role", "sha256"}
    if (
        not isinstance(value, dict)
        or not base.issubset(value)
        or not set(value).issubset(base | optional)
    ):
        return False
    return (
        isinstance(value.get("path"), str)
        and _valid_relative_path(value["path"])
        and isinstance(value.get("reason"), str)
        and value["reason"] in {"duplicate", "irrelevant", "unreadable", "restricted", "other"}
        and isinstance(value.get("rationale"), str)
        and bool(value["rationale"].strip())
        and (
            "role" not in value
            or value["role"]
            in {"main_article", "registry", "supplement", "sap", "protocol", "other"}
        )
        and (
            "declared_role" not in value
            or value["declared_role"] is None
            or value["declared_role"]
            in {"main_article", "registry", "supplement", "sap", "protocol", "other"}
        )
        and (
            "sha256" not in value
            or value["sha256"] is None
            or (
                isinstance(value["sha256"], str)
                and re.fullmatch(r"sha256:[0-9a-f]{64}", value["sha256"]) is not None
            )
        )
    )


def _valid_relative_path(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and "\\" not in value
        and not value.startswith("/")
        and not re.match(r"^[A-Za-z]:", value)
        and ".." not in Path(value).parts
        and posixpath.normpath(value) == value
    )


def _valid_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _valid_source(source: object, trial_id: str) -> bool:
    if not isinstance(source, dict) or set(source) not in (
        {
            "id",
            "trial_id",
            "role",
            "label",
            "logical_path",
            "sha256",
            "media_type",
            "page_count",
            "projection_hash",
            "origin",
        },
        {
            "id",
            "trial_id",
            "role",
            "label",
            "logical_path",
            "sha256",
            "media_type",
            "page_count",
            "projection_hash",
            "origin",
            "declared_role",
        },
    ):
        return False
    strings = (
        "id",
        "role",
        "label",
        "logical_path",
        "sha256",
        "media_type",
        "projection_hash",
        "origin",
    )
    path = source.get("logical_path")
    if (
        source.get("trial_id") != trial_id
        or not all(isinstance(source.get(key), str) and source[key].strip() for key in strings)
        or not re.fullmatch(r"source_[0-9a-f]{64}", source["id"])
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", source["sha256"])
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", source["projection_hash"])
        or source["origin"] not in {"local_dossier", "registry", "researcher_provided"}
        or source["role"]
        not in {"main_article", "registry", "supplement", "sap", "protocol", "other"}
        or (
            "declared_role" in source
            and source["declared_role"] is not None
            and source["declared_role"]
            not in {"main_article", "registry", "supplement", "sap", "protocol", "other"}
        )
        or not _valid_relative_path(path)
        or not isinstance(source.get("page_count"), int)
        or isinstance(source["page_count"], bool)
        or source["page_count"] < 1
    ):
        return False
    expected = (
        "source_"
        + hashlib.sha256(
            f"{source['trial_id']}\0{source['logical_path']}\0{source['sha256']}".encode()
        ).hexdigest()
    )
    return source["id"] == expected


def _valid_registry(value: object) -> bool:
    if not isinstance(value, dict) or not isinstance(value.get("kind"), str):
        return False
    kind = value["kind"]
    fields = {
        "matched": {"kind", "registry_id", "title", "url", "retrieved_at"},
        "not_found": {"kind", "query", "retrieved_at"},
        "ambiguous": {"kind", "query", "candidates", "retrieved_at"},
        "unavailable": {"kind", "query", "reason", "retrieved_at"},
        "contradiction": {"kind", "registry_id", "facts", "retrieved_at"},
    }.get(kind)
    if fields is None or set(value) != fields:
        return False
    if not _valid_timestamp(value.get("retrieved_at")):
        return False
    if not all(
        isinstance(value.get(key), str) and value[key].strip()
        for key in fields - {"candidates", "facts"}
    ):
        return False
    if kind == "ambiguous":
        return (
            isinstance(value["candidates"], list)
            and len(value["candidates"]) >= 2
            and all(isinstance(item, str) and item.strip() for item in value["candidates"])
            and len(set(value["candidates"])) == len(value["candidates"])
        )
    if kind == "contradiction":
        return (
            isinstance(value["facts"], list)
            and bool(value["facts"])
            and all(isinstance(item, str) and item.strip() for item in value["facts"])
        )
    return True


def _valid_conditions(conditions: object, trial_ids: set[str]) -> bool:
    if not isinstance(conditions, list):
        return False
    for condition in conditions:
        if not isinstance(condition, dict) or not isinstance(condition.get("code"), str):
            return False
        code = condition["code"]
        trial_id = condition.get("trial_id")
        if trial_id not in trial_ids:
            return False
        if code in {"unsupported_source", "declared_source_missing"}:
            valid = _valid_visibility_condition(condition)
        elif code == "unreadable_source":
            valid = set(condition) == {"code", "trial_id", "path"} or _valid_visibility_condition(
                condition
            )
        elif code == "invalid_registry_identifier":
            valid = (
                set(condition) == {"code", "trial_id", "value"}
                and isinstance(condition.get("value"), str)
                and bool(condition["value"].strip())
            )
        elif code == "registry_review":
            valid = set(condition) == {"code", "trial_id", "outcome"} and _valid_registry(
                condition.get("outcome")
            )
        elif code == "omission_review":
            paths, records = condition.get("paths"), condition.get("records")
            valid = (
                set(condition) == {"code", "trial_id", "paths", "records"}
                and isinstance(paths, list)
                and isinstance(records, list)
                and len(paths) == len(records)
                and len(paths) == len(set(paths))
                and all(isinstance(path, str) and path.strip() for path in paths)
                and all(_valid_omission(record) for record in records)
                and [record["path"] for record in records] == paths
            )
        elif code == "no_supported_sources":
            valid = set(condition) == {"code", "trial_id"}
        else:
            valid = False
        if not valid:
            return False
    return True


def _valid_visibility_condition(condition: dict[str, object]) -> bool:
    reason = condition.get("reason")
    sha256 = condition.get("sha256")
    return (
        set(condition) == {"code", "trial_id", "path", "role", "declared_role", "reason", "sha256"}
        and isinstance(condition.get("path"), str)
        and _valid_relative_path(condition["path"])
        and condition.get("role")
        in {"main_article", "registry", "supplement", "sap", "protocol", "other"}
        and (
            condition.get("declared_role") is None
            or condition.get("declared_role")
            in {"main_article", "registry", "supplement", "sap", "protocol", "other"}
        )
        and isinstance(reason, str)
        and bool(reason.strip())
        and (
            sha256 is None
            or (
                isinstance(sha256, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", sha256) is not None
            )
        )
    )


def _valid_source_ref(reference: object, authoritative: object, trial_id: object) -> bool:
    if (
        not isinstance(reference, dict)
        or set(reference) != {"id", "projection_hash"}
        or not isinstance(reference["id"], str)
        or not isinstance(reference["projection_hash"], str)
        or not isinstance(authoritative, dict)
        or reference["id"] != authoritative.get("id")
        or reference["projection_hash"] != authoritative.get("projection_hash")
        or authoritative.get("trial_id") != trial_id
    ):
        return False
    expected = (
        "source_"
        + hashlib.sha256(
            f"{trial_id}\0{authoritative.get('logical_path')}\0{authoritative.get('sha256')}".encode()
        ).hexdigest()
    )
    return reference["id"] == expected


def _valid_search_account(
    account: object,
    trial_id: object,
    batch_identity: object,
    authoritative: dict[str, dict[str, object]],
    identity_fn,
) -> bool:
    legacy_keys = {
        "trial_id",
        "sources",
        "query",
        "normalized_query",
        "mode",
        "hits",
        "total_matches",
        "truncated",
        "limit",
        "condition",
        "batch_identity",
        "session_id",
        "session_handle",
        "candidate_count",
        "matching_page_count",
        "ranking_complete",
        "returned_rank_start",
        "returned_rank_end",
        "next_cursor",
        "exhausted",
        "returned_material",
        "returned_candidates",
        "identity",
        "handle",
    }
    modern_keys = legacy_keys | {"profile"}
    purpose_keys = {"purpose_domain_id", "purpose_question_id"}
    if not isinstance(account, dict) or set(account) not in (
        legacy_keys,
        modern_keys,
        modern_keys | purpose_keys,
    ):
        return False
    modern = "profile" in account
    query = account.get("query")
    sources = account.get("sources")
    hits = account.get("hits")
    limit = account.get("limit")
    total_matches = account.get("total_matches")
    truncated = account.get("truncated")
    source_ids = (
        [item.get("id") for item in sources if isinstance(item, dict)]
        if isinstance(sources, list)
        else []
    )
    hit_pairs = (
        [(hit.get("source_id"), hit.get("page")) for hit in hits if isinstance(hit, dict)]
        if isinstance(hits, list)
        else []
    )
    returned_candidates = account.get("returned_candidates")
    candidate_pairs = (
        [
            (item.get("source_id"), item.get("page"))
            for item in returned_candidates
            if isinstance(item, dict)
        ]
        if isinstance(returned_candidates, list)
        else []
    )
    candidate_ranks = (
        [item.get("rank") for item in returned_candidates if isinstance(item, dict)]
        if isinstance(returned_candidates, list)
        else []
    )
    session_id = account.get("session_id")
    session_handle = account.get("session_handle")
    session_fields_valid = ("session_id" not in account and "session_handle" not in account) or (
        isinstance(session_id, str)
        and re.fullmatch(r"sha256:[0-9a-f]{64}", session_id) is not None
        and isinstance(session_handle, str)
        and re.fullmatch(r"ss_[0-9a-f]{16}", session_handle) is not None
        and session_handle == "ss_" + session_id.removeprefix("sha256:")[:16]
    )
    purpose_valid = True
    if set(account) == modern_keys | purpose_keys:
        purpose_domain_id = account.get("purpose_domain_id")
        purpose_question_id = account.get("purpose_question_id")
        purpose_valid = purpose_domain_id is None or (
            isinstance(purpose_domain_id, str) and purpose_domain_id in _EXPECTED_DOMAIN_IDS
        )
        if purpose_question_id is not None:
            purpose_valid = purpose_valid and (
                isinstance(purpose_domain_id, str)
                and isinstance(purpose_question_id, str)
                and purpose_question_id in _DOMAIN_QUESTION_IDS.get(purpose_domain_id, set())
            )
    scalar_optional_valid = (
        all(
            (
                key not in account
                or (
                    isinstance(account[key], int)
                    and not isinstance(account[key], bool)
                    and account[key] >= 0
                )
            )
            for key in (
                "candidate_count",
                "matching_page_count",
                "returned_material",
            )
        )
        and all(
            (
                key not in account
                or account[key] is None
                or (
                    isinstance(account[key], int)
                    and not isinstance(account[key], bool)
                    and account[key] >= 0
                )
            )
            for key in ("returned_rank_start", "returned_rank_end")
        )
        and all(
            key not in account or isinstance(account[key], bool)
            for key in ("ranking_complete", "exhausted")
        )
    )
    cursor_valid = (
        "next_cursor" not in account
        or account["next_cursor"] is None
        or (
            isinstance(account["next_cursor"], str)
            and re.fullmatch(r"sc_[0-9a-f]{16}_[0-9]+", account["next_cursor"]) is not None
        )
    )
    candidates_valid = "returned_candidates" not in account or (
        isinstance(returned_candidates, list)
        and all(
            isinstance(item, dict)
            and set(item) == {"rank", "source_id", "page", "start_line", "end_line"}
            and isinstance(item["rank"], int)
            and not isinstance(item["rank"], bool)
            and item["rank"] >= 1
            and isinstance(item["source_id"], str)
            and isinstance(item["page"], int)
            and not isinstance(item["page"], bool)
            and item["page"] >= 1
            and isinstance(item["start_line"], int)
            and not isinstance(item["start_line"], bool)
            and item["start_line"] >= 1
            and isinstance(item["end_line"], int)
            and not isinstance(item["end_line"], bool)
            and item["end_line"] >= item["start_line"]
            and item["source_id"] in source_ids
            and isinstance(authoritative.get(item["source_id"]), dict)
            and item["page"] <= authoritative[item["source_id"]].get("page_count", 0)
            for item in returned_candidates
        )
        and candidate_pairs == hit_pairs
    )
    if (
        account.get("trial_id") != trial_id
        or account.get("batch_identity") != batch_identity
        or account.get("identity")
        != identity_fn(
            {key: value for key, value in account.items() if key not in {"identity", "handle"}}
        )
        or account.get("handle") != "sr_" + str(account["identity"]).removeprefix("sha256:")[:16]
        or not isinstance(query, str)
        or not query.strip()
        or not isinstance(account.get("normalized_query"), str)
        or not account["normalized_query"].strip()
        or account["normalized_query"]
        != (
            _canonical_search_text(query).casefold()
            if account.get("mode") == "literal"
            else _canonical_query_text(query)
        )
        or not isinstance(account.get("mode"), str)
        or account["mode"]
        not in (
            {"all", "phrase", "any", "prefix", "literal"}
            if modern
            else {"all", "phrase", "any", "prefix"}
        )
        or (modern and account.get("profile") != "porter-unicode61-v1")
        or not purpose_valid
        or not isinstance(limit, int)
        or isinstance(limit, bool)
        or not 1 <= limit <= 100
        or not isinstance(total_matches, int)
        or isinstance(total_matches, bool)
        or total_matches < 0
        or not isinstance(truncated, bool)
        or not session_fields_valid
        or not scalar_optional_valid
        or not cursor_valid
        or not candidates_valid
        or not isinstance(sources, list)
        or any(not isinstance(source_id, str) for source_id in source_ids)
        or len(set(source_ids)) != len(sources)
        or any(
            not _valid_source_ref(
                item,
                authoritative.get(item.get("id")) if isinstance(item, dict) else None,
                trial_id,
            )
            for item in sources
        )
        or not isinstance(hits, list)
        or any(
            not isinstance(source_id, str) or not isinstance(page, int) or isinstance(page, bool)
            for source_id, page in hit_pairs
        )
        or account.get("returned_material") != len(hits)
        or not isinstance(account.get("candidate_count"), int)
        or account["candidate_count"] < len(hits)
        or account.get("matching_page_count") != total_matches
        or account.get("ranking_complete") is not True
        or (
            (not hits)
            != (
                account.get("returned_rank_start") is None
                and account.get("returned_rank_end") is None
            )
        )
        or (
            bool(hits)
            and account["returned_rank_end"] - account["returned_rank_start"] + 1 != len(hits)
        )
        or (
            bool(hits)
            and candidate_ranks
            != list(
                range(
                    account["returned_rank_start"],
                    account["returned_rank_end"] + 1,
                )
            )
        )
        or account.get("exhausted")
        != (not hits or account["returned_rank_end"] >= account["candidate_count"])
        or truncated != (not account.get("exhausted"))
        or (
            account.get("next_cursor")
            != (
                None
                if account.get("exhausted")
                else "sc_"
                + str(account["session_id"]).removeprefix("sha256:")[:16]
                + "_"
                + str(account["returned_rank_end"])
            )
        )
        or any(
            not isinstance(hit, dict)
            or set(hit) != {"source_id", "page"}
            or hit.get("source_id") not in source_ids
            or not isinstance(authoritative.get(hit.get("source_id")), dict)
            or not isinstance(hit.get("page"), int)
            or isinstance(hit["page"], bool)
            or hit["page"] < 1
            or hit["page"] > authoritative[hit["source_id"]].get("page_count", 0)
            for hit in hits
        )
        or (bool(hits) and account.get("condition") is not None)
        or (not hits and account.get("condition") != "no_hits")
        or (not hits and (total_matches != 0 or truncated))
    ):
        return False
    if source_ids != [
        source["id"]
        for source in _ordered_sources(
            authoritative[source_id] for source_id in source_ids if source_id in authoritative
        )
    ]:
        return False
    if len(hit_pairs) > limit:
        return False
    # Search deliberately interleaves Sources. Membership, coordinates,
    # uniqueness, and the bound are verified above; receipt identity binds order.
    return account.get("condition") in {None, "no_hits"}


def _valid_selected_evidence(
    item: object, sources: dict[str, dict[str, object]], identity_fn
) -> bool:
    """Validate the closed disposable Evidence record behind a selected handle."""
    if not isinstance(item, dict) or item.get("kind") not in {"narrative", "figure"}:
        return False
    kind = item["kind"]
    expected = (
        {"kind", "trial_id", "source_id", "page", "start", "end", "quote", "identity", "handle"}
        if kind == "narrative"
        else {
            "kind",
            "trial_id",
            "source_id",
            "render",
            "transcription",
            "region",
            "provenance",
            "identity",
            "handle",
        }
    )
    if kind == "narrative":
        has_line_coordinates = {"start_line", "end_line"}.issubset(item)
        if "search_session" in item and (
            not isinstance(item.get("search_session"), str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", item["search_session"]) is None
            or not isinstance(item.get("candidate_rank"), int)
            or isinstance(item.get("candidate_rank"), bool)
            or item["candidate_rank"] < 1
            or not has_line_coordinates
        ):
            return False
        if "search_session" in item:
            expected |= {"search_session", "candidate_rank"}
        if "source_version" in item:
            expected.add("source_version")
        if has_line_coordinates:
            expected |= {"start_line", "end_line"}
    elif kind == "figure" and "delivery_receipt" in item:
        expected.add("delivery_receipt")
    if kind == "figure" and "uncertainty" in item:
        expected.add("uncertainty")
    if set(item) != expected:
        return False
    source = sources.get(str(item.get("source_id")))
    if (
        not isinstance(source, dict)
        or item.get("trial_id") != source.get("trial_id")
        or item.get("identity")
        != identity_fn(
            {key: value for key, value in item.items() if key not in {"identity", "handle"}}
        )
        or item.get("handle") != "eh_" + str(item["identity"]).removeprefix("sha256:")[:16]
    ):
        return False
    if kind == "narrative":
        return (
            isinstance(item.get("page"), int)
            and not isinstance(item.get("page"), bool)
            and 1 <= item["page"] <= source.get("page_count", 0)
            and isinstance(item.get("start"), int)
            and not isinstance(item.get("start"), bool)
            and isinstance(item.get("end"), int)
            and not isinstance(item.get("end"), bool)
            and 0 <= item["start"] < item["end"]
            and isinstance(item.get("quote"), str)
            and bool(item["quote"])
            and item["end"] - item["start"] == len(item["quote"])
            and (
                "source_version" not in item
                or item["source_version"] == source.get("projection_hash")
            )
            and (
                "start_line" not in item
                or (
                    isinstance(item["start_line"], int)
                    and not isinstance(item["start_line"], bool)
                    and isinstance(item["end_line"], int)
                    and not isinstance(item["end_line"], bool)
                    and 1 <= item["start_line"] <= item["end_line"]
                    and len(item["quote"].splitlines()) == item["end_line"] - item["start_line"] + 1
                )
            )
        )
    render = item.get("render")
    region = item.get("region")
    return (
        isinstance(render, dict)
        and set(render) == {"identity", "source_id", "page", "png_sha256", "recipe"}
        and render.get("source_id") == item.get("source_id")
        and render.get("identity")
        == identity_fn(
            {
                "source_id": item.get("source_id"),
                "source_sha256": source.get("sha256"),
                "page": render.get("page"),
                "recipe": render.get("recipe"),
            }
        )
        and isinstance(render.get("page"), int)
        and not isinstance(render.get("page"), bool)
        and 1 <= render["page"] <= source.get("page_count", 0)
        and isinstance(render.get("png_sha256"), str)
        and bool(re.fullmatch(r"sha256:[0-9a-f]{64}", render["png_sha256"]))
        and isinstance(render.get("recipe"), str)
        and bool(render["recipe"])
        and isinstance(item.get("transcription"), str)
        and bool(item["transcription"])
        and item["transcription"] == item["transcription"].strip()
        and item.get("provenance") in {"text_corroborated", "host_visual"}
        and (
            "uncertainty" not in item
            or (
                isinstance(item.get("uncertainty"), str)
                and bool(item["uncertainty"].strip())
                and item["uncertainty"] == item["uncertainty"].strip()
                and len(item["uncertainty"]) <= 2_000
            )
        )
        and (
            "delivery_receipt" not in item
            or item.get("delivery_receipt")
            == identity(
                {
                    "trial_id": item.get("trial_id"),
                    "source_id": item.get("source_id"),
                    "render_identity": render.get("identity"),
                    "png_sha256": render.get("png_sha256"),
                    "channel": "mcp_image_content",
                    "mime_type": "image/png",
                }
            )
        )
        and (item.get("provenance") != "text_corroborated" or region == [0.0, 0.0, 1.0, 1.0])
        and isinstance(region, list)
        and len(region) == 4
        and all(
            isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
            for value in region
        )
        and 0 <= region[0] < region[2] <= 1
        and 0 <= region[1] < region[3] <= 1
    )


_PUNCTUATION_EQUIVALENTS = str.maketrans(
    {
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2015": "-",
        "\u2212": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u201f": '"',
    }
)


def _canonical_search_text(value: str) -> str:
    """Reproduce the product's conservative discovery normalization."""
    normalized, _spans = _normalized_with_spans(value)
    return " ".join(normalized.split())


def _canonical_query_text(value: str) -> str:
    """Reproduce lexical query normalization used for session identity."""
    return " ".join(
        term
        for raw in _canonical_search_text(value).casefold().split()
        if (term := re.sub(r"^\W+|\W+$", "", raw))
    )


def _normalized_with_spans(
    value: str, *, dehyphenate_line_ends: bool = True
) -> tuple[str, list[tuple[int, int]]]:
    filtered: list[tuple[str, int, int]] = []
    for index, character in enumerate(value):
        if character == "\u00ad":
            if re.match(r"[^\S\r\n]*\r?\n", value[index + 1 :]):
                filtered.append(("-", index, index + 1))
            continue
        category = unicodedata.category(character)
        if category == "Cf" or category == "Cc" and not character.isspace():
            continue
        filtered.append((character, index, index + 1))
    characters: list[str] = []
    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(filtered):
        cluster = [filtered[index]]
        index += 1
        while index < len(filtered) and unicodedata.combining(filtered[index][0]):
            cluster.append(filtered[index])
            index += 1
        raw_start = cluster[0][1]
        raw_end = cluster[-1][2]
        chunk = unicodedata.normalize("NFKC", "".join(item[0] for item in cluster)).translate(
            _PUNCTUATION_EQUIVALENTS
        )
        chunk = "".join(
            character for character in chunk if unicodedata.category(character) != "Cf"
        ).casefold()
        for character in chunk:
            if character.isspace():
                if characters and characters[-1] == " ":
                    spans[-1] = (spans[-1][0], raw_end)
                else:
                    characters.append(" ")
                    spans.append((raw_start, raw_end))
            else:
                characters.append(character)
                spans.append((raw_start, raw_end))

    output: list[str] = []
    output_spans: list[tuple[int, int]] = []
    index = 0
    while index < len(characters):
        if characters[index] == "-" and output and (output[-1].isalnum() or output[-1] == "_"):
            next_index = index + 1
            while next_index < len(characters) and characters[next_index] == " ":
                next_index += 1
            whitespace = (
                value[spans[index][1] : spans[next_index][0]] if next_index < len(spans) else ""
            )
            # Preserve numeric ranges' hyphens across the line break.
            if (
                next_index > index + 1
                and any(character in "\r\n" for character in whitespace)
                and next_index < len(characters)
                and (characters[next_index].isalnum() or characters[next_index] == "_")
            ):
                if output[-1].isdigit() and characters[next_index].isdigit():
                    output.append(characters[index])
                    output_spans.append(spans[index])
                    index = next_index
                    continue
                if dehyphenate_line_ends:
                    output_spans[-1] = (output_spans[-1][0], spans[next_index][0])
                else:
                    output.append(" ")
                    output_spans.append((spans[index][0], spans[next_index][0]))
                index = next_index
                continue
        output.append(characters[index])
        output_spans.append(spans[index])
        index += 1
    return "".join(output), output_spans


def _normalized_contains(material: str, phrase: str) -> bool:
    normalized_material, _ = _normalized_with_spans(material)
    normalized_phrase, _ = _normalized_with_spans(phrase)
    if not normalized_phrase:
        return False
    if normalized_phrase in normalized_material:
        return True

    wrapped_material, _ = _normalized_with_spans(material, dehyphenate_line_ends=False)
    wrapped_phrase, _ = _normalized_with_spans(phrase, dehyphenate_line_ends=False)
    line_wrap_phrase = re.sub(r"(?<=\w)-(?=\w)", " ", wrapped_phrase)
    return bool(line_wrap_phrase) and line_wrap_phrase in wrapped_material


def _numeric_boundary_before(value: str, index: int) -> bool:
    if index == 0:
        return True
    immediate = value[index - 1]
    if immediate.isspace():
        cursor = index - 2
        while cursor >= 0 and value[cursor].isspace():
            cursor -= 1
        if cursor < 0 or value[cursor] not in "+-<>≤≥":
            return True
        if value[cursor] == "+":
            return False
        before_operator = cursor - 1
        while before_operator >= 0 and value[before_operator].isspace():
            before_operator -= 1
        return value[cursor] == "-" and before_operator >= 0 and value[before_operator].isdigit()
    cursor = index - 1
    character = value[cursor]
    if character.isdigit() or character in "+<>≤≥" or character.isalpha() or character == "_":
        return False
    if character == "-":
        return cursor > 0 and value[cursor - 1].isdigit()
    if character in ".,":
        return cursor == 0 or not value[cursor - 1].isdigit()
    if character in "eE":
        return cursor == 0 or not value[cursor - 1].isdigit()
    return True


def _numeric_boundary_after(value: str, index: int, *, allow_percent_suffix: bool = False) -> bool:
    if index == len(value):
        return True
    immediate = value[index]
    if immediate.isspace():
        cursor = index + 1
        while cursor < len(value) and value[cursor].isspace():
            cursor += 1
        if cursor == len(value) or value[cursor] not in "+-":
            return True
        if value[cursor] == "+":
            return False
        next_cursor = cursor + 1
        while next_cursor < len(value) and value[next_cursor].isspace():
            next_cursor += 1
        return (
            next_cursor == len(value)
            or value[next_cursor].isdigit()
            or value[next_cursor].isalpha()
        )
    cursor = index
    character = value[cursor]
    if character.isdigit() or character.isalpha() or character == "_":
        return False
    if character == "%":
        return allow_percent_suffix
    if character in ".,":
        return cursor + 1 == len(value) or not value[cursor + 1].isdigit()
    if character in "/:":
        return cursor + 1 == len(value) or not value[cursor + 1].isdigit()
    if character == "+":
        return False
    if character == "-":
        next_cursor = cursor + 1
        while next_cursor < len(value) and value[next_cursor].isspace():
            next_cursor += 1
        return next_cursor < len(value) and value[next_cursor].isdigit()
    if character in "eE":
        next_cursor = cursor + 1
        if next_cursor < len(value) and value[next_cursor] in "+-":
            next_cursor += 1
        return False
    if character in "<>≤≥":
        next_cursor = cursor + 1
        while next_cursor < len(value) and value[next_cursor].isspace():
            next_cursor += 1
        return next_cursor == len(value) or not value[next_cursor].isdigit()
    return True


_NUMERIC_ATOM_PATTERN = r"[+-]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\d+,\d+)(?:[eE][+-]?\d+)?"
_NUMERIC_COMPOUND_PATTERN = re.compile(
    rf"{_NUMERIC_ATOM_PATTERN}\s*(?:\(\s*{_NUMERIC_ATOM_PATTERN}\s*\)|±\s*{_NUMERIC_ATOM_PATTERN})"
)


def _numeric_compound_marker_end(value: str, index: int) -> bool:
    if index == len(value):
        return True
    if not value[index].islower():
        return False
    cursor = index + 1
    while cursor < len(value) and value[cursor] == ",":
        cursor += 1
        if cursor == len(value) or not value[cursor].islower():
            return False
        cursor += 1
    return cursor == len(value) or not value[cursor].isalnum() and value[cursor] != "_"


def _numeric_contains(material: str, phrase: str, *, allow_percent_suffix: bool = False) -> bool:
    normalized_material, _ = _normalized_with_spans(material)
    normalized_phrase, _ = _normalized_with_spans(phrase)
    if not normalized_phrase or not any(character.isdigit() for character in normalized_phrase):
        return _normalized_contains(material, phrase)
    compound_phrase = _NUMERIC_COMPOUND_PATTERN.fullmatch(normalized_phrase) is not None
    compound_spans = tuple(
        match.span()
        for match in _NUMERIC_COMPOUND_PATTERN.finditer(normalized_material)
        if match.end() < len(normalized_material)
        and normalized_material[match.end()].islower()
        and _numeric_compound_marker_end(normalized_material, match.end())
    )
    start = normalized_material.find(normalized_phrase)
    while start >= 0:
        end = start + len(normalized_phrase)
        in_compound = any(
            start >= compound_start
            and end <= compound_end
            and (start, end) != (compound_start, compound_end)
            for compound_start, compound_end in compound_spans
        )
        after_is_valid = _numeric_boundary_after(
            normalized_material, end, allow_percent_suffix=allow_percent_suffix
        ) or (compound_phrase and _numeric_compound_marker_end(normalized_material, end))
        if (
            not in_compound
            and _numeric_boundary_before(normalized_material, start)
            and after_is_valid
        ):
            return True
        start = normalized_material.find(normalized_phrase, start + 1)
    return False


def _result_value_contains(material: str, phrase: str, field_path: str | None = None) -> bool:
    numeric_field = field_path is None or field_path in {
        "/reported/estimate",
        "/reported/precision",
        "/reported/denominator_basis",
    }
    numeric_field = numeric_field or (
        field_path is not None
        and field_path.startswith("/reported/")
        and field_path.endswith("/value")
    )
    allow_percent_suffix = field_path is None or field_path.endswith("/value")
    return (
        _numeric_contains(
            material,
            phrase,
            allow_percent_suffix=allow_percent_suffix,
        )
        if numeric_field
        else _normalized_contains(material, phrase)
    )


def _normalized_equal(left: str, right: str) -> bool:
    """Compare mapping values as complete normalized leaves, not substrings."""
    return _normalized_with_spans(left)[0] == _normalized_with_spans(right)[0]


_FORBIDDEN_PATH_FIELDS = frozenset(
    {
        "absolute_path",
        "directory",
        "file_name",
        "filename",
        "source_directory",
        "source_path",
        "source_root",
        "workspace",
        "workspace_path",
    }
)
_PATH_FIELDS = frozenset({"logical_path", "path"})


def _nonblank(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_reasoning_annotations(answer: dict[str, Any]) -> bool:
    if "unknowns" not in answer and "counterevidence" not in answer:
        return True
    unknowns = answer.get("unknowns")
    counterevidence = answer.get("counterevidence")
    if not isinstance(unknowns, list) or any(not _nonblank(item) for item in unknowns):
        return False
    if not isinstance(counterevidence, list):
        return False
    indexes: set[int] = set()
    for item in counterevidence:
        if (
            not isinstance(item, dict)
            or set(item) != {"basis_index", "implication"}
            or not isinstance(item.get("basis_index"), int)
            or isinstance(item["basis_index"], bool)
            or item["basis_index"] < 0
            or item["basis_index"] >= len(answer.get("bases", []))
            or not _nonblank(item.get("implication"))
        ):
            return False
        indexes.add(item["basis_index"])
    return all(
        basis.get("kind") != "contradiction" or index in indexes
        for index, basis in enumerate(answer.get("bases", []))
        if isinstance(basis, dict)
    )


def _valid_limitation_basis(
    basis: object, accounts: dict[str, dict[str, object]], trial_id: str
) -> bool:
    """Accept current limitation provenance and replay the legacy receipt gate."""
    if not isinstance(basis, dict):
        return False
    if set(basis) == {"kind", "text", "search_receipt"}:
        handle = basis.get("search_receipt")
        account = accounts.get(handle) if isinstance(handle, str) else None
        return (
            basis.get("kind") == "limitation"
            and _nonblank(basis.get("text"))
            and isinstance(account, dict)
            and account.get("trial_id") == trial_id
            and account.get("truncated") is False
        )
    if set(basis) not in (
        {"kind", "unresolved_premise", "stopping_rationale"},
        {"kind", "unresolved_premise", "stopping_rationale", "search_receipt"},
    ):
        return False
    if (
        basis.get("kind") != "limitation"
        or not _nonblank(basis.get("unresolved_premise"))
        or not _nonblank(basis.get("stopping_rationale"))
    ):
        return False
    if "search_receipt" not in basis:
        return True
    handle = basis.get("search_receipt")
    account = accounts.get(handle) if isinstance(handle, str) else None
    return isinstance(account, dict) and account.get("trial_id") == trial_id


def _valid_missing_data(
    value: object,
    question_id: object,
    evidence: dict[str, Any],
    trial_id: object,
) -> bool:
    """Validate the canonical Domain 3.1 count reconciliation."""
    if question_id != "sq:missing:data-available" or not isinstance(value, dict):
        return False
    if (
        set(value) != {"rows", "conflicts"}
        or not isinstance(value["rows"], list)
        or not value["rows"]
        or not isinstance(value["conflicts"], list)
    ):
        return False

    def valid_semantics(value: object) -> bool:
        if not isinstance(value, dict):
            return False
        allowed = {
            "population_role",
            "outcome_status",
            "event_count",
            "event_definition",
            "post_randomization_exclusions",
            "censoring",
        }
        if set(value) - allowed:
            return False
        if value.get("population_role") is not None and value.get("population_role") not in {
            "randomized",
            "safety",
            "analyzed",
            "per_protocol",
            "follow_up",
            "unknown",
        }:
            return False
        if value.get("outcome_status") is not None and value.get("outcome_status") not in {
            "observed",
            "missing",
            "imputed",
            "unknown",
            "not_reported",
        }:
            return False
        event_count = value.get("event_count")
        event_definition = value.get("event_definition")
        if event_count is not None and (
            isinstance(event_count, bool) or not isinstance(event_count, int) or event_count < 0
        ):
            return False
        if event_count is not None and not _nonblank(event_definition):
            return False
        if event_count is None and event_definition is not None:
            return False
        exclusions = value.get("post_randomization_exclusions", [])
        if not isinstance(exclusions, list) or any(not _nonblank(item) for item in exclusions):
            return False
        censoring = value.get("censoring")
        if censoring is not None:
            if not isinstance(censoring, dict) or set(censoring) - {
                "kind",
                "count",
                "timing",
                "reason",
            }:
                return False
            if censoring.get("kind") not in {
                "administrative",
                "loss_to_follow_up",
                "withdrawal",
                "treatment_change",
                "unknown",
            }:
                return False
            count = censoring.get("count")
            if count is not None and (
                isinstance(count, bool) or not isinstance(count, int) or count < 0
            ):
                return False
            for key in ("timing", "reason"):
                if censoring.get(key) is not None and not _nonblank(censoring[key]):
                    return False
        return True

    def valid_row(row: object) -> bool:
        required = {
            "scope",
            "randomized",
            "observed",
            "analyzed",
            "imputed",
            "exclusions",
            "basis",
            "missing",
            "missing_fraction",
        }
        optional = {"semantics"}
        if not isinstance(row, dict) or set(row) - required - optional or not required <= set(row):
            return False
        scope = row["scope"]
        if (
            not isinstance(scope, dict)
            or set(scope) != {"arm", "population", "unit", "time_point"}
            or any(not _nonblank(scope[key]) for key in scope)
        ):
            return False
        for key in ("randomized", "observed", "analyzed", "imputed", "missing"):
            item = row[key]
            if item is not None and (
                isinstance(item, bool) or not isinstance(item, int) or item < 0
            ):
                return False
        if not isinstance(row["exclusions"], list) or not all(
            _nonblank(item) for item in row["exclusions"]
        ):
            return False
        if "semantics" in row and not valid_semantics(row["semantics"]):
            return False
        if (
            not isinstance(row["basis"], list)
            or not row["basis"]
            or not all(
                _nonblank(identity)
                and isinstance(evidence.get(identity), dict)
                and evidence[identity].get("trial_id") == trial_id
                for identity in row["basis"]
            )
        ):
            return False
        randomized, observed = row["randomized"], row["observed"]
        expected_missing = (
            randomized - observed
            if isinstance(randomized, int)
            and not isinstance(randomized, bool)
            and isinstance(observed, int)
            and not isinstance(observed, bool)
            and randomized >= observed
            else None
        )
        if row["missing"] != expected_missing:
            return False
        expected_fraction = (
            expected_missing / randomized
            if expected_missing is not None and randomized
            else 0.0
            if expected_missing is not None
            else None
        )
        return row["missing_fraction"] == expected_fraction

    if not all(valid_row(row) for row in value["rows"]):
        return False
    if not all(
        isinstance(conflict, dict)
        and set(conflict) == {"scope", "reports"}
        and isinstance(conflict["scope"], dict)
        and set(conflict["scope"]) == {"arm", "population", "unit", "time_point"}
        and all(_nonblank(conflict["scope"][key]) for key in conflict["scope"])
        and isinstance(conflict["reports"], list)
        and len(conflict["reports"]) >= 2
        and all(valid_row(row) for row in conflict["reports"])
        and all(row["scope"] == conflict["scope"] for row in conflict["reports"])
        for conflict in value["conflicts"]
    ):
        return False
    compared_fields = (
        "randomized",
        "observed",
        "analyzed",
        "imputed",
        "exclusions",
        "semantics",
    )
    expected_conflicts: list[dict[str, object]] = []
    seen: dict[tuple[object, ...], dict[str, object]] = {}
    for row in value["rows"]:
        scope = row["scope"]
        key = tuple(scope[field] for field in ("arm", "population", "unit", "time_point"))
        prior = seen.get(key)
        if prior is not None and tuple(prior[field] for field in compared_fields) != tuple(
            row[field] for field in compared_fields
        ):
            expected_conflicts.append({"scope": scope, "reports": [prior, row]})
        else:
            seen[key] = row
    return value["conflicts"] == expected_conflicts


def _contains_platform_path(value: object, field: str | None = None) -> bool:
    if field in _FORBIDDEN_PATH_FIELDS:
        return True
    if not isinstance(value, str):
        return False
    if field in _PATH_FIELDS and "\\" in value:
        return True
    if len(value) >= 3 and value[0].isalpha() and value[1] == ":" and value[2] in "/\\":
        return True
    return value.startswith("\\\\")


def _contains_forbidden_paths(value: object, field: str | None = None) -> bool:
    if _contains_platform_path(value, field):
        return True
    if isinstance(value, dict):
        return any(_contains_forbidden_paths(child, str(key)) for key, child in value.items())
    if isinstance(value, list):
        return any(_contains_forbidden_paths(child, field) for child in value)
    return False


def _domain_identity_fields(
    record: dict[str, object], *, legacy_semantics: bool = False
) -> tuple[str, ...]:
    fields: list[str] = [
        "trial_id",
        "domain_id",
        "answers",
        "supersedes",
        "revision_basis",
        "search_accounts",
        "active_questions",
        "inactive_questions",
        "judgment",
        "trace",
    ]
    if not legacy_semantics and "driver_questions" in record:
        fields.append("driver_questions")
    if not legacy_semantics and "evidence_sufficiency" in record:
        fields.append("evidence_sufficiency")
    if not legacy_semantics and "result_identity" in record:
        fields.append("result_identity")
    return tuple(fields)


def _domain_identity(record: dict[str, object], *, legacy_semantics: bool = False) -> str:
    """Recompute the identity of a Domain checkpoint without the runtime."""

    fields = _domain_identity_fields(record, legacy_semantics=legacy_semantics)
    return identity({key: record.get(key) for key in fields})


_PROPOSAL_REVIEW_FIELDS = frozenset({"kind", "purpose", "workflow_basis", "candidate", "identity"})
_PROPOSAL_ACK_FIELDS = frozenset(
    {
        "review_identity",
        "purpose",
        "caller",
        "method",
        "observed_at",
        "workflow_basis",
        "identity",
    }
)


def _proposal_evidence_handles(value: object) -> set[str]:
    handles: set[str] = set()

    def visit(item: object) -> None:
        if isinstance(item, dict):
            if isinstance(item.get("handle"), str):
                handles.add(item["handle"])
            if isinstance(item.get("evidence"), str):
                handles.add(item["evidence"])
            elif isinstance(item.get("evidence"), list):
                handles.update(value for value in item["evidence"] if isinstance(value, str))
            if isinstance(item.get("boundary_evidence"), list):
                handles.update(
                    value for value in item["boundary_evidence"] if isinstance(value, str)
                )
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return handles


def _valid_proposal_gate(review: object, acknowledgment: object, proposal: object) -> bool:
    if (
        not isinstance(review, dict)
        or set(review) != _PROPOSAL_REVIEW_FIELDS
        or not isinstance(acknowledgment, dict)
        or set(acknowledgment) != _PROPOSAL_ACK_FIELDS
        or not isinstance(proposal, dict)
    ):
        return False
    candidate = review.get("candidate")
    payload = proposal.get("payload")
    catalog = proposal.get("evidence")
    if not isinstance(candidate, dict) or not isinstance(catalog, dict):
        return False
    handles = _proposal_evidence_handles(payload)
    expected_candidate_evidence = {
        key: item
        for key, item in catalog.items()
        if isinstance(item, dict) and (key in handles or item.get("handle") in handles)
    }
    return bool(
        review.get("kind") == "review"
        and review.get("purpose") == "proposal"
        and isinstance(review.get("workflow_basis"), int)
        and not isinstance(review.get("workflow_basis"), bool)
        and set(candidate) == {"identity", "proposal", "evidence"}
        and isinstance(review.get("identity"), str)
        and review["identity"]
        == identity({key: value for key, value in review.items() if key != "identity"})
        and acknowledgment.get("review_identity") == review.get("identity")
        and acknowledgment.get("purpose") == "proposal"
        and isinstance(acknowledgment.get("caller"), str)
        and bool(acknowledgment["caller"].strip())
        and isinstance(acknowledgment.get("method"), str)
        and bool(acknowledgment["method"].strip())
        and _valid_timestamp(acknowledgment.get("observed_at"))
        and isinstance(acknowledgment.get("workflow_basis"), int)
        and not isinstance(acknowledgment.get("workflow_basis"), bool)
        and acknowledgment.get("workflow_basis") == review.get("workflow_basis")
        and isinstance(acknowledgment.get("identity"), str)
        and acknowledgment["identity"]
        == identity({key: value for key, value in acknowledgment.items() if key != "identity"})
        and candidate.get("identity") == proposal.get("identity")
        and candidate.get("proposal") == payload
        and candidate.get("evidence") == expected_candidate_evidence
    )


def _domain_evidence_ids(record: object) -> set[str]:
    if not isinstance(record, dict) or not isinstance(record.get("answers"), list):
        return set()
    answer_basis_ids = {
        basis.get("evidence")
        for answer in record["answers"]
        if isinstance(answer, dict) and isinstance(answer.get("bases"), list)
        for basis in answer["bases"]
        if isinstance(basis, dict) and isinstance(basis.get("evidence"), str)
    }
    missing_data_ids = {
        evidence_identity
        for answer in record["answers"]
        if isinstance(answer, dict)
        for row in (answer.get("missing_data") or {}).get("rows", [])
        if isinstance(row, dict) and isinstance(row.get("basis"), list)
        for evidence_identity in row["basis"]
        if isinstance(evidence_identity, str)
    }
    return answer_basis_ids | missing_data_ids


def _valid_evidence_sufficiency(
    summary: object,
    answers: list[object],
    accounts: dict[str, object],
    evidence: dict[str, object],
    trial_id: object,
    *,
    legacy_semantics: bool = False,
) -> bool:
    def expected_claims() -> list[dict[str, object]] | None:
        derived: list[dict[str, object]] = []
        for answer in answers:
            if not isinstance(answer, dict) or not isinstance(answer.get("question_id"), str):
                return None
            bases = answer.get("bases", [])
            if not isinstance(bases, list):
                return None
            evidence_ids: list[str] = []
            receipt_ids: list[str] = []
            unresolved: list[str] = []
            kinds: set[str] = set()
            incomplete = False
            for basis in bases:
                if not isinstance(basis, dict):
                    return None
                kind = basis.get("kind")
                if isinstance(kind, str):
                    kinds.add(kind)
                evidence_id = basis.get("evidence")
                if isinstance(evidence_id, str):
                    evidence_ids.append(evidence_id)
                receipt_id = basis.get("search_receipt")
                if isinstance(receipt_id, str):
                    receipt_ids.append(receipt_id)
                    account = accounts.get(receipt_id)
                    if not isinstance(account, dict):
                        return None
                    incomplete = incomplete or bool(
                        account.get("truncated")
                        or not account.get("ranking_complete", True)
                        or account.get("next_cursor")
                        or not account.get("exhausted", True)
                    )
                if kind == "limitation":
                    premise = basis.get("unresolved_premise")
                    if isinstance(premise, str) and premise.strip():
                        unresolved.append(premise)
            if "contradiction" in kinds:
                status = "contradicted"
            elif incomplete:
                status = "retrieval_incomplete"
            elif "limitation" in kinds or "absence" in kinds:
                status = "unresolved"
            elif "indirect_support" in kinds:
                status = "indirect"
            elif "direct_support" in kinds:
                status = "supported"
            else:
                status = "unresolved"
            derived.append(
                {
                    "question_id": answer["question_id"],
                    "status": status,
                    "evidence": list(dict.fromkeys(evidence_ids)),
                    "search_receipts": list(dict.fromkeys(receipt_ids)),
                    "unresolved_premises": list(dict.fromkeys(unresolved)),
                }
            )
        return derived

    if not isinstance(summary, dict) or set(summary) != {"claims", "identity"}:
        return False
    claims = summary.get("claims")
    if (
        not isinstance(claims, list)
        or not claims
        or summary.get("identity") != identity({"claims": claims})
    ):
        return False
    answer_map = {
        item.get("question_id"): item
        for item in answers
        if isinstance(item, dict) and isinstance(item.get("question_id"), str)
    }
    if len(answer_map) != len(answers):
        return False
    claim_ids: set[str] = set()
    for claim in claims:
        if (
            not isinstance(claim, dict)
            or set(claim)
            != {
                "question_id",
                "status",
                "evidence",
                "search_receipts",
                "unresolved_premises",
            }
            or not isinstance(claim.get("question_id"), str)
            or claim["question_id"] in claim_ids
            or claim["question_id"] not in answer_map
            or claim.get("status")
            not in {
                "supported",
                "contradicted",
                "indirect",
                "unresolved",
                "not_reported",
                "retrieval_incomplete",
            }
            or not isinstance(claim.get("evidence"), list)
            or not isinstance(claim.get("search_receipts"), list)
            or not isinstance(claim.get("unresolved_premises"), list)
            or any(
                not isinstance(value, str)
                or value not in evidence
                or not isinstance(evidence[value], dict)
                or cast(dict[str, object], evidence[value]).get("trial_id") != trial_id
                for value in claim["evidence"]
            )
            or any(
                not isinstance(value, str) or value not in accounts
                for value in claim["search_receipts"]
            )
            or any(
                not isinstance(value, str) or not value.strip()
                for value in claim["unresolved_premises"]
            )
        ):
            return False
        claim_ids.add(claim["question_id"])
    if claim_ids != set(answer_map):
        return False
    if not legacy_semantics:
        derived = expected_claims()
        if derived is None or claims != derived:
            return False
    return True


def _valid_domain_lineage(
    history_by_key: object,
    records_by_key: object,
    active_by_key: object,
    evidence: dict[str, object],
    *,
    legacy_semantics: bool = False,
) -> bool:
    if not (
        isinstance(history_by_key, dict)
        and isinstance(records_by_key, dict)
        and isinstance(active_by_key, dict)
        and set(history_by_key) == set(records_by_key) == set(active_by_key)
    ):
        return False
    for key, history in history_by_key.items():
        records = records_by_key.get(key)
        active = active_by_key.get(key)
        if (
            not isinstance(history, list)
            or not history
            or not isinstance(records, list)
            or len(records) != len(history)
            or not isinstance(active, dict)
            or history[-1] != active.get("identity")
        ):
            return False
        prior: dict[str, object] | None = None
        for index, (checkpoint, record) in enumerate(zip(history, records, strict=True)):
            record_identity_fields = (
                _domain_identity_fields(record, legacy_semantics=legacy_semantics)
                if isinstance(record, dict)
                else ()
            )
            record_shape_fields = (
                _domain_identity_fields(record) if isinstance(record, dict) else ()
            )
            record_shape = {*record_shape_fields, "observed_at", "identity"}
            if (
                not isinstance(checkpoint, str)
                or not isinstance(record, dict)
                or set(record) != record_shape
                or record.get("identity") != checkpoint
                or record.get("identity")
                != identity({key: record.get(key) for key in record_identity_fields})
                or key != f"{record.get('trial_id')}:{record.get('domain_id')}"
                or not _valid_timestamp(record.get("observed_at"))
                or (
                    "result_identity" in record
                    and not isinstance(record.get("result_identity"), str)
                )
            ):
                return False
            basis = record.get("revision_basis")
            if index == 0:
                if record.get("supersedes") is not None or basis is not None:
                    return False
            else:
                if not isinstance(prior, dict):
                    return False
                if record.get("result_identity") != prior.get("result_identity"):
                    if record.get("supersedes") is not None or basis is not None:
                        return False
                else:
                    if record.get("supersedes") != prior.get("identity"):
                        return False
                    if not isinstance(basis, dict) or basis.get("kind") not in {
                        "new_evidence",
                        "self_correction",
                        "mechanical_repair",
                    }:
                        return False
                    if basis.get("kind") == "self_correction":
                        if (
                            set(basis) != {"kind", "rationale"}
                            or not str(basis.get("rationale", "")).strip()
                        ):
                            return False
                    elif basis.get("kind") == "new_evidence":
                        if (
                            set(basis) != {"kind", "evidence", "rationale"}
                            or not isinstance(basis.get("evidence"), str)
                            or not str(basis.get("rationale", "")).strip()
                            or basis["evidence"] not in evidence
                            or basis["evidence"] in _domain_evidence_ids(prior)
                            or basis["evidence"] not in _domain_evidence_ids(record)
                        ):
                            return False
                        else:
                            evidence_item = evidence.get(basis["evidence"])
                            if not isinstance(evidence_item, dict) or evidence_item.get(
                                "trial_id"
                            ) != record.get("trial_id"):
                                return False
                    else:
                        if set(basis) != {"kind", "repair_id", "codes"}:
                            return False
                        repair_id = basis.get("repair_id")
                        codes = basis.get("codes")
                        if repair_id is not None and (
                            not isinstance(repair_id, str) or not repair_id.strip()
                        ):
                            return False
                        if (
                            not isinstance(codes, list)
                            or any(not isinstance(code, str) or not code.strip() for code in codes)
                            or len(codes) != len(set(codes))
                            or (repair_id is None and not codes)
                        ):
                            return False
            prior = record
    return True


def _snapshot_identity(snapshot: dict[str, object]) -> str:
    return identity({key: value for key, value in snapshot.items() if key != "identity"})


def _overall_judgment(judgments: dict[str, str]) -> str:
    if "high" in judgments.values() or list(judgments.values()).count("some_concerns") >= 2:
        return "high"
    if "some_concerns" in judgments.values():
        return "some_concerns"
    return "low"


def _relation_name(value: object) -> str:
    if not isinstance(value, str):
        return ""
    normalized = unicodedata.normalize("NFKC", value)
    for character in "‐‑‒–—":
        normalized = normalized.replace(character, "-")
    return " ".join(normalized.casefold().replace("-", " ").split())


def _domain_judgment(domain_id: str, answers: dict[str, str]) -> str:
    y = {"yes", "probably_yes"}
    no = {"probably_no", "no"}
    no_or_unknown = no | {"no_information"}
    if domain_id == "domain:randomization":
        if answers["sq:randomization:concealment"] in no:
            return "high"
        if (
            answers["sq:randomization:concealment"] == "no_information"
            and answers["sq:randomization:baseline-imbalance"] in y
        ):
            return "high"
        if (
            answers["sq:randomization:sequence"] in no
            or answers["sq:randomization:concealment"] == "no_information"
            or answers["sq:randomization:baseline-imbalance"] in y
        ):
            return "some_concerns"
        return "low"
    if domain_id == "domain:deviations":
        if (
            answers.get("sq:deviations:context-deviations") in y
            and answers.get("sq:deviations:affected-outcome") in y | {"no_information"}
            and answers.get("sq:deviations:balanced") in no_or_unknown
        ):
            return "high"
        if answers["sq:deviations:appropriate-analysis"] in no_or_unknown and answers.get(
            "sq:deviations:substantial-impact"
        ) in y | {"no_information"}:
            return "high"
        if (
            answers.get("sq:deviations:context-deviations") == "no_information"
            or answers.get("sq:deviations:affected-outcome") in no
            or answers.get("sq:deviations:balanced") in y
            or answers.get("sq:deviations:substantial-impact") in no
        ):
            return "some_concerns"
        return "low"
    if domain_id == "domain:missing":
        if (
            answers["sq:missing:data-available"] in y
            or answers.get("sq:missing:evidence-unbiased") in y
            or answers.get("sq:missing:true-value-dependent") in no
        ):
            return "low"
        return (
            "high"
            if answers.get("sq:missing:likely-dependent") in y | {"no_information"}
            else "some_concerns"
        )
    if domain_id == "domain:measurement":
        if (
            answers["sq:measurement:method-inappropriate"] in y
            or answers["sq:measurement:differential"] in y
        ):
            return "high"
        if answers.get("sq:measurement:influence-likely") in y | {"no_information"}:
            return "high"
        if (
            answers["sq:measurement:differential"] == "no_information"
            or answers.get("sq:measurement:influence-likely") in no
        ):
            return "some_concerns"
        return "low"
    if domain_id == "domain:selection":
        if (
            answers["sq:selection:multiple-measurements"] in y
            or answers["sq:selection:multiple-analyses"] in y
        ):
            return "high"
        if (
            answers["sq:selection:prespecified-analysis"] in no_or_unknown
            or answers["sq:selection:multiple-measurements"] == "no_information"
            or answers["sq:selection:multiple-analyses"] == "no_information"
        ):
            return "some_concerns"
        return "low"
    raise ValueError("unknown Domain")


def _domain_question_sets(
    domain_id: object, answers: object, *, require_complete: bool = True
) -> tuple[list[str], list[str]]:
    """Recompute the exact active and inactive questions from canonical answers."""

    order = _DOMAIN_QUESTION_ORDER.get(domain_id)
    if order is None or not isinstance(answers, dict):
        raise ValueError("invalid Domain question inputs")
    if any(not isinstance(question_id, str) for question_id in answers):
        raise ValueError("invalid Domain question IDs")
    for question_id, answer in answers.items():
        if question_id not in order:
            raise ValueError("answers contain a question outside the Domain")
        allowed = _QUESTION_ALLOWED_ANSWERS.get(question_id, _ANSWER_VALUES)
        if not isinstance(answer, str) or answer not in allowed:
            raise ValueError("answer is not allowed")

    def accepted(question_id: str, values: set[str]) -> bool:
        return question_id in active and answers.get(question_id) in values

    active = set(order[:3]) if domain_id == "domain:randomization" else set()
    if domain_id == "domain:deviations":
        active.update(
            {
                "sq:deviations:participants-aware",
                "sq:deviations:personnel-aware",
                "sq:deviations:appropriate-analysis",
            }
        )
        if accepted(
            "sq:deviations:participants-aware", {"yes", "probably_yes", "no_information"}
        ) or accepted("sq:deviations:personnel-aware", {"yes", "probably_yes", "no_information"}):
            active.add("sq:deviations:context-deviations")
        if accepted("sq:deviations:context-deviations", {"yes", "probably_yes"}):
            active.add("sq:deviations:affected-outcome")
        if accepted("sq:deviations:affected-outcome", {"yes", "probably_yes", "no_information"}):
            active.add("sq:deviations:balanced")
        if accepted("sq:deviations:appropriate-analysis", {"probably_no", "no", "no_information"}):
            active.add("sq:deviations:substantial-impact")
    elif domain_id == "domain:missing":
        active.add("sq:missing:data-available")
        if accepted("sq:missing:data-available", {"probably_no", "no", "no_information"}):
            active.add("sq:missing:evidence-unbiased")
        if accepted("sq:missing:evidence-unbiased", {"probably_no", "no"}):
            active.add("sq:missing:true-value-dependent")
        if accepted("sq:missing:true-value-dependent", {"yes", "probably_yes", "no_information"}):
            active.add("sq:missing:likely-dependent")
    elif domain_id == "domain:measurement":
        active.update({"sq:measurement:method-inappropriate", "sq:measurement:differential"})
        if accepted(
            "sq:measurement:method-inappropriate", {"probably_no", "no", "no_information"}
        ) and accepted("sq:measurement:differential", {"probably_no", "no", "no_information"}):
            active.add("sq:measurement:assessor-aware")
        if accepted("sq:measurement:assessor-aware", {"yes", "probably_yes", "no_information"}):
            active.add("sq:measurement:influence-possible")
        if accepted("sq:measurement:influence-possible", {"yes", "probably_yes", "no_information"}):
            active.add("sq:measurement:influence-likely")
    elif domain_id == "domain:selection":
        active.update(order)

    if require_complete and set(answers) != active:
        raise ValueError("answers do not match active questions")
    return [question_id for question_id in order if question_id in active], [
        question_id for question_id in order if question_id not in active
    ]


def _domain_evaluation(domain_id: object, answers: dict[str, str]) -> tuple[str, str, list[str]]:
    """Replay the domain rule and its severity-driving questions independently."""

    if not isinstance(domain_id, str):
        raise ValueError("invalid Domain")
    _domain_question_sets(domain_id, answers)
    y = {"yes", "probably_yes"}
    no = {"probably_no", "no"}
    no_or_unknown = no | {"no_information"}

    def result(
        judgment: str, trace: str, drivers: set[str] | None = None
    ) -> tuple[str, str, list[str]]:
        ordered = [
            question_id
            for question_id in _DOMAIN_QUESTION_ORDER[domain_id]
            if question_id in (drivers or set())
        ]
        return judgment, trace, ordered

    if domain_id == "domain:randomization":
        if answers["sq:randomization:concealment"] in no:
            return result(
                "high",
                "randomization.concealment_failed",
                {"sq:randomization:concealment"},
            )
        if (
            answers["sq:randomization:concealment"] == "no_information"
            and answers["sq:randomization:baseline-imbalance"] in y
        ):
            return result(
                "high",
                "randomization.unknown_concealment_and_imbalance",
                {"sq:randomization:concealment", "sq:randomization:baseline-imbalance"},
            )
        drivers = {
            question_id
            for question_id, condition in (
                ("sq:randomization:sequence", answers["sq:randomization:sequence"] in no),
                (
                    "sq:randomization:concealment",
                    answers["sq:randomization:concealment"] == "no_information",
                ),
                (
                    "sq:randomization:baseline-imbalance",
                    answers["sq:randomization:baseline-imbalance"] in y,
                ),
            )
            if condition
        }
        if drivers:
            return result("some_concerns", "randomization.some_concerns", drivers)
        return result("low", "randomization.low")

    if domain_id == "domain:deviations":
        if (
            answers.get("sq:deviations:context-deviations") in y
            and answers.get("sq:deviations:affected-outcome") in y | {"no_information"}
            and answers.get("sq:deviations:balanced") in no_or_unknown
        ):
            return result(
                "high",
                "deviations.unbalanced_impact",
                {
                    "sq:deviations:context-deviations",
                    "sq:deviations:affected-outcome",
                    "sq:deviations:balanced",
                },
            )
        if answers["sq:deviations:appropriate-analysis"] in no_or_unknown and answers.get(
            "sq:deviations:substantial-impact"
        ) in y | {"no_information"}:
            return result(
                "high",
                "deviations.analysis_substantial_impact",
                {"sq:deviations:appropriate-analysis", "sq:deviations:substantial-impact"},
            )
        drivers = {
            question_id
            for question_id, condition in (
                (
                    "sq:deviations:context-deviations",
                    answers.get("sq:deviations:context-deviations") == "no_information",
                ),
                (
                    "sq:deviations:affected-outcome",
                    answers.get("sq:deviations:affected-outcome") in no,
                ),
                (
                    "sq:deviations:balanced",
                    answers.get("sq:deviations:balanced") in y,
                ),
                (
                    "sq:deviations:substantial-impact",
                    answers.get("sq:deviations:substantial-impact") in no,
                ),
            )
            if condition
        }
        if drivers:
            return result("some_concerns", "deviations.some_concerns", drivers)
        return result("low", "deviations.low")

    if domain_id == "domain:missing":
        if (
            answers["sq:missing:data-available"] in y
            or answers.get("sq:missing:evidence-unbiased") in y
            or answers.get("sq:missing:true-value-dependent") in no
        ):
            return result("low", "missing.low")
        if answers.get("sq:missing:likely-dependent") in y | {"no_information"}:
            return result("high", "missing.likely_dependent", {"sq:missing:likely-dependent"})
        return result(
            "some_concerns",
            "missing.some_concerns",
            {
                "sq:missing:data-available",
                "sq:missing:evidence-unbiased",
                "sq:missing:true-value-dependent",
                "sq:missing:likely-dependent",
            },
        )

    if domain_id == "domain:measurement":
        drivers = {
            question_id
            for question_id, condition in (
                (
                    "sq:measurement:method-inappropriate",
                    answers["sq:measurement:method-inappropriate"] in y,
                ),
                (
                    "sq:measurement:differential",
                    answers["sq:measurement:differential"] in y,
                ),
            )
            if condition
        }
        if drivers:
            return result("high", "measurement.inappropriate_or_differential", drivers)
        if answers.get("sq:measurement:influence-likely") in y | {"no_information"}:
            return result(
                "high", "measurement.likely_influenced", {"sq:measurement:influence-likely"}
            )
        drivers = {
            question_id
            for question_id, condition in (
                (
                    "sq:measurement:differential",
                    answers["sq:measurement:differential"] == "no_information",
                ),
                (
                    "sq:measurement:influence-likely",
                    answers.get("sq:measurement:influence-likely") in no,
                ),
            )
            if condition
        }
        if drivers:
            return result("some_concerns", "measurement.some_concerns", drivers)
        return result("low", "measurement.low")

    if domain_id == "domain:selection":
        drivers = {
            question_id
            for question_id, condition in (
                (
                    "sq:selection:multiple-measurements",
                    answers["sq:selection:multiple-measurements"] in y,
                ),
                (
                    "sq:selection:multiple-analyses",
                    answers["sq:selection:multiple-analyses"] in y,
                ),
            )
            if condition
        }
        if drivers:
            return result("high", "selection.selective_choice", drivers)
        drivers = {
            question_id
            for question_id, condition in (
                (
                    "sq:selection:prespecified-analysis",
                    answers["sq:selection:prespecified-analysis"] in no_or_unknown,
                ),
                (
                    "sq:selection:multiple-measurements",
                    answers["sq:selection:multiple-measurements"] == "no_information",
                ),
                (
                    "sq:selection:multiple-analyses",
                    answers["sq:selection:multiple-analyses"] == "no_information",
                ),
            )
            if condition
        }
        if drivers:
            return result("some_concerns", "selection.some_concerns", drivers)
        return result("low", "selection.low")
    raise ValueError("unknown Domain")


def _overall_evaluation(judgments: dict[str, str]) -> tuple[str, str, list[str]]:
    if set(judgments) != _EXPECTED_DOMAIN_IDS:
        raise ValueError("all five Domain judgments are required")
    if "high" in judgments.values():
        return (
            "high",
            "overall.any_high",
            [domain_id for domain_id in _EXPECTED_DOMAIN_ORDER if judgments[domain_id] == "high"],
        )
    concerns = list(judgments.values()).count("some_concerns")
    if concerns >= 2:
        return (
            "high",
            "overall.multiple_some_concerns_high",
            [
                domain_id
                for domain_id in _EXPECTED_DOMAIN_ORDER
                if judgments[domain_id] == "some_concerns"
            ],
        )
    if concerns:
        return (
            "some_concerns",
            "overall.any_concerns",
            [
                domain_id
                for domain_id in _EXPECTED_DOMAIN_ORDER
                if judgments[domain_id] == "some_concerns"
            ],
        )
    return "low", "overall.all_low", []


def _counterfactual_answer_branch(
    domain_id: str,
    answers: dict[str, str],
    question_id: str,
    replacement: str,
) -> tuple[dict[str, str], list[str], list[str]]:
    """Project a one-step alternative onto the branch it activates."""

    alternative_answers = dict(answers)
    alternative_answers[question_id] = replacement
    active, _ = _domain_question_sets(domain_id, alternative_answers, require_complete=False)
    projected = {
        question_id: alternative_answers[question_id]
        for question_id in active
        if question_id in alternative_answers
    }
    missing = [question_id for question_id in active if question_id not in projected]
    return projected, active, missing


def _counterfactual_missing_reason(missing: list[str]) -> str:
    return f"missing active question IDs: [{', '.join(missing)}]"


def _valid_overall_receipt(
    receipt: object,
    snapshot: dict[str, object],
    records: dict[str, object],
) -> bool:
    """Replay the diagnostic overall aggregation receipt independently."""

    if not isinstance(receipt, dict) or set(receipt) != {
        "rule",
        "driver_domains",
        "drivers",
        "alternatives",
        "stability",
        "diagnostic_only",
    }:
        return False
    judgments = snapshot.get("domain_judgments")
    if not isinstance(judgments, dict):
        return False
    try:
        expected_overall, expected_rule, expected_driver_domains = _overall_evaluation(judgments)
    except (KeyError, TypeError, ValueError):
        return False
    if (
        receipt.get("rule") != expected_rule
        or receipt.get("driver_domains") != expected_driver_domains
        or receipt.get("diagnostic_only") is not True
        or receipt.get("stability")
        not in {"stable", "sensitive", "not_assessed", "requires_reassessment"}
        or not isinstance(receipt.get("drivers"), list)
        or not isinstance(receipt.get("alternatives"), list)
    ):
        return False
    trial_id = snapshot.get("trial_id")
    if not isinstance(trial_id, str):
        return False
    drivers = receipt["drivers"]
    if [item.get("domain_id") for item in drivers if isinstance(item, dict)] != (
        expected_driver_domains
    ):
        return False
    for item in drivers:
        if not isinstance(item, dict) or set(item) != {
            "domain_id",
            "checkpoint",
            "judgment",
            "trace",
            "driver_questions",
            "driver_answers",
            "evidence_sufficiency",
        }:
            return False
        domain_id = item.get("domain_id")
        record = records.get(f"{trial_id}:{domain_id}")
        if not isinstance(record, dict):
            return False
        answers = {
            answer.get("question_id"): answer.get("answer")
            for answer in record.get("answers", [])
            if isinstance(answer, dict)
            and isinstance(answer.get("question_id"), str)
            and isinstance(answer.get("answer"), str)
        }
        try:
            expected_judgment, expected_trace, expected_questions = _domain_evaluation(
                domain_id, answers
            )
        except (KeyError, TypeError, ValueError):
            return False
        if (
            item.get("checkpoint") != record.get("identity")
            or item.get("judgment") != record.get("judgment")
            or item.get("judgment") != expected_judgment
            or item.get("trace") != record.get("trace")
            or item.get("trace") != [expected_trace]
            or record.get("driver_questions") != expected_questions
            or item.get("driver_questions") != expected_questions
            or item.get("evidence_sufficiency") != record.get("evidence_sufficiency")
            or not isinstance(item.get("driver_answers"), list)
        ):
            return False
        expected_answers = {
            answer.get("question_id"): answer.get("answer")
            for answer in record.get("answers", [])
            if isinstance(answer, dict)
        }
        if item["driver_answers"] != [
            {"question_id": question_id, "answer": expected_answers[question_id]}
            for question_id in expected_questions
        ]:
            return False

    expected_keys: set[tuple[str, str, str, str]] = set()
    observed_keys: set[tuple[str, str, str, str]] = set()
    evaluated_overalls: set[str] = set()
    has_pending = False
    required = {
        "domain_id",
        "question_id",
        "from_answer",
        "to_answer",
        "diagnostic_only",
        "status",
    }
    for domain_id in _EXPECTED_DOMAIN_ORDER:
        record = records.get(f"{trial_id}:{domain_id}")
        if not isinstance(record, dict):
            return False
        answers = {
            answer.get("question_id"): answer.get("answer")
            for answer in record.get("answers", [])
            if isinstance(answer, dict)
            and isinstance(answer.get("question_id"), str)
            and isinstance(answer.get("answer"), str)
        }
        sufficiency = record.get("evidence_sufficiency")
        claims = sufficiency.get("claims", []) if isinstance(sufficiency, dict) else []
        statuses = {
            claim.get("question_id"): claim.get("status")
            for claim in claims
            if isinstance(claim, dict)
        }
        for question_id, answer in answers.items():
            if answer != "no_information" and statuses.get(question_id) not in {
                "unresolved",
                "retrieval_incomplete",
                "not_reported",
            }:
                continue
            for replacement in ("probably_yes", "probably_no"):
                expected_keys.add((domain_id, question_id, answer, replacement))

    for alternative in receipt["alternatives"]:
        if not isinstance(alternative, dict) or not required.issubset(alternative):
            return False
        status = alternative.get("status")
        domain_id = alternative.get("domain_id")
        question_id = alternative.get("question_id")
        from_answer = alternative.get("from_answer")
        to_answer = alternative.get("to_answer")
        key = (domain_id, question_id, from_answer, to_answer)
        if (
            alternative.get("diagnostic_only") is not True
            or status not in {"evaluated", "requires_reassessment"}
            or domain_id not in _EXPECTED_DOMAIN_IDS
            or not isinstance(question_id, str)
            or from_answer not in _ANSWER_VALUES
            or to_answer not in {"probably_yes", "probably_no"}
            or key in observed_keys
        ):
            return False
        record = records.get(f"{trial_id}:{domain_id}")
        if not isinstance(record, dict):
            return False
        answers = {
            answer.get("question_id"): answer.get("answer")
            for answer in record.get("answers", [])
            if isinstance(answer, dict)
            and isinstance(answer.get("question_id"), str)
            and isinstance(answer.get("answer"), str)
        }
        if question_id not in answers or answers[question_id] != from_answer:
            return False
        observed_keys.add(key)
        try:
            projected_answers, _active, missing_active = _counterfactual_answer_branch(
                domain_id,
                answers,
                question_id,
                to_answer,
            )
        except (KeyError, TypeError, ValueError):
            return False
        if missing_active:
            if (
                status != "requires_reassessment"
                or any(
                    alternative.get(key) is not None
                    for key in ("hypothetical_domain_judgment", "hypothetical_overall")
                )
                or set(alternative)
                != required | {"hypothetical_domain_judgment", "hypothetical_overall", "reason"}
                or alternative.get("reason") != _counterfactual_missing_reason(missing_active)
            ):
                return False
            has_pending = True
            continue
        try:
            hypothetical_domain, _, _ = _domain_evaluation(domain_id, projected_answers)
            hypothetical_judgments = dict(judgments)
            hypothetical_judgments[domain_id] = hypothetical_domain
            hypothetical_overall, _, _ = _overall_evaluation(hypothetical_judgments)
        except (KeyError, TypeError, ValueError):
            return False
        expected_alternative_keys = required | {
            "hypothetical_domain_judgment",
            "hypothetical_overall",
        }
        if (
            status != "evaluated"
            or set(alternative)
            not in (expected_alternative_keys, expected_alternative_keys | {"reason"})
            or ("reason" in alternative and alternative["reason"] is not None)
            or alternative.get("hypothetical_domain_judgment") != hypothetical_domain
            or alternative.get("hypothetical_overall") != hypothetical_overall
        ):
            return False
        evaluated_overalls.add(hypothetical_overall)

    if observed_keys != expected_keys:
        return False
    if not receipt["alternatives"]:
        expected_stability = "not_assessed"
    elif any(value != expected_overall for value in evaluated_overalls):
        expected_stability = "sensitive"
    elif has_pending:
        expected_stability = "requires_reassessment"
    else:
        expected_stability = "stable"
    return receipt.get("stability") == expected_stability


def _leaves(value: object, path: str) -> dict[str, object]:
    if isinstance(value, dict):
        return {
            leaf_path: leaf
            for key, child in value.items()
            if key not in {"form", "kind"}
            for leaf_path, leaf in _leaves(child, f"{path}/{key}").items()
        }
    if isinstance(value, list):
        return {
            leaf_path: leaf
            for index, child in enumerate(value)
            for leaf_path, leaf in _leaves(child, f"{path}/{index}").items()
        }
    return {path: value}


def _source_bound_leaves(value: object, path: str) -> dict[str, object]:
    """Return Result claims that must be replayed against Source Evidence.

    Repeated group references and category dimension declarations are structural
    and are checked by the result-shape validator instead. Target timing and
    randomized-arm descriptions are caller/model interpretation fields; they
    remain required and are shown in the audit, but are not duplicate source
    quotations that need exact leaf bindings.
    """
    caller_owned = {
        "/target/outcome_definition",
        "/target/measurement/metric",
        "/target/measurement/method",
        "/target/effect_of_interest",
        "/target/intended_analysis_population",
        "/target/intended_effect_measure",
        "/reported/group_id",
        "/reported/analysis_population",
    }

    return {
        leaf_path: leaf
        for leaf_path, leaf in _leaves(value, path).items()
        if not (
            leaf_path in caller_owned
            or (leaf_path == "/reported/precision" and leaf is None)
            or (leaf_path == "/reported/endpoint/definition" and leaf is None)
            or leaf_path.startswith("/target/time_point_or_window/")
            or (leaf_path.startswith("/target/comparison_groups/") and leaf_path.endswith("/id"))
            or (
                leaf_path.startswith("/target/comparison_groups/")
                and leaf_path.endswith("/assignment")
            )
            or (leaf_path.startswith("/reported/group_values/") and leaf_path.endswith("/group_id"))
            or (leaf_path.startswith("/reported/values/") and leaf_path.endswith("/group_id"))
            or leaf_path.startswith("/reported/category_axis_names/")
        )
    }


def _decimal(value: object) -> Decimal:
    if not isinstance(value, str):
        raise InvalidOperation
    parsed = Decimal(value)
    if not parsed.is_finite():
        raise InvalidOperation
    return parsed


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f") if value else "0"


def _valid_requested_result(
    result: object,
    requested_outcome: str,
    semantics_version: str = "rob2-kit.result-semantics.v0.8",
) -> bool:
    if not isinstance(result, dict) or _relation_name(
        result.get("requested_outcome")
    ) != _relation_name(requested_outcome):
        return False
    if result.get("kind") == "assessable":
        target = result.get("target")
        measurement = target.get("measurement") if isinstance(target, dict) else None
        if (
            not isinstance(target, dict)
            or not isinstance(measurement, dict)
            or _relation_name(target.get("outcome_definition")) != _relation_name(requested_outcome)
            or _relation_name(measurement.get("metric")) != _relation_name(requested_outcome)
        ):
            return False
    return True


def _valid_result_shape(
    result: dict[str, object],
    requested_outcome: str,
    semantics_version: str = "rob2-kit.result-semantics.v0.8",
) -> bool:
    if not _valid_requested_result(result, requested_outcome, semantics_version):
        return False
    base_keys = {
        "kind",
        "trial_id",
        "requested_outcome",
        "relation",
        "relation_rationale",
        "target",
        "reported",
        "clarity",
        "evidence",
        "bindings",
    }
    expected_keys = (
        base_keys
        if semantics_version == "rob2-kit.result-semantics.v0.5"
        else base_keys | {"applicability"}
    )
    if set(result) != expected_keys:
        return False
    applicability = result.get("applicability")
    if semantics_version != "rob2-kit.result-semantics.v0.5" and applicability is None:
        return False
    if applicability is not None:
        expected_keys = (
            {"design", "status", "rationale", "evidence"}
            if semantics_version == "rob2-kit.result-semantics.v0.6"
            else {"design", "rationale", "evidence"}
        )
        if not isinstance(applicability, dict) or set(applicability) != expected_keys:
            return False
        designs = {"individual_parallel", "cluster_randomized", "crossover", "unclear"}
        if applicability.get("design") not in designs:
            return False
        if (
            not isinstance(applicability.get("rationale"), str)
            or not applicability["rationale"].strip()
        ):
            return False
        evidence = applicability.get("evidence")
        if not isinstance(evidence, list) or any(
            not isinstance(item, str) or not item for item in evidence
        ):
            return False
        if applicability["design"] != "unclear" and not evidence:
            return False
        if semantics_version == "rob2-kit.result-semantics.v0.6":
            status_by_design = {
                "individual_parallel": "supported",
                "cluster_randomized": "unsupported",
                "crossover": "unsupported",
                "unclear": "uncertain",
            }
            if applicability.get("status") != status_by_design[applicability["design"]]:
                return False
    target = result.get("target")
    reported = result.get("reported")
    if not isinstance(target, dict) or not isinstance(reported, dict):
        return False
    endpoint = reported.get("endpoint")
    clarity = result.get("clarity")
    if (
        not isinstance(clarity, dict)
        or set(clarity)
        != {
            "outcome_definition",
            "measurement",
            "time_point",
            "analysis_population",
            "comparison_groups",
            "effect_measure",
            "source_table_meaning",
            "eligible_result_choice",
        }
        or any(
            not isinstance(value, str) or value not in {"specified", "unclear", "unavailable"}
            for value in clarity.values()
        )
        or set(target)
        != {
            "outcome_definition",
            "measurement",
            "time_point_or_window",
            "effect_of_interest",
            "comparison_groups",
            "intended_analysis_population",
            "intended_effect_measure",
        }
        or target.get("effect_of_interest") != "assignment"
        or not isinstance(target.get("intended_analysis_population"), str)
        or not target["intended_analysis_population"].strip()
        or not isinstance(target.get("intended_effect_measure"), str)
        or not target["intended_effect_measure"].strip()
        or not _nonblank(result.get("relation_rationale"))
        or not isinstance(endpoint, dict)
        or not _nonblank(reported.get("analysis_population"))
        or set(endpoint) != {"name", "definition"}
        or not _nonblank(endpoint.get("name"))
        or (endpoint.get("definition") is not None and not _nonblank(endpoint.get("definition")))
    ):
        return False
    measurement = target.get("measurement")
    timing = target.get("time_point_or_window")
    groups = target.get("comparison_groups")
    if (
        not isinstance(measurement, dict)
        or set(measurement) != {"metric", "method"}
        or not all(_nonblank(measurement.get(key)) for key in ("metric", "method"))
        or not isinstance(timing, dict)
        or not isinstance(timing.get("kind"), str)
        or not _nonblank(timing.get("description"))
        or not isinstance(groups, list)
        or len(groups) < 2
        or any(
            not isinstance(group, dict)
            or set(group) != {"id", "assignment"}
            or not _nonblank(group.get("id"))
            or not _nonblank(group.get("assignment"))
            for group in groups
        )
    ):
        return False
    if timing["kind"] == "described":
        if set(timing) != {"kind", "description"}:
            return False
    elif timing["kind"] == "quantified":
        if set(timing) != {"kind", "description", "value", "unit"} or not all(
            _nonblank(timing.get(key)) for key in ("value", "unit")
        ):
            return False
    else:
        return False
    target_ids = [group["id"] for group in groups]
    if len(target_ids) != len(set(target_ids)):
        return False

    def valid_values(values: object, *, optional: bool = False) -> tuple[bool, set[str]]:
        if not isinstance(values, list):
            return False, set()
        if optional and not values:
            return True, set()
        if len(values) < 2:
            return False, set()
        ids: list[str] = []
        for item in values:
            if (
                not isinstance(item, dict)
                or set(item) != {"group_id", "statistic", "value", "unit"}
                or not all(
                    _nonblank(item.get(key)) for key in ("group_id", "statistic", "value", "unit")
                )
            ):
                return False, set()
            ids.append(item["group_id"])
        return len(ids) == len(set(ids)), set(ids)

    form = reported.get("form")
    if form == "comparative_effect":
        if (
            set(reported)
            != {
                "form",
                "effect_measure",
                "estimate",
                "precision",
                "analysis_population",
                "endpoint",
                "group_values",
            }
            or not all(_nonblank(reported[key]) for key in ("effect_measure", "estimate"))
            or (reported["precision"] is not None and not _nonblank(reported["precision"]))
        ):
            return False
        valid, reported_ids = valid_values(reported["group_values"], optional=True)
    elif form == "group_bound_values":
        values_key = (
            "group_values" if semantics_version == "rob2-kit.result-semantics.v0.8" else "values"
        )
        if set(reported) != {"form", "analysis_population", "endpoint", values_key}:
            return False
        valid, reported_ids = valid_values(reported[values_key])
    elif form == "single_group_category_profile":
        if (
            set(reported)
            != {
                "form",
                "analysis_population",
                "endpoint",
                "group_id",
                "denominator_basis",
                "category_axis_names",
                "categories",
            }
            or not all(_nonblank(reported.get(key)) for key in ("group_id", "denominator_basis"))
            or not isinstance(reported.get("category_axis_names"), list)
            or not reported["category_axis_names"]
            or len(set(reported["category_axis_names"])) != len(reported["category_axis_names"])
            or not all(
                isinstance(axis, str) and axis.strip() for axis in reported["category_axis_names"]
            )
        ):
            return False
        categories = reported.get("categories")
        if not isinstance(categories, list) or not categories:
            return False
        if any(
            not isinstance(item, dict)
            or set(item) != {"category_axes", "value"}
            or not _nonblank(item.get("value"))
            or not isinstance(item.get("category_axes"), list)
            or len(item["category_axes"]) != len(reported["category_axis_names"])
            or any(not isinstance(axis, str) or not axis.strip() for axis in item["category_axes"])
            for item in categories
        ):
            return False
        category_keys = {tuple(item["category_axes"]) for item in categories}
        if len(category_keys) != len(categories):
            return False
        valid, reported_ids = True, {reported.get("group_id")}
    else:
        return False
    if form == "single_group_category_profile":
        return valid and len(reported_ids) == 1 and reported_ids <= set(target_ids)
    return valid and (not reported_ids or reported_ids == set(target_ids))


def _reported_result_has_coherent_anchor(
    result: dict[str, object],
    evidence: list[dict[str, object]],
    by_handle: dict[str, dict[str, object]],
    *,
    strict_numeric: bool = True,
    semantics_version: str = "rob2-kit.result-semantics.v0.8",
) -> bool:
    reported = cast(dict[str, Any], result["reported"])
    endpoint = reported["endpoint"]
    endpoint_name = endpoint["name"]

    def supports(
        value: object, reference: dict[str, object], field_path: str | None = None
    ) -> bool:
        if reference.get("kind") == "table_multispan":
            spans = reference.get("spans")
            if not isinstance(spans, list):
                return False
            return any(
                isinstance(span, dict)
                and isinstance((selected := by_handle.get(str(span.get("handle")))), dict)
                and selected.get("trial_id") == result["trial_id"]
                and (
                    _result_value_contains(
                        str(selected.get("quote", selected.get("transcription", ""))),
                        str(value),
                        field_path,
                    )
                    if strict_numeric
                    else _normalized_contains(
                        str(selected.get("quote", selected.get("transcription", ""))),
                        str(value),
                    )
                )
                for span in spans
            )
        selected = by_handle.get(str(reference.get("handle")))
        if not isinstance(selected, dict) or selected.get("trial_id") != result["trial_id"]:
            return False
        if reference.get("kind") == "derived":
            return value == reference.get("value")
        material = str(
            reference.get("transcription", "")
            if reference.get("kind") == "figure"
            else selected.get("quote", selected.get("transcription", ""))
        )
        return (
            _result_value_contains(material, str(value), field_path)
            if strict_numeric
            else _normalized_contains(material, str(value))
        )

    if reported["form"] == "comparative_effect":
        quantitative_tuples = [
            (
                ("/reported/effect_measure", reported["effect_measure"]),
                ("/reported/estimate", reported["estimate"]),
            ),
            *(
                (
                    (f"/reported/group_values/{index}/statistic", item["statistic"]),
                    (f"/reported/group_values/{index}/value", item["value"]),
                    (f"/reported/group_values/{index}/unit", item["unit"]),
                )
                for index, item in enumerate(reported["group_values"])
            ),
        ]
    elif reported["form"] == "group_bound_values":
        values_key = (
            "group_values" if semantics_version == "rob2-kit.result-semantics.v0.8" else "values"
        )
        quantitative_tuples = [
            (
                (f"/reported/{values_key}/{index}/statistic", item["statistic"]),
                (f"/reported/{values_key}/{index}/value", item["value"]),
                (f"/reported/{values_key}/{index}/unit", item["unit"]),
            )
            for index, item in enumerate(reported[values_key])
        ]
    else:
        quantitative_tuples = [
            tuple(
                [
                    *(
                        (
                            f"/reported/categories/{index}/category_axes/{axis}",
                            value,
                        )
                        for axis, value in enumerate(item["category_axes"])
                    ),
                    (f"/reported/categories/{index}/value", item["value"]),
                ]
            )
            for index, item in enumerate(reported["categories"])
        ]

    def multispan_anchor(reference: dict[str, object]) -> bool:
        spans = reference.get("spans")
        if not isinstance(spans, list):
            return False
        roles = {
            span.get("role")
            for span in spans
            if isinstance(span, dict) and isinstance(span.get("role"), str)
        }
        if {"header", "quantitative_row"} - roles or _is_generic_table_endpoint(endpoint_name):
            return False

        def supports_roles(value: object, accepted_roles: set[str], field_path: str) -> bool:
            return any(
                isinstance(span, dict)
                and span.get("role") in accepted_roles
                and supports(value, {**reference, "spans": [span]}, field_path)
                for span in spans
            )

        return supports_roles(
            endpoint_name, {"title_or_definition", "header"}, "/reported/endpoint/name"
        ) and any(
            all(
                supports_roles(value, {"header", "quantitative_row", "unit", "footnote"}, path)
                for path, value in quantitative
            )
            for quantitative in quantitative_tuples
        )

    return any(
        (
            multispan_anchor(reference)
            if reference.get("kind") == "table_multispan"
            else supports(endpoint_name, reference, "/reported/endpoint/name")
        )
        and any(
            all(supports(value, reference, field_path) for field_path, value in quantitative)
            for quantitative in quantitative_tuples
        )
        for reference in evidence
    )


def _is_generic_table_endpoint(value: object) -> bool:
    return isinstance(value, str) and " ".join(value.casefold().split()) in {
        "total",
        "overall",
        "all",
        "all patients",
        "all participants",
    }


def _valid_no_supported_sources_basis(batch: object, trial_id: str) -> bool:
    """Require the exact captured intake condition for a source-free Trial."""
    if not isinstance(batch, dict):
        return False
    conditions = batch.get("conditions")
    trials = batch.get("trials")
    expected = {"code": "no_supported_sources", "trial_id": trial_id}
    return (
        isinstance(conditions, list)
        and any(condition == expected for condition in conditions)
        and isinstance(trials, list)
        and any(
            isinstance(trial, dict)
            and trial.get("id") == trial_id
            and isinstance(trial.get("sources"), list)
            and not trial["sources"]
            for trial in trials
        )
    )


def _valid_result_evidence(
    result: object,
    catalog: dict[str, object],
    sources: dict[str, dict[str, object]],
    requested_outcomes: dict[str, str],
    batch: object = None,
    semantics_version: str = "rob2-kit.result-semantics.v0.8",
) -> bool:
    """Replay the closed Result Evidence contract from exported selections."""
    if not isinstance(result, dict) or not isinstance(result.get("trial_id"), str):
        return False
    kind = result.get("kind")
    relation = result.get("relation")
    requested_outcome = requested_outcomes.get(result["trial_id"])
    if requested_outcome is None or not _valid_requested_result(
        result, requested_outcome, semantics_version
    ):
        return False
    if kind == "unavailable":
        facts = result.get("missing_facts")
        if (
            set(result) != {"kind", "trial_id", "requested_outcome", "relation", "missing_facts"}
            or relation not in {"ambiguous", "unavailable"}
            or not isinstance(facts, list)
            or not facts
            or any(
                not isinstance(fact, dict)
                or set(fact) != {"fact", "basis"}
                or not isinstance(fact.get("fact"), str)
                or not fact["fact"].strip()
                or not isinstance(fact.get("basis"), dict)
                or (
                    fact["basis"].get("kind") == "missing_reporting"
                    and (
                        set(fact["basis"]) != {"kind", "evidence", "source"}
                        or not all(
                            isinstance(fact["basis"].get(key), str) and fact["basis"][key].strip()
                            for key in ("evidence", "source")
                        )
                    )
                )
                or (
                    fact["basis"].get("kind") == "intake_condition"
                    and (
                        set(fact["basis"]) != {"kind", "code"}
                        or fact["basis"].get("code") != "no_supported_sources"
                    )
                )
                or fact["basis"].get("kind") not in {"missing_reporting", "intake_condition"}
                for fact in facts
            )
            or len({fact["fact"] for fact in facts}) != len(facts)
        ):
            return False
        for fact in facts:
            basis = fact["basis"]
            if basis.get("kind") == "intake_condition":
                if (
                    set(basis) != {"kind", "code"}
                    or basis.get("code") != "no_supported_sources"
                    or not _valid_no_supported_sources_basis(batch, result["trial_id"])
                ):
                    return False
                continue
            if set(basis) != {"kind", "evidence", "source"}:
                return False
        by_handle = {
            key: item
            for item in catalog.values()
            if isinstance(item, dict)
            for key in (item.get("handle"), item.get("identity"))
            if isinstance(key, str)
        }
        for fact in facts:
            basis = fact["basis"]
            if basis.get("kind") == "intake_condition":
                continue
            selected = by_handle.get(basis["evidence"])
            if not isinstance(selected, dict) or selected.get("trial_id") != result["trial_id"]:
                return False
            material = str(selected.get("quote", selected.get("transcription", "")))
            if material != basis["source"]:
                return False
        return True
    if kind != "assessable" or relation not in {
        "exact",
        "broader",
        "narrower",
        "component",
        "related",
    }:
        return False
    if not _valid_result_shape(result, requested_outcome, semantics_version):
        return False
    strict_numeric = semantics_version == "rob2-kit.result-semantics.v0.8"

    def supports_material(material: str, value: str, field_path: str | None = None) -> bool:
        return (
            _result_value_contains(material, value, field_path)
            if strict_numeric
            else _normalized_contains(material, value)
        )

    if not isinstance(result.get("target"), dict) or not isinstance(result.get("reported"), dict):
        return False
    evidence = result.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        return False
    reported = cast(dict[str, object], result["reported"])
    endpoint = cast(dict[str, object], reported["endpoint"])
    endpoint_definition = endpoint.get("definition")
    by_handle = {
        item.get("handle"): item
        for item in catalog.values()
        if isinstance(item, dict) and isinstance(item.get("handle"), str)
    }
    applicability = result.get("applicability")
    if isinstance(applicability, dict) and any(
        not isinstance(by_handle.get(handle), dict)
        or by_handle[handle].get("trial_id") != result["trial_id"]
        for handle in applicability.get("evidence", [])
    ):
        return False
    target_groups = {
        group.get("id")
        for group in result["target"].get("comparison_groups", [])
        if isinstance(group, dict) and isinstance(group.get("id"), str)
    }
    for reference in evidence:
        if not isinstance(reference, dict):
            return False
        item_kind = reference.get("kind")
        expected_keys = {
            "narrative": {"kind", "handle"},
            "table": {
                "kind",
                "handle",
                "basis",
                "title",
                "scope",
                "cohort",
                "row",
                "columns",
                "group_or_category_axes",
                "cells",
                "units",
                "denominators",
                "footnotes",
            },
            "table_multispan": {
                "kind",
                "basis",
                "spans",
                "title",
                "scope",
                "cohort",
                "row",
                "columns",
                "group_or_category_axes",
                "cells",
                "units",
                "denominators",
                "footnotes",
            },
            "figure": {
                "kind",
                "handle",
                "render_identity",
                "region",
                "transcription",
                "provenance",
            },
            "derived": {"kind", "operation", "inputs", "value"},
        }
        expected = expected_keys.get(item_kind)
        if expected is None or frozenset(reference) not in (
            {frozenset(expected), frozenset(expected | {"delivery_receipt"})}
            if item_kind == "figure"
            else {frozenset(expected)}
        ):
            return False
        if item_kind == "derived":
            inputs = reference.get("inputs")
            if (
                reference.get("operation") not in {"difference", "ratio", "sum"}
                or not isinstance(inputs, list)
                or not inputs
            ):
                return False
            try:
                values = [_decimal(item.get("value")) for item in inputs if isinstance(item, dict)]
                if len(values) != len(inputs):
                    return False
                derived = (
                    sum(values, Decimal("0"))
                    if reference["operation"] == "sum"
                    else values[0] - values[1]
                    if reference["operation"] == "difference" and len(values) == 2
                    else values[0] / values[1]
                    if reference["operation"] == "ratio" and len(values) == 2 and values[1]
                    else None
                )
                if derived is None or _decimal_text(derived) != reference.get("value"):
                    return False
            except (InvalidOperation, ValueError, ZeroDivisionError):
                return False
            for input in inputs:
                if not isinstance(input, dict) or set(input) != {"handle", "value"}:
                    return False
                selected = by_handle.get(input.get("handle"))
                material = (
                    ""
                    if not isinstance(selected, dict)
                    else str(selected.get("quote", selected.get("transcription", "")))
                )
                if (
                    not isinstance(selected, dict)
                    or selected.get("trial_id") != result["trial_id"]
                    or not supports_material(material, str(input.get("value", "")))
                ):
                    return False
            continue
        if item_kind == "table_multispan":
            spans = reference.get("spans")
            if (
                reference.get("basis") != "text"
                or not isinstance(spans, list)
                or len(spans) < 2
                or len(
                    {
                        span.get("handle")
                        for span in spans
                        if isinstance(span, dict) and isinstance(span.get("handle"), str)
                    }
                )
                < 2
                or any(
                    not isinstance(span, dict)
                    or set(span) != {"role", "handle"}
                    or span.get("role")
                    not in {"title_or_definition", "header", "quantitative_row", "unit", "footnote"}
                    or not isinstance((selected := by_handle.get(span.get("handle"))), dict)
                    or selected.get("kind") != "narrative"
                    or selected.get("trial_id") != result["trial_id"]
                    for span in spans
                )
            ):
                return False
            roles = {span["role"] for span in spans}
            if {"header", "quantitative_row"} - roles:
                return False
            scalar_fields = [reference.get(key) for key in ("title", "scope", "cohort", "row")]
            array_fields = {
                key: reference.get(key)
                for key in (
                    "columns",
                    "group_or_category_axes",
                    "cells",
                    "units",
                    "denominators",
                    "footnotes",
                )
            }
            required_array_fields = {
                key: values for key, values in array_fields.items() if key != "footnotes"
            }
            if (
                any(not isinstance(value, str) or not value.strip() for value in scalar_fields)
                or any(
                    not isinstance(items, list) or not items
                    for items in required_array_fields.values()
                )
                or not isinstance(array_fields["footnotes"], list)
                or any(
                    not isinstance(value, str) or not value.strip()
                    for items in array_fields.values()
                    for value in items
                )
                or target_groups & set(reference.get("group_or_category_axes", []))
                or _is_generic_table_endpoint(endpoint.get("name"))
            ):
                return False
            materials = [str(by_handle[span["handle"]].get("quote", "")) for span in spans]
            values = [
                *scalar_fields,
                *[value for items in array_fields.values() for value in items],
            ]
            if any(
                not any(supports_material(material, value) for material in materials)
                for value in values
            ):
                return False
            continue
        selected = by_handle.get(reference.get("handle"))
        if not isinstance(selected, dict) or selected.get("trial_id") != result["trial_id"]:
            return False
        expected_kind = (
            "narrative"
            if item_kind == "table" and reference.get("basis") == "text"
            else "figure"
            if item_kind == "table"
            else item_kind
        )
        if (
            item_kind not in {"narrative", "table", "figure"}
            or selected.get("kind") != expected_kind
        ):
            return False
        material = str(selected.get("quote", selected.get("transcription", "")))
        if item_kind == "narrative":
            # The selected handle resolves to the immutable page-preserving
            # premise. Clauses and source-to-value mappings are not part of the
            # Proposal contract.
            pass
        elif item_kind == "table":
            scalar_fields = [reference.get(key) for key in ("title", "scope", "cohort", "row")]
            array_fields = {
                key: reference.get(key)
                for key in (
                    "columns",
                    "group_or_category_axes",
                    "cells",
                    "units",
                    "denominators",
                    "footnotes",
                )
            }
            required_array_fields = {
                key: values for key, values in array_fields.items() if key != "footnotes"
            }
            if (
                reference.get("basis") not in {"text", "visual"}
                or any(
                    not isinstance(value, str)
                    or not value.strip()
                    or not supports_material(material, value)
                    for value in scalar_fields
                )
                or any(
                    not isinstance(values, list) or not values
                    for values in required_array_fields.values()
                )
                or not isinstance(array_fields["footnotes"], list)
                or any(
                    not isinstance(value, str) or not value.strip()
                    for values in array_fields.values()
                    for value in values
                )
                or any(
                    not supports_material(material, value)
                    for values in array_fields.values()
                    for value in values
                )
                or target_groups & set(reference.get("group_or_category_axes", []))
            ):
                return False
        else:
            render = selected.get("render")
            region = reference.get("region")
            source = sources.get(str(selected.get("source_id")))
            if (
                not isinstance(render, dict)
                or not isinstance(region, list)
                or len(region) != 4
                or not all(
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and math.isfinite(value)
                    for value in region
                )
                or not (0 <= region[0] < region[2] <= 1 and 0 <= region[1] < region[3] <= 1)
                or reference.get("render_identity") != render.get("identity")
                or reference.get("delivery_receipt") != selected.get("delivery_receipt")
                or reference.get("transcription") != selected.get("transcription")
                or reference.get("provenance") != selected.get("provenance")
                or region != selected.get("region")
                or not isinstance(source, dict)
                or not isinstance(reference.get("transcription"), str)
                or not reference["transcription"].strip()
                or render.get("identity")
                != identity(
                    {
                        "source_id": selected.get("source_id"),
                        "source_sha256": source.get("sha256"),
                        "page": render.get("page"),
                        "recipe": render.get("recipe"),
                    }
                )
            ):
                return False
    if not _reported_result_has_coherent_anchor(
        result,
        evidence,
        cast(dict[str, dict[str, object]], by_handle),
        strict_numeric=strict_numeric,
        semantics_version=semantics_version,
    ):
        return False
    leaves = {
        **_source_bound_leaves(result["target"], "/target"),
        **_source_bound_leaves(result["reported"], "/reported"),
    }
    bindings = result.get("bindings")
    if not isinstance(bindings, list) or len(bindings) != len(leaves):
        return False
    paths = [item.get("field", {}).get("path") for item in bindings if isinstance(item, dict)]
    if len(paths) != len(bindings) or set(paths) != set(leaves) or len(set(paths)) != len(paths):
        return False
    if endpoint_definition is not None:
        endpoint_binding_indices = {
            item.get("evidence_index")
            for item in bindings
            if isinstance(item, dict)
            and item.get("field", {}).get("path")
            in {"/reported/endpoint/name", "/reported/endpoint/definition"}
        }
        if len(endpoint_binding_indices) != 1:
            return False
    for binding in bindings:
        if (
            not isinstance(binding, dict)
            or set(binding) != {"field", "evidence_index", "value_digest"}
            or not isinstance(binding.get("field"), dict)
            or set(binding["field"]) != {"path"}
        ):
            return False
        path, index = binding["field"]["path"], binding.get("evidence_index")
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(evidence):
            return False
        if binding.get("value_digest") != identity(leaves[path]):
            return False
        reference = evidence[index]
        value, item_kind = str(leaves[path]), reference.get("kind")
        if item_kind == "narrative":
            material = str(
                by_handle[reference["handle"]].get(
                    "quote", by_handle[reference["handle"]].get("transcription", "")
                )
            )
            if not supports_material(material, value, path):
                return False
        if item_kind == "table" and not supports_material(
            str(
                by_handle[reference["handle"]].get(
                    "quote", by_handle[reference["handle"]].get("transcription", "")
                )
            ),
            value,
        ):
            return False
        if item_kind == "table_multispan" and not any(
            supports_material(str(by_handle[span["handle"]].get("quote", "")), value, path)
            for span in reference["spans"]
        ):
            return False
        if item_kind == "figure":
            figure_material = str(reference.get("transcription", ""))
            if not supports_material(figure_material, value, path):
                return False
        if item_kind == "derived" and value != reference.get("value"):
            return False
    return True


def _claims(canonical: dict[str, object]) -> dict[str, object]:
    dispositions = canonical["dispositions"]
    assert isinstance(dispositions, dict)
    modern = "trial_reviews" in canonical and "trial_closures" in canonical
    counts = {
        name: sum(value == name for value in dispositions.values())
        for name in (
            ("assessed", "needs_input", "unsupported_design", "failed", "pending", "reviewable")
            if modern
            else ("assessed", "needs_input", "failed", "pending")
        )
    }
    total = len(dispositions)
    if modern:
        wording = (
            "Batch finalized. No RoB 2 assessments were completed."
            if not counts["assessed"]
            else "Batch finalized. "
            f"RoB 2 assessments completed for {counts['assessed']}/{total} Trials. "
            f"{counts['needs_input']} Trials need information; "
            f"{counts['unsupported_design']} have unsupported designs; "
            f"{counts['failed']} Trials failed."
        )
    else:
        wording = (
            "Batch finalized. No RoB 2 assessments were completed."
            if not counts["assessed"]
            else "Batch finalized. "
            f"RoB 2 assessments completed for {counts['assessed']}/{total} Trials. "
            f"{counts['needs_input']} Trials need input; {counts['failed']} Trials failed."
        )
    snapshots = canonical.get("snapshots", {})
    if not isinstance(snapshots, dict):
        snapshots = {}
    return {
        "trial_dispositions": dispositions,
        "counts": counts,
        "authoritative_wording": wording,
        "overall": {
            trial_id: snapshot.get("overall")
            for trial_id, snapshot in snapshots.items()
            if dispositions.get(trial_id) == "assessed" and isinstance(snapshot, dict)
        },
    }


def _valid_trial_review_closures(
    trial_reviews: object,
    trial_closures: object,
    terminals: object,
    dispositions: dict[str, Any],
    batch_trial_ids: set[str],
    current_results: dict[str, dict[str, Any]],
    domain_records: dict[str, Any],
) -> bool:
    if (
        not isinstance(trial_reviews, dict)
        or not isinstance(trial_closures, dict)
        or not isinstance(terminals, dict)
        or set(trial_reviews) != batch_trial_ids
        or set(trial_closures) != batch_trial_ids
        or set(dispositions) != batch_trial_ids
    ):
        return False

    allowed = {"assessed", "needs_input", "unsupported_design", "failed"}
    terminal_by_trial: dict[str, dict[str, Any]] = {}
    for terminal_identity, terminal in terminals.items():
        if (
            not isinstance(terminal_identity, str)
            or not isinstance(terminal, dict)
            or set(terminal)
            != {"identity", "trial_id", "disposition", "reason", "facts", "review_identity"}
            or terminal.get("identity") != terminal_identity
            or terminal.get("disposition") not in {"needs_input", "unsupported_design", "failed"}
            or not isinstance(terminal.get("trial_id"), str)
            or not isinstance(terminal.get("reason"), str)
            or not terminal["reason"].strip()
            or not isinstance(terminal.get("facts"), list)
            or not terminal["facts"]
            or any(not isinstance(fact, str) or not fact.strip() for fact in terminal["facts"])
            or not isinstance(terminal.get("review_identity"), str)
            or identity({key: value for key, value in terminal.items() if key != "identity"})
            != terminal_identity
        ):
            return False
        trial_id = terminal["trial_id"]
        if trial_id not in batch_trial_ids or trial_id in terminal_by_trial:
            return False
        terminal_by_trial[trial_id] = terminal

    for trial_id in batch_trial_ids:
        review = trial_reviews[trial_id]
        closure = trial_closures[trial_id]
        disposition = dispositions[trial_id]
        result = current_results.get(trial_id)
        review_shape = {
            "identity",
            "trial_id",
            "result_identity",
            "checkpoint_ids",
            "disposition",
            "reason",
            "facts",
        }
        review_shape_with_attribution = review_shape | {"domain_attribution"}
        if (
            not isinstance(review, dict)
            or set(review) not in (review_shape, review_shape_with_attribution)
            or review.get("trial_id") != trial_id
            or review.get("disposition") not in allowed
            or review.get("disposition") != disposition
            or not isinstance(review.get("result_identity"), str)
            or not isinstance(result, dict)
            or review["result_identity"] != identity(result)
            or (
                review.get("reason") is not None
                and (not isinstance(review.get("reason"), str) or not review["reason"].strip())
            )
            or not isinstance(review.get("facts"), list)
            or any(not isinstance(fact, str) or not fact.strip() for fact in review["facts"])
            or review.get("identity")
            != identity({key: value for key, value in review.items() if key != "identity"})
            or not isinstance(closure, dict)
            or set(closure) != {"identity", "trial_id", "review_identity", "disposition"}
            or closure.get("trial_id") != trial_id
            or closure.get("review_identity") != review.get("identity")
            or closure.get("disposition") != disposition
            or closure.get("identity")
            != identity({key: value for key, value in closure.items() if key != "identity"})
        ):
            return False

        checkpoint_ids: list[str] = []
        for domain_id in _EXPECTED_DOMAIN_ORDER:
            record = domain_records.get(f"{trial_id}:{domain_id}")
            if record is not None:
                if not isinstance(record, dict) or not isinstance(record.get("identity"), str):
                    return False
                checkpoint_ids.append(record["identity"])
        if review.get("checkpoint_ids") != checkpoint_ids:
            return False
        if "domain_attribution" in review:
            attribution = review.get("domain_attribution")
            if not isinstance(attribution, list) or len(attribution) != len(checkpoint_ids):
                return False
            domain_ids = [
                domain_id
                for domain_id in _EXPECTED_DOMAIN_ORDER
                if f"{trial_id}:{domain_id}" in domain_records
            ]
            for domain_id, item in zip(domain_ids, attribution, strict=True):
                record = domain_records.get(f"{trial_id}:{domain_id}")
                if not isinstance(item, dict) or not isinstance(record, dict):
                    return False
                basis = record.get("revision_basis")
                expected_attribution = (
                    basis.get("kind")
                    if isinstance(basis, dict)
                    and basis.get("kind")
                    in {"new_evidence", "self_correction", "mechanical_repair"}
                    else "unchanged"
                )
                expected = {
                    "domain_id": domain_id,
                    "attribution": expected_attribution,
                    "checkpoint_identity": record.get("identity"),
                }
                if isinstance(record.get("supersedes"), str):
                    expected["supersedes"] = record["supersedes"]
                if expected_attribution != "unchanged":
                    expected["revision_basis"] = basis
                if item != expected:
                    return False
        if disposition == "assessed" and len(checkpoint_ids) != len(_EXPECTED_DOMAIN_ORDER):
            return False
        if disposition == "assessed":
            if review.get("reason") is not None or review.get("facts"):
                return False
        elif (
            not isinstance(review.get("reason"), str)
            or not review["reason"].strip()
            or not review.get("facts")
        ):
            return False

        result_kind = result.get("kind")
        applicability = result.get("applicability")
        design = applicability.get("design") if isinstance(applicability, dict) else None
        unsupported_design = design in {"cluster_randomized", "crossover"}
        if (
            (result_kind == "unavailable" and disposition != "needs_input")
            or (design == "unclear" and disposition != "needs_input")
            or (unsupported_design and disposition != "unsupported_design")
            or (disposition == "unsupported_design" and not unsupported_design)
            or (
                disposition == "assessed"
                and (result_kind != "assessable" or design != "individual_parallel")
            )
        ):
            return False

        terminal = terminal_by_trial.get(trial_id)
        if disposition == "assessed":
            if terminal is not None:
                return False
        elif (
            terminal is None
            or terminal.get("disposition") != disposition
            or terminal.get("review_identity") != review.get("identity")
            or terminal.get("reason") != review.get("reason")
            or terminal.get("facts") != review.get("facts")
        ):
            return False
        if result_kind == "unavailable":
            missing_facts = result.get("missing_facts")
            if not isinstance(missing_facts, list) or terminal_by_trial.get(trial_id, {}).get(
                "facts"
            ) != [item.get("fact") for item in missing_facts if isinstance(item, dict)]:
                return False
    return set(terminal_by_trial) == {
        trial_id for trial_id, disposition in dispositions.items() if disposition != "assessed"
    }


def verify(path: Path) -> tuple[bool, str]:
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if names != sorted(names) or len(names) != len(set(names)):
                return False, "archive names are not deterministic"
            for info in archive.infolist():
                if info.date_time != (1980, 1, 1, 0, 0, 0):
                    return False, "archive timestamps are not deterministic"
                if info.external_attr != 0o644 << 16:
                    return False, "archive permissions are not deterministic"
                if info.compress_type != zipfile.ZIP_DEFLATED:
                    return False, "archive compression is not deterministic"
            if any(name.startswith("/") or ".." in Path(name).parts for name in names):
                return False, "archive contains an unsafe path"
            if any("\\" in name or posixpath.normpath(name) != name for name in names):
                return False, "archive contains a non-canonical path"
            manifest = json.loads(archive.read("manifest.json"))
            if not isinstance(manifest, dict) or set(manifest) != {"schema", "identity", "files"}:
                return False, "manifest envelope is not closed"
            if manifest.get("schema") != "rob2-kit.bundle.v0.3":
                return False, "unsupported bundle schema"
            rows = manifest.get("files")
            if not isinstance(rows, list):
                return False, "manifest files are missing"
            if any(not isinstance(row, dict) or set(row) != {"path", "sha256"} for row in rows):
                return False, "manifest file rows are malformed"
            row_paths = [row["path"] for row in rows]
            if len(row_paths) != len(set(row_paths)) or row_paths != sorted(row_paths):
                return False, "manifest file order is not deterministic"
            expected = {row["path"] for row in rows} | {"manifest.json"}
            if set(names) != expected:
                return False, "manifest members do not match archive"
            forbidden = {".bin", "source_bytes", "prompts", "traces"}
            if any(
                Path(name).suffix == ".bin" or any(part in forbidden for part in Path(name).parts)
                for name in names
            ):
                return False, "bundle contains private capture or trace data"
            for row in rows:
                data = archive.read(row["path"])
                digest = "sha256:" + hashlib.sha256(data).hexdigest()
                if digest != row.get("sha256"):
                    return False, f"hash mismatch: {row.get('path')}"
                if str(row["path"]).endswith(".json"):
                    try:
                        parsed = json.loads(data)
                    except json.JSONDecodeError:
                        return False, f"invalid JSON: {row.get('path')}"
                    if _contains_forbidden_paths(parsed):
                        return False, "bundle contains a platform path"
            canonical = json.loads(archive.read("canonical.json"))
            legacy_canonical_fields = {
                "batch",
                "proposal",
                "proposal_review",
                "proposal_acknowledgment",
                "dispositions",
                "snapshots",
                "domain_records",
                "domain_history",
                "domain_history_records",
                "snapshot_history",
                "snapshot_history_records",
                "terminals",
                "scientific_pack",
            }
            has_trial_reviews = isinstance(canonical, dict) and "trial_reviews" in canonical
            has_trial_closures = isinstance(canonical, dict) and "trial_closures" in canonical
            if has_trial_reviews != has_trial_closures:
                return False, "trial review and closure fields must appear together"
            canonical_shapes = {
                frozenset(legacy_canonical_fields),
                frozenset(legacy_canonical_fields | {"proposal_history"}),
            }
            if has_trial_reviews:
                new_trial_fields = {"trial_reviews", "trial_closures"}
                canonical_shapes.update(
                    {
                        frozenset(legacy_canonical_fields | new_trial_fields),
                        frozenset(
                            legacy_canonical_fields | new_trial_fields | {"proposal_history"}
                        ),
                    }
                )
            if not isinstance(canonical, dict) or set(canonical) not in canonical_shapes:
                return False, "canonical envelope is not closed"
            scientific_pack = canonical.get("scientific_pack")
            if scientific_pack not in (
                _SCIENTIFIC_PACK,
                _CURRENT_PACK_PRE_SEMANTIC_GUIDANCE,
                _CURRENT_PACK_PRE_INFERENCE_GATES,
                _CURRENT_PACK_PRE_DEVIATIONS_GUIDANCE,
                _CURRENT_PACK_LEGACY_PROOF,
                _CURRENT_PACK_PRIOR_GUIDANCE,
                _CURRENT_PACK_PREVIOUS_PROOF,
                _FORMER_CURRENT_PACK_PREVIOUS_PROOF,
                _PREVIOUS_SCIENTIFIC_PACK,
                _LEGACY_SCIENTIFIC_PACK,
                _HISTORICAL_SCIENTIFIC_PACK,
                _OLDER_SCIENTIFIC_PACK,
            ):
                return False, "scientific pack descriptor differs"
            semantics_version = (
                scientific_pack.get("result_semantics_version", "rob2-kit.result-semantics.v0.5")
                if isinstance(scientific_pack, dict)
                else "rob2-kit.result-semantics.v0.5"
            )
            legacy_semantics = semantics_version in {
                "rob2-kit.result-semantics.v0.6",
                "rob2-kit.result-semantics.v0.7",
            }
            batch = canonical.get("batch")
            dispositions = canonical.get("dispositions")
            snapshots = canonical.get("snapshots")
            terminals = canonical.get("terminals")
            if (
                not isinstance(batch, dict)
                or not isinstance(dispositions, dict)
                or not isinstance(terminals, dict)
            ):
                return False, "canonical batch/dispositions are missing"
            if not _valid_batch(batch):
                return False, "Batch or Source identity is invalid"
            batch_trial_ids = {trial["id"] for trial in batch["trials"]}
            if set(dispositions) != batch_trial_ids:
                return False, "trial dispositions do not match Batch trials"
            if not isinstance(snapshots, dict):
                return False, "canonical snapshots are missing"
            valid_dispositions = {"assessed", "needs_input", "failed"}
            if has_trial_reviews:
                valid_dispositions.add("unsupported_design")
            if any(value not in valid_dispositions for value in dispositions.values()):
                return False, "invalid trial disposition"
            terminal_trials: dict[str, int] = {}
            if not has_trial_reviews:
                for terminal_identity, terminal in terminals.items():
                    if (
                        not isinstance(terminal_identity, str)
                        or not isinstance(terminal, dict)
                        or set(terminal)
                        != {"trial_id", "disposition", "reason", "missing_facts", "identity"}
                        or terminal.get("identity") != terminal_identity
                        or terminal.get("disposition") not in {"needs_input", "failed"}
                        or not isinstance(terminal.get("trial_id"), str)
                        or not isinstance(terminal.get("reason"), str)
                        or not terminal["reason"].strip()
                        or not isinstance(terminal.get("missing_facts"), list)
                        or not terminal["missing_facts"]
                        or any(
                            not isinstance(fact, str) or not fact.strip()
                            for fact in terminal["missing_facts"]
                        )
                        or terminal_identity
                        != identity(
                            {key: value for key, value in terminal.items() if key != "identity"}
                        )
                    ):
                        return False, "terminal record identity or facts are invalid"
                    trial_id = terminal["trial_id"]
                    if (
                        trial_id not in dispositions
                        or terminal.get("disposition") != dispositions[trial_id]
                        or trial_id in terminal_trials
                    ):
                        return False, "terminal record is orphaned or duplicated"
                    terminal_trials[trial_id] = 1
                for trial_id, disposition in dispositions.items():
                    has_terminal = trial_id in terminal_trials
                    if (disposition in {"needs_input", "failed"}) != has_terminal:
                        return False, "terminal record does not match disposition"
            expected_identity = identity({"schema": "rob2-kit.bundle.v0.3", "canonical": canonical})
            if manifest.get("identity") != expected_identity:
                return False, "manifest identity mismatch"
            # Every payload identity is part of the independent proof.  A
            # producer cannot make a changed Evidence binding or Domain
            # judgment look like the old Canonical record by merely updating
            # the enclosing manifest hash.
            proposal = canonical.get("proposal")
            if not isinstance(proposal, dict):
                return False, "proposal is missing"
            if not _valid_proposal_gate(
                canonical.get("proposal_review"),
                canonical.get("proposal_acknowledgment"),
                proposal,
            ):
                return False, "Proposal Review acknowledgment is invalid"
            proposal_evidence_for_history = proposal.get("evidence")
            if not isinstance(proposal_evidence_for_history, dict):
                return False, "proposal Evidence catalog is malformed"
            proposal_history = canonical.get("proposal_history")
            history_versions = proposal_history if isinstance(proposal_history, list) else []
            if proposal_history is not None and not history_versions:
                return False, "approved Proposal history is empty"
            approved_result_identities: dict[str, set[str]] = {}
            if proposal_history is None:
                history_versions = [
                    {
                        "proposal": proposal,
                        "review": canonical.get("proposal_review"),
                        "acknowledgment": canonical.get("proposal_acknowledgment"),
                    }
                ]
            historical_proposal_ids: set[str] = set()
            for version in history_versions:
                if not isinstance(version, dict) or set(version) != {
                    "proposal",
                    "review",
                    "acknowledgment",
                }:
                    return False, "approved Proposal history is malformed"
                historical_proposal = version.get("proposal")
                historical_payload = (
                    historical_proposal.get("payload")
                    if isinstance(historical_proposal, dict)
                    else None
                )
                historical_evidence = (
                    historical_proposal.get("evidence")
                    if isinstance(historical_proposal, dict)
                    else None
                )
                if (
                    not isinstance(historical_proposal, dict)
                    or set(historical_proposal) != {"identity", "payload", "evidence"}
                    or not isinstance(historical_payload, dict)
                    or not isinstance(historical_payload.get("results"), list)
                    or not isinstance(historical_evidence, dict)
                    or historical_proposal.get("identity") != identity(historical_payload)
                    or not _valid_proposal_gate(
                        version.get("review"),
                        version.get("acknowledgment"),
                        historical_proposal,
                    )
                    or historical_proposal["identity"] in historical_proposal_ids
                    or any(
                        proposal_evidence_for_history.get(evidence_identity) != evidence_item
                        for evidence_identity, evidence_item in historical_evidence.items()
                    )
                ):
                    return False, "approved Proposal history identity or gate is invalid"
                historical_proposal_ids.add(historical_proposal["identity"])
                for result in historical_payload["results"]:
                    if not isinstance(result, dict) or not isinstance(result.get("trial_id"), str):
                        return False, "approved Proposal history Result is malformed"
                    approved_result_identities.setdefault(result["trial_id"], set()).add(
                        identity(result)
                    )
            if history_versions:
                latest_version = history_versions[-1]
                latest_proposal = latest_version.get("proposal")
                if (
                    not isinstance(latest_proposal, dict)
                    or latest_proposal.get("identity") != proposal.get("identity")
                    or latest_proposal.get("payload") != proposal.get("payload")
                    or latest_version.get("review") != canonical.get("proposal_review")
                    or latest_version.get("acknowledgment")
                    != canonical.get("proposal_acknowledgment")
                ):
                    return False, "latest approved Proposal history does not match canonical state"
            current_payload = proposal.get("payload")
            current_results = (
                current_payload.get("results") if isinstance(current_payload, dict) else None
            )
            current_result_identities: dict[str, str] = {}
            current_results_by_trial: dict[str, dict[str, Any]] = {}
            if isinstance(current_results, list):
                current_results_by_trial = {
                    result["trial_id"]: result
                    for result in current_results
                    if isinstance(result, dict) and isinstance(result.get("trial_id"), str)
                }
                current_result_identities = {
                    trial_id: identity(result)
                    for trial_id, result in current_results_by_trial.items()
                }
            if proposal is not None:
                if (
                    not isinstance(proposal, dict)
                    or set(proposal) != {"identity", "payload", "evidence"}
                    or not isinstance(proposal.get("payload"), dict)
                    or set(proposal["payload"])
                    != (
                        {"results", "main_report_scopes"}
                        if semantics_version == "rob2-kit.result-semantics.v0.6"
                        else {"results"}
                    )
                ):
                    return False, "proposal is malformed"
                if proposal.get("identity") != identity(proposal["payload"]):
                    return False, "proposal identity mismatch"
                proposal_evidence = proposal.get("evidence")
                if not isinstance(proposal_evidence, dict):
                    return False, "proposal Evidence catalog is malformed"
                expected_evidence_members = {
                    f"evidence/{catalog_identity.removeprefix('sha256:')}.json"
                    for catalog_identity in proposal_evidence
                }
                actual_evidence_members = {name for name in names if name.startswith("evidence/")}
                if actual_evidence_members != expected_evidence_members:
                    return False, "Evidence members do not match the catalog"
                for catalog_identity, item in proposal_evidence.items():
                    if (
                        not isinstance(item, dict)
                        or item.get("identity") != catalog_identity
                        or catalog_identity
                        != identity(
                            {
                                key: value
                                for key, value in item.items()
                                if key not in {"identity", "handle"}
                            }
                        )
                        or item.get("handle")
                        != "eh_" + catalog_identity.removeprefix("sha256:")[:16]
                    ):
                        return False, "Evidence identity mismatch"
                    member = f"evidence/{catalog_identity.removeprefix('sha256:')}.json"
                    if member not in names or json.loads(archive.read(member)) != item:
                        return False, "Evidence binding is not self-contained"
                batch_trials = batch.get("trials")
                if not isinstance(batch_trials, list):
                    return False, "canonical batch trials are malformed"
                requested_outcomes: dict[str, str] = {}
                sources: dict[str, dict[str, object]] = {}
                for trial in batch_trials:
                    if (
                        not isinstance(trial, dict)
                        or not isinstance(trial.get("id"), str)
                        or not isinstance(trial.get("requested_outcome"), str)
                        or not trial["requested_outcome"].strip()
                        or trial["id"] in requested_outcomes
                        or not isinstance(trial.get("sources"), list)
                    ):
                        return False, "canonical trial requested_outcome is malformed"
                    requested_outcomes[trial["id"]] = trial["requested_outcome"]
                    for item in trial["sources"]:
                        if isinstance(item, dict) and isinstance(item.get("id"), str):
                            sources[item["id"]] = item
                if any(
                    not isinstance(item, dict)
                    or item.get("kind") not in {"narrative", "figure"}
                    or not _valid_selected_evidence(item, sources, identity)
                    for item in proposal_evidence.values()
                ):
                    return False, "Evidence record is not a closed authoritative Source selection"
                if (
                    semantics_version == "rob2-kit.result-semantics.v0.6"
                    and not _valid_main_report_scopes(
                        proposal["payload"].get("main_report_scopes"), batch, proposal_evidence
                    )
                ):
                    return False, "main-report scope is malformed"
                expected_visual_paths = {
                    f"visual/{str(item['render']['identity']).removeprefix('sha256:')}.png"
                    for item in proposal_evidence.values()
                    if isinstance(item, dict)
                    and item.get("kind") == "figure"
                    and isinstance(item.get("render"), dict)
                }
                actual_visual_paths = {name for name in names if name.startswith("visual/")}
                if actual_visual_paths != expected_visual_paths:
                    return False, "visual Evidence pixels are not closed"
                for item in proposal_evidence.values():
                    if not isinstance(item, dict) or item.get("kind") != "figure":
                        continue
                    render = item.get("render")
                    if not isinstance(render, dict):
                        return False, "visual Evidence render is malformed"
                    visual_path = f"visual/{str(render['identity']).removeprefix('sha256:')}.png"
                    visual_digest = (
                        "sha256:" + hashlib.sha256(archive.read(visual_path)).hexdigest()
                    )
                    if visual_digest != render.get("png_sha256"):
                        return False, "visual Evidence pixels do not match render identity"
                results = proposal["payload"].get("results")
                if (
                    not isinstance(results, list)
                    or len(results) != len(batch_trial_ids)
                    or {item.get("trial_id") for item in results if isinstance(item, dict)}
                    != batch_trial_ids
                    or not all(
                        _valid_result_evidence(
                            result,
                            proposal_evidence,
                            sources,
                            requested_outcomes,
                            batch,
                            semantics_version,
                        )
                        for result in results
                    )
                ):
                    return False, "Result Evidence contract is invalid"
                terminal_by_trial = {
                    terminal["trial_id"]: terminal for terminal in terminals.values()
                }
                for result in results:
                    trial_id = result["trial_id"]
                    disposition = dispositions[trial_id]
                    if disposition == "assessed" and result.get("kind") != "assessable":
                        return False, "assessed Trial requires an assessable Result"
                    if has_trial_reviews:
                        continue
                    if result.get("kind") == "unavailable":
                        terminal = terminal_by_trial.get(trial_id)
                        facts = [item["fact"] for item in result["missing_facts"]]
                        if (
                            disposition != "needs_input"
                            or not isinstance(terminal, dict)
                            or terminal.get("missing_facts") != facts
                        ):
                            return False, "unavailable Result does not match its terminal"
                    applicability = result.get("applicability")
                    unsupported_design = isinstance(applicability, dict) and applicability.get(
                        "design"
                    ) in {"cluster_randomized", "crossover", "unclear"}
                    if unsupported_design and disposition != "needs_input":
                        return False, "unsupported or uncertain design must remain unassessed"
            domains = canonical.get("domain_records")
            if not isinstance(domains, dict):
                return False, "Domain records are missing"
            proposal_evidence = (canonical.get("proposal") or {}).get("evidence", {})
            if not isinstance(proposal_evidence, dict):
                return False, "proposal Evidence catalog is malformed"
            trials = {
                item.get("id"): item.get("sources", [])
                for item in batch.get("trials", [])
                if isinstance(item, dict)
            }
            for key, record in domains.items():
                expected_domain_fields = {
                    "trial_id",
                    "domain_id",
                    "answers",
                    "supersedes",
                    "revision_basis",
                    "search_accounts",
                    "active_questions",
                    "inactive_questions",
                    "judgment",
                    "trace",
                    "observed_at",
                    "identity",
                }
                if isinstance(record, dict) and "result_identity" in record:
                    expected_domain_fields.add("result_identity")
                if isinstance(record, dict):
                    expected_domain_fields.update(
                        key for key in ("driver_questions", "evidence_sufficiency") if key in record
                    )
                if (
                    not isinstance(record, dict)
                    or set(record) != expected_domain_fields
                    or record.get("identity")
                    != _domain_identity(record, legacy_semantics=legacy_semantics)
                    or (
                        "result_identity" in record
                        and (
                            not isinstance(record.get("result_identity"), str)
                            or record["result_identity"]
                            not in approved_result_identities.get(record.get("trial_id"), set())
                            or record["result_identity"]
                            != current_result_identities.get(record.get("trial_id"))
                        )
                    )
                    or (
                        len(approved_result_identities.get(record.get("trial_id"), set())) > 1
                        and "result_identity" not in record
                    )
                ):
                    return False, f"Domain identity mismatch: {key}"
                accounts = record.get("search_accounts")
                if not isinstance(record.get("answers"), list) or not isinstance(accounts, list):
                    return False, "Domain structures are malformed"
                active_questions = record.get("active_questions")
                inactive_questions = record.get("inactive_questions")
                answers = record.get("answers")
                if (
                    not isinstance(active_questions, list)
                    or not isinstance(inactive_questions, list)
                    or not isinstance(answers, list)
                    or len(set(active_questions)) != len(active_questions)
                    or len(set(inactive_questions)) != len(inactive_questions)
                    or set(active_questions) & set(inactive_questions)
                ):
                    return False, "Domain question or limitation coverage is invalid"
                answer_map: dict[str, str] = {}
                for answer in answers:
                    if (
                        not isinstance(answer, dict)
                        or set(answer)
                        not in (
                            {"question_id", "answer", "bases"},
                            {"question_id", "answer", "bases", "justification"},
                            {"question_id", "answer", "bases", "missing_data"},
                            {"question_id", "answer", "bases", "justification", "missing_data"},
                            {"question_id", "answer", "bases", "unknowns", "counterevidence"},
                            {
                                "question_id",
                                "answer",
                                "bases",
                                "justification",
                                "unknowns",
                                "counterevidence",
                            },
                            {
                                "question_id",
                                "answer",
                                "bases",
                                "missing_data",
                                "unknowns",
                                "counterevidence",
                            },
                            {
                                "question_id",
                                "answer",
                                "bases",
                                "justification",
                                "missing_data",
                                "unknowns",
                                "counterevidence",
                            },
                        )
                        or not isinstance(answer.get("question_id"), str)
                        or not isinstance(answer.get("answer"), str)
                        or not answer["answer"].strip()
                        or (
                            "justification" in answer
                            and (
                                not isinstance(answer.get("justification"), str)
                                or not answer["justification"].strip()
                            )
                        )
                        or not isinstance(answer.get("bases"), list)
                        or not answer["bases"]
                        or not _valid_reasoning_annotations(answer)
                        or (
                            "missing_data" in answer
                            and not _valid_missing_data(
                                answer["missing_data"],
                                answer.get("question_id"),
                                proposal_evidence,
                                record.get("trial_id"),
                            )
                        )
                        or answer["question_id"] in answer_map
                    ):
                        return False, "Domain answer shape is invalid"
                    answer_map[answer["question_id"]] = answer["answer"]
                allowed_questions = _DOMAIN_QUESTION_IDS.get(record.get("domain_id"), set())
                if set(active_questions) | set(inactive_questions) != allowed_questions:
                    return False, "Domain active question set is invalid"
                try:
                    expected_active, expected_inactive = _domain_question_sets(
                        record.get("domain_id"), answer_map
                    )
                except ValueError:
                    return False, "Domain answers or active question set is invalid"
                if active_questions != expected_active or inactive_questions != expected_inactive:
                    return False, "Domain active question set does not match answers"
                if set(answer_map) != set(active_questions):
                    return False, "Domain answer coverage is incomplete"
                account_by_identity = cast(
                    dict[str, dict[str, object]],
                    {item.get("identity"): item for item in accounts if isinstance(item, dict)},
                )
                if len(account_by_identity) != len(accounts):
                    return False, "search accounts are malformed"
                sources = {
                    item.get("id"): item
                    for item in trials.get(record.get("trial_id"), [])
                    if isinstance(item, dict)
                }
                for account in accounts:
                    if not _valid_search_account(
                        account,
                        record.get("trial_id"),
                        batch.get("identity"),
                        sources,
                        identity,
                    ):
                        return False, "search account is malformed"
                for answer in answers:
                    direct_basis = False
                    uncertainty_basis = False
                    for use in answer["bases"]:
                        if not isinstance(use, dict):
                            return False, "Domain Evidence basis is malformed"
                        if use.get("kind") in {
                            "direct_support",
                            "indirect_support",
                            "contradiction",
                        }:
                            direct_basis = True
                        if use.get("kind") == "limitation":
                            if not _valid_limitation_basis(
                                use, account_by_identity, record.get("trial_id")
                            ):
                                return False, "Domain limitation basis is malformed"
                            uncertainty_basis = True
                            continue
                        if use.get("kind") == "absence":
                            if set(use) != {"kind", "search_receipt"}:
                                return False, "absence Domain basis is malformed"
                            if (
                                not isinstance(use.get("search_receipt"), str)
                                or use["search_receipt"] not in account_by_identity
                            ):
                                return False, "absence Evidence receipt is not self-contained"
                            account = account_by_identity[use["search_receipt"]]
                            if (
                                account.get("truncated") is not False
                                or account.get("total_matches") != 0
                                or account.get("condition") != "no_hits"
                            ):
                                return False, "absence requires an untruncated no-hit search"
                            uncertainty_basis = True
                            continue
                        if use.get("kind") not in {
                            "direct_support",
                            "indirect_support",
                            "contradiction",
                            "context",
                            "inference",
                        } or set(use) != {"kind", "evidence", "source"}:
                            return False, "direct Domain Evidence basis is malformed"
                        if use.get("kind") in {"context", "inference"}:
                            uncertainty_basis = True
                        evidence_item = proposal_evidence.get(use.get("evidence"))
                        if not isinstance(evidence_item, dict) or evidence_item.get(
                            "trial_id"
                        ) != record.get("trial_id"):
                            return False, "Domain Evidence is outside the Trial"
                        source = use.get("source")
                        if not isinstance(source, str) or not source:
                            return False, "direct Domain Evidence source is empty"
                        material = str(
                            evidence_item.get("quote") or evidence_item.get("transcription") or ""
                        )
                        if material != source:
                            return False, "Domain Evidence source is not an exact selected fragment"
                    if answer["answer"] in {"yes", "no"} and not direct_basis:
                        return False, "definitive Domain answer lacks a direct basis"
                    if answer["answer"] in {"probably_yes", "probably_no"} and not (
                        direct_basis or uncertainty_basis
                    ):
                        return False, "confident Domain answer lacks a direct basis"
                if "evidence_sufficiency" in record and not _valid_evidence_sufficiency(
                    record["evidence_sufficiency"],
                    answers,
                    cast(dict[str, object], account_by_identity),
                    proposal_evidence,
                    record.get("trial_id"),
                    legacy_semantics=legacy_semantics,
                ):
                    return False, "Domain evidence sufficiency is invalid"
            domain_history = canonical.get("domain_history")
            domain_history_records = canonical.get("domain_history_records")
            snapshot_history = canonical.get("snapshot_history")
            snapshot_history_records = canonical.get("snapshot_history_records")
            if (
                not isinstance(domain_history, dict)
                or not isinstance(domain_history_records, dict)
                or not isinstance(snapshot_history, dict)
                or not isinstance(snapshot_history_records, dict)
            ):
                return False, "Domain history is malformed"
            if (
                set(domain_history) != set(domains)
                or set(domain_history_records) != set(domains)
                or set(snapshot_history) != set(snapshots)
                or set(snapshot_history_records) != set(snapshots)
            ):
                return False, "Domain history keys are not canonical"
            if not _valid_domain_lineage(
                domain_history,
                domain_history_records,
                domains,
                proposal_evidence,
                legacy_semantics=legacy_semantics,
            ):
                return False, "Domain revision lineage is invalid"
            for key, historical in domain_history_records.items():
                history = domain_history[key]
                if not isinstance(history, list) or not history or not isinstance(historical, list):
                    return False, "Domain history records are malformed"
                for item, digest in zip(historical, history, strict=True):
                    item_expected_fields = {
                        "trial_id",
                        "domain_id",
                        "answers",
                        "supersedes",
                        "revision_basis",
                        "search_accounts",
                        "active_questions",
                        "inactive_questions",
                        "judgment",
                        "trace",
                        "observed_at",
                        "identity",
                    }
                    if isinstance(item, dict) and "result_identity" in item:
                        item_expected_fields.add("result_identity")
                    if isinstance(item, dict):
                        item_expected_fields.update(
                            key
                            for key in ("driver_questions", "evidence_sufficiency")
                            if key in item
                        )
                    if (
                        not isinstance(item, dict)
                        or set(item) != item_expected_fields
                        or item.get("identity") != digest
                        or item.get("identity")
                        != _domain_identity(item, legacy_semantics=legacy_semantics)
                        or key != f"{item.get('trial_id')}:{item.get('domain_id')}"
                        or (
                            "result_identity" in item
                            and (
                                not isinstance(item.get("result_identity"), str)
                                or item["result_identity"]
                                not in approved_result_identities.get(item.get("trial_id"), set())
                            )
                        )
                        or not isinstance(item.get("answers"), list)
                        or not isinstance(item.get("active_questions"), list)
                        or not isinstance(item.get("inactive_questions"), list)
                    ):
                        return False, "Domain history record shape is invalid"
                    answer_map = {
                        answer.get("question_id"): answer.get("answer")
                        for answer in item["answers"]
                        if isinstance(answer, dict)
                    }
                    try:
                        expected_active, expected_inactive = _domain_question_sets(
                            item.get("domain_id"), answer_map
                        )
                        judgment = _domain_judgment(item["domain_id"], answer_map)
                    except (KeyError, TypeError, ValueError):
                        return False, "Domain history semantics are invalid"
                    if (
                        item["active_questions"] != expected_active
                        or item["inactive_questions"] != expected_inactive
                        or item.get("judgment") != judgment
                    ):
                        return False, "Domain history semantics are invalid"
                    accounts = item["search_accounts"]
                    if not isinstance(accounts, list):
                        return False, "Domain history search accounts are malformed"
                    trial_sources = {
                        source.get("id"): source
                        for source in trials.get(item.get("trial_id"), [])
                        if isinstance(source, dict)
                    }
                    for account in accounts:
                        if not _valid_search_account(
                            account,
                            item.get("trial_id"),
                            batch.get("identity"),
                            trial_sources,
                            identity,
                        ):
                            return False, "Domain history search account is invalid"
                    account_ids = {
                        account.get("identity") for account in accounts if isinstance(account, dict)
                    }
                    account_by_identity = cast(
                        dict[str, dict[str, object]],
                        {
                            account.get("identity"): account
                            for account in accounts
                            if isinstance(account, dict)
                        },
                    )
                    if len(account_by_identity) != len(accounts):
                        return False, "Domain history search accounts are malformed"
                    for answer in item["answers"]:
                        if (
                            not isinstance(answer, dict)
                            or set(answer)
                            not in (
                                {"question_id", "answer", "bases"},
                                {"question_id", "answer", "bases", "justification"},
                                {"question_id", "answer", "bases", "missing_data"},
                                {"question_id", "answer", "bases", "justification", "missing_data"},
                                {"question_id", "answer", "bases", "unknowns", "counterevidence"},
                                {
                                    "question_id",
                                    "answer",
                                    "bases",
                                    "justification",
                                    "unknowns",
                                    "counterevidence",
                                },
                                {
                                    "question_id",
                                    "answer",
                                    "bases",
                                    "missing_data",
                                    "unknowns",
                                    "counterevidence",
                                },
                                {
                                    "question_id",
                                    "answer",
                                    "bases",
                                    "justification",
                                    "missing_data",
                                    "unknowns",
                                    "counterevidence",
                                },
                            )
                            or (
                                "justification" in answer
                                and (
                                    not isinstance(answer.get("justification"), str)
                                    or not answer["justification"].strip()
                                )
                            )
                            or not isinstance(answer.get("bases"), list)
                            or not answer["bases"]
                            or not _valid_reasoning_annotations(answer)
                            or (
                                "missing_data" in answer
                                and not _valid_missing_data(
                                    answer["missing_data"],
                                    answer.get("question_id"),
                                    proposal_evidence,
                                    item.get("trial_id"),
                                )
                            )
                        ):
                            return False, "Domain history answer shape is invalid"
                        direct_basis = False
                        uncertainty_basis = False
                        for use in answer["bases"]:
                            if not isinstance(use, dict):
                                return False, "Domain history basis is malformed"
                            if use.get("kind") in {
                                "direct_support",
                                "indirect_support",
                                "contradiction",
                            }:
                                direct_basis = True
                            if use.get("kind") == "limitation":
                                if not _valid_limitation_basis(
                                    use, account_by_identity, item.get("trial_id")
                                ):
                                    return False, "Domain history limitation is malformed"
                                uncertainty_basis = True
                                continue
                            if use.get("kind") == "absence":
                                if (
                                    set(use) != {"kind", "search_receipt"}
                                    or use["search_receipt"] not in account_ids
                                ):
                                    return False, "Domain history absence basis is invalid"
                                account = account_by_identity[use["search_receipt"]]
                                if (
                                    account.get("truncated") is not False
                                    or account.get("total_matches") != 0
                                    or account.get("condition") != "no_hits"
                                ):
                                    return False, "absence requires an untruncated no-hit search"
                                uncertainty_basis = True
                                continue
                            if use.get("kind") not in {
                                "direct_support",
                                "indirect_support",
                                "contradiction",
                                "context",
                                "inference",
                            } or set(use) != {"kind", "evidence", "source"}:
                                return False, "Domain history Evidence basis is malformed"
                            if use.get("kind") in {"context", "inference"}:
                                uncertainty_basis = True
                            evidence_item = proposal_evidence.get(use.get("evidence"))
                            source = use.get("source")
                            if (
                                not isinstance(evidence_item, dict)
                                or evidence_item.get("trial_id") != item.get("trial_id")
                                or not isinstance(source, str)
                            ):
                                return False, "Domain history Evidence basis is invalid"
                            material = str(
                                evidence_item.get("quote")
                                or evidence_item.get("transcription")
                                or ""
                            )
                            if material != source:
                                return False, "Domain history Evidence source is invalid"
                        if answer["answer"] in {"yes", "no"} and not direct_basis:
                            return False, "definitive Domain history answer lacks a direct basis"
                        if answer["answer"] in {"probably_yes", "probably_no"} and not (
                            direct_basis or uncertainty_basis
                        ):
                            return False, "Domain history confident answer lacks a basis"
                    if "evidence_sufficiency" in item and not _valid_evidence_sufficiency(
                        item["evidence_sufficiency"],
                        item["answers"],
                        cast(dict[str, object], account_by_identity),
                        proposal_evidence,
                        item.get("trial_id"),
                        legacy_semantics=legacy_semantics,
                    ):
                        return False, "Domain history evidence sufficiency is invalid"
            for trial_id, historical in snapshot_history_records.items():
                history = snapshot_history[trial_id]
                if not isinstance(history, list) or not history or not isinstance(historical, list):
                    return False, "snapshot history records are malformed"
                for item, digest in zip(historical, history, strict=True):
                    expected_shape = {
                        "trial_id",
                        "checkpoints",
                        "domain_judgments",
                        "overall",
                        "identity",
                    }
                    if isinstance(item, dict) and "result_identity" in item:
                        expected_shape.add("result_identity")
                    if isinstance(item, dict):
                        expected_shape.update(
                            key
                            for key in (
                                "overall_trace",
                                "overall_driver_domains",
                                "overall_receipt",
                            )
                            if key in item
                        )
                    if (
                        not isinstance(item, dict)
                        or set(item) != expected_shape
                        or item.get("identity") != digest
                        or item.get("trial_id") != trial_id
                        or item.get("identity") != _snapshot_identity(item)
                        or (
                            "result_identity" in item
                            and (
                                not isinstance(item.get("result_identity"), str)
                                or item["result_identity"]
                                not in approved_result_identities.get(trial_id, set())
                            )
                        )
                        or (
                            len(approved_result_identities.get(trial_id, set())) > 1
                            and "result_identity" not in item
                        )
                        or not isinstance(item.get("checkpoints"), list)
                        or len(item["checkpoints"]) != len(_EXPECTED_DOMAIN_ORDER)
                        or not isinstance(item.get("domain_judgments"), dict)
                        or set(item["domain_judgments"]) != _EXPECTED_DOMAIN_IDS
                        or any(
                            checkpoint not in domain_history.get(f"{trial_id}:{domain_id}", [])
                            for domain_id, checkpoint in zip(
                                _EXPECTED_DOMAIN_ORDER, item["checkpoints"], strict=True
                            )
                        )
                    ):
                        return False, "snapshot history semantics are invalid"
                    judgments = item["domain_judgments"]
                    try:
                        (
                            expected_overall,
                            expected_rule,
                            expected_driver_domains,
                        ) = _overall_evaluation(judgments)
                    except (KeyError, TypeError, ValueError):
                        return False, "snapshot history overall inputs are invalid"
                    if item.get("overall") != expected_overall:
                        return False, "snapshot history overall is invalid"
                    if ("overall_trace" in item and item["overall_trace"] != [expected_rule]) or (
                        "overall_driver_domains" in item
                        and item["overall_driver_domains"] != expected_driver_domains
                    ):
                        return False, "snapshot history overall metadata is invalid"
                    historical_records: dict[str, object] = {}
                    for domain_id, checkpoint in zip(
                        _EXPECTED_DOMAIN_ORDER, item["checkpoints"], strict=True
                    ):
                        records_for_domain = domain_history_records.get(
                            f"{trial_id}:{domain_id}", []
                        )
                        matching = next(
                            (
                                record
                                for record in records_for_domain
                                if isinstance(record, dict) and record.get("identity") == checkpoint
                            ),
                            None,
                        )
                        if not isinstance(matching, dict) or item["domain_judgments"].get(
                            domain_id
                        ) != matching.get("judgment"):
                            return False, "snapshot history judgment does not match checkpoint"
                        if item.get("result_identity") != matching.get("result_identity"):
                            return False, "snapshot history Result does not match checkpoint"
                        historical_records[f"{trial_id}:{domain_id}"] = matching
                    if (
                        not legacy_semantics
                        and "overall_receipt" in item
                        and not _valid_overall_receipt(
                            item["overall_receipt"], item, historical_records
                        )
                    ):
                        return False, "snapshot history overall receipt is invalid"
            for key, record in domains.items():
                history = domain_history.get(key)
                historical = domain_history_records.get(key)
                if (
                    not isinstance(history, list)
                    or not history
                    or history[-1] != record.get("identity")
                    or not isinstance(historical, list)
                    or len(historical) != len(history)
                    or any(
                        not isinstance(item, dict)
                        or item.get("identity") != digest
                        or item.get("identity")
                        != _domain_identity(item, legacy_semantics=legacy_semantics)
                        for item, digest in zip(historical, history, strict=True)
                    )
                ):
                    return False, "Domain history does not name the active checkpoint"
            for trial_id, snapshot in snapshots.items():
                history = snapshot_history.get(trial_id)
                historical = snapshot_history_records.get(trial_id)
                if (
                    not isinstance(history, list)
                    or not history
                    or history[-1] != snapshot.get("identity")
                    or not isinstance(historical, list)
                    or len(historical) != len(history)
                    or any(
                        not isinstance(item, dict)
                        or item.get("identity") != digest
                        or item.get("identity") != _snapshot_identity(item)
                        for item, digest in zip(historical, history, strict=True)
                    )
                ):
                    return False, "snapshot history does not name the active snapshot"
            for trial_id, snapshot in snapshots.items():
                if not isinstance(snapshot, dict) or snapshot.get("identity") != _snapshot_identity(
                    snapshot
                ):
                    return False, f"snapshot identity mismatch: {trial_id}"
                if dispositions.get(trial_id) == "assessed":
                    trial_records = [
                        record
                        for key, record in domains.items()
                        if key.startswith(f"{trial_id}:")
                        and isinstance(record, dict)
                        and record.get("trial_id") == trial_id
                    ]
                    record_ids = [record.get("domain_id") for record in trial_records]
                    if (
                        len(record_ids) != len(set(record_ids))
                        or set(record_ids) != _EXPECTED_DOMAIN_IDS
                    ):
                        return False, f"assessed Trial Domain coverage is incomplete: {trial_id}"
                    records = {record["domain_id"]: record for record in trial_records}
                    if (
                        "result_identity" in snapshot
                        and snapshot.get("result_identity")
                        != current_result_identities.get(trial_id)
                    ) or (
                        len(approved_result_identities.get(trial_id, set())) > 1
                        and "result_identity" not in snapshot
                    ):
                        return False, f"snapshot Result is stale: {trial_id}"
                    expected_judgments: dict[str, str] = {}
                    for domain_id, record in records.items():
                        if record.get("result_identity") != snapshot.get("result_identity"):
                            return False, f"Domain Result is stale: {trial_id}"
                        answers = record.get("answers")
                        if not isinstance(domain_id, str) or not isinstance(answers, list):
                            return False, f"Domain judgment inputs are malformed: {trial_id}"
                        answer_map = {
                            item["question_id"]: item["answer"]
                            for item in answers
                            if isinstance(item, dict)
                            and isinstance(item.get("question_id"), str)
                            and isinstance(item.get("answer"), str)
                        }
                        if len(answer_map) != len(answers):
                            return False, f"Domain judgment inputs are malformed: {trial_id}"
                        expected = _domain_judgment(domain_id, answer_map)
                        if record.get("judgment") != expected:
                            return False, f"Domain judgment mismatch: {trial_id}:{domain_id}"
                        expected_judgments[domain_id] = expected
                    snapshot_judgments = snapshot.get("domain_judgments")
                    checkpoints = snapshot.get("checkpoints")
                    if (
                        not isinstance(snapshot_judgments, dict)
                        or set(snapshot_judgments) != _EXPECTED_DOMAIN_IDS
                        or not isinstance(checkpoints, list)
                        or len(checkpoints) != len(_EXPECTED_DOMAIN_IDS)
                        or checkpoints
                        != [records[domain_id]["identity"] for domain_id in _EXPECTED_DOMAIN_ORDER]
                    ):
                        return False, f"snapshot Domain coverage is incomplete: {trial_id}"
                    if expected_judgments != snapshot_judgments:
                        return False, f"snapshot Domain judgments mismatch: {trial_id}"
                    try:
                        overall, expected_rule, expected_driver_domains = _overall_evaluation(
                            expected_judgments
                        )
                    except (KeyError, TypeError, ValueError):
                        return False, f"overall inputs are invalid: {trial_id}"
                    if (
                        "overall_trace" in snapshot and snapshot["overall_trace"] != [expected_rule]
                    ) or (
                        "overall_driver_domains" in snapshot
                        and snapshot["overall_driver_domains"] != expected_driver_domains
                    ):
                        return False, f"overall metadata mismatch: {trial_id}"
                    if (
                        not legacy_semantics
                        and "overall_receipt" in snapshot
                        and not _valid_overall_receipt(
                            snapshot["overall_receipt"], snapshot, domains
                        )
                    ):
                        return False, f"overall receipt mismatch: {trial_id}"
                    if snapshot.get("overall") != overall:
                        return False, f"overall judgment mismatch: {trial_id}"
            if has_trial_reviews and not _valid_trial_review_closures(
                canonical.get("trial_reviews"),
                canonical.get("trial_closures"),
                terminals,
                dispositions,
                batch_trial_ids,
                current_results_by_trial,
                domains,
            ):
                return False, "Trial review or closure is invalid"
            report = archive.read("report.html").decode("utf-8")
            claims = json.loads(archive.read("claims.json"))
            if not isinstance(claims, dict) or claims != _claims(canonical):
                return False, "claims do not match dispositions"
            if json.dumps(claims, sort_keys=True) not in report:
                return False, "report does not contain dispositions"
            verification = json.loads(archive.read("verification.json"))
            if (
                not isinstance(verification, dict)
                or set(verification) != {"schema", "manifest_identity", "result", "checks"}
                or verification.get("schema") != "rob2-kit.independent-verifier-input.v0.3"
                or verification.get("manifest_identity") != manifest.get("identity")
                or verification.get("result") != "verified"
                or verification.get("checks")
                != [
                    "canonical_identity",
                    "content_hashes",
                    "proposal_gate",
                    "domain_lineage",
                    "snapshot_derivations",
                    "claims",
                ]
            ):
                return False, "verification claim does not match manifest"
            return True, "bundle verified"
    except (
        OSError,
        KeyError,
        ValueError,
        TypeError,
        json.JSONDecodeError,
        zipfile.BadZipFile,
    ) as error:
        return False, str(error)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: verify_bundle.py BUNDLE.rob2.zip", file=sys.stderr)
        return 2
    ok, message = verify(Path(args[0]))
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

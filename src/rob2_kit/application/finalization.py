import hashlib
import json
import math
import os
import posixpath
import re
import tempfile
import unicodedata
import zipfile
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from typing import Any, cast

from pydantic import ValidationError

from ..logic.evaluator import active_questions as derive_active_questions
from ..logic.evaluator import evaluate_overall
from ..models import canonical_json_bytes
from ..packs import SCIENTIFIC_PACK
from ..workflow_models import (
    AssessableResult,
    CapturedBatch,
    ExpectedRevision,
    ResultApplicability,
    exact_relation_rationale,
)
from ._state import (
    _canonical_evidence_records,
    _canonical_query_text,
    _commit_records,
    _db,
    _ensure,
    _identity,
    _ordered_sources,
    _result,
    _root,
    _state,
    internal_path,
)
from .contracts import WorkflowConflict
from .evidence import (
    _normalized_contains,
    _render_page_png,
)
from .status import presentation

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

_RESULT_SEMANTICS_VERSION = "rob2-kit.result-semantics.v0.7"
_LEGACY_RESULT_SEMANTICS_VERSION = "rob2-kit.result-semantics.v0.6"
_HISTORICAL_RESULT_SEMANTICS_VERSION = "rob2-kit.result-semantics.v0.5"


def _nonblank(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_missing_data(
    value: object,
    question_id: object,
    evidence: dict[str, Any],
    trial_id: object,
) -> bool:
    """Validate the canonical reconciliation stored on Domain 3.1 answers."""
    if question_id != "sq:missing:data-available" or not isinstance(value, dict):
        return False
    if (
        set(value) != {"rows", "conflicts"}
        or not isinstance(value["rows"], list)
        or not value["rows"]
        or not isinstance(value["conflicts"], list)
    ):
        return False

    def valid_row(row: object) -> bool:
        if not isinstance(row, dict) or set(row) != {
            "scope",
            "randomized",
            "observed",
            "analyzed",
            "imputed",
            "exclusions",
            "basis",
            "missing",
            "missing_fraction",
        }:
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
    for conflict in value["conflicts"]:
        if (
            not isinstance(conflict, dict)
            or set(conflict) != {"scope", "reports"}
            or not isinstance(conflict["reports"], list)
            or len(conflict["reports"]) < 2
            or not all(valid_row(row) for row in conflict["reports"])
            or any(row["scope"] != conflict["scope"] for row in conflict["reports"])
        ):
            return False
    compared_fields = ("randomized", "observed", "analyzed", "imputed", "exclusions")
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


_PATH_FIELDS = frozenset({"logical_path", "path"})


def _contains_platform_path(value: object, field: str | None = None) -> bool:
    if not isinstance(value, str):
        return False
    if field in _FORBIDDEN_PATH_FIELDS:
        return True
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


def _bundle_leaves(value: object, path: str) -> dict[str, object]:
    if isinstance(value, dict):
        return {
            leaf_path: leaf
            for key, child in value.items()
            if key not in {"form", "kind"}
            for leaf_path, leaf in _bundle_leaves(child, f"{path}/{key}").items()
        }
    if isinstance(value, list):
        return {
            leaf_path: leaf
            for index, child in enumerate(value)
            for leaf_path, leaf in _bundle_leaves(child, f"{path}/{index}").items()
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
    }

    return {
        leaf_path: leaf
        for leaf_path, leaf in _bundle_leaves(value, path).items()
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


def _host_visual_leaf_allowed(path: str) -> bool:
    return (
        path.startswith("/reported/")
        or (path.startswith("/target/comparison_groups/") and path.endswith("/assignment"))
        or path.startswith("/target/time_point_or_window/")
    )


def _relation_name(value: object) -> str:
    if not isinstance(value, str):
        return ""
    normalized = unicodedata.normalize("NFKC", value)
    for character in "‐‑‒–—":
        normalized = normalized.replace(character, "-")
    return " ".join(normalized.casefold().replace("-", " ").split())


def _valid_batch(batch: object) -> bool:
    if not isinstance(batch, dict) or set(batch) != {"identity", "trials", "conditions"}:
        return False
    if (
        not isinstance(batch.get("trials"), list)
        or not batch["trials"]
        or not isinstance(batch.get("conditions"), list)
    ):
        return False
    if batch.get("identity") != _identity(
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
        if trial["identity"] != _identity(
            {key: value for key, value in trial.items() if key != "identity"}
        ):
            return False
        registry = trial.get("registry")
        if not isinstance(registry, dict) or not _valid_registry(registry):
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
    if not _valid_conditions(batch["conditions"], trial_ids):
        return False
    try:
        CapturedBatch.model_validate(
            {
                "trials": batch["trials"],
                "conditions": [
                    {
                        "kind": "review_condition",
                        "code": condition["code"],
                        "trial_id": condition.get("trial_id"),
                        "detail": condition["code"],
                    }
                    for condition in batch["conditions"]
                ],
                "identity": None,
            }
        )
    except (TypeError, ValueError, ValidationError):
        return False
    return True


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
    return (
        isinstance(value, dict)
        and set(value) == {"path", "reason", "rationale"}
        and isinstance(value.get("path"), str)
        and _valid_relative_path(value["path"])
        and isinstance(value.get("reason"), str)
        and value["reason"] in {"duplicate", "irrelevant", "unreadable", "restricted", "other"}
        and isinstance(value.get("rationale"), str)
        and bool(value["rationale"].strip())
    )


def _valid_relative_path(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and "\\" not in value
        and not value.startswith("/")
        and not re.match(r"^[A-Za-z]:", value)
        and ".." not in PurePosixPath(value).parts
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
    if not isinstance(source, dict) or set(source) != {
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
    }:
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
        if code == "unreadable_source":
            valid = (
                set(condition) == {"code", "trial_id", "path"}
                and isinstance(condition.get("path"), str)
                and bool(condition["path"].strip())
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
    identity: Callable[[object], str],
) -> bool:
    required_keys = {
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
    if (
        not isinstance(account, dict)
        or not required_keys.issubset(account)
        or set(account) != required_keys
    ):
        return False
    query = account.get("query")
    sources = account.get("sources")
    hits = account.get("hits")
    total_matches = account.get("total_matches")
    truncated = account.get("truncated")
    limit = account.get("limit")
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
        [(item.get("source_id"), item.get("page")) for item in returned_candidates]
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
        != identity(
            {key: value for key, value in account.items() if key not in {"identity", "handle"}}
        )
        or account.get("handle") != "sr_" + str(account["identity"]).removeprefix("sha256:")[:16]
        or not isinstance(query, str)
        or not query.strip()
        or not isinstance(account.get("normalized_query"), str)
        or not account["normalized_query"].strip()
        or account["normalized_query"] != _canonical_query_text(query)
        or not isinstance(account.get("mode"), str)
        or account["mode"] not in {"all", "phrase", "any", "prefix"}
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
    item: object, sources: dict[str, dict[str, object]], identity: Callable[[object], str]
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
        if has_line_coordinates:
            expected |= {"start_line", "end_line"}
    if set(item) != expected:
        return False
    source = sources.get(str(item.get("source_id")))
    if (
        not isinstance(source, dict)
        or item.get("trial_id") != source.get("trial_id")
        or item.get("identity")
        != identity(
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
        == identity(
            {
                "source_id": item.get("source_id"),
                "source_sha256": source.get("sha256"),
                "page": render.get("page"),
                "recipe": render.get("recipe"),
            }
        )
        and render.get("identity") == item.get("render", {}).get("identity")
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


def _valid_requested_result(
    result: object, requested_outcome: str, semantics_version: str | None = None
) -> bool:
    if not isinstance(result, dict) or _relation_name(
        result.get("requested_outcome")
    ) != _relation_name(requested_outcome):
        return False
    if result.get("kind") == "assessable":
        validation_value = result
        if semantics_version == _LEGACY_RESULT_SEMANTICS_VERSION:
            applicability = result.get("applicability")
            if isinstance(applicability, dict):
                validation_value = {
                    **result,
                    "applicability": {
                        key: value for key, value in applicability.items() if key != "status"
                    },
                }
        try:
            AssessableResult.model_validate(validation_value)
        except (TypeError, ValueError, ValidationError):
            return False
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
    semantics_version: str = _RESULT_SEMANTICS_VERSION,
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
        if semantics_version == _HISTORICAL_RESULT_SEMANTICS_VERSION
        else base_keys | {"applicability"}
    )
    if set(result) != expected_keys:
        return False
    if (
        semantics_version != _HISTORICAL_RESULT_SEMANTICS_VERSION
        and result.get("applicability") is None
    ):
        return False
    if "applicability" in result:
        applicability = result["applicability"]
        expected_applicability_keys = (
            {"design", "status", "rationale", "evidence"}
            if semantics_version == _LEGACY_RESULT_SEMANTICS_VERSION
            else {"design", "rationale", "evidence"}
        )
        if not isinstance(applicability, dict) or set(applicability) != expected_applicability_keys:
            return False
        if semantics_version == _LEGACY_RESULT_SEMANTICS_VERSION:
            status_by_design = {
                "individual_parallel": "supported",
                "cluster_randomized": "unsupported",
                "crossover": "unsupported",
                "unclear": "uncertain",
            }
            if applicability.get("status") != status_by_design.get(applicability.get("design")):
                return False
            applicability = {key: value for key, value in applicability.items() if key != "status"}
        try:
            ResultApplicability.model_validate(applicability)
        except (TypeError, ValueError, ValidationError):
            return False
    target = result.get("target")
    reported = result.get("reported")
    if not isinstance(target, dict) or not isinstance(reported, dict):
        return False
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
        or not isinstance(reported.get("endpoint"), dict)
        or set(reported["endpoint"]) != {"name", "definition"}
        or not _nonblank(reported["endpoint"].get("name"))
        or (
            reported["endpoint"].get("definition") is not None
            and not _nonblank(reported["endpoint"].get("definition"))
        )
        or (
            result.get("relation") == "exact"
            and (
                (
                    semantics_version == _HISTORICAL_RESULT_SEMANTICS_VERSION
                    and (
                        _relation_name(target.get("outcome_definition"))
                        != _relation_name(reported["endpoint"].get("name"))
                        or result.get("relation_rationale")
                        != exact_relation_rationale(
                            target.get("outcome_definition", ""), reported["endpoint"]["name"]
                        )
                    )
                )
                or (
                    semantics_version != _HISTORICAL_RESULT_SEMANTICS_VERSION
                    and _relation_name(target.get("outcome_definition"))
                    == _relation_name(reported["endpoint"].get("name"))
                    and result.get("relation_rationale")
                    != exact_relation_rationale(
                        target.get("outcome_definition", ""), reported["endpoint"]["name"]
                    )
                )
            )
        )
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
                "endpoint",
                "group_values",
            }
            or not all(_nonblank(reported[key]) for key in ("effect_measure", "estimate"))
            or (reported["precision"] is not None and not _nonblank(reported["precision"]))
        ):
            return False
        valid, reported_ids = valid_values(reported["group_values"], optional=True)
    elif form == "group_bound_values":
        if set(reported) != {"form", "endpoint", "values"}:
            return False
        valid, reported_ids = valid_values(reported["values"])
    elif form == "single_group_category_profile":
        if set(reported) != {
            "form",
            "endpoint",
            "group_id",
            "denominator_basis",
            "category_axis_names",
            "categories",
        } or not all(_nonblank(reported.get(key)) for key in ("group_id", "denominator_basis")):
            return False
        axis_names = reported.get("category_axis_names")
        if (
            not isinstance(axis_names, list)
            or not axis_names
            or any(not isinstance(name, str) or not name.strip() for name in axis_names)
            or len(axis_names) != len(set(axis_names))
        ):
            return False
        categories = reported.get("categories")
        if not isinstance(categories, list) or not categories:
            return False
        if any(
            not isinstance(item, dict)
            or set(item) != {"category_axes", "value"}
            or not _nonblank(item.get("value"))
            for item in categories
        ):
            return False
        if any(
            not isinstance(item.get("category_axes"), list)
            or not item["category_axes"]
            or any(not isinstance(axis, str) or not axis.strip() for axis in item["category_axes"])
            or len(item["category_axes"]) != len(axis_names)
            for item in categories
        ):
            return False
        category_keys = [tuple(item["category_axes"]) for item in categories]
        if len(category_keys) != len(set(category_keys)):
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
) -> bool:
    reported = cast(dict[str, Any], result["reported"])
    endpoint = reported["endpoint"]
    endpoint_name = endpoint["name"]

    def supports(value: object, reference: dict[str, object]) -> bool:
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
        return _normalized_contains(material, str(value))

    if reported["form"] == "comparative_effect":
        quantitative_tuples = [
            (reported["effect_measure"], reported["estimate"]),
            *(
                (item["statistic"], item["value"], item["unit"])
                for item in reported["group_values"]
            ),
        ]
    elif reported["form"] == "group_bound_values":
        quantitative_tuples = [
            (item["statistic"], item["value"], item["unit"]) for item in reported["values"]
        ]
    else:
        quantitative_tuples = [
            (*item["category_axes"], item["value"]) for item in reported["categories"]
        ]
    return any(
        supports(endpoint_name, reference)
        and any(
            all(supports(value, reference) for value in quantitative)
            for quantitative in quantitative_tuples
        )
        for reference in evidence
    )


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


def _verify_result_evidence(
    result: object,
    catalog: dict[str, object],
    sources: dict[str, dict[str, object]],
    identity: Callable[[object], str],
    requested_outcomes: dict[str, str],
    batch: object = None,
    semantics_version: str = _RESULT_SEMANTICS_VERSION,
) -> bool:
    """Replay Result Evidence bindings from only the exported Canonical data."""
    if not isinstance(result, dict) or not isinstance(result.get("trial_id"), str):
        return False
    requested_outcome = requested_outcomes.get(result["trial_id"])
    if requested_outcome is None or not _valid_requested_result(
        result, requested_outcome, semantics_version
    ):
        return False
    if result.get("kind") == "unavailable":
        facts = result.get("missing_facts")
        if (
            set(result) != {"kind", "trial_id", "requested_outcome", "relation", "missing_facts"}
            or result.get("relation") not in {"ambiguous", "unavailable"}
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
    if result.get("kind") != "assessable" or result.get("relation") not in {
        "exact",
        "broader",
        "narrower",
        "component",
        "related",
    }:
        return False
    if not _valid_result_shape(result, requested_outcome, semantics_version):
        return False
    evidence = result.get("evidence")
    if (
        not isinstance(result.get("target"), dict)
        or not isinstance(result.get("reported"), dict)
        or not isinstance(evidence, list)
        or not evidence
    ):
        return False
    reported = cast(dict[str, object], result["reported"])
    endpoint = cast(dict[str, object], reported["endpoint"])
    endpoint_definition = endpoint.get("definition")
    by_handle = {item.get("handle"): item for item in catalog.values() if isinstance(item, dict)}
    applicability = result.get("applicability")
    if isinstance(applicability, dict) and any(
        not isinstance(by_handle.get(handle), dict)
        or by_handle[handle].get("trial_id") != result["trial_id"]
        for handle in applicability.get("evidence", [])
    ):
        return False
    groups = {
        item.get("id")
        for item in result["target"].get("comparison_groups", [])
        if isinstance(item, dict)
    }
    for reference in evidence:
        if not isinstance(reference, dict):
            return False
        kind = reference.get("kind")
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
        if kind not in expected_keys or set(reference) != expected_keys[kind]:
            return False
        if kind == "derived":
            inputs = reference.get("inputs")
            if (
                reference.get("operation") not in {"difference", "ratio", "sum"}
                or not isinstance(inputs, list)
                or not inputs
            ):
                return False
            try:
                if any(
                    not isinstance(item, dict)
                    or not isinstance(item.get("value"), str)
                    or not item["value"].strip()
                    for item in inputs
                ):
                    return False
                values = [Decimal(item["value"]) for item in inputs]
                if len(values) != len(inputs) or not all(value.is_finite() for value in values):
                    return False
                value = (
                    sum(values, Decimal("0"))
                    if reference["operation"] == "sum"
                    else values[0] - values[1]
                    if reference["operation"] == "difference" and len(values) == 2
                    else values[0] / values[1]
                    if reference["operation"] == "ratio" and len(values) == 2 and values[1]
                    else None
                )
                if value is None or (
                    format(value.normalize(), "f") if value else "0"
                ) != reference.get("value"):
                    return False
            except (InvalidOperation, ValueError, ZeroDivisionError):
                return False
            if any(
                not isinstance(item, dict)
                or set(item) != {"handle", "value"}
                or not isinstance((selected := by_handle.get(item.get("handle"))), dict)
                or selected.get("trial_id") != result["trial_id"]
                or not _normalized_contains(
                    str(selected.get("quote", selected.get("transcription", ""))),
                    str(item.get("value", "")),
                )
                for item in inputs
            ):
                return False
            continue
        selected = by_handle.get(reference.get("handle"))
        expected = (
            "narrative"
            if kind == "table" and reference.get("basis") == "text"
            else "figure"
            if kind == "table"
            else kind
        )
        if (
            kind not in {"narrative", "table", "figure"}
            or not isinstance(selected, dict)
            or selected.get("kind") != expected
            or selected.get("trial_id") != result["trial_id"]
        ):
            return False
        material = str(selected.get("quote", selected.get("transcription", "")))
        if kind == "narrative":
            # The selected handle is already an immutable, page-preserving
            # premise.  Narrative clauses and value mappings were redundant
            # caller-authored copies and are intentionally absent.
            pass
        elif kind == "table":
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
                    or not _normalized_contains(material, value)
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
                    not _normalized_contains(material, value)
                    for values in array_fields.values()
                    for value in values
                )
                or groups & set(reference.get("group_or_category_axes", []))
            ):
                return False
        else:
            render, region, source = (
                selected.get("render"),
                reference.get("region"),
                sources.get(str(selected.get("source_id"))),
            )
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
                or reference.get("transcription") != selected.get("transcription")
                or reference.get("provenance") != selected.get("provenance")
                or region != selected.get("region")
                or not isinstance(source, dict)
                or not isinstance(reference.get("transcription"), str)
                or not reference["transcription"].strip()
                or reference["transcription"] != reference["transcription"].strip()
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
    if len(paths) != len(bindings) or set(paths) != set(leaves) or len(paths) != len(set(paths)):
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
        if (
            not isinstance(index, int)
            or isinstance(index, bool)
            or not 0 <= index < len(evidence)
            or binding.get("value_digest") != identity(leaves[path])
        ):
            return False
        reference, value = evidence[index], str(leaves[path])
        if reference["kind"] == "narrative":
            selected = by_handle[reference["handle"]]
            material = str(selected.get("quote", selected.get("transcription", "")))
            if not _normalized_contains(material, value):
                return False
        if reference["kind"] == "table" and not _normalized_contains(
            str(
                by_handle[reference["handle"]].get(
                    "quote", by_handle[reference["handle"]].get("transcription", "")
                )
            ),
            value,
        ):
            return False
        if reference["kind"] == "figure":
            selected = by_handle[reference["handle"]]
            if selected.get("provenance") == "host_visual" and not _host_visual_leaf_allowed(path):
                return False
            figure_material = str(reference.get("transcription", ""))
            if not _normalized_contains(figure_material, value):
                return False
        if reference["kind"] == "derived" and value != reference.get("value"):
            return False
    return True


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


def _proposal_authorization(
    root: Path, state: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the exact Proposal Review and its sole researcher acknowledgment.

    The approved Review and acknowledgment are persisted directly in v0.3 state.
    Keeping this check at finalization prevents a bundle from silently becoming
    an assessment artifact without the one required human decision.
    """
    proposal = state.get("proposal")
    if not isinstance(proposal, dict):
        raise ValueError("finalized bundle requires a saved Proposal")
    acknowledgment = state.get("proposal_acknowledgment")
    if not isinstance(acknowledgment, dict):
        raise ValueError("finalized bundle requires exactly one Proposal acknowledgment")
    if (
        not isinstance(acknowledgment, dict)
        or set(acknowledgment) != _PROPOSAL_ACK_FIELDS
        or not isinstance(acknowledgment.get("review_identity"), str)
    ):
        raise ValueError("Proposal acknowledgment has an invalid shape")
    review = state.get("proposal_review")
    if not isinstance(review, dict):
        raise ValueError("the exact Proposal Review record is unavailable")
    if not isinstance(review, dict) or set(review) != _PROPOSAL_REVIEW_FIELDS:
        raise ValueError("the exact Proposal Review record is unavailable")
    if not _valid_proposal_gate(review, acknowledgment, proposal, _identity):
        raise ValueError("Proposal acknowledgment does not prove the displayed Review")
    return review, acknowledgment


def _valid_proposal_gate(
    review: object,
    acknowledgment: object,
    proposal: object,
    identity: Callable[[object], str],
) -> bool:
    """Check the sole human gate without consulting mutable workflow state."""
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
    handles: set[str] = set()

    def collect_handles(value: object) -> None:
        if isinstance(value, dict):
            handle = value.get("handle")
            if isinstance(handle, str):
                handles.add(handle)
            evidence_identity = value.get("evidence")
            if isinstance(evidence_identity, str):
                handles.add(evidence_identity)
            elif isinstance(evidence_identity, list):
                handles.update(item for item in evidence_identity if isinstance(item, str))
            boundary_evidence = value.get("boundary_evidence")
            if isinstance(boundary_evidence, list):
                handles.update(item for item in boundary_evidence if isinstance(item, str))
            for child in value.values():
                collect_handles(child)
        elif isinstance(value, list):
            for child in value:
                collect_handles(child)

    collect_handles(payload)
    expected_candidate_evidence = (
        {
            key: item
            for key, item in catalog.items()
            if isinstance(item, dict) and (key in handles or item.get("handle") in handles)
        }
        if isinstance(catalog, dict)
        else None
    )
    return bool(
        review.get("kind") == "review"
        and review.get("purpose") == "proposal"
        and isinstance(review.get("workflow_basis"), int)
        and not isinstance(review.get("workflow_basis"), bool)
        and isinstance(candidate, dict)
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


def _verify_domain_lineage(
    domain_history: object,
    domain_history_records: object,
    domain_records: object,
    evidence: dict[str, Any],
    identity: Callable[[object], str],
) -> bool:
    """Replay every Domain checkpoint and its explicit revision predecessor."""
    if not (
        isinstance(domain_history, dict)
        and isinstance(domain_history_records, dict)
        and isinstance(domain_records, dict)
        and set(domain_history) == set(domain_history_records) == set(domain_records)
    ):
        return False
    identity_fields = (
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
    )
    record_shape = {
        *identity_fields,
        "observed_at",
        "identity",
    }
    for key, history in domain_history.items():
        records = domain_history_records.get(key)
        active = domain_records.get(key)
        if (
            not isinstance(history, list)
            or not history
            or not isinstance(records, list)
            or len(records) != len(history)
            or not isinstance(active, dict)
            or history[-1] != active.get("identity")
        ):
            return False
        prior: dict[str, Any] | None = None
        for index, (checkpoint, record) in enumerate(zip(history, records, strict=True)):
            if (
                not isinstance(checkpoint, str)
                or not isinstance(record, dict)
                or set(record) != record_shape
                or record.get("identity") != checkpoint
                or record.get("identity")
                != identity({key: record.get(key) for key in identity_fields})
                or key != f"{record.get('trial_id')}:{record.get('domain_id')}"
                or not _valid_timestamp(record.get("observed_at"))
            ):
                return False
            supersedes = record.get("supersedes")
            basis = record.get("revision_basis")
            if index == 0:
                if supersedes is not None or basis is not None:
                    return False
            else:
                if not isinstance(prior, dict) or supersedes != prior.get("identity"):
                    return False
                if not isinstance(basis, dict) or basis.get("kind") not in {
                    "new_evidence",
                    "self_correction",
                }:
                    return False
                if basis.get("kind") == "self_correction":
                    if (
                        set(basis) != {"kind", "rationale"}
                        or not str(basis.get("rationale", "")).strip()
                    ):
                        return False
                else:
                    if (
                        set(basis) != {"kind", "evidence", "rationale"}
                        or not isinstance(basis.get("evidence"), str)
                        or not str(basis.get("rationale", "")).strip()
                    ):
                        return False
                    evidence_item = evidence.get(basis["evidence"])
                    if (
                        not isinstance(evidence_item, dict)
                        or evidence_item.get("trial_id") != record.get("trial_id")
                        or basis["evidence"] in _domain_evidence_ids(prior)
                        or basis["evidence"] not in _domain_evidence_ids(record)
                    ):
                        return False
            prior = record
    return True


def _scientific_contract_descriptor() -> dict[str, Any]:
    """Return the exact scientific contract bound into finalized artifacts.

    The pack's content hash binds the complete question and decision contract.
    The official source hash is repeated on each question because the pack's
    provenance model records the source version but not its digest.  Requiring
    one consistent pair here makes an ambiguous or partially edited pack fail
    at finalization instead of producing an artifact with unclear provenance.
    """
    official_sources = {
        (question.guidance.official.version, question.guidance.official.source_sha256)
        for question in SCIENTIFIC_PACK.questions
    }
    if len(official_sources) != 1:
        raise ValueError("scientific pack has inconsistent official source provenance")
    official_version, official_sha256 = next(iter(official_sources))
    if official_version != SCIENTIFIC_PACK.provenance.version:
        raise ValueError("scientific pack has inconsistent official source provenance")
    return {
        "id": SCIENTIFIC_PACK.id,
        "version": SCIENTIFIC_PACK.version,
        "result_semantics_version": _RESULT_SEMANTICS_VERSION,
        "content_hash": SCIENTIFIC_PACK.content_hash,
        "official_source": {
            "version": official_version,
            "source_sha256": official_sha256,
        },
    }


def _valid_scientific_contract_descriptor(value: object) -> bool:
    """Validate the artifact's scientific contract against the installed pack."""
    try:
        expected = _scientific_contract_descriptor()
    except (AttributeError, StopIteration, ValueError):
        return False
    if isinstance(value, dict) and value == expected:
        return True
    historical = {
        "id": "rob2.parallel.assignment",
        "version": "2019.1",
        "content_hash": "sha256:4bfd30a3d997e9eab0354ef7148726c5b112004a64b59dd57f02ac1493b61597",
        "official_source": expected["official_source"],
    }
    legacy = {
        "id": "rob2.parallel.assignment",
        "version": "2019.1",
        "result_semantics_version": _LEGACY_RESULT_SEMANTICS_VERSION,
        "content_hash": "sha256:3ef492b34a81c19e3f75d72fea2b92c40aebde80c06e24e44c36cd76dc4cf3d4",
        "official_source": expected["official_source"],
    }
    previous = {
        "id": "rob2.parallel.assignment",
        "version": "2019.1",
        "result_semantics_version": _RESULT_SEMANTICS_VERSION,
        "content_hash": "sha256:9c293fbfaf1b10b82682a90d2e90986c3283fa1412f2c8b62a4d82a14a795dc8",
        "official_source": expected["official_source"],
    }
    older_v07 = {
        "id": "rob2.parallel.assignment",
        "version": "2019.1",
        "result_semantics_version": _RESULT_SEMANTICS_VERSION,
        "content_hash": "sha256:3ef492b34a81c19e3f75d72fea2b92c40aebde80c06e24e44c36cd76dc4cf3d4",
        "official_source": expected["official_source"],
    }
    return value in (historical, legacy, previous, older_v07)


def _assessment_summary(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Project assessed Trial judgments directly from frozen snapshots."""
    snapshots = state.get("snapshots", {})
    return {
        trial_id: {
            "overall": snapshot["overall"],
            "domains": dict(snapshot["domain_judgments"]),
        }
        for trial_id, disposition in state.get("trial_dispositions", {}).items()
        if disposition == "assessed" and isinstance(snapshots.get(trial_id), dict)
        for snapshot in (snapshots[trial_id],)
    }


def _bundle(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    final_root = internal_path(root, "finalized")
    proposal = state.get("proposal")
    if not isinstance(proposal, dict) or not isinstance(proposal.get("evidence"), dict):
        raise ValueError("finalized bundle requires an approved proposal evidence catalog")
    proposal_review, proposal_acknowledgment = _proposal_authorization(root, state)
    evidence = dict(proposal["evidence"])
    domain_evidence_ids: set[str] = set()
    historical_records = state.get("domain_history_records")
    records_to_scan = (
        historical_records.values()
        if isinstance(historical_records, dict)
        else (state.get("domain_records") or {}).values()
    )
    for history in records_to_scan:
        records = history if isinstance(history, list) else [history]
        for record in records:
            domain_evidence_ids.update(_domain_evidence_ids(record))
    promoted = _canonical_evidence_records(root, domain_evidence_ids - set(evidence))
    missing = domain_evidence_ids - set(evidence) - set(promoted)
    if missing:
        raise ValueError(
            "Domain evidence identities are not promoted to Canonical storage: "
            + ", ".join(sorted(missing))
        )
    evidence.update(promoted)
    visual_files: dict[str, bytes] = {}
    source_by_id = {
        source["id"]: source
        for trial in (state.get("batch") or {}).get("trials", [])
        if isinstance(trial, dict)
        for source in trial.get("sources", [])
        if isinstance(source, dict) and isinstance(source.get("id"), str)
    }
    with _db(root, "derivative.sqlite3") as connection:
        for item in evidence.values():
            if item.get("kind") != "figure" or not isinstance(item.get("render"), dict):
                continue
            render = item["render"]
            row = connection.execute(
                "SELECT payload,png FROM renders WHERE identity=?", (render.get("identity"),)
            ).fetchone()
            if row is None:
                source = source_by_id.get(str(item.get("source_id")))
                if not isinstance(source, dict) or not isinstance(render.get("page"), int):
                    raise ValueError("selected figure render is unavailable")
                expected_identity = _identity(
                    {
                        "source_id": item.get("source_id"),
                        "source_sha256": source.get("sha256"),
                        "page": render.get("page"),
                        "recipe": render.get("recipe"),
                    }
                )
                if expected_identity != render.get("identity"):
                    raise ValueError("selected figure render identity is invalid")
                png = _render_page_png(
                    root,
                    str(item.get("trial_id")),
                    str(item.get("source_id")),
                    render["page"],
                )
                if render.get("png_sha256") != "sha256:" + hashlib.sha256(png).hexdigest():
                    raise ValueError("selected figure render pixels changed")
                connection.execute(
                    "INSERT INTO renders(identity,payload,png) VALUES (?,?,?)",
                    (render["identity"], canonical_json_bytes(render), png),
                )
                row = (canonical_json_bytes(render), png)
            png = bytes(row[1])
            try:
                stored_render = json.loads(bytes(row[0]))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError("selected figure render payload is corrupt") from error
            if (
                not isinstance(stored_render, dict)
                or canonical_json_bytes(stored_render) != canonical_json_bytes(render)
                or render.get("png_sha256") != "sha256:" + hashlib.sha256(png).hexdigest()
            ):
                raise ValueError("selected figure render does not match cached pixels")
            path = f"visual/{str(render['identity']).removeprefix('sha256:')}.png"
            visual_files[path] = png
    canonical_proposal = {**proposal, "evidence": evidence}
    canonical = {
        "batch": state.get("batch"),
        "proposal": canonical_proposal,
        "proposal_review": proposal_review,
        "proposal_acknowledgment": proposal_acknowledgment,
        "dispositions": state.get("trial_dispositions", {}),
        "snapshots": state.get("snapshots", {}),
        "domain_records": state.get("domain_records", {}),
        "domain_history": state.get("domain_history", {}),
        "domain_history_records": state.get("domain_history_records", {}),
        "snapshot_history": state.get("snapshot_history", {}),
        "snapshot_history_records": state.get("snapshot_history_records", {}),
        "terminals": state.get("terminals", {}),
        "scientific_pack": _scientific_contract_descriptor(),
    }
    identity = _identity({"schema": "rob2-kit.bundle.v0.3", "canonical": canonical})
    public = presentation(state)
    claims = {
        "trial_dispositions": state.get("trial_dispositions", {}),
        "counts": public["counts"],
        "authoritative_wording": public["wording"],
        "overall": {
            trial_id: snapshot.get("overall")
            for trial_id, snapshot in state.get("snapshots", {}).items()
            if state.get("trial_dispositions", {}).get(trial_id) == "assessed"
            and isinstance(snapshot, dict)
        },
    }
    files: dict[str, bytes] = {
        "canonical.json": canonical_json_bytes(canonical),
        "claims.json": canonical_json_bytes(claims),
        "report.html": (
            "<html><body><h1>Batch finalized</h1><pre>"
            + json.dumps(claims, sort_keys=True)
            + "</pre></body></html>"
        ).encode(),
    }
    files.update(visual_files)
    files.update(
        {
            f"evidence/{identity.removeprefix('sha256:')}.json": canonical_json_bytes(item)
            for identity, item in sorted(evidence.items())
        }
    )
    # This is an artifact member, not an out-of-band producer hint.  Its
    # content can safely precede the manifest because it names the stable
    # scientific bundle identity rather than a hash of manifest bytes.
    verification = {
        "schema": "rob2-kit.independent-verifier-input.v0.3",
        "manifest_identity": identity,
        "result": "verified",
        "checks": [
            "canonical_identity",
            "content_hashes",
            "proposal_gate",
            "domain_lineage",
            "snapshot_derivations",
            "claims",
        ],
    }
    files["verification.json"] = canonical_json_bytes(verification)
    manifest = {
        "schema": "rob2-kit.bundle.v0.3",
        "identity": identity,
        "files": [
            {"path": path, "sha256": "sha256:" + hashlib.sha256(data).hexdigest()}
            for path, data in sorted(files.items())
        ],
    }
    files["manifest.json"] = canonical_json_bytes(manifest)
    target = final_root / f"{identity.removeprefix('sha256:')}.rob2.zip"
    final_root.mkdir(parents=True, exist_ok=True)
    target_preexisting = target.exists()
    if target_preexisting and not target.is_file():
        raise ValueError("finalized bundle target is not a regular file")
    if target_preexisting:
        try:
            if verify_bundle(target):
                return {
                    "path": target.relative_to(root).as_posix(),
                    "identity": identity,
                    "sha256": "sha256:" + hashlib.sha256(target.read_bytes()).hexdigest(),
                    "files": sorted(files),
                }
        except (OSError, ValueError, zipfile.BadZipFile):
            pass
    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{identity.removeprefix('sha256:')[:16]}-",
            suffix=".tmp",
            dir=final_root,
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(files):
                info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, files[path])
        with temporary.open("r+b") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    try:
        verified = verify_bundle(target)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    if not verified:
        target.unlink(missing_ok=True)
        raise ValueError("finalized bundle failed independent verification")
    return {
        "path": target.relative_to(root).as_posix(),
        "identity": identity,
        "sha256": "sha256:" + hashlib.sha256(target.read_bytes()).hexdigest(),
        "files": sorted(files),
    }


def finalize_batch(workspace: str | Path, expected_revision: ExpectedRevision) -> dict[str, Any]:
    root = _root(workspace)
    _ensure(root)
    state = _state(root)
    if state.get("phase") == "finalized":
        artifact = state.get("artifact")
        if (
            isinstance(artifact, dict)
            and isinstance(artifact.get("path"), str)
            and (root / artifact["path"]).is_file()
            and verify_bundle(root / artifact["path"])
        ):
            return _result(
                "success",
                state,
                artifact=artifact,
                trial_dispositions=dict(state.get("trial_dispositions", {})),
                assessment_summary=_assessment_summary(state),
                retry=True,
            )
        # A process can terminate after the canonical state commit and before
        # the final path is made durable.  Rebuild the content-addressed file
        # from the committed final state; this does not create a new identity.
        rebuilt = _bundle(root, state)
        if rebuilt != artifact:
            state = _commit_records(
                root, {**state, "artifact": rebuilt}, state.get("revision", 0), {}
            )
        return _result(
            "success",
            state,
            artifact=rebuilt,
            trial_dispositions=dict(state.get("trial_dispositions", {})),
            assessment_summary=_assessment_summary(state),
            retry=True,
        )
    if expected_revision != state.get("revision", 0):
        raise WorkflowConflict(expected_revision, int(state.get("revision", 0)))
    dispositions = dict(state.get("trial_dispositions", {}))
    snapshots = dict(state.get("snapshots", {}))
    if any(value == "pending" for value in dispositions.values()):
        raise ValueError("all Trials must have a terminal disposition")
    if any(
        value == "assessed"
        and (
            not isinstance(snapshots.get(trial), dict)
            or snapshots[trial].get("provisional") is not False
        )
        for trial, value in dispositions.items()
    ):
        raise ValueError("assessed Trial requires a frozen final AssessmentSnapshot")
    state = {
        **state,
        "phase": "ready_to_finalize",
        "trial_dispositions": dispositions,
        "snapshots": snapshots,
    }
    final_dispositions = dispositions
    final_state = {**state, "phase": "finalized", "trial_dispositions": final_dispositions}
    artifact = _bundle(root, final_state)
    artifact_path = root / artifact["path"]
    final_state["artifact"] = artifact
    # The frozen snapshot is an immutable Canonical record, not merely a
    # mutable field in the current-state projection.
    try:
        state = _commit_records(
            root,
            final_state,
            expected_revision,
            {
                f"snapshot:{snapshot['identity']}": snapshot
                for disposition, snapshot in (
                    (final_dispositions.get(trial_id), snapshots.get(trial_id))
                    for trial_id in final_dispositions
                )
                if disposition == "assessed" and isinstance(snapshot, dict)
            },
        )
    except Exception:
        # A compare-and-swap conflict must not leave a newly created artifact
        # that no committed workflow head references.  A pre-existing file may
        # belong to a successful concurrent retry and is therefore retained;
        # reconcile that race against the durable head before deciding.
        latest = _state(root)
        referenced = (
            latest.get("phase") == "finalized"
            and isinstance(latest.get("artifact"), dict)
            and latest["artifact"].get("path") == artifact["path"]
        )
        if artifact_path is not None and not referenced:
            artifact_path.unlink(missing_ok=True)
        raise
    return _result(
        "success",
        state,
        artifact=artifact,
        trial_dispositions=final_dispositions,
        assessment_summary=_assessment_summary(state),
    )


def verify_bundle(path: str | Path) -> bool:
    """Independently check a finalized bundle without opening the workspace."""

    def independent_identity(value: object) -> str:
        """Deliberately local identity implementation for artifact verification."""
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()

    def snapshot_identity(snapshot: dict[str, object]) -> str:
        """Recompute a final Trial snapshot identity independently."""
        return independent_identity(
            {key: value for key, value in snapshot.items() if key != "identity"}
        )

    def active_for_domain(domain_id: str, answers: dict[str, str]) -> set[str]:
        active: set[str] = set()
        for question in SCIENTIFIC_PACK.questions:
            if question.domain_id != domain_id:
                continue
            activation = question.activation
            if activation.kind == "always":
                active.add(question.id)
                continue
            matches = [
                answers.get(predicate.question_id)
                in {answer.value for answer in predicate.accepted_answers}
                for predicate in activation.predicates
            ]
            if (activation.mode == "any" and any(matches)) or (
                activation.mode == "all" and all(matches)
            ):
                active.add(question.id)
        return active

    def local_domain_judgment(domain_id: str, answers: dict[str, str]) -> str:
        """Independent transcription of the pinned RoB 2 decision tables."""
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
        raise ValueError("unknown domain")

    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if names != sorted(names) or len(names) != len(set(names)):
                return False
            for info in archive.infolist():
                if info.date_time != (1980, 1, 1, 0, 0, 0):
                    return False
                if info.external_attr != 0o644 << 16:
                    return False
                if info.compress_type != zipfile.ZIP_DEFLATED:
                    return False
            if any(
                name.startswith("/")
                or ".." in Path(name).parts
                or "\\" in name
                or posixpath.normpath(name) != name
                for name in names
            ):
                return False
            forbidden = {".bin", "source_bytes", "prompts", "traces"}
            if any(
                Path(name).suffix == ".bin" or any(part in forbidden for part in Path(name).parts)
                for name in names
            ):
                return False
            manifest = json.loads(archive.read("manifest.json"))
            if not isinstance(manifest, dict) or set(manifest) != {"schema", "identity", "files"}:
                return False
            if manifest.get("schema") != "rob2-kit.bundle.v0.3":
                return False
            rows = manifest.get("files")
            if not isinstance(rows, list) or any(
                not isinstance(row, dict) or set(row) != {"path", "sha256"} for row in rows
            ):
                return False
            row_paths = [row["path"] for row in rows]
            if len(row_paths) != len(set(row_paths)) or row_paths != sorted(row_paths):
                return False
            expected = set(row_paths) | {"manifest.json"}
            if set(names) != expected:
                return False
            for row in rows:
                data = archive.read(row["path"])
                if "sha256:" + hashlib.sha256(data).hexdigest() != row["sha256"]:
                    return False
                if str(row["path"]).endswith(".json"):
                    try:
                        parsed = json.loads(data)
                    except json.JSONDecodeError:
                        return False
                    if _contains_forbidden_paths(parsed):
                        return False
            canonical = archive.read("canonical.json")
            canonical_value = json.loads(canonical)
            if not isinstance(canonical_value, dict) or set(canonical_value) != {
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
            }:
                return False
            scientific_pack = canonical_value.get("scientific_pack")
            if not _valid_scientific_contract_descriptor(scientific_pack):
                return False
            semantics_version = (
                scientific_pack.get(
                    "result_semantics_version", _HISTORICAL_RESULT_SEMANTICS_VERSION
                )
                if isinstance(scientific_pack, dict)
                else _HISTORICAL_RESULT_SEMANTICS_VERSION
            )
            if not _valid_batch(canonical_value["batch"]):
                return False
            dispositions = canonical_value.get("dispositions")
            snapshots = canonical_value.get("snapshots")
            domains = canonical_value.get("domain_records")
            terminals = canonical_value.get("terminals")
            if (
                not isinstance(dispositions, dict)
                or not isinstance(snapshots, dict)
                or not isinstance(domains, dict)
                or not isinstance(terminals, dict)
            ):
                return False
            if any(
                value not in {"assessed", "needs_input", "failed"}
                for value in dispositions.values()
            ):
                return False
            batch_trial_ids = {trial["id"] for trial in canonical_value["batch"]["trials"]}
            if set(dispositions) != batch_trial_ids:
                return False
            terminal_trials: dict[str, int] = {}
            for identity, terminal in terminals.items():
                if (
                    not isinstance(identity, str)
                    or not isinstance(terminal, dict)
                    or set(terminal)
                    != {"trial_id", "disposition", "reason", "missing_facts", "identity"}
                    or terminal.get("identity") != identity
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
                    or independent_identity(
                        {key: value for key, value in terminal.items() if key != "identity"}
                    )
                    != identity
                ):
                    return False
                trial_id = terminal["trial_id"]
                if (
                    trial_id not in dispositions
                    or terminal.get("disposition") != dispositions[trial_id]
                    or trial_id in terminal_trials
                ):
                    return False
                terminal_trials[trial_id] = 1
            for trial_id, disposition in dispositions.items():
                has_terminal = trial_id in terminal_trials
                if (disposition in {"needs_input", "failed"}) != has_terminal:
                    return False
            domain_identity_fields = (
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
            )
            proposal_evidence = (canonical_value.get("proposal") or {}).get("evidence", {})
            evidence_by_identity = proposal_evidence if isinstance(proposal_evidence, dict) else {}
            batch_trials = {
                item.get("id"): item.get("sources", [])
                for item in canonical_value["batch"].get("trials", [])
                if isinstance(item, dict)
            }
            for record in domains.values():
                if (
                    not isinstance(record, dict)
                    or set(record)
                    != {
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
                    or record.get("identity")
                    != independent_identity(
                        {key: record.get(key) for key in domain_identity_fields}
                    )
                ):
                    return False
                accounts = record.get("search_accounts")
                if not isinstance(record.get("answers"), list) or not isinstance(accounts, list):
                    return False
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
                    return False
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
                        or (
                            "missing_data" in answer
                            and not _valid_missing_data(
                                answer["missing_data"],
                                answer.get("question_id"),
                                evidence_by_identity,
                                record.get("trial_id"),
                            )
                        )
                        or not isinstance(answer.get("bases"), list)
                        or not answer["bases"]
                        or answer["question_id"] in answer_map
                    ):
                        return False
                    answer_map[answer["question_id"]] = answer["answer"]
                allowed_questions = {
                    item.id
                    for item in SCIENTIFIC_PACK.questions
                    if item.domain_id == record.get("domain_id")
                }
                try:
                    derived_active = {
                        question_id
                        for question_id in derive_active_questions(answer_map)
                        if question_id in allowed_questions
                    }
                except ValueError:
                    return False
                if (
                    set(active_questions) | set(inactive_questions) != allowed_questions
                    or set(active_questions) != derived_active
                ):
                    return False
                if set(answer_map) != set(active_questions):
                    return False
                account_by_identity = {
                    item.get("identity"): item for item in accounts if isinstance(item, dict)
                }
                if len(account_by_identity) != len(accounts):
                    return False
                sources = {
                    item.get("id"): item
                    for item in batch_trials.get(record.get("trial_id"), [])
                    if isinstance(item, dict)
                }
                for account in accounts:
                    if not _valid_search_account(
                        account,
                        record.get("trial_id"),
                        canonical_value["batch"].get("identity"),
                        sources,
                        independent_identity,
                    ):
                        return False
                for answer in answers:
                    direct_basis = False
                    uncertainty_basis = False
                    for use in answer["bases"]:
                        if not isinstance(use, dict):
                            return False
                        if use.get("kind") in {
                            "direct_support",
                            "indirect_support",
                            "contradiction",
                        }:
                            direct_basis = True
                        if use.get("kind") == "limitation":
                            if (
                                set(use) != {"kind", "text", "search_receipt"}
                                or not use["text"].strip()
                                or not isinstance(use["search_receipt"], str)
                                or use["search_receipt"] not in account_by_identity
                            ):
                                return False
                            account = account_by_identity[use["search_receipt"]]
                            if account.get("truncated") is not False:
                                return False
                            uncertainty_basis = True
                            continue
                        if use.get("kind") == "absence":
                            if set(use) != {"kind", "search_receipt"}:
                                return False
                            receipt = use.get("search_receipt")
                            if not isinstance(receipt, str) or receipt not in account_by_identity:
                                return False
                            account = account_by_identity[receipt]
                            if (
                                account.get("truncated") is not False
                                or account.get("total_matches") != 0
                                or account.get("condition") != "no_hits"
                            ):
                                return False
                            uncertainty_basis = True
                            continue
                        if use.get("kind") not in {
                            "direct_support",
                            "indirect_support",
                            "contradiction",
                            "context",
                            "inference",
                        }:
                            return False
                        if use.get("kind") in {"context", "inference"}:
                            uncertainty_basis = True
                        if set(use) != {"kind", "evidence", "source"}:
                            return False
                        evidence = evidence_by_identity.get(use.get("evidence"))
                        if not isinstance(evidence, dict) or evidence.get("trial_id") != record.get(
                            "trial_id"
                        ):
                            return False
                        source = use.get("source")
                        if not isinstance(source, str) or not source:
                            return False
                        material = str(evidence.get("quote") or evidence.get("transcription") or "")
                        if material != source:
                            return False
                    if answer["answer"] in {"yes", "no"} and not direct_basis:
                        return False
                    if answer["answer"] in {"probably_yes", "probably_no"} and not (
                        direct_basis or uncertainty_basis
                    ):
                        return False
            domain_history = canonical_value.get("domain_history")
            domain_history_records = canonical_value.get("domain_history_records")
            snapshot_history = canonical_value.get("snapshot_history")
            snapshot_history_records = canonical_value.get("snapshot_history_records")
            if (
                not isinstance(domain_history, dict)
                or not isinstance(domain_history_records, dict)
                or not isinstance(snapshot_history, dict)
                or not isinstance(snapshot_history_records, dict)
            ):
                return False
            if (
                set(domain_history) != set(domains)
                or set(domain_history_records) != set(domains)
                or set(snapshot_history) != set(snapshots)
                or set(snapshot_history_records) != set(snapshots)
            ):
                return False
            if not _verify_domain_lineage(
                domain_history,
                domain_history_records,
                domains,
                evidence_by_identity,
                independent_identity,
            ):
                return False
            domain_record_shape = {
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
            for key, historical in domain_history_records.items():
                history = domain_history[key]
                if not isinstance(history, list) or not history or not isinstance(historical, list):
                    return False
                for item, digest in zip(historical, history, strict=True):
                    if (
                        not isinstance(item, dict)
                        or set(item) != domain_record_shape
                        or item.get("identity") != digest
                        or item.get("identity")
                        != independent_identity(
                            {field: item.get(field) for field in domain_identity_fields}
                        )
                        or key != f"{item.get('trial_id')}:{item.get('domain_id')}"
                        or not isinstance(item.get("answers"), list)
                        or not isinstance(item.get("active_questions"), list)
                        or not isinstance(item.get("inactive_questions"), list)
                    ):
                        return False
                    answer_map = {
                        answer.get("question_id"): answer.get("answer")
                        for answer in item["answers"]
                        if isinstance(answer, dict)
                    }
                    allowed = {
                        question.id
                        for question in SCIENTIFIC_PACK.questions
                        if question.domain_id == item.get("domain_id")
                    }
                    try:
                        derived = {
                            question_id
                            for question_id in derive_active_questions(answer_map)
                            if question_id in allowed
                        }
                        judgment = local_domain_judgment(item["domain_id"], answer_map)
                    except (KeyError, TypeError, ValueError):
                        return False
                    if (
                        set(answer_map) != set(item["active_questions"])
                        or set(item["active_questions"]) != derived
                        or set(item["active_questions"]) | set(item["inactive_questions"])
                        != allowed
                        or item.get("judgment") != judgment
                    ):
                        return False
                    accounts = item["search_accounts"]
                    if not isinstance(accounts, list):
                        return False
                    trial_sources = {
                        source.get("id"): source
                        for source in batch_trials.get(item.get("trial_id"), [])
                        if isinstance(source, dict)
                    }
                    for account in accounts:
                        if not _valid_search_account(
                            account,
                            item.get("trial_id"),
                            canonical_value["batch"].get("identity"),
                            trial_sources,
                            independent_identity,
                        ):
                            return False
                    history_account_by_identity = {
                        account.get("identity"): account
                        for account in accounts
                        if isinstance(account, dict)
                    }
                    if len(history_account_by_identity) != len(accounts):
                        return False
                    account_ids = {
                        account.get("identity") for account in accounts if isinstance(account, dict)
                    }
                    for answer in item["answers"]:
                        if (
                            not isinstance(answer, dict)
                            or set(answer)
                            not in (
                                {"question_id", "answer", "bases"},
                                {"question_id", "answer", "bases", "justification"},
                                {"question_id", "answer", "bases", "missing_data"},
                                {"question_id", "answer", "bases", "justification", "missing_data"},
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
                            or (
                                "missing_data" in answer
                                and not _valid_missing_data(
                                    answer["missing_data"],
                                    answer.get("question_id"),
                                    evidence_by_identity,
                                    item.get("trial_id"),
                                )
                            )
                        ):
                            return False
                        direct_basis = False
                        uncertainty_basis = False
                        for use in answer["bases"]:
                            if not isinstance(use, dict):
                                return False
                            if use.get("kind") in {
                                "direct_support",
                                "indirect_support",
                                "contradiction",
                            }:
                                direct_basis = True
                            if use.get("kind") == "limitation":
                                if (
                                    set(use) != {"kind", "text", "search_receipt"}
                                    or not use["text"].strip()
                                    or not isinstance(use["search_receipt"], str)
                                    or use["search_receipt"] not in history_account_by_identity
                                ):
                                    return False
                                account = history_account_by_identity[use["search_receipt"]]
                                if account.get("truncated") is not False:
                                    return False
                                uncertainty_basis = True
                                continue
                            if use.get("kind") == "absence":
                                if (
                                    set(use) != {"kind", "search_receipt"}
                                    or use["search_receipt"] not in account_ids
                                ):
                                    return False
                                account = history_account_by_identity[use["search_receipt"]]
                                if (
                                    account.get("truncated") is not False
                                    or account.get("total_matches") != 0
                                    or account.get("condition") != "no_hits"
                                ):
                                    return False
                                uncertainty_basis = True
                                continue
                            if use.get("kind") not in {
                                "direct_support",
                                "indirect_support",
                                "contradiction",
                                "context",
                                "inference",
                            } or set(use) != {"kind", "evidence", "source"}:
                                return False
                            if use.get("kind") in {"context", "inference"}:
                                uncertainty_basis = True
                            evidence = evidence_by_identity.get(use.get("evidence"))
                            source = use.get("source")
                            if (
                                not isinstance(evidence, dict)
                                or evidence.get("trial_id") != item.get("trial_id")
                                or not isinstance(source, str)
                            ):
                                return False
                            material = str(
                                evidence.get("quote") or evidence.get("transcription") or ""
                            )
                            if material != source:
                                return False
                        if answer["answer"] in {"yes", "no"} and not direct_basis:
                            return False
                        if answer["answer"] in {"probably_yes", "probably_no"} and not (
                            direct_basis or uncertainty_basis
                        ):
                            return False
            for trial_id, historical in snapshot_history_records.items():
                history = snapshot_history[trial_id]
                if not isinstance(history, list) or not history or not isinstance(historical, list):
                    return False
                for item, digest in zip(historical, history, strict=True):
                    expected_shape = {
                        "trial_id",
                        "checkpoints",
                        "provisional",
                        "domain_judgments",
                        "multiple_concerns",
                        "overall",
                        "identity",
                    }
                    if (
                        not isinstance(item, dict)
                        or set(item) != expected_shape
                        or item.get("provisional") is not False
                        or item.get("identity") != digest
                        or item.get("trial_id") != trial_id
                        or item.get("identity") != snapshot_identity(item)
                        or not isinstance(item.get("checkpoints"), list)
                        or len(item["checkpoints"]) != len(SCIENTIFIC_PACK.domains)
                        or not isinstance(item.get("domain_judgments"), dict)
                        or set(item["domain_judgments"])
                        != {domain.id for domain in SCIENTIFIC_PACK.domains}
                        or any(
                            checkpoint not in domain_history.get(f"{trial_id}:{domain.id}", [])
                            for domain, checkpoint in zip(
                                SCIENTIFIC_PACK.domains, item["checkpoints"], strict=True
                            )
                        )
                    ):
                        return False
                    for domain, checkpoint in zip(
                        SCIENTIFIC_PACK.domains, item["checkpoints"], strict=True
                    ):
                        records_for_domain = domain_history_records.get(
                            f"{trial_id}:{domain.id}", []
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
                            domain.id
                        ) != matching.get("judgment"):
                            return False
                    judgments = item["domain_judgments"]
                    concerns = list(judgments.values()).count("some_concerns")
                    multiple = item.get("multiple_concerns")
                    if "high" in judgments.values() or concerns < 2:
                        if multiple is not None:
                            return False
                        combined = None
                    elif (
                        not isinstance(multiple, dict)
                        or set(multiple) != {"raises_overall_to_high", "rationale"}
                        or not isinstance(multiple["raises_overall_to_high"], bool)
                        or not isinstance(multiple["rationale"], str)
                        or not multiple["rationale"]
                    ):
                        return False
                    else:
                        combined = multiple["raises_overall_to_high"]
                    if (
                        item.get("overall")
                        != evaluate_overall(judgments, combined_concerns=combined).judgment.value
                    ):
                        return False
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
                        != independent_identity(
                            {field: item.get(field) for field in domain_identity_fields}
                        )
                        for item, digest in zip(historical, history, strict=True)
                    )
                ):
                    return False
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
                        or item.get("identity") != snapshot_identity(item)
                        for item, digest in zip(historical, history, strict=True)
                    )
                ):
                    return False
            for trial_id, disposition in dispositions.items():
                snapshot = snapshots.get(trial_id)
                if disposition == "assessed" and (
                    not isinstance(snapshot, dict)
                    or snapshot.get("provisional") is not False
                    or not isinstance(snapshot.get("domain_judgments"), dict)
                    or len(snapshot["domain_judgments"]) != len(SCIENTIFIC_PACK.domains)
                ):
                    return False
                if disposition == "assessed":
                    if snapshot.get("identity") != snapshot_identity(snapshot):
                        return False
                    expected_checkpoints: list[str] = []
                    expected_judgments: dict[str, str] = {}
                    for domain in SCIENTIFIC_PACK.domains:
                        record = domains.get(f"{trial_id}:{domain.id}")
                        if not isinstance(record, dict) or record.get("domain_id") != domain.id:
                            return False
                        answers = record.get("answers")
                        if not isinstance(answers, list):
                            return False
                        answer_map = {
                            item["question_id"]: item["answer"]
                            for item in answers
                            if isinstance(item, dict)
                            and isinstance(item.get("question_id"), str)
                            and isinstance(item.get("answer"), str)
                        }
                        if len(answer_map) != len(answers):
                            return False
                        active = active_for_domain(domain.id, answer_map)
                        ordered_active = [
                            question.id
                            for question in SCIENTIFIC_PACK.questions
                            if question.domain_id == domain.id and question.id in active
                        ]
                        if (
                            set(answer_map) != active
                            or record.get("active_questions") != ordered_active
                        ):
                            return False
                        if (
                            set(record.get("inactive_questions", []))
                            != {
                                question.id
                                for question in SCIENTIFIC_PACK.questions
                                if question.domain_id == domain.id
                            }
                            - active
                        ):
                            return False
                        judgment = local_domain_judgment(domain.id, answer_map)
                        if record.get("judgment") != judgment:
                            return False
                        expected_checkpoints.append(str(record.get("identity")))
                        expected_judgments[domain.id] = judgment
                    if (
                        snapshot.get("checkpoints") != expected_checkpoints
                        or snapshot.get("domain_judgments") != expected_judgments
                    ):
                        return False
                    domain_values = list(expected_judgments.values())
                    concerns = domain_values.count("some_concerns")
                    multiple = snapshot.get("multiple_concerns")
                    if "high" in domain_values or concerns < 2:
                        if multiple is not None:
                            return False
                        combined = None
                    else:
                        if (
                            not isinstance(multiple, dict)
                            or set(multiple) != {"raises_overall_to_high", "rationale"}
                            or not isinstance(multiple["raises_overall_to_high"], bool)
                            or not isinstance(multiple["rationale"], str)
                            or not multiple["rationale"]
                        ):
                            return False
                        combined = multiple["raises_overall_to_high"]
                    overall = evaluate_overall(
                        expected_judgments, combined_concerns=combined
                    ).judgment.value
                    if snapshot.get("overall") != overall:
                        return False
            expected_identity = independent_identity(
                {"schema": "rob2-kit.bundle.v0.3", "canonical": canonical_value}
            )
            if manifest.get("identity") != expected_identity:
                return False
            report = archive.read("report.html").decode("utf-8")
            claims = json.loads(archive.read("claims.json"))
            expected_claims = {
                "trial_dispositions": dispositions,
                "counts": presentation({"phase": "finalized", "trial_dispositions": dispositions})[
                    "counts"
                ],
                "authoritative_wording": presentation(
                    {"phase": "finalized", "trial_dispositions": dispositions}
                )["wording"],
                "overall": {
                    trial_id: snapshot.get("overall")
                    for trial_id, snapshot in snapshots.items()
                    if dispositions.get(trial_id) == "assessed" and isinstance(snapshot, dict)
                },
            }
            if not isinstance(claims, dict) or claims != expected_claims:
                return False
            if json.dumps(claims, sort_keys=True) not in report:
                return False
            proposal = canonical_value.get("proposal") or {}
            proposal_review = canonical_value.get("proposal_review")
            proposal_acknowledgment = canonical_value.get("proposal_acknowledgment")
            payload = proposal.get("payload") if isinstance(proposal, dict) else None
            bound_catalog = proposal.get("evidence") if isinstance(proposal, dict) else None
            if (
                not isinstance(proposal, dict)
                or not isinstance(payload, dict)
                or set(proposal) != {"identity", "payload", "evidence"}
                or set(payload)
                != (
                    {"results"}
                    if semantics_version != _LEGACY_RESULT_SEMANTICS_VERSION
                    else {"results", "main_report_scopes"}
                )
                or proposal.get("identity") != independent_identity(payload)
                or not isinstance(bound_catalog, dict)
                or not _valid_proposal_gate(
                    proposal_review,
                    proposal_acknowledgment,
                    proposal,
                    independent_identity,
                )
            ):
                return False
            if (
                semantics_version == _LEGACY_RESULT_SEMANTICS_VERSION
                and not _valid_main_report_scopes(
                    payload.get("main_report_scopes"), canonical_value["batch"], bound_catalog
                )
            ):
                return False
            evidence_members = {name for name in names if name.startswith("evidence/")}
            expected_evidence_members = {
                f"evidence/{catalog_identity.removeprefix('sha256:')}.json"
                for catalog_identity in bound_catalog
            }
            if evidence_members != expected_evidence_members:
                return False
            for catalog_identity, item in bound_catalog.items():
                member = f"evidence/{catalog_identity.removeprefix('sha256:')}.json"
                if json.loads(archive.read(member)) != item:
                    return False
            if any(
                not isinstance(item, dict)
                or item.get("identity") != catalog_identity
                or catalog_identity
                != independent_identity(
                    {key: value for key, value in item.items() if key not in {"identity", "handle"}}
                )
                or item.get("handle") != "eh_" + catalog_identity.removeprefix("sha256:")[:16]
                for catalog_identity, item in bound_catalog.items()
            ):
                return False
            expected_visual_paths = {
                f"visual/{str(item['render']['identity']).removeprefix('sha256:')}.png"
                for item in bound_catalog.values()
                if isinstance(item, dict)
                and item.get("kind") == "figure"
                and isinstance(item.get("render"), dict)
            }
            actual_visual_paths = {name for name in names if name.startswith("visual/")}
            if actual_visual_paths != expected_visual_paths:
                return False
            for item in bound_catalog.values():
                if not isinstance(item, dict) or item.get("kind") != "figure":
                    continue
                render = item.get("render")
                if not isinstance(render, dict):
                    return False
                visual_path = f"visual/{str(render['identity']).removeprefix('sha256:')}.png"
                if "sha256:" + hashlib.sha256(archive.read(visual_path)).hexdigest() != render.get(
                    "png_sha256"
                ):
                    return False
            batch_trials = canonical_value["batch"].get("trials")
            if not isinstance(batch_trials, list):
                return False
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
                    return False
                requested_outcomes[trial["id"]] = trial["requested_outcome"]
                for item in trial["sources"]:
                    if isinstance(item, dict) and isinstance(item.get("id"), str):
                        sources[item["id"]] = item
            if any(
                not isinstance(item, dict)
                or item.get("kind") not in {"narrative", "figure"}
                or not _valid_selected_evidence(item, sources, independent_identity)
                for item in bound_catalog.values()
            ):
                return False
            results = payload.get("results") if isinstance(payload, dict) else None
            if (
                not isinstance(results, list)
                or len(results) != len(batch_trial_ids)
                or {item.get("trial_id") for item in results if isinstance(item, dict)}
                != batch_trial_ids
                or not all(
                    _verify_result_evidence(
                        item,
                        bound_catalog,
                        sources,
                        independent_identity,
                        requested_outcomes,
                        canonical_value["batch"],
                        semantics_version,
                    )
                    for item in results
                )
            ):
                return False
            terminal_by_trial = {terminal["trial_id"]: terminal for terminal in terminals.values()}
            for result in results:
                trial_id = result["trial_id"]
                disposition = dispositions[trial_id]
                if disposition == "assessed" and result.get("kind") != "assessable":
                    return False
                if result.get("kind") == "unavailable":
                    terminal = terminal_by_trial.get(trial_id)
                    facts = [item["fact"] for item in result["missing_facts"]]
                    if (
                        disposition != "needs_input"
                        or not isinstance(terminal, dict)
                        or terminal.get("missing_facts") != facts
                    ):
                        return False
                applicability = result.get("applicability")
                unsupported_design = isinstance(applicability, dict) and applicability.get(
                    "design"
                ) in {"cluster_randomized", "crossover", "unclear"}
                if unsupported_design and disposition != "needs_input":
                    return False
            # verification.json is informational only; this verifier recomputes
            # hashes and derivations itself and never trusts a producer claim.
            verification = json.loads(archive.read("verification.json"))
            return (
                isinstance(verification, dict)
                and set(verification) == {"schema", "manifest_identity", "result", "checks"}
                and verification.get("schema") == "rob2-kit.independent-verifier-input.v0.3"
                and verification.get("manifest_identity") == manifest.get("identity")
                and verification.get("result") == "verified"
                and verification.get("checks")
                == [
                    "canonical_identity",
                    "content_hashes",
                    "proposal_gate",
                    "domain_lineage",
                    "snapshot_derivations",
                    "claims",
                ]
            )
    except (OSError, KeyError, ValueError, TypeError, json.JSONDecodeError, zipfile.BadZipFile):
        return False
